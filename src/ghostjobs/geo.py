"""Distance from home, using free UK place lookups from postcodes.io (no key needed).

Each town name is looked up once and cached in the database, so after the first run this
is almost entirely offline.
"""

import logging
import math
import re

import httpx
from sqlmodel import Session

from ghostjobs.config import get_settings
from ghostjobs.db import Place

log = logging.getLogger(__name__)

PLACES_URL = "https://api.postcodes.io/places"
POSTCODE_URL = "https://api.postcodes.io/postcodes/{pc}"
OUTCODE_URL = "https://api.postcodes.io/outcodes/{oc}"
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})?\b", re.IGNORECASE)


_TYPE_RANK = {"City": 0, "Town": 1, "Other Settlement": 2, "Suburban Area": 3, "Village": 4}


def _place_rank(p: dict, query: str) -> tuple[int, int]:
    """Prefer an exact name match, then bigger places - so "Corby" beats "Corby Glen"."""
    exact = (p.get("name_1") or "").strip().lower() == query.strip().lower()
    return (0 if exact else 1, _TYPE_RANK.get(p.get("local_type"), 9))


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 3958.8 * 2 * math.asin(math.sqrt(h))


class Geocoder:
    def __init__(self, session: Session, client: httpx.Client | None = None):
        self.session = session
        self.client = client or httpx.Client(timeout=10)
        self.offline = False  # stop trying after a network failure, for this run

    def _lookup_remote(self, name: str) -> tuple[float, float] | None:
        m = POSTCODE_RE.search(name)
        tries = []
        if m and m.group(2):
            tries.append(POSTCODE_URL.format(pc=(m.group(1) + m.group(2)).replace(" ", "")))
        if m:
            tries.append(OUTCODE_URL.format(oc=m.group(1)))
        for url in tries:
            r = self.client.get(url)
            if r.status_code == 200 and (res := r.json().get("result")):
                return res["latitude"], res["longitude"]
        # Town name: try "Kettering, Northamptonshire" then just "Kettering".
        for q in dict.fromkeys([name, name.split(",")[0].strip()]):
            r = self.client.get(PLACES_URL, params={"q": q, "limit": 10})
            if r.status_code == 200 and (res := r.json().get("result")):
                best = min(res, key=lambda p: _place_rank(p, q))
                return best["latitude"], best["longitude"]
        return None

    def coords(self, name: str) -> tuple[float, float] | None:
        key = (name or "").strip().lower()
        if not key or key in ("remote", "work from home", "home based", "uk", "united kingdom"):
            return None
        cached = self.session.get(Place, key)
        if cached:
            return (cached.lat, cached.lon) if cached.lat is not None else None
        if self.offline:
            return None
        try:
            found = self._lookup_remote(name)
        except httpx.HTTPError as e:
            log.warning("Place lookup failed (%s) - sorting without distances this run", e)
            self.offline = True
            return None
        self.session.add(
            Place(name=key, lat=found[0] if found else None, lon=found[1] if found else None)
        )
        self.session.commit()
        return found

    def miles_from_home(self, location: str) -> float | None:
        there = self.coords(location)
        if not there:
            return None
        home = self.coords(get_settings().default_location)
        if not home:
            return None
        return round(haversine_miles(home, there), 1)
