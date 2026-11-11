import json
import time
from datetime import timedelta

import httpx

from ghostjobs.config import Settings
from ghostjobs.db import utcnow
from ghostjobs.listener import Commander, run_lock
from ghostjobs.notify import Notifier


def make(tmp_path, cli_out="Fetched 10, scored 10, notified 2."):
    sent, calls = [], []
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200))
    )
    s = Settings(
        _env_file=None, ntfy_topic="alerts", ntfy_command_topic="cmds", command_cooldown_minutes=30
    )

    def cli(*args):
        calls.append(args)
        return cli_out

    c = Commander(s, Notifier(s, client), cli=cli, state_path=str(tmp_path / "state.json"))
    return c, sent, calls


def wait_idle(c):
    for _ in range(100):
        if not c.busy.locked():
            return
        time.sleep(0.01)


def titles(sent):
    return [r.headers["Title"] for r in sent]


def test_help_has_tap_buttons(tmp_path):
    c, sent, _ = make(tmp_path)
    c.handle("help")
    assert titles(sent) == ["Ghost Job Tracker"]
    actions = sent[0].headers["Actions"]
    assert "https://ntfy.sh/cmds" in actions and "body=run" in actions


def test_run_then_cooldown(tmp_path):
    c, sent, calls = make(tmp_path)
    c.handle("Run")
    wait_idle(c)
    assert calls == [("run",)]
    assert titles(sent) == ["Running", "Done: run"]
    assert b"notified 2" in sent[-1].content
    c.handle("run")  # straight away again -> refused
    assert titles(sent)[-1] == "Not yet"
    assert calls == [("run",)]


def test_cooldown_expires(tmp_path):
    c, sent, calls = make(tmp_path)
    last = (utcnow() - timedelta(minutes=31)).isoformat()
    (tmp_path / "state.json").write_text(json.dumps({"last_run": last}))
    c.handle("run")
    wait_idle(c)
    assert calls == [("run",)]


def test_send_resend_skills_status(tmp_path):
    c, sent, calls = make(tmp_path, cli_out="Sent 3 job(s), sorted by distance.")
    c.handle("send")
    wait_idle(c)
    c.handle("resend")
    wait_idle(c)
    c.handle("skills")
    c.handle("status")
    assert calls == [("notify",), ("notify", "--resend"), ("skills",), ("status",)]


def test_unknown_command(tmp_path):
    c, sent, _ = make(tmp_path)
    c.handle("make me a coffee")
    assert titles(sent) == ["Unknown command"]


def test_scheduled_run_in_progress(tmp_path):
    c, sent, _ = make(tmp_path, cli_out="Another run is already running - skipping this one.")
    c.handle("run")
    wait_idle(c)
    assert titles(sent)[-1] == "Already running"


def test_run_lock_is_exclusive(tmp_path):
    path = str(tmp_path / "x.lock")
    with run_lock(path) as first:
        with run_lock(path) as second:
            assert first and not second
    with run_lock(path) as again:
        assert again
