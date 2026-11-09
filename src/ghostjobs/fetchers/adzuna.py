"""Adzuna API client. Docs: https://developer.adzuna.com/docs/search"""

from datetime import datetime

import httpx

from ghostjobs.config import get_settings
from ghostjobs.fetchers.base import Fetcher, RawPosting

BASE_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"


class AdzunaFetcher(Fetcher):
    name = "adzuna"

    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        self.app_id, self.app_key = s.adzuna_app_id, s.adzuna_app_key
        self.radius_miles = s.search_radius_miles
        self.client = client or httpx.Client(timeout=20)

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_key)

    def search(self, keywords: str, location: str, pages: int = 1) -> list[RawPosting]:
        results: list[RawPosting] = []
        for page in range(1, pages + 1):
            resp = self.client.get(
                BASE_URL.format(page=page),
                params={
                    "app_id": self.app_id,
                    "app_key": self.app_key,
                    "what": keywords,
                    "where": location,
                    "distance": round(self.radius_miles * 1.609),  # km
                    "results_per_page": 50,
                    "content-type": "application/json",
                },
            )
            resp.raise_for_status()
            jobs = resp.json().get("results", [])
            results.extend(self._parse(j) for j in jobs)
            if len(jobs) < 50:
                break
        return results

    @staticmethod
    def _parse(j: dict) -> RawPosting:
        created = j.get("created")
        return RawPosting(
            source="adzuna",
            external_id=str(j["id"]),
            title=j.get("title", ""),
            company=(j.get("company") or {}).get("display_name", ""),
            location=(j.get("location") or {}).get("display_name", ""),
            description=j.get("description", ""),  # a snippet - Adzuna has no full-text API
            description_full=False,
            salary_min=j.get("salary_min"),
            # "1" means Adzuna guessed the salary; the employer didn't publish one.
            salary_predicted=str(j.get("salary_is_predicted", "0")).lower() in ("1", "true"),
            salary_max=j.get("salary_max"),
            url=j.get("redirect_url", ""),
            posted_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
        )
