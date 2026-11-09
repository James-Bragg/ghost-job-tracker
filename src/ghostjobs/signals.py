"""Turn a posting into ghost-job signals. Each signal is a value in 0..1 (1 = more ghost-like)."""

import re
from dataclasses import dataclass
from datetime import datetime

from rapidfuzz import fuzz

from ghostjobs.db import Posting, as_utc, is_active, utcnow

EVERGREEN_PHRASES = [
    "always looking",
    "talent pool",
    "future opportunities",
    "pipeline of",
    "register your interest",
    "speculative",
    "ongoing recruitment",
    "rolling basis",
]

VAGUE_PHRASES = [
    "fast-paced environment",
    "competitive salary",
    "dynamic team",
    "rockstar",
    "ninja",
    "self-starter",
    "wear many hats",
    "other duties as assigned",
]

SIGNAL_NAMES = ["age", "reposts", "evergreen", "no_salary", "vague", "volume", "applications"]


@dataclass
class Signal:
    name: str
    value: float  # 0..1
    reason: str


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _plain(text: str) -> str:
    """Reed's full descriptions are HTML."""
    return re.sub(r"<[^>]+>", " ", text or "")


def age_signal(p: Posting, now: datetime | None = None) -> Signal:
    now = as_utc(now or utcnow())
    start = as_utc(p.posted_at or p.first_seen)
    # For a closed advert, measure how long it was up, not time since it opened.
    end = now if is_active(p, now) else min(now, as_utc(p.last_seen))
    days = max(0, (end - start).days)
    # 0 at <=14 days, 1 at >=60 days
    return Signal("age", _clamp((days - 14) / 46), f"Advert has been up {days} days")


def salary_signal(p: Posting) -> Signal:
    if p.salary_min is None and p.salary_max is None:
        return Signal("no_salary", 1.0, "No salary listed")
    if p.salary_predicted:
        return Signal("no_salary", 1.0, "No salary from employer (figure is Adzuna's estimate)")
    return Signal("no_salary", 0.0, "")


def evergreen_signal(p: Posting) -> Signal:
    text = f"{p.title} {_plain(p.description)}".lower()
    hits = [ph for ph in EVERGREEN_PHRASES if ph in text]
    return Signal(
        "evergreen",
        _clamp(len(hits) / 2),
        f"Talent-pool wording: {', '.join(hits)}" if hits else "",
    )


def vagueness_signal(p: Posting) -> Signal:
    text = _plain(p.description).lower()
    hits = sum(ph in text for ph in VAGUE_PHRASES)
    parts = []
    short = 0.0
    # Search results only carry a snippet, so length only means something for the full text.
    if p.description_full:
        words = len(re.findall(r"\w+", text))
        if words < 80:
            short = 1.0
            parts.append(f"very short description ({words} words)")
    if hits:
        parts.append(f"{hits} buzzword phrase(s)")
    value = _clamp(0.5 * short + 0.25 * hits)
    return Signal("vague", value, "; ".join(parts).capitalize())


def _same_employer(a: Posting, b: Posting) -> bool:
    return bool(a.company) and a.company.strip().lower() == b.company.strip().lower()


def repost_signal(p: Posting, others: list[Posting], threshold: int = 95) -> Signal:
    """Same board + same employer + near-identical title under a different ID = a repost.

    The same job appearing on Reed *and* Adzuna is normal syndication, so other boards
    are ignored here.
    """
    dupes = [
        o
        for o in others
        if o.id != p.id
        and o.source == p.source
        and _same_employer(o, p)
        and fuzz.token_sort_ratio(o.title, p.title) >= threshold
    ]
    n = len(dupes)
    return Signal(
        "reposts", _clamp(n / 3), f"Posted {n + 1} times on {p.source} (reposts)" if n else ""
    )


def volume_signal(p: Posting, others: list[Posting], now: datetime | None = None) -> Signal:
    """Lots of *currently open* adverts from one employer (often agencies harvesting CVs)."""
    if not p.company:
        return Signal("volume", 0.0, "")
    titles = {
        o.title.strip().lower()  # one job on two boards counts once
        for o in others
        if _same_employer(o, p) and is_active(o, now)
    }
    n = len(titles)
    return Signal(
        "volume", _clamp((n - 5) / 25), f"{n} open adverts from this employer" if n > 5 else ""
    )


def applications_signal(p: Posting) -> Signal:
    if p.applications is None:
        return Signal("applications", 0.0, "")
    return Signal(
        "applications",
        _clamp((p.applications - 100) / 400),
        f"{p.applications} applications already" if p.applications > 100 else "",
    )


def compute_signals(p: Posting, others: list[Posting], now: datetime | None = None) -> list[Signal]:
    return [
        age_signal(p, now),
        salary_signal(p),
        evergreen_signal(p),
        vagueness_signal(p),
        repost_signal(p, others),
        volume_signal(p, others, now),
        applications_signal(p),
    ]
