# app/api/routes.py
from fastapi import APIRouter, HTTPException, Query
from app.services.history import get_stored_analytics, refresh_symbol_analytics
from app.services.price_service import (
    get_latest_price,
    schedule_cache_warmer,
    schedule_polling_job,
    warm_symbols,
)

router = APIRouter()

@router.get("/prices/latest")
async def get_price(
    symbol: str = Query(...),
    provider: str = Query(default="yfinance")
):
    return await get_latest_price(symbol, provider)

@router.post("/prices/poll")
async def poll_prices(
    symbol: str,
    interval: int = Query(..., description="Polling interval in seconds"),
    provider: str = "yfinance"
):
    return await schedule_polling_job(symbol, interval, provider)


@router.post("/prices/warm")
async def warm_prices(
    symbols: str = Query(..., description="Comma-separated symbols"),
    interval: int = Query(default=0, description="If > 0, refresh the list on this period"),
    provider: str = "yfinance",
):
    symbol_list = [part.strip().upper() for part in symbols.split(",") if part.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="symbols is empty")
    if interval > 0:
        return await schedule_cache_warmer(symbol_list, interval, provider)
    return await warm_symbols(symbol_list, provider)


@router.get("/analytics/{symbol}")
async def get_analytics(
    symbol: str,
    refresh: bool = Query(default=False),
    period: str = Query(default="5y"),
):
    try:
        if not refresh:
            stored = get_stored_analytics(symbol)
            if stored is not None:
                return stored
        return refresh_symbol_analytics(symbol, period=period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
