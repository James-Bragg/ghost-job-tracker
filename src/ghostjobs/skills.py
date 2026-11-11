"""Which skills, tools and certs do local entry-level adverts keep asking for?

Each posting's description is scanned against skills.toml when it's scored, and the matches
are stored on the posting. `report()` then counts them across the relevant jobs you've
seen, overall and per kind of role, so you can see what's worth learning.
"""

import json
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlmodel import Session, select

from ghostjobs.config import get_settings
from ghostjobs.db import Posting, as_utc, utcnow

# Kind of role, from the title. First match wins.
ROLE_FAMILIES: list[tuple[str, re.Pattern]] = [
    ("data", re.compile(r"\b(data|bi|business intelligence|reporting|analytics|sql)\b", re.I)),
    ("testing", re.compile(r"\b(qa|test|tester|testing|quality assurance)\b", re.I)),
    ("security", re.compile(r"\b(cyber|security|soc)\b", re.I)),
    (
        "support",
        re.compile(
            r"\b(support|service desk|help ?desk|technician|1st line|2nd line|first line|"
            r"second line|desktop|it analyst|end user)\b",
            re.I,
        ),
    ),
    (
        "infrastructure",
        re.compile(r"\b(infrastructure|network|systems? admin|sysadmin|cloud|devops)\b", re.I),
    ),
    (
        "development",
        re.compile(
            r"\b(developer|software|programmer|engineer|web|front ?end|back ?end|full ?stack)\b",
            re.I,
        ),
    ),
]
FAMILY_NAMES = [name for name, _ in ROLE_FAMILIES] + ["other"]


def role_family(title: str) -> str:
    for name, rx in ROLE_FAMILIES:
        if rx.search(title or ""):
            return name
    return "other"


@dataclass
class Skill:
    name: str
    category: str
    pattern: re.Pattern


def _alias_regex(aliases: list[str]) -> re.Pattern:
    """Lower-case aliases ignore case; aliases with capitals must match exactly."""
    parts = []
    for a in sorted(aliases, key=len, reverse=True):
        body = re.escape(a)
        parts.append(body if a != a.lower() else f"(?i:{body})")
    # Whole-word-ish edges that still work for c#, c++, .net, node.js, ci/cd...
    return re.compile(rf"(?<![\w#+.])(?:{'|'.join(parts)})(?![\w#+])")


@lru_cache
def load_skills(path: str | None = None) -> list[Skill]:
    p = Path(path or get_settings().skills_path)
    if not p.is_file():
        return []
    data = tomllib.loads(p.read_text())
    return [
        Skill(name, category, _alias_regex(aliases))
        for category, entries in data.items()
        if isinstance(entries, dict)
        for name, aliases in entries.items()
        if aliases
    ]


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def extract(text: str, skills: list[Skill] | None = None) -> list[str]:
    text = _plain(text)
    return [
        s.name for s in (skills if skills is not None else load_skills()) if s.pattern.search(text)
    ]


@dataclass
class SkillsReport:
    days: int
    total: int  # relevant jobs counted
    full_text: int  # of which we had the full advert (more reliable)
    overall: list[tuple[str, int]]
    by_family: dict[str, tuple[int, list[tuple[str, int]]]]  # family -> (jobs, top skills)
    categories: dict[str, str]


def report(
    session: Session, days: int = 30, family: str | None = None, now: datetime | None = None
) -> SkillsReport:
    """Count skills across relevant jobs first seen in the last `days` days (0 = all time)."""
    now = now or utcnow()
    cutoff = now - timedelta(days=days) if days else None
    rows = [
        p
        for p in session.exec(select(Posting).where(Posting.relevant == True)).all()  # noqa: E712
        if cutoff is None or as_utc(p.first_seen) >= cutoff
    ]
    # The same job on two boards shouldn't count twice.
    seen, unique = set(), []
    for p in rows:
        k = (p.company.strip().lower(), p.title.strip().lower())
        if k not in seen:
            seen.add(k)
            unique.append(p)
    if family:
        unique = [p for p in unique if role_family(p.title) == family]

    overall: Counter[str] = Counter()
    fam_jobs: Counter[str] = Counter()
    fam_skills: dict[str, Counter[str]] = {f: Counter() for f in FAMILY_NAMES}
    for p in unique:
        skills = json.loads(p.skills or "[]")
        fam = role_family(p.title)
        fam_jobs[fam] += 1
        overall.update(skills)
        fam_skills[fam].update(skills)

    return SkillsReport(
        days=days,
        total=len(unique),
        full_text=sum(p.description_full for p in unique),
        overall=overall.most_common(),
        by_family={
            f: (fam_jobs[f], fam_skills[f].most_common()) for f in FAMILY_NAMES if fam_jobs[f]
        },
        categories={s.name: s.category for s in load_skills()},
    )


def format_report(r: SkillsReport, top: int = 15, per_family: int = 5) -> str:
    if not r.total:
        return "No relevant jobs in that period yet - give it a few runs."
    period = f"last {r.days} days" if r.days else "all time"

    def pct(n: int, of: int) -> str:
        return f"{round(100 * n / of):>3}%"

    lines = [f"Skills asked for in {r.total} relevant jobs ({period})"]
    for name, n in r.overall[:top]:
        lines.append(f"{pct(n, r.total)}  {name}")
    families = r.by_family if len(r.by_family) > 1 else {}
    for fam, (jobs, skills) in sorted(families.items(), key=lambda kv: -kv[1][0]):
        if jobs < 3 or not skills:
            continue
        top_s = ", ".join(f"{name} {round(100 * n / jobs)}%" for name, n in skills[:per_family])
        lines.append(f"\n{fam.title()} ({jobs} jobs): {top_s}")
    if r.full_text < r.total:
        lines.append(
            f"\n({r.full_text}/{r.total} from full adverts; the rest from short previews, "
            "so real figures are likely a bit higher.)"
        )
    return "\n".join(lines)
