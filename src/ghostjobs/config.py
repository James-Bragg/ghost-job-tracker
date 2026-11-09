from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    reed_api_key: str = ""

    database_url: str = "sqlite:///ghostjobs.db"
    default_keywords: str = "junior developer"
    default_location: str = "Corby"
    search_radius_miles: int = 20

    # An advert not seen by any fetch for this many days is treated as taken down.
    stale_after_days: int = 3
    # Reed only returns a snippet in search results; fetch full text for this many new jobs/run.
    reed_details_per_run: int = 60
    # Learned weights from `ghostjobs calibrate --apply` (optional).
    weights_path: str = "weights.json"
    # Which jobs are worth notifying you about.
    relevance_path: str = "relevance.toml"

    # Searches run by `ghostjobs run`, separated by ";". Falls back to default_keywords.
    searches: str = ""

    # Phone notifications via ntfy (https://ntfy.sh). Leave topic blank to disable.
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""  # only needed for a protected/self-hosted topic
    notify_max_score: float = 30  # notify when ghost score is at or below this
    notify_require_salary: bool = False
    notify_max_per_run: int = 5  # anything beyond this is sent as one summary

    def search_list(self) -> list[str]:
        items = [s.strip() for s in self.searches.split(";") if s.strip()]
        return items or [self.default_keywords]


@lru_cache
def get_settings() -> Settings:
    return Settings()
