import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Aircraft, Flight, Position
from airports import nearest_iata

logger = logging.getLogger(__name__)

AIRCRAFT_CONFIG = [
    {
        "icao_hex": "505c06",
        "registration": "OM-BYA",
        "aircraft_type": "Airbus A319 CJ",
        "category": "plane",
        "label": "Airbus A319 CJ",
        "photo_url": "https://t.plnspttrs.net/11014/1927275_dc67f7d8f2_280.jpg",
    },
    {
        "icao_hex": "505c09",
        "registration": "OM-BYK",
        "aircraft_type": "Airbus A319 CJ",
        "category": "plane",
        "label": "Airbus A319 CJ",
        "photo_url": "https://t.plnspttrs.net/44469/1927305_81eee88eb9_280.jpg",
    },
    {
        "icao_hex": "505c07",
        "registration": "OM-BYB",
        "aircraft_type": "Fokker 100",
        "category": "plane",
        "label": "Fokker 100",
        "photo_url": "https://t.plnspttrs.net/46894/1911922_6f10ec3b93_280.jpg",
    },
    {
        "icao_hex": "505c04",
        "registration": "OM-BYD",
        "aircraft_type": "Bell 429 GlobalRanger",
        "category": "helicopter",
        "label": "Bell 429 GlobalRanger",
        "photo_url": "https://t.plnspttrs.net/48542/1360071_31dc729db3_280.jpg",
    },
    {
        "icao_hex": "505c17",
        "registration": "OM-BYW",
        "aircraft_type": "AgustaWestland AW189",
        "category": "helicopter",
        "label": "AgustaWestland AW189",
        "photo_url": "https://t.plnspttrs.net/41353/1720967_2d8e5f4f51_280.jpg",
    },
    {
        "icao_hex": "505fa0",
        "registration": "9513",
        "aircraft_type": "Bombardier Global 5000",
        "category": "plane",
        "label": "Bombardier Global 5000",
        "photo_url": "https://cdn.plnspttrs.net/48971/9513-slovak-air-force-bombardier-global-5000-bd-700-1a11_PlanespottersNet_1790915_e9a96cb2d4_o.jpg",
    },
    {
        "icao_hex": "505fa1",
        "registration": "9633",
        "aircraft_type": "Bombardier Global 5000",
        "category": "plane",
        "label": "Bombardier Global 5000",
        "photo_url": "https://cdn.plnspttrs.net/38522/9633-slovak-air-force-bombardier-global-5000-bd-700-1a11_PlanespottersNet_1778866_8eba5f862f_o.jpg",
    },
]

POLL_INTERVAL = 30       # seconds between polls
STALE_FLIGHT_MIN = 15    # minutes without signal before closing a flight

# readsb v2 JSON providers, tried in order; the next one is used only when
# the previous returns an HTTP/network error (an empty "ac" list is a valid
# "not visible" answer). airplanes.live was dropped: 403 for all since 8/2026.
# {hex} is a comma-separated list — one request per poll for the whole fleet,
# since both providers rate-limit (429) bursts of per-aircraft requests.
ADSB_PROVIDERS = [
    "https://api.adsb.lol/v2/icao/{hex}",
    "https://opendata.adsb.fi/api/v2/hex/{hex}",
]
# adsb.lol rejects generic User-Agents with 403 and requires contact info.
HTTP_HEADERS = {
    "User-Agent": "kamletifico.sk/1.0 (+https://kamletifico.sk; online.easysolutions@gmail.com)",
}


def seed_aircraft(db: Session):
    for cfg in AIRCRAFT_CONFIG:
        existing = db.query(Aircraft).filter_by(icao_hex=cfg["icao_hex"]).first()
        if existing:
            for k, v in cfg.items():
                setattr(existing, k, v)
        else:
            db.add(Aircraft(**cfg))
    db.commit()


async def fetch_all(client: httpx.AsyncClient, icao_hexes: list) -> dict:
    """Return {icao_hex: readsb entry} for the aircraft currently visible."""
    joined = ",".join(icao_hexes)
    for url in ADSB_PROVIDERS:
        url = url.format(hex=joined)
        try:
            r = await client.get(url)
            r.raise_for_status()
            ac = r.json().get("ac") or []
        except Exception as e:
            logger.warning("Fetch error %s: %s", url.split("/")[2], e)
            continue
        # skip stale entries (seen > 120 s)
        return {
            e["hex"].lower(): e
            for e in ac
            if e.get("hex") and e.get("seen", 0) <= 120
        }
    logger.error("All ADS-B providers failed")
    return {}


def _safe_int(val) -> Optional[int]:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def process_position(db: Session, aircraft: Aircraft, data: dict):
    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None:
        return

    on_ground = bool(data.get("gnd", True))
    # Override: if altitude clearly shows airborne, don't trust a stale 'gnd' flag
    alt_raw = data.get("alt_baro")
    if on_ground and alt_raw and alt_raw != "ground":
        alt_ft = _safe_int(alt_raw)
        if alt_ft and alt_ft > 1000:
            on_ground = False
    now = datetime.utcnow()

    # Opportunistically update registration / type
    reg = (data.get("r") or "").strip()
    atype = (data.get("t") or "").strip()
    changed = False
    if reg and aircraft.registration != reg:
        aircraft.registration = reg
        changed = True
    if atype and aircraft.aircraft_type != atype:
        aircraft.aircraft_type = atype
        changed = True
    if changed:
        db.flush()

    active_flight = (
        db.query(Flight).filter_by(aircraft_id=aircraft.id, is_active=True).first()
    )

    if not on_ground:
        if not active_flight:
            flight_num = (data.get("flight") or "").strip() or None
            active_flight = Flight(
                aircraft_id=aircraft.id,
                flight_number=flight_num,
                start_time=now,
                is_active=True,
                departure_airport=nearest_iata(lat, lon),
            )
            db.add(active_flight)
            db.flush()
            logger.info("Flight started: %s (%s) dep=%s", aircraft.icao_hex, aircraft.label, active_flight.departure_airport)
    else:
        if active_flight:
            active_flight.is_active = False
            active_flight.end_time = now
            active_flight.arrival_airport = nearest_iata(lat, lon)
            logger.info("Flight landed: %s arr=%s", aircraft.icao_hex, active_flight.arrival_airport)
            active_flight = None

    pos = Position(
        aircraft_id=aircraft.id,
        flight_id=active_flight.id if active_flight else None,
        timestamp=now,
        lat=lat,
        lon=lon,
        altitude_ft=_safe_int(data.get("alt_baro")),
        ground_speed=data.get("gs"),
        heading=data.get("track"),
        squawk=(data.get("squawk") or "").strip() or None,
        flight_number=(data.get("flight") or "").strip() or None,
        on_ground=on_ground,
    )
    db.add(pos)
    db.commit()


def close_stale_flights(db: Session):
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_FLIGHT_MIN)
    for flight in db.query(Flight).filter_by(is_active=True).all():
        last = (
            db.query(Position)
            .filter_by(flight_id=flight.id)
            .order_by(Position.timestamp.desc())
            .first()
        )
        if last and last.timestamp < cutoff:
            flight.is_active = False
            flight.end_time = last.timestamp
            logger.info("Closed stale flight %d", flight.id)
    db.commit()


async def poll_once():
    async with httpx.AsyncClient(timeout=10, headers=HTTP_HEADERS) as client:
        db = SessionLocal()
        try:
            aircraft_list = db.query(Aircraft).all()
            seen = await fetch_all(client, [a.icao_hex for a in aircraft_list])
            for aircraft in aircraft_list:
                result = seen.get(aircraft.icao_hex.lower())
                if result is None:
                    continue
                await asyncio.to_thread(process_position, db, aircraft, result)
            await asyncio.to_thread(close_stale_flights, db)
        finally:
            db.close()


async def poll_loop():
    logger.info("Poller started")
    while True:
        try:
            await poll_once()
        except Exception as e:
            logger.error("Poll error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)
