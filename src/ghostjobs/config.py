from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Which job boards to use, comma-separated: "reed", "adzuna" or "reed,adzuna".
    # A board also needs its key(s) below. Adzuna is off by default: its free tier is only
    # 25 test calls; full access is a paid plan.
    sources: str = "reed"

    reed_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    database_url: str = "sqlite:///ghostjobs.db"
    default_keywords: str = "junior developer"
    default_location: str = "Corby"
    search_radius_miles: int = 20
    # Result pages per search (Reed: 100 jobs/page). Raise this for a wide radius, otherwise
    # jobs past page 1 are missed and can wrongly look "taken down".
    pages: int = 1

    # An advert not seen by any fetch for this many days is treated as taken down.
    stale_after_days: int = 3
    # Reed only returns a snippet in search results; fetch full text for this many new jobs/run.
    reed_details_per_run: int = 60
    # Learned weights from `ghostjobs calibrate --apply` (optional).
    weights_path: str = "weights.json"
    # Which jobs are worth notifying you about.
    relevance_path: str = "relevance.toml"
    # Skills / tools / certs to count in adverts.
    skills_path: str = "skills.toml"

    # Phone commands: a SECOND ntfy topic the Pi listens on. Send "run", "skills", "help"...
    # from the ntfy app. Leave blank to turn off. Make it long and random too.
    ntfy_command_topic: str = ""
    # Minimum minutes between phone-triggered full runs (protects your Reed quota).
    command_cooldown_minutes: int = 30

    # Searches run by `ghostjobs run`, separated by ";". Falls back to default_keywords.
    searches: str = ""

    # Phone notifications via ntfy (https://ntfy.sh). Leave topic blank to disable.
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""  # only needed for a protected/self-hosted topic
    notify_max_score: float = 30  # notify when ghost score is at or below this
    notify_require_salary: bool = False
    notify_max_per_run: int = 5  # beyond this -> one summary. 0 = every job its own alert
    notify_delay_seconds: float = 1.0  # pause between alerts (ntfy.sh rate-limits bursts)
    # Order alerts by any of: distance, score, salary, newest, title, company.
    # Comma-separate for tie-breaks, e.g. "distance,score".
    notify_sort: str = "score"
    # Phones list the newest notification at the top, so send in reverse to make the
    # list read top-to-bottom in the order above.
    notify_reverse_send: bool = True

    def source_list(self) -> list[str]:
        return [s.strip().lower() for s in self.sources.split(",") if s.strip()]

    def search_list(self) -> list[str]:
        items = [s.strip() for s in self.searches.split(";") if s.strip()]
        return items or [self.default_keywords]


@lru_cache
def get_settings() -> Settings:
    return Settings()
