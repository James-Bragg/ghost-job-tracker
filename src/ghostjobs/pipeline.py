"""Fetch -> store -> score."""

import json
import logging

import httpx
from sqlmodel import Session, select

from ghostjobs.config import get_settings
from ghostjobs.db import Posting, utcnow
from ghostjobs.fetchers import AdzunaFetcher, Fetcher, RawPosting, ReedFetcher
from ghostjobs.relevance import check, check_title, load_rules
from ghostjobs.scoring import load_weights, score
from ghostjobs.signals import compute_signals

log = logging.getLogger(__name__)


def available_fetchers() -> list[Fetcher]:
    return [f for f in (AdzunaFetcher(), ReedFetcher()) if f.is_configured()]


def upsert(session: Session, raw: RawPosting) -> tuple[Posting, bool]:
    """Insert a new posting or refresh an existing one. Returns (posting, is_new)."""
    existing = session.exec(
        select(Posting).where(Posting.source == raw.source, Posting.external_id == raw.external_id)
    ).first()
    if existing:
        existing.last_seen = utcnow()
        existing.times_seen += 1
        existing.applications = raw.applications or existing.applications
        session.add(existing)
        return existing, False
    p = Posting(**raw.__dict__)
    session.add(p)
    return p, True


def fetch_and_store(
    session: Session,
    keywords: str,
    location: str,
    pages: int = 1,
    fetchers: list[Fetcher] | None = None,
    details_budget: dict | None = None,
) -> int:
    budget = (
        details_budget
        if details_budget is not None
        else {"left": get_settings().reed_details_per_run}
    )
    count = 0
    for fetcher in fetchers if fetchers is not None else available_fetchers():
        for raw in fetcher.search(keywords, location, pages):
            p, is_new = upsert(session, raw)
            count += 1
            # Snippet-only boards: grab the full advert once - only for new jobs whose
            # title you'd care about, so API calls aren't wasted on irrelevant ones.
            if is_new and not p.description_full and budget["left"] > 0 and check_title(p.title)[0]:
                try:
                    full = fetcher.full_description(p.external_id)
                except httpx.HTTPError as e:
                    log.warning("Couldn't get full description for %s: %s", p.external_id, e)
                    full = None
                if full:
                    budget["left"] -= 1
                    p.description, p.description_full = full, True
    session.commit()
    return count


def run_all(session: Session, location: str, pages: int = 1) -> dict:
    """Everything a scheduled run does: every saved search -> score -> notify."""
    from ghostjobs.notify import notify_genuine

    fetchers = available_fetchers()
    budget = {"left": get_settings().reed_details_per_run}
    fetched = 0
    for keywords in get_settings().search_list():
        fetched += fetch_and_store(session, keywords, location, pages, fetchers, budget)
    scored = rescore_all(session)
    notified = notify_genuine(session)
    return {"fetched": fetched, "scored": scored, "notified": notified}


def rescore_all(session: Session) -> int:
    postings = list(session.exec(select(Posting)).all())
    weights = load_weights()
    rules = load_rules()
    for p in postings:
        p.relevant, p.irrelevant_reason = check(p, rules)
        value, reasons = score(compute_signals(p, postings), weights)
        p.ghost_score = value
        p.reasons = json.dumps(reasons)
        session.add(p)
    session.commit()
    return len(postings)
