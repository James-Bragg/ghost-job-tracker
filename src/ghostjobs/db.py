"""Database models and session helpers."""

from datetime import UTC, datetime

from sqlalchemy import inspect, text
from sqlmodel import Field, Session, SQLModel, UniqueConstraint, create_engine

from ghostjobs.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Posting(SQLModel, table=True):
    """One job advert from one source. Re-seen on later fetches -> last_seen/times_seen update."""

    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)  # "adzuna" | "reed"
    external_id: str
    title: str
    company: str = Field(default="", index=True)
    location: str = ""
    description: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    url: str = ""
    posted_at: datetime | None = None  # date the board says it was posted
    applications: int | None = None  # Reed exposes this; Adzuna doesn't
    description_full: bool = False  # False = search-result snippet only
    salary_predicted: bool = False  # Adzuna's own estimate, not the employer's

    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)
    times_seen: int = 1

    ghost_score: float | None = Field(default=None, index=True)
    reasons: str = ""  # JSON list of human-readable reasons

    # Your own ground truth, for training a model later:
    # "responded" | "ghosted" | "rejected" | None
    label: str | None = None

    notified: bool = False  # phone notification already sent

    relevant: bool = True  # matches your relevance.toml
    irrelevant_reason: str = ""


def as_utc(d: datetime) -> datetime:
    """Older DBs / drivers may hand back naive datetimes; treat those as UTC."""
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def is_active(p: Posting, now: datetime | None = None, stale_days: int | None = None) -> bool:
    """An advert counts as still open if a fetch has seen it in the last few days."""
    if stale_days is None:
        stale_days = get_settings().stale_after_days
    return ((now or utcnow()) - as_utc(p.last_seen)).days < stale_days


class Place(SQLModel, table=True):
    """Cache of town name -> coordinates, so each place is only looked up once."""

    name: str = Field(primary_key=True)
    lat: float | None = None
    lon: float | None = None


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url)
    return _engine


# Columns added after the first release: (name, SQL type + default).
_ADDED_COLUMNS = [
    ("notified", "BOOLEAN NOT NULL DEFAULT 0"),
    ("description_full", "BOOLEAN NOT NULL DEFAULT 0"),
    ("salary_predicted", "BOOLEAN NOT NULL DEFAULT 0"),
    ("relevant", "BOOLEAN NOT NULL DEFAULT 1"),
    ("irrelevant_reason", "VARCHAR NOT NULL DEFAULT ''"),
]


def init_db(engine=None) -> None:
    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)
    # Tiny migration so an existing ghostjobs.db picks up new columns.
    existing = {c["name"] for c in inspect(engine).get_columns("posting")}
    with engine.begin() as conn:
        for name, ddl in _ADDED_COLUMNS:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE posting ADD COLUMN {name} {ddl}"))


def get_session(engine=None) -> Session:
    return Session(engine or get_engine())
