"""
Import last N days of flight history from globe.adsbexchange.com trace files.
Run from backend/ directory:  python3 import_history.py
"""

import json
import logging
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, ".")
from database import SessionLocal, engine
from models import Base, Aircraft, Flight, Position
from airports import nearest_iata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

HISTORY_DAYS  = 30
SLEEP_OK      = 1.2   # seconds between successful fetches
SLEEP_ERR     = 3.0   # seconds after an error
MIN_POSITIONS = 8     # skip segments with fewer points
MIN_DURATION  = 5 * 60  # skip segments shorter than 5 minutes

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer":    "https://globe.adsbexchange.com/",
    "Accept":     "application/json",
}


def fetch_trace(icao_hex: str, date: datetime) -> Optional[dict]:
    date_str = date.strftime("%Y/%m/%d")
    suffix   = icao_hex[-2:]
    url      = (
        f"https://globe.adsbexchange.com/globe_history/"
        f"{date_str}/traces/{suffix}/trace_full_{icao_hex}.json"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code != 404:
            log.warning("HTTP %d: %s", e.code, url)
            time.sleep(SLEEP_ERR)
        return None
    except Exception as e:
        log.warning("Fetch error %s %s: %s", icao_hex, date_str, e)
        time.sleep(SLEEP_ERR)
        return None


def parse_points(data: dict) -> list[dict]:
    """Convert raw trace array to list of dicts."""
    day_ts = data.get("timestamp", 0)
    points = []
    for p in data.get("trace", []):
        alt      = p[3]
        on_ground = (alt == "ground")
        extra    = p[8] if len(p) > 8 and isinstance(p[8], dict) else {}
        callsign = extra.get("flight", "").strip() or None

        points.append({
            "timestamp":   datetime.utcfromtimestamp(day_ts + p[0]),
            "lat":         p[1],
            "lon":         p[2],
            "altitude_ft": None if on_ground else (int(p[3]) if isinstance(p[3], (int, float)) else None),
            "ground_speed": p[4] if isinstance(p[4], (int, float)) else None,
            "heading":     p[5] if isinstance(p[5], (int, float)) else None,
            "on_ground":   on_ground,
            "callsign":    callsign,
        })
    return points


def segment_flights(points: list[dict]) -> list[list[dict]]:
    """Split position list into airborne flight segments."""
    segments, current = [], []
    for pt in points:
        if not pt["on_ground"]:
            current.append(pt)
        else:
            if current:
                segments.append(current)
                current = []
    if current:
        segments.append(current)

    result = []
    for seg in segments:
        if len(seg) < MIN_POSITIONS:
            continue
        duration = (seg[-1]["timestamp"] - seg[0]["timestamp"]).total_seconds()
        if duration < MIN_DURATION:
            continue
        result.append(seg)
    return result


def pick_callsign(seg: list[dict]) -> Optional[str]:
    for pt in seg:
        if pt["callsign"]:
            return pt["callsign"]
    return None


def find_existing_flight(db, aircraft_id: int, start: datetime) -> Optional[Flight]:
    window = timedelta(minutes=10)
    return (
        db.query(Flight)
        .filter(
            Flight.aircraft_id == aircraft_id,
            Flight.start_time  >= start - window,
            Flight.start_time  <= start + window,
        )
        .first()
    )


def import_day(db, aircraft: Aircraft, date: datetime) -> tuple[int, int]:
    data = fetch_trace(aircraft.icao_hex, date)
    time.sleep(SLEEP_OK)
    if not data:
        return 0, 0

    points   = parse_points(data)
    segments = segment_flights(points)
    flights_added = positions_added = 0

    for seg in segments:
        start = seg[0]["timestamp"]
        end   = seg[-1]["timestamp"]
        dep   = nearest_iata(seg[0]["lat"],  seg[0]["lon"])
        arr   = nearest_iata(seg[-1]["lat"], seg[-1]["lon"])

        existing = find_existing_flight(db, aircraft.id, start)
        if existing:
            # Back-fill airports on already-imported flights if missing
            changed = False
            if not existing.departure_airport and dep:
                existing.departure_airport = dep; changed = True
            if not existing.arrival_airport and arr:
                existing.arrival_airport = arr;   changed = True
            if changed:
                db.commit()
            continue

        flight = Flight(
            aircraft_id       = aircraft.id,
            flight_number     = pick_callsign(seg),
            start_time        = start,
            end_time          = end,
            is_active         = False,
            departure_airport = dep,
            arrival_airport   = arr,
        )
        db.add(flight)
        db.flush()

        # Subsample: every 3rd point ≈ ~2 min resolution, enough for smooth track
        for pt in seg[::3]:
            db.add(Position(
                aircraft_id  = aircraft.id,
                flight_id    = flight.id,
                timestamp    = pt["timestamp"],
                lat          = pt["lat"],
                lon          = pt["lon"],
                altitude_ft  = pt["altitude_ft"],
                ground_speed = pt["ground_speed"],
                heading      = pt["heading"],
                flight_number= pt["callsign"],
                on_ground    = False,
            ))
            positions_added += 1

        db.commit()
        flights_added += 1
        duration_min = int((end - start).total_seconds() / 60)
        log.info("  ✓ %s  %s → %s  (%d min, %d pos, %s)",
                 aircraft.registration or aircraft.icao_hex,
                 start.strftime("%H:%M"), end.strftime("%H:%M"),
                 duration_min, positions_added,
                 flight.flight_number or "no callsign")

    return flights_added, positions_added


def main():
    filter_hexes = [h.lower() for h in sys.argv[1:]]
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        aircraft_list = db.query(Aircraft).all()
        if filter_hexes:
            aircraft_list = [a for a in aircraft_list if a.icao_hex.lower() in filter_hexes]
        if not aircraft_list:
            log.error("No aircraft in DB — start the backend first (seeds aircraft on startup).")
            return

        total_f = total_p = 0
        now = datetime.utcnow()

        for ac in aircraft_list:
            log.info("── %s  %s  (%s) ──", ac.registration, ac.label, ac.icao_hex)
            ac_f = ac_p = 0
            for days_ago in range(0, HISTORY_DAYS + 1):
                date = now - timedelta(days=days_ago)
                f, p = import_day(db, ac, date)
                ac_f += f
                ac_p += p
            log.info("  → %d flights, %d positions", ac_f, ac_p)
            total_f += ac_f
            total_p += ac_p

        log.info("═══ Done: %d flights, %d positions total ═══", total_f, total_p)
    finally:
        db.close()


if __name__ == "__main__":
    main()
