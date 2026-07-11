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


# Slovak exonyms for common destinations; fallback is the English city
# name from airportsdata.
_SK_CITY = {
    "BTS": "Bratislava", "KSC": "Košice", "TAT": "Poprad", "SLD": "Sliač",
    "ILZ": "Žilina", "PZY": "Piešťany",
    "VIE": "Viedeň", "PRG": "Praha", "BUD": "Budapešť", "WAW": "Varšava",
    "KRK": "Krakov", "BER": "Berlín", "MUC": "Mníchov", "FRA": "Frankfurt",
    "CGN": "Kolín", "HAM": "Hamburg", "CDG": "Paríž", "ORY": "Paríž",
    "LBG": "Paríž", "LHR": "Londýn", "LGW": "Londýn", "STN": "Londýn",
    "LTN": "Londýn", "LCY": "Londýn", "BRU": "Brusel", "ANR": "Antverpy",
    "AMS": "Amsterdam", "LUX": "Luxemburg", "GVA": "Ženeva", "ZRH": "Zürich",
    "FCO": "Rím", "CIA": "Rím", "MXP": "Miláno", "LIN": "Miláno",
    "VCE": "Benátky", "NAP": "Neapol", "MAD": "Madrid", "BCN": "Barcelona",
    "LIS": "Lisabon", "ATH": "Atény", "SOF": "Sofia", "OTP": "Bukurešť",
    "BEG": "Belehrad", "ZAG": "Záhreb", "LJU": "Ľubľana", "SJJ": "Sarajevo",
    "SKP": "Skopje", "TGD": "Podgorica", "TIA": "Tirana", "KIV": "Kišiňov",
    "IEV": "Kyjev", "KBP": "Kyjev", "SVO": "Moskva", "VKO": "Moskva",
    "DME": "Moskva", "MSQ": "Minsk", "IST": "Istanbul", "SAW": "Istanbul",
    "ESB": "Ankara", "GYD": "Baku", "EVN": "Jerevan", "TBS": "Tbilisi",
    "NQZ": "Astana", "TAS": "Taškent", "PEK": "Peking", "PKX": "Peking",
    "PVG": "Šanghaj", "HAN": "Hanoj", "SGN": "Ho Či Minovo Mesto",
    "HND": "Tokio", "NRT": "Tokio", "ICN": "Soul", "DXB": "Dubaj",
    "AUH": "Abú Zabí", "DOH": "Dauha", "RUH": "Rijád", "TLV": "Tel Aviv",
    "CAI": "Káhira", "ALG": "Alžír", "TUN": "Tunis", "RBA": "Rabat",
    "JFK": "New York", "EWR": "New York", "IAD": "Washington",
    "CPH": "Kodaň", "ARN": "Štokholm", "OSL": "Oslo", "HEL": "Helsinki",
    "DUB": "Dublin", "VNO": "Vilnius", "RIX": "Riga", "TLL": "Tallinn",
    "LCA": "Larnaka", "MLA": "Malta", "GRZ": "Graz", "LNZ": "Linz",
    "SZG": "Salzburg", "INN": "Innsbruck", "BSL": "Bazilej", "NCE": "Nice",
    "LYS": "Lyon", "MRS": "Marseille", "EDI": "Edinburgh", "MAN": "Manchester",
}


def city_name(iata: Optional[str]) -> Optional[str]:
    """Slovak (or English fallback) city name for an IATA code."""
    if not iata:
        return None
    if iata in _SK_CITY:
        return _SK_CITY[iata]
    ap = _load().get(iata)
    return ap.get("city") or None if ap else None
