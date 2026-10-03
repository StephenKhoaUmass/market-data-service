import json
import os
import redis
import yfinance as yf
from datetime import datetime, timezone
from app.models.db import session_scope
from app.models.market_data import RawMarketData, PricePoint
from app.core.kafka_producer import send_to_kafka

redis_client = redis.Redis(host="localhost", port=6379, db=0)

CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
STAT_HITS = "mds:stats:cache_hits"
STAT_MISSES = "mds:stats:cache_misses"
STAT_UPSTREAM = "mds:stats:upstream_calls"

def get_cache_stats() -> dict:
    def _read(key: str) -> int:
        value = redis_client.get(key)
        return int(value) if value is not None else 0

    return {
        "cache_hits": _read(STAT_HITS),
        "cache_misses": _read(STAT_MISSES),
        "upstream_calls": _read(STAT_UPSTREAM),
    }


def reset_cache_stats() -> None:
    redis_client.delete(STAT_HITS, STAT_MISSES, STAT_UPSTREAM)


async def get_latest_price(symbol: str, provider: str = "yfinance"):
    cache_key = f"{symbol}:{provider}"
    cached = redis_client.get(cache_key)
    if cached:
        redis_client.incr(STAT_HITS)
        return json.loads(cached)

    redis_client.incr(STAT_MISSES)
    redis_client.incr(STAT_UPSTREAM)

    # Fetch using yfinance 
    ticker = yf.Ticker(symbol)
    data = ticker.history(period="1d")
    if data.empty:
        return {"error": f"No price data found for {symbol}"}

    price = float(round(data["Close"].iloc[-1], 2))
    timestamp = datetime.now(timezone.utc).isoformat()

    with session_scope() as db:
        raw_data = RawMarketData(
            symbol=symbol,
            provider=provider,
            response=data.to_json(),
            created_at=datetime.now(timezone.utc)
        )
        db.add(raw_data)
        db.flush()

        price_point = PricePoint(
            symbol=symbol,
            price=price,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(price_point)
        raw_id = str(raw_data.id)

    send_to_kafka(
        topic="price-events",
        key=symbol,
        value={
            "symbol": symbol,
            "price": price,
            "timestamp": timestamp,
            "source": provider,
            "raw_response_id": raw_id
        }
    )

    result = {
        "symbol": symbol,
        "price": price,
        "timestamp": timestamp
    }
    redis_client.setex(cache_key, CACHE_TTL, json.dumps(result))
    return result


async def refresh_price(symbol: str, provider: str = "yfinance"):
    """Fetch from the provider even if a cached value is still inside its TTL."""
    redis_client.delete(f"{symbol}:{provider}")
    return await get_latest_price(symbol, provider)


async def warm_symbols(symbols: list[str], provider: str = "yfinance"):
    warmed = []
    for symbol in symbols:
        warmed.append(await refresh_price(symbol, provider))
    return {"warmed": len(warmed), "symbols": symbols}


polling_jobs = {}  # In-memory simulation only
warmer_jobs = {}

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


async def schedule_cache_warmer(symbols: list[str], interval: int, provider: str = "yfinance"):
    from asyncio import create_task, sleep

    async def warm_loop():
        while True:
            await warm_symbols(symbols, provider)
            await sleep(interval)

    job_id = f"warm:{provider}:{interval}:{','.join(symbols)}"
    if job_id in warmer_jobs:
        return {"status": "already warming", "job_id": job_id}

    warmer_jobs[job_id] = create_task(warm_loop())
    return {"status": "warming started", "job_id": job_id, "symbols": symbols, "interval": interval}
