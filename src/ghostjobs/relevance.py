"""Is this job actually relevant to you? Rules live in relevance.toml."""

import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ghostjobs.config import get_settings
from ghostjobs.db import Posting

YEARS_RE = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*years?[’']?\s*(?:of\s+)?"
    r"(?:commercial|professional|industry|relevant|proven|hands[- ]on|demonstrable|previous)?"
    r"\s*(?:\w+\s+){0,3}?experience",
    re.IGNORECASE,
)


@dataclass
class Rules:
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    max_years_experience: int = 0
    description_exclude: list[str] = field(default_factory=list)
    min_salary: float = 0


def _phrase_re(phrases: list[str]) -> re.Pattern | None:
    if not phrases:
        return None
    # Whole-word match that still works for things like "c#" and ".net".
    alts = "|".join(re.escape(p.lower()) for p in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"(?<![\w#.])(?:{alts})(?![\w#])", re.IGNORECASE)


@lru_cache
def load_rules(path: str | None = None) -> Rules:
    p = Path(path or get_settings().relevance_path)
    if not p.is_file():
        return Rules()  # no file = everything is relevant
    data = tomllib.loads(p.read_text())
    return Rules(**{k: v for k, v in data.items() if k in Rules.__dataclass_fields__})


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def check_title(title: str, rules: Rules | None = None) -> tuple[bool, str]:
    rules = rules or load_rules()
    inc, exc = _phrase_re(rules.title_include), _phrase_re(rules.title_exclude)
    if exc and (m := exc.search(title)):
        return False, f'title contains "{m.group(0)}"'
    if inc and not inc.search(title):
        return False, "title doesn't match any role you're looking for"
    return True, ""


def check(p: Posting, rules: Rules | None = None) -> tuple[bool, str]:
    """(relevant?, reason if not)."""
    rules = rules or load_rules()
    ok, why = check_title(p.title, rules)
    if not ok:
        return ok, why

    text = _plain(p.description)
    if rules.max_years_experience:
        years = [int(m.group(1)) for m in YEARS_RE.finditer(text)]
        if years and min(years) >= rules.max_years_experience:
            return False, f"asks for {min(years)}+ years' experience"

    if (dx := _phrase_re(rules.description_exclude)) and (m := dx.search(text)):
        return False, f'description mentions "{m.group(0)}"'

    if rules.min_salary and not p.salary_predicted:
        top = p.salary_max or p.salary_min
        if top and top < rules.min_salary:
            return False, f"salary £{top:,.0f} is below your £{rules.min_salary:,.0f} minimum"

    return True, ""
