"""Compare cache strategies on one mixed watchlist.

The watchlist is 6 symbols. A pass asks for each symbol once.
The paced workload is 4 passes, 20 seconds apart: 24 user requests over about a minute.

Strategies, decided before looking at the results:
- ttl-30 and ttl-120, no warmer. A longer TTL can help only when a repeat falls outside 30s.
- ttl-30 plus a warmer that force-refreshes the whole list every 30s.
  Warmer calls count as upstream calls. User-request hits are counted separately.
"""

import asyncio
import json
import time
from pathlib import Path

import app.services.price_service as price_service
from app.services.price_service import get_cache_stats, get_latest_price, refresh_price, reset_cache_stats

WATCHLIST = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "SPY"]
PASSES = 4
GAP_S = 20
WARM_INTERVAL_S = 30


def _reduction(requests_made: int, upstream: int) -> float:
    if requests_made == 0:
        return 0.0
    return round(1 - (upstream / requests_made), 4)


def _clear() -> None:
    for symbol in WATCHLIST:
        price_service.redis_client.delete(f"{symbol}:yfinance")


async def _user_pass() -> list[float]:
    samples = []
    for symbol in WATCHLIST:
        started = time.perf_counter()
        result = await get_latest_price(symbol)
        samples.append((time.perf_counter() - started) * 1000)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result["error"])
    return samples


async def _paced(ttl: int, warm_interval_s: int | None) -> dict:
    price_service.CACHE_TTL = ttl
    _clear()
    reset_cache_stats()
    user_samples = []
    next_warm = time.monotonic()
    warm_runs = 0
    for index in range(PASSES):
        if index:
            await asyncio.sleep(GAP_S)
        if warm_interval_s is not None and time.monotonic() >= next_warm:
            for symbol in WATCHLIST:
                await refresh_price(symbol)
            warm_runs += 1
            next_warm = time.monotonic() + warm_interval_s
        user_samples.extend(await _user_pass())
    stats = get_cache_stats()
    user_requests = PASSES * len(WATCHLIST)
    return {
        "ttl_s": ttl,
        "warm_interval_s": warm_interval_s,
        "warm_runs": warm_runs,
        "user_requests": user_requests,
        **stats,
        "upstream_reduction_vs_user_requests": _reduction(user_requests, stats["upstream_calls"]),
        "user_hit_rate": round(stats["cache_hits"] / user_requests, 4),
        "user_latency_ms": {
            "n": len(user_samples),
            "median_ms": round(sorted(user_samples)[len(user_samples) // 2], 3),
            "max_ms": round(max(user_samples), 3),
        },
    }


async def _burst(ttl: int) -> dict:
    price_service.CACHE_TTL = ttl
    _clear()
    reset_cache_stats()
    repeats = 8
    for _ in range(repeats):
        await _user_pass()
    stats = get_cache_stats()
    user_requests = repeats * len(WATCHLIST)
    return {
        "ttl_s": ttl,
        "user_requests": user_requests,
        "note": "8 immediate passes. Both TTLs outlast the burst, so they should match.",
        **stats,
        "upstream_reduction_vs_user_requests": _reduction(user_requests, stats["upstream_calls"]),
    }


async def main() -> dict:
    burst_30, burst_120 = await _burst(30), await _burst(120)
    paced_30 = await _paced(30, None)
    paced_120 = await _paced(120, None)
    paced_warm = await _paced(30, WARM_INTERVAL_S)
    results = {
        "watchlist": WATCHLIST,
        "paced": {"passes": PASSES, "gap_s": GAP_S},
        "burst_ttl_30": burst_30,
        "burst_ttl_120": burst_120,
        "paced_ttl_30": paced_30,
        "paced_ttl_120": paced_120,
        "paced_ttl_30_warm_every_30s": paced_warm,
    }
    out = Path("benchmarks/cache_strategies.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    asyncio.run(main())
