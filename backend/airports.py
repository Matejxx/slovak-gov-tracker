"""
Nearest-airport lookup using the bundled airportsdata dataset.
Only considers airports with an IATA code (major/commercial airports).
"""
import math
from typing import Optional

import airportsdata

_AIRPORTS: Optional[dict] = None


def _load() -> dict:
    global _AIRPORTS
    if _AIRPORTS is None:
        raw = airportsdata.load("IATA")
        _AIRPORTS = {k: v for k, v in raw.items() if v.get("lat") and v.get("lon")}
    return _AIRPORTS


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def nearest_iata(lat: float, lon: float, max_km: float = 50.0) -> Optional[str]:
    """Return IATA code of nearest airport within max_km, or None."""
    airports = _load()
    best_code = None
    best_dist = float("inf")
    for code, ap in airports.items():
        d = _haversine_km(lat, lon, ap["lat"], ap["lon"])
        if d < best_dist:
            best_dist = d
            best_code = code
    return best_code if best_dist <= max_km else None
