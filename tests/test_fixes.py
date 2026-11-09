"""Tests for the snippet / syndication / closed-advert / calibration fixes."""

import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlmodel import create_engine, select

from ghostjobs.calibrate import MIN_PER_CLASS, calibrate
from ghostjobs.db import Posting, get_session, init_db
from ghostjobs.fetchers import RawPosting
from ghostjobs.fetchers.adzuna import AdzunaFetcher
from ghostjobs.fetchers.reed import ReedFetcher
from ghostjobs.pipeline import fetch_and_store
from ghostjobs.scoring import DEFAULT_WEIGHTS, load_weights
from ghostjobs.signals import repost_signal, salary_signal, vagueness_signal, volume_signal

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def P(i, **kw):
    base = dict(
        id=i,
        source="reed",
        external_id=str(i),
        title="Junior Developer",
        company="Acme",
        first_seen=NOW,
        last_seen=NOW,
    )
    base.update(kw)
    return Posting(**base)


def test_snippet_not_marked_vague():
    snippet = P(1, source="adzuna", description="Short snippet...", description_full=False)
    assert vagueness_signal(snippet).value == 0
    full = P(2, description="<p>Short full advert.</p>", description_full=True)
    assert vagueness_signal(full).value == 0.5


def test_cross_board_duplicate_is_not_a_repost():
    reed = P(1, source="reed")
    adz = P(2, source="adzuna")
    assert repost_signal(reed, [reed, adz]).value == 0
    again = P(3, source="reed")
    assert repost_signal(reed, [reed, adz, again]).value > 0


def test_closed_adverts_dont_count_towards_volume():
    me = P(0, company="Agency")
    open_ = [P(i, company="Agency", title=f"Role {i}") for i in range(1, 12)]
    closed = [
        P(i, company="Agency", title=f"Old {i}", last_seen=NOW - timedelta(days=20))
        for i in range(20, 60)
    ]
    with_closed = volume_signal(me, [me, *open_, *closed], NOW)
    assert with_closed.value == volume_signal(me, [me, *open_], NOW).value
    assert "12 open adverts" in with_closed.reason


def test_adzuna_predicted_salary_counts_as_missing():
    p = P(1, source="adzuna", salary_min=25000, salary_max=25000, salary_predicted=True)
    assert salary_signal(p).value == 1.0
    raw = AdzunaFetcher._parse(
        {
            "id": 1,
            "title": "x",
            "salary_is_predicted": "1",
            "salary_min": 25000,
            "created": "2026-11-01T10:00:00Z",
        }
    )
    assert raw.salary_predicted and raw.posted_at.tzinfo is not None


def test_reed_full_description_fetched_for_new_jobs_only():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "jobId": 7,
                            "jobTitle": "Junior Developer",
                            "employerName": "Acme",
                            "date": "01/11/2026",
                            "jobDescription": "snippet...",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"jobDescription": "<p>The full advert</p>"})

    fetcher = ReedFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))
    fetcher.api_key = "k"
    engine = create_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as s:
        fetch_and_store(s, "dev", "Corby", fetchers=[fetcher])
        fetch_and_store(s, "dev", "Corby", fetchers=[fetcher])
        p = s.exec(select(Posting)).one()
    assert p.description_full and "full advert" in p.description
    assert calls.count("/api/1.0/jobs/7") == 1  # not re-fetched on the second run


def test_calibration_learns_from_labels(tmp_path):
    ghosts = [
        P(i, title=f"G{i}", company=f"G{i}", label="ghosted", posted_at=NOW - timedelta(days=90))
        for i in range(MIN_PER_CLASS)
    ]
    real = [
        P(
            100 + i,
            title=f"R{i}",
            company=f"R{i}",
            label="responded",
            posted_at=NOW,
            salary_min=25000,
        )
        for i in range(MIN_PER_CLASS)
    ]
    res = calibrate(ghosts + real)
    assert res.enough_data
    # Age separated them perfectly; buzzwords didn't fire at all.
    assert res.weights["age"] > DEFAULT_WEIGHTS["age"]
    assert res.weights["vague"] < DEFAULT_WEIGHTS["vague"]

    f = tmp_path / "w.json"
    f.write_text(json.dumps(res.weights))
    assert load_weights(str(f))["age"] == res.weights["age"]
    assert load_weights(str(tmp_path / "missing.json")) == DEFAULT_WEIGHTS


def test_not_enough_labels():
    assert not calibrate([P(1, label="ghosted")]).enough_data


def test_raw_posting_roundtrip():
    # Every RawPosting field must exist on Posting, or upsert breaks.
    assert set(RawPosting.__dataclass_fields__) <= set(Posting.model_fields)


def test_irrelevant_titles_skip_the_details_call():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "jobId": 8,
                        "jobTitle": "Senior Developer",
                        "employerName": "Acme",
                        "date": "01/11/2026",
                        "jobDescription": "snippet",
                    }
                ]
            },
        )

    fetcher = ReedFetcher(client=httpx.Client(transport=httpx.MockTransport(handler)))
    fetcher.api_key = "k"
    engine = create_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as s:
        fetch_and_store(s, "dev", "Corby", fetchers=[fetcher])
    assert calls == ["/api/1.0/search"]


def test_one_board_failing_doesnt_stop_the_others():
    def broken(req):
        return httpx.Response(429)

    def ok(req):
        if req.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "jobId": 9,
                            "jobTitle": "Senior Developer",
                            "employerName": "Acme",
                            "date": "01/11/2026",
                            "jobDescription": "snippet",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    adz = AdzunaFetcher(client=httpx.Client(transport=httpx.MockTransport(broken)))
    reed = ReedFetcher(client=httpx.Client(transport=httpx.MockTransport(ok)))
    engine = create_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as s:
        assert fetch_and_store(s, "dev", "Corby", fetchers=[adz, reed]) == 1


def test_sources_setting_controls_boards(monkeypatch):
    from ghostjobs import pipeline
    from ghostjobs.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "reed_api_key", "r")
    monkeypatch.setattr(s, "adzuna_app_id", "a")
    monkeypatch.setattr(s, "adzuna_app_key", "b")
    monkeypatch.setattr(s, "sources", "reed")
    assert [f.name for f in pipeline.available_fetchers()] == ["reed"]
    monkeypatch.setattr(s, "sources", "reed,adzuna")
    assert [f.name for f in pipeline.available_fetchers()] == ["reed", "adzuna"]
