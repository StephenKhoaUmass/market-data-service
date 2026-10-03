from sqlalchemy import Column, Integer, String, Float, DateTime, Date, JSON, func, Index, UniqueConstraint
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
    symbol = Column(String, nullable=False)
    price = Column(Float)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_price_points_symbol_timestamp", "symbol", "timestamp"),
    )


class SymbolAverage(Base):
    __tablename__ = "symbol_averages"

    symbol = Column(String, primary_key=True)
    average = Column(Float)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DailyBar(Base):
    """One adjusted daily close. Kept separate from live price_points."""

    __tablename__ = "daily_bars"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    bar_date = Column(Date, nullable=False)
    close = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "bar_date", name="uq_daily_bars_symbol_date"),
        Index("ix_daily_bars_symbol_date", "symbol", "bar_date"),
    )


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    symbol = Column(String, primary_key=True)
    payload = Column(JSON, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
