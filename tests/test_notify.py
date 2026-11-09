import httpx
from sqlmodel import create_engine

from ghostjobs.config import Settings
from ghostjobs.db import Posting, get_session, init_db
from ghostjobs.notify import Notifier, notify_genuine


def setup():
    engine = create_engine("sqlite://")
    init_db(engine)
    sent: list[httpx.Request] = []
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: sent.append(req) or httpx.Response(200))
    )
    settings = Settings(
        _env_file=None, ntfy_topic="test-topic", notify_max_per_run=2, notify_delay_seconds=0
    )
    return engine, Notifier(settings, client), sent


def add(session, i, score, **kw):
    session.add(
        Posting(
            source="reed",
            external_id=str(i),
            title=f"Job {i}",
            company="Acme",
            ghost_score=score,
            url=f"https://example.com/{i}",
            **kw,
        )
    )


def test_only_genuine_postings_notified_once():
    engine, notifier, sent = setup()
    with get_session(engine) as s:
        add(s, 1, 10, salary_min=25000)
        add(s, 2, 80)  # ghost - skipped
        s.commit()
        assert notify_genuine(s, notifier) == 1
        assert len(sent) == 1
        assert sent[0].headers["Title"] == "Job 1"
        assert sent[0].headers["Click"] == "https://example.com/1"
        assert b"25,000" in sent[0].content

        # Second run: nothing new, nothing sent
        assert notify_genuine(s, notifier) == 0
        assert len(sent) == 1


def test_overflow_is_summarised():
    engine, notifier, sent = setup()
    with get_session(engine) as s:
        for i in range(5):
            add(s, i, 5 + i)
        s.commit()
        assert notify_genuine(s, notifier) == 5
        # 2 individual + 1 summary
        assert len(sent) == 3
        titles = [r.headers["Title"] for r in sent]
        assert "3 more genuine-looking jobs" in titles


def test_disabled_without_topic():
    engine, _, sent = setup()
    notifier = Notifier(Settings(_env_file=None, ntfy_topic=""))
    with get_session(engine) as s:
        add(s, 1, 10)
        s.commit()
        assert notify_genuine(s, notifier) == 0


def test_migration_adds_notified_column():
    engine = create_engine("sqlite://")
    # Simulate an old DB without the column
    with engine.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE posting (id INTEGER PRIMARY KEY, source TEXT, external_id TEXT)"
        )
    init_db(engine)
    with engine.begin() as c:
        cols = [r[1] for r in c.exec_driver_sql("PRAGMA table_info(posting)")]
    assert "notified" in cols


def test_same_job_on_two_boards_alerts_once():
    engine, notifier, sent = setup()
    with get_session(engine) as s:
        add(s, 1, 0)
        s.add(
            Posting(source="adzuna", external_id="1", title="Job 1", company="Acme", ghost_score=0)
        )
        s.commit()
        assert notify_genuine(s, notifier) == 1
        assert len(sent) == 1


def test_zero_means_every_job_individually():
    engine, notifier, sent = setup()
    notifier.s.notify_max_per_run = 0
    with get_session(engine) as s:
        for i in range(8):
            add(s, i, 5)
        s.commit()
        assert notify_genuine(s, notifier) == 8
        assert len(sent) == 8
        assert not any("more genuine" in r.headers["Title"] for r in sent)


def test_rate_limited_part_way_resumes_next_run():
    engine = create_engine("sqlite://")
    init_db(engine)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429 if calls["n"] == 3 else 200)

    settings = Settings(
        _env_file=None, ntfy_topic="t", notify_max_per_run=0, notify_delay_seconds=0
    )
    notifier = Notifier(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    with get_session(engine) as s:
        for i in range(5):
            add(s, i, 5)
        s.commit()
        assert notify_genuine(s, notifier) == 2  # third one was refused
        assert notify_genuine(s, notifier) == 3  # the rest go next time, none repeated
        assert calls["n"] == 6
