import time
import json
import redis
import yfinance as yf
from datetime import datetime, timezone
from app.models.db import get_db_session
from app.models.market_data import RawMarketData, PricePoint
from app.core.kafka_producer import send_to_kafka  # you must implement this
from sqlalchemy.orm import Session

redis_client = redis.Redis(host="localhost", port=6379, db=0)

CACHE_TTL = 30  # seconds

async def get_latest_price(symbol: str, provider: str = "yfinance"):
    cache_key = f"{symbol}:{provider}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Fetch using yfinance 
    ticker = yf.Ticker(symbol)
    data = ticker.history(period="1d")
    if data.empty:
        return {"error": f"No price data found for {symbol}"}

    price = float(round(data["Close"].iloc[-1], 2))
    timestamp = datetime.now(timezone.utc).isoformat()

    # Save raw response
    db: Session = next(get_db_session())
    raw_data = RawMarketData(
        symbol=symbol,
        provider=provider,
        response=data.to_json(),
        created_at=datetime.now(timezone.utc)
    )
    db.add(raw_data)
    db.commit()
    db.refresh(raw_data)

    # Save to price_points table
    price_point = PricePoint(
        symbol=symbol,
        price=price,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(price_point)
    db.commit()

    # Publish to Kafka
    send_to_kafka(
        topic="price-events",
        key=symbol,
        value={
            "symbol": symbol,
            "price": price,
            "timestamp": timestamp,
            "source": provider,
            "raw_response_id": str(raw_data.id)
        }
    )

    result = {
        "symbol": symbol,
        "price": price,
        "timestamp": timestamp
    }
    redis_client.setex(cache_key, CACHE_TTL, json.dumps(result))
    return result


polling_jobs = {}  # In-memory simulation only

async def schedule_polling_job(symbol: str, interval: int, provider: str):
    from asyncio import create_task, sleep

    async def poll_loop():
        while True:
            await get_latest_price(symbol, provider)
            await sleep(interval)

    job_id = f"{symbol}:{provider}:{interval}"
    if job_id in polling_jobs:
        return {"status": "already polling", "job_id": job_id}

    task = create_task(poll_loop())
    polling_jobs[job_id] = task

    return {"status": "polling started", "job_id": job_id}
