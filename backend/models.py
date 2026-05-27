from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Aircraft(Base):
    __tablename__ = "aircraft"

    id = Column(Integer, primary_key=True)
    icao_hex = Column(String(6), unique=True, nullable=False, index=True)
    registration = Column(String(20))
    aircraft_type = Column(String(100))
    category = Column(String(20), default="plane")  # 'plane' or 'helicopter'
    label = Column(String(100))
    photo_url = Column(String(500))

    flights = relationship("Flight", back_populates="aircraft")


class Flight(Base):
    __tablename__ = "flights"

    id = Column(Integer, primary_key=True)
    aircraft_id = Column(Integer, ForeignKey("aircraft.id"), nullable=False, index=True)
    flight_number = Column(String(20))
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, index=True)
    is_active = Column(Boolean, default=True, index=True)
    departure_airport = Column(String(10))
    arrival_airport = Column(String(10))

    aircraft = relationship("Aircraft", back_populates="flights")
    positions = relationship("Position", back_populates="flight", order_by="Position.timestamp")


class Position(Base):
    __tablename__ = "positions"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    aircraft_id = Column(Integer, ForeignKey("aircraft.id"), nullable=False, index=True)
    flight_id = Column(Integer, ForeignKey("flights.id"), index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    lat = Column(Float)
    lon = Column(Float)
    altitude_ft = Column(Integer)
    ground_speed = Column(Float)
    heading = Column(Float)
    squawk = Column(String(4))
    flight_number = Column(String(20))
    on_ground = Column(Boolean, default=False)

    flight = relationship("Flight", back_populates="positions")
