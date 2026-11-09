"""Reed API client. Docs: https://www.reed.co.uk/developers/jobseeker"""

from datetime import UTC, datetime

import httpx

from ghostjobs.config import get_settings
from ghostjobs.fetchers.base import Fetcher, RawPosting

BASE_URL = "https://www.reed.co.uk/api/1.0/search"
DETAILS_URL = "https://www.reed.co.uk/api/1.0/jobs/{job_id}"


class ReedFetcher(Fetcher):
    name = "reed"

    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        self.api_key = s.reed_api_key
        self.radius_miles = s.search_radius_miles
        # Reed uses HTTP basic auth: API key as username, blank password.
        self.client = client or httpx.Client(timeout=20, auth=(self.api_key, ""))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(self, keywords: str, location: str, pages: int = 1) -> list[RawPosting]:
        results: list[RawPosting] = []
        per_page = 100
        for page in range(pages):
            resp = self.client.get(
                BASE_URL,
                params={
                    "keywords": keywords,
                    "locationName": location,
                    "distanceFromLocation": self.radius_miles,
                    "resultsToTake": per_page,
                    "resultsToSkip": page * per_page,
                },
            )
            resp.raise_for_status()
            jobs = resp.json().get("results", [])
            results.extend(self._parse(j) for j in jobs)
            if len(jobs) < per_page:
                break
        return results

    def full_description(self, external_id: str) -> str | None:
        resp = self.client.get(DETAILS_URL.format(job_id=external_id))
        if resp.status_code == 404:  # taken down between search and details
            return None
        resp.raise_for_status()
        return resp.json().get("jobDescription") or None

    @staticmethod
    def _parse(j: dict) -> RawPosting:
        date = j.get("date")  # "dd/mm/yyyy"
        return RawPosting(
            source="reed",
            external_id=str(j["jobId"]),
            title=j.get("jobTitle", ""),
            company=j.get("employerName", ""),
            location=j.get("locationName", ""),
            description=j.get("jobDescription", ""),  # snippet; see full_description()
            salary_min=j.get("minimumSalary"),
            salary_max=j.get("maximumSalary"),
            url=j.get("jobUrl", ""),
            posted_at=datetime.strptime(date, "%d/%m/%Y").replace(tzinfo=UTC) if date else None,
            applications=j.get("applications"),
        )
