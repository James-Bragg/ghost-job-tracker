from datetime import UTC, datetime, timedelta

from ghostjobs.db import Posting
from ghostjobs.scoring import score, verdict
from ghostjobs.signals import compute_signals

NOW = datetime(2026, 11, 8, tzinfo=UTC)
GOOD_DESC = " ".join(["We are hiring a junior Python developer to join our data team."] * 10)


def make(**kw) -> Posting:
    base = dict(
        id=1,
        source="reed",
        external_id="1",
        title="Junior Python Developer",
        company="Acme Ltd",
        description=GOOD_DESC,
        salary_min=26000,
        salary_max=30000,
        posted_at=NOW - timedelta(days=3),
    )
    base.update(kw)
    return Posting(**base)


def test_fresh_detailed_posting_looks_genuine():
    p = make()
    value, reasons = score(compute_signals(p, [p], NOW))
    assert value < 35
    assert verdict(value) == "Looks genuine"


def test_old_vague_reposted_posting_is_ghost():
    p = make(
        posted_at=NOW - timedelta(days=90),
        salary_min=None,
        salary_max=None,
        description="Join our talent pool! We are always looking for rockstars.",
    )
    reposts = [make(id=i, external_id=str(i)) for i in range(2, 6)]
    value, reasons = score(compute_signals(p, [p, *reposts], NOW))
    assert value >= 60
    assert any("talent-pool" in r.lower() for r in reasons)
    assert any("posted 5 times" in r.lower() for r in reasons)
