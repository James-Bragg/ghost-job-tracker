"""Push notifications to your phone via ntfy (https://ntfy.sh).

Install the ntfy app (Android / iOS), subscribe to your topic, done.
"""

import json

import httpx
from sqlmodel import Session, select

from ghostjobs.config import Settings, get_settings
from ghostjobs.db import Posting, is_active


class Notifier:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.s = settings or get_settings()
        self.client = client or httpx.Client(timeout=15)

    @property
    def enabled(self) -> bool:
        return bool(self.s.ntfy_topic)

    def send(
        self,
        title: str,
        message: str,
        click: str = "",
        tags: str = "briefcase",
        priority: str = "default",
    ) -> None:
        headers = {"Title": title, "Tags": tags, "Priority": priority}
        if click:
            headers["Click"] = click
        if self.s.ntfy_token:
            headers["Authorization"] = f"Bearer {self.s.ntfy_token}"
        # Header values must be latin-1; strip anything else (e.g. emoji in job titles).
        headers = {k: v.encode("latin-1", "ignore").decode("latin-1") for k, v in headers.items()}
        url = f"{self.s.ntfy_server.rstrip('/')}/{self.s.ntfy_topic}"
        self.client.post(url, content=message.encode("utf-8"), headers=headers).raise_for_status()


def _salary(p: Posting) -> str:
    if p.salary_predicted:
        return "Salary not listed (Adzuna estimate shown on site)"
    if p.salary_min and p.salary_max and p.salary_min != p.salary_max:
        return f"£{p.salary_min:,.0f}–£{p.salary_max:,.0f}"
    if p.salary_min or p.salary_max:
        return f"£{(p.salary_min or p.salary_max):,.0f}"
    return "Salary not listed"


def candidates(session: Session, settings: Settings | None = None) -> list[Posting]:
    """Postings that look genuine and haven't been notified yet, best first."""
    s = settings or get_settings()
    q = select(Posting).where(
        Posting.notified == False,  # noqa: E712
        Posting.relevant == True,  # noqa: E712
        Posting.ghost_score.is_not(None),
        Posting.ghost_score <= s.notify_max_score,
    )
    rows = [p for p in session.exec(q.order_by(Posting.ghost_score)).all() if is_active(p)]
    if s.notify_require_salary:
        rows = [p for p in rows if (p.salary_min or p.salary_max) and not p.salary_predicted]

    # The same job is often on Reed *and* Adzuna - only alert once.
    def key(p: Posting) -> tuple[str, str]:
        return p.company.strip().lower(), p.title.strip().lower()

    already = {
        key(p)
        for p in session.exec(select(Posting).where(Posting.notified == True)).all()  # noqa: E712
    }
    unique: list[Posting] = []
    for p in rows:
        if key(p) not in already:
            already.add(key(p))
            unique.append(p)
        else:
            p.notified = True  # covered by the other board's alert
            session.add(p)
    return unique


def notify_genuine(session: Session, notifier: Notifier | None = None) -> int:
    """Send a push for each new genuine-looking posting. Returns how many were covered."""
    notifier = notifier or Notifier()
    if not notifier.enabled:
        return 0
    rows = candidates(session, notifier.s)
    if not rows:
        return 0

    limit = notifier.s.notify_max_per_run
    for p in rows[:limit]:
        reasons = json.loads(p.reasons or "[]")
        body = (
            f"{p.company} · {p.location}\n{_salary(p)}\n"
            f"Ghost score {p.ghost_score:.0f}/100 · #{p.id}"
        )
        if reasons:
            body += f"\nNote: {reasons[0]}"
        notifier.send(title=p.title, message=body, click=p.url, tags="white_check_mark")

    extra = rows[limit:]
    if extra:
        lines = "\n".join(f"• #{p.id} {p.title} @ {p.company}" for p in extra[:15])
        more = f"\n…and {len(extra) - 15} more" if len(extra) > 15 else ""
        notifier.send(
            title=f"{len(extra)} more genuine-looking jobs",
            message=lines + more,
            tags="clipboard",
            priority="low",
        )

    for p in rows:
        p.notified = True
        session.add(p)
    session.commit()
    return len(rows)
