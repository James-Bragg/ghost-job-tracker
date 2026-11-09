from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawPosting:
    """Source-agnostic shape every fetcher returns."""

    source: str
    external_id: str
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    url: str = ""
    posted_at: datetime | None = None
    applications: int | None = None
    description_full: bool = False
    salary_predicted: bool = False


class Fetcher(ABC):
    name: str

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def search(self, keywords: str, location: str, pages: int = 1) -> list[RawPosting]: ...

    def full_description(self, external_id: str) -> str | None:
        """Full advert text, for boards whose search only returns a snippet."""
        return None
