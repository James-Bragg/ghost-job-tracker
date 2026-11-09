from datetime import UTC, datetime, timedelta

import httpx
from sqlmodel import create_engine

from ghostjobs.config import Settings
from ghostjobs.db import Posting, get_session, init_db
from ghostjobs.geo import Geocoder, haversine_miles
from ghostjobs.notify import Notifier, notify_genuine, sort_postings

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def P(i, **kw):
    base = dict(
        id=i,
        source="reed",
        external_id=str(i),
        title=f"Job {i}",
        company="Acme",
        ghost_score=10,
        posted_at=NOW,
    )
    base.update(kw)
    return Posting(**base)


def test_sort_by_distance_then_score():
    rows = [P(1, ghost_score=5), P(2, ghost_score=1), P(3, ghost_score=0), P(4)]
    miles = {1: 30.0, 2: 5.0, 3: 30.0, 4: None}
    assert [p.id for p in sort_postings(rows, "distance,score", miles)] == [2, 3, 1, 4]


def test_sort_by_salary_newest_title_company():
    rows = [
        P(1, salary_max=25000, title="b", company="Z", posted_at=NOW - timedelta(days=3)),
        P(2, salary_max=31000, title="a", company="Y", posted_at=NOW - timedelta(days=1)),
        P(3, salary_max=40000, salary_predicted=True, title="c", company="X", posted_at=NOW),
    ]
    assert [p.id for p in sort_postings(rows, "salary")] == [2, 1, 3]  # estimate counts as none
    assert [p.id for p in sort_postings(rows, "newest")] == [3, 2, 1]
    assert [p.id for p in sort_postings(rows, "title")] == [2, 1, 3]
    assert [p.id for p in sort_postings(rows, "company")] == [3, 2, 1]
    assert [p.id for p in sort_postings(rows, "nonsense")] == [1, 2, 3]  # falls back to score


def test_phone_list_reads_in_sorted_order():
    """Sent in reverse, so the phone (newest on top) shows the closest job first."""
    engine = create_engine("sqlite://")
    init_db(engine)
    sent = []
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200))
    )
    s = Settings(
        _env_file=None,
        ntfy_topic="t",
        notify_max_per_run=2,
        notify_delay_seconds=0,
        notify_sort="distance",
    )
    with get_session(engine) as ses:
        for i in (1, 2, 3, 4):
            ses.add(P(i, id=None, location=f"Town {i}"))
        ses.commit()
        miles = {1: 40.0, 2: 3.0, 3: 12.0, 4: 60.0}
        assert notify_genuine(ses, Notifier(s, client), distances=miles) == 4
    titles = [r.headers["Title"] for r in sent]
    # Sent: summary, then 2nd-closest, then closest -> phone shows closest at the top.
    assert titles == ["2 more genuine-looking jobs", "Job 3", "Job 2"]
    assert b"(3 mi)" in sent[-1].content


def test_geocoder_caches_and_measures():
    calls = []

    def handler(req):
        calls.append(req.url.params.get("q"))
        q = req.url.params.get("q")
        places = {
            "Corby": [
                {
                    "name_1": "Corby Glen",
                    "local_type": "Village",
                    "latitude": 52.81,
                    "longitude": -0.52,
                },
                {
                    "name_1": "Corby",
                    "local_type": "Town",
                    "latitude": 52.4887,
                    "longitude": -0.7014,
                },
            ],
            "Northampton": [
                {
                    "name_1": "Northampton",
                    "local_type": "Town",
                    "latitude": 52.2405,
                    "longitude": -0.9027,
                }
            ],
        }
        return httpx.Response(200, json={"result": places.get(q, [])})

    engine = create_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as ses:
        geo = Geocoder(ses, httpx.Client(transport=httpx.MockTransport(handler)))
        d = geo.miles_from_home("Northampton")
        assert 18 < d < 21
        geo.miles_from_home("Northampton")
        assert calls.count("Northampton") == 1  # cached
        assert geo.miles_from_home("Remote") is None
        assert geo.miles_from_home("Nowhereville") is None
        geo.miles_from_home("Nowhereville")
        assert calls.count("Nowhereville") == 1  # misses are cached too


def test_haversine():
    assert 40 < haversine_miles((51.5074, -0.1278), (51.7520, -1.2577)) < 60  # London-Oxford
