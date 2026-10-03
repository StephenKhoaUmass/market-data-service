import yfinance as yf
from sqlalchemy.dialects.postgresql import insert

from app.models.db import session_scope
from app.models.market_data import AnalyticsSnapshot, DailyBar
from app.services.analytics import build_report

ALLOWED_PERIODS = {"1y", "2y", "5y", "10y"}


def backfill_daily_bars(symbol: str, period: str = "5y") -> int:
    symbol = symbol.upper()
    history = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
    if history.empty:
        return 0

    records = []
    for ts, row in history.iterrows():
        close = float(row["Close"])
        if close != close:  # NaN
            continue
        records.append({
            "symbol": symbol,
            "bar_date": ts.date(),
            "close": close,
        })
    if not records:
        return 0

    stmt = insert(DailyBar).values(records)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_bars_symbol_date",
        set_={"close": stmt.excluded.close},
    )
    with session_scope() as db:
        db.execute(stmt)
    return len(records)


def load_daily_bars(symbol: str):
    symbol = symbol.upper()
    with session_scope() as db:
        rows = (
            db.query(DailyBar)
            .filter(DailyBar.symbol == symbol)
            .order_by(DailyBar.bar_date.asc())
            .all()
        )
        return [row.bar_date for row in rows], [row.close for row in rows]


def refresh_symbol_analytics(symbol: str, period: str = "5y") -> dict:
    if period not in ALLOWED_PERIODS:
        raise ValueError(f"period must be one of {sorted(ALLOWED_PERIODS)}")
    symbol = symbol.upper()
    backfill_daily_bars(symbol, period=period)
    dates, prices = load_daily_bars(symbol)
    report = build_report(symbol, dates, prices)
    report["period"] = period
    with session_scope() as db:
        existing = db.get(AnalyticsSnapshot, symbol)
        if existing is None:
            db.add(AnalyticsSnapshot(symbol=symbol, payload=report))
        else:
            existing.payload = report
    return report


def get_stored_analytics(symbol: str):
    symbol = symbol.upper()
    with session_scope() as db:
        row = db.get(AnalyticsSnapshot, symbol)
        if row is None:
            return None
        return row.payload
