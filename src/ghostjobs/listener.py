"""Control the tracker from your phone.

The Pi keeps a connection open to a second ntfy topic (NTFY_COMMAND_TOPIC). Anything you
send to that topic from the ntfy app is read as a command; replies come back on your
normal alerts topic, with buttons so next time you can just tap.

Commands: run, send, resend, skills, status, help
"""

import fcntl
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import httpx

from ghostjobs.config import Settings, get_settings
from ghostjobs.db import utcnow
from ghostjobs.notify import Notifier

log = logging.getLogger(__name__)

LOCK_FILE = "ghostjobs.lock"
STATE_FILE = ".listener_state.json"

HELP = (
    "Send one of these to your command topic:\n"
    "run - fetch new jobs from Reed now, score them, alert you\n"
    "send - send any genuine jobs you haven't had yet (no Reed calls)\n"
    "resend - send all current genuine jobs again\n"
    "skills - which skills local jobs ask for (last 30 days)\n"
    "status - what's set up and stored\n"
    "help - this list"
)


# --- a run lock shared by the 18:00 timer, phone runs and manual runs -------------------


@contextmanager
def run_lock(path: str = LOCK_FILE):
    """Yields True if we got the lock, False if another run holds it. Never blocks."""
    f = open(path, "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        f.close()  # also releases the lock


# --- commands ----------------------------------------------------------------------------


def _cli(*args: str, timeout: int = 3600) -> str:
    """Run a ghostjobs command in a fresh process, so it always reads the current .env."""
    proc = subprocess.run(
        [sys.executable, "-m", "ghostjobs.cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=os.getcwd(),
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        out = (
            (out + "\n" if out else "")
            + "Error: "
            + (err[-1] if err else f"exit {proc.returncode}")
        )
    return out


def _last_line_with(text: str, needle: str) -> str:
    for line in reversed(text.splitlines()):
        if needle in line:
            return line.strip()
    return text.strip().splitlines()[-1] if text.strip() else "(no output)"


class Commander:
    def __init__(
        self,
        settings: Settings | None = None,
        notifier: Notifier | None = None,
        cli: Callable[..., str] = _cli,
        state_path: str = STATE_FILE,
    ):
        self.s = settings or get_settings()
        self.notifier = notifier or Notifier(self.s)
        self.cli = cli
        self.state_path = Path(state_path)
        self.busy = threading.Lock()

    # buttons that post straight back to the command topic
    def buttons(self) -> str:
        url = f"{self.s.ntfy_server.rstrip('/')}/{self.s.ntfy_command_topic}"
        return "; ".join(
            f"http, {label}, {url}, body={cmd}, clear=true"
            for label, cmd in (("Run now", "run"), ("Send new", "send"), ("Skills", "skills"))
        )

    def reply(self, title: str, message: str) -> None:
        try:
            self.notifier.send(title, message, tags="robot", actions=self.buttons())
        except httpx.HTTPError as e:
            log.warning("Couldn't send reply: %s", e)

    def _last_manual_run(self) -> datetime | None:
        try:
            return datetime.fromisoformat(json.loads(self.state_path.read_text())["last_run"])
        except (OSError, ValueError, KeyError):
            return None

    def _mark_manual_run(self) -> None:
        self.state_path.write_text(json.dumps({"last_run": utcnow().isoformat()}))

    def handle(self, text: str) -> None:
        cmd = (text or "").strip().lower().split()[0] if (text or "").strip() else ""
        log.info("Command received: %r", cmd)
        if cmd in ("help", "menu", "?", ""):
            self.reply("Ghost Job Tracker", HELP)
        elif cmd == "status":
            self.reply("Status", self.cli("status"))
        elif cmd == "skills":
            self.reply("Skills in demand", self.cli("skills"))
        elif cmd in ("send", "notify"):
            self._background("send", lambda: self.cli("notify"), "Sent")
        elif cmd == "resend":
            self._background("resend", lambda: self.cli("notify", "--resend"), "Sent")
        elif cmd == "run":
            last = self._last_manual_run()
            wait = self.s.command_cooldown_minutes
            if last and (utcnow() - last).total_seconds() < wait * 60:
                mins = wait - int((utcnow() - last).total_seconds() // 60)
                self.reply(
                    "Not yet",
                    f"Last phone run was recently. Try again in {mins} min "
                    "(protects your Reed quota). 'send' works any time.",
                )
                return
            self._mark_manual_run()
            self.reply("Running", "Fetching from Reed now - this takes a few minutes.")
            self._background("run", lambda: self.cli("run"), "Fetched")
        else:
            self.reply("Unknown command", f"Didn't understand '{text.strip()[:40]}'.\n\n{HELP}")

    def _background(self, name: str, job: Callable[[], str], needle: str) -> None:
        """Long jobs run in a thread so the listener keeps answering 'status' etc."""
        if not self.busy.acquire(blocking=False):
            self.reply("Busy", f"Still working on the last request - try '{name}' again shortly.")
            return

        def work():
            try:
                out = job()
                if "already running" in out.lower():
                    self.reply("Already running", "The scheduled run is going right now.")
                else:
                    self.reply(f"Done: {name}", _last_line_with(out, needle))
            except Exception as e:  # noqa: BLE001 - always tell the phone something
                log.exception("%s failed", name)
                self.reply(f"{name} failed", str(e)[:300])
            finally:
                self.busy.release()

        threading.Thread(target=work, daemon=True).start()


# --- the long-lived listener --------------------------------------------------------------


def listen(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    if not s.ntfy_command_topic:
        log.warning("NTFY_COMMAND_TOPIC isn't set - phone commands are off. Sleeping.")
        time.sleep(3600)  # systemd restarts us later, picking up any .env change
        return
    if s.ntfy_command_topic == s.ntfy_topic:
        log.error("NTFY_COMMAND_TOPIC must be different from NTFY_TOPIC.")
        time.sleep(3600)
        return

    commander = Commander(s)
    url = f"{s.ntfy_server.rstrip('/')}/{s.ntfy_command_topic}/json"
    headers = {"Authorization": f"Bearer {s.ntfy_token}"} if s.ntfy_token else {}
    since: str | None = None  # last message id, so a reconnect doesn't miss anything
    backoff = 5
    log.info("Listening for phone commands on %s", s.ntfy_command_topic)

    while True:
        params = {"since": since} if since else {}
        try:
            # ntfy sends a keepalive every ~45s, so a long silence means a dead connection.
            timeout = httpx.Timeout(15, read=120)
            with httpx.stream("GET", url, params=params, headers=headers, timeout=timeout) as r:
                r.raise_for_status()
                backoff = 5
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("event") != "message":
                        continue
                    since = ev.get("id") or since
                    commander.handle(ev.get("message", ""))
        except httpx.HTTPError as e:
            log.warning("Connection to ntfy lost (%s) - retrying in %ss", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
