from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, func
from app.models.db import Base
import uuid

class RawMarketData(Base):
    __tablename__ = "raw_market_data"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String, index=True)
    provider = Column(String)
    response = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PricePoint(Base):
    __tablename__ = "price_points"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    price = Column(Float)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class SymbolAverage(Base):
    __tablename__ = "symbol_averages"

    symbol = Column(String, primary_key=True)
    average = Column(Float)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
