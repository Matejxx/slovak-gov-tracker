from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from airports import city_name
from database import SessionLocal
from models import Aircraft, Flight, Position

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ago(ts: Optional[datetime]) -> Optional[str]:
    if not ts:
        return None
    return ts.isoformat() + "Z"


_AIRCRAFT_ORDER = ['505c06', '505c09', '505c07', '505fa0', '505fa1', '505c04', '505c17']

@router.get("/aircraft")
def list_aircraft(db: Session = Depends(get_db)):
    result = []
    aircraft_list = sorted(
        db.query(Aircraft).all(),
        key=lambda a: _AIRCRAFT_ORDER.index(a.icao_hex) if a.icao_hex in _AIRCRAFT_ORDER else 99
    )
    for a in aircraft_list:
        latest = (
            db.query(Position)
            .filter_by(aircraft_id=a.id)
            .order_by(desc(Position.timestamp))
            .first()
        )
        active = db.query(Flight).filter_by(aircraft_id=a.id, is_active=True).first()
        result.append(
            {
                "id": a.id,
                "icao_hex": a.icao_hex,
                "registration": a.registration,
                "type": a.aircraft_type,
                "category": a.category,
                "label": a.label,
                "photo_url": a.photo_url,
                "is_airborne": active is not None,
                "latest_position": (
                    {
                        "lat": latest.lat,
                        "lon": latest.lon,
                        "altitude_ft": latest.altitude_ft,
                        "ground_speed": latest.ground_speed,
                        "heading": latest.heading,
                        "squawk": latest.squawk,
                        "flight_number": latest.flight_number,
                        "on_ground": latest.on_ground,
                        "timestamp": _ago(latest.timestamp),
                    }
                    if latest
                    else None
                ),
            }
        )
    return result


@router.get("/flights")
def list_flights(
    limit: int = Query(30, le=200),
    offset: int = 0,
    icao: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Flight).join(Aircraft)
    if icao:
        q = q.filter(Aircraft.icao_hex == icao)

    total = q.count()
    flights = q.order_by(desc(Flight.start_time)).offset(offset).limit(limit).all()

    return {
        "total": total,
        "flights": [
            {
                "id": f.id,
                "flight_number": f.flight_number,
                "start_time": _ago(f.start_time),
                "end_time": _ago(f.end_time),
                "is_active": f.is_active,
                "duration_minutes": (
                    int((f.end_time - f.start_time).total_seconds() / 60)
                    if f.end_time
                    else None
                ),
                "departure_airport": f.departure_airport,
                "arrival_airport": f.arrival_airport,
                "departure_city": city_name(f.departure_airport),
                "arrival_city": city_name(f.arrival_airport),
                "aircraft": {
                    "icao_hex": f.aircraft.icao_hex,
                    "registration": f.aircraft.registration,
                    "label": f.aircraft.label,
                    "category": f.aircraft.category,
                },
            }
            for f in flights
        ],
    }


@router.get("/flights/{flight_id}/track")
def get_flight_track(flight_id: int, db: Session = Depends(get_db)):
    flight = db.query(Flight).filter_by(id=flight_id).first()
    if not flight:
        raise HTTPException(404, "Flight not found")

    positions = (
        db.query(Position)
        .filter_by(flight_id=flight_id)
        .order_by(Position.timestamp)
        .all()
    )

    return {
        "flight": {
            "id": flight.id,
            "flight_number": flight.flight_number,
            "start_time": _ago(flight.start_time),
            "end_time": _ago(flight.end_time),
            "is_active": flight.is_active,
            "departure_airport": flight.departure_airport,
            "arrival_airport": flight.arrival_airport,
            "departure_city": city_name(flight.departure_airport),
            "arrival_city": city_name(flight.arrival_airport),
            "aircraft": {
                "icao_hex": flight.aircraft.icao_hex,
                "registration": flight.aircraft.registration,
                "label": flight.aircraft.label,
                "category": flight.aircraft.category,
            },
        },
        "track": [
            {
                "lat": p.lat,
                "lon": p.lon,
                "altitude_ft": p.altitude_ft,
                "ground_speed": p.ground_speed,
                "heading": p.heading,
                "squawk": p.squawk,
                "timestamp": _ago(p.timestamp),
            }
            for p in positions
            if p.lat and p.lon
        ],
    }


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    total_flights = db.query(Flight).count()
    active_flights = db.query(Flight).filter_by(is_active=True).count()
    total_positions = db.query(Position).count()
    return {
        "total_flights": total_flights,
        "active_flights": active_flights,
        "total_positions": total_positions,
    }
