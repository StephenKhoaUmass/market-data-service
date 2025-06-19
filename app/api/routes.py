# app/api/routes.py
from fastapi import APIRouter, Query
from app.services.price_service import get_latest_price, schedule_polling_job
from typing import Optional

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
