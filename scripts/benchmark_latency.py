"""Measure /prices/latest and count real Yahoo Finance calls.

Workloads, all starting from an empty cache key:
- warm: 1 untimed fill, then 200 requests. Hits should not call Yahoo.
- burst: 100 requests as fast as possible. One upstream call per 30s TTL.
- distinct: one request for each of several symbols. Cache cannot help.
- spaced: 10 requests, 6 seconds apart. With a 30s TTL this is the arrival
  rate that implies about an 80% reduction (1 - 6/30).
- cold: delete the key before every request, so every request calls Yahoo.
"""

import json
import time
from pathlib import Path

import numpy as np
import requests

from app.services.price_service import get_cache_stats, redis_client, reset_cache_stats

BASE = "http://127.0.0.1:8000/prices/latest"
WARM_SYMBOL = "AAPL"
DISTINCT_SYMBOLS = ["MSFT", "GOOGL", "AMZN", "SPY", "NVDA"]


def _percentile(samples_ms: list[float]) -> dict:
    arr = np.asarray(samples_ms, dtype=float)
    return {
        "n": int(arr.size),
        "min_ms": round(float(arr.min()), 3),
        "median_ms": round(float(np.percentile(arr, 50)), 3),
        "p95_ms": round(float(np.percentile(arr, 95)), 3),
        "p99_ms": round(float(np.percentile(arr, 99)), 3),
        "max_ms": round(float(arr.max()), 3),
        "percentile_method": "numpy linear",
    }


def _reduction(requests_made: int, upstream: int) -> float:
    if requests_made == 0:
        return 0.0
    return round(1 - (upstream / requests_made), 4)


def _get(symbol: str) -> tuple[float, dict]:
    started = time.perf_counter()
    response = requests.get(
        BASE,
        params={"symbol": symbol, "provider": "yfinance"},
        timeout=60,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise RuntimeError(body["error"])
    return elapsed_ms, body


def _clear(symbol: str) -> None:
    redis_client.delete(f"{symbol}:yfinance")


def _run_counted(name: str, symbols: list[str], pause_s: float = 0.0) -> dict:
    reset_cache_stats()
    for symbol in set(symbols):
        _clear(symbol)
    samples = []
    for index, symbol in enumerate(symbols):
        if index and pause_s:
            time.sleep(pause_s)
        samples.append(_get(symbol)[0])
    stats = get_cache_stats()
    return {
        "name": name,
        "pause_s": pause_s,
        "requests": len(symbols),
        **stats,
        "upstream_reduction": _reduction(len(symbols), stats["upstream_calls"]),
        "latency_ms": _percentile(samples),
    }


def main() -> dict:
    # One untimed fill, then time only cache hits.
    _clear(WARM_SYMBOL)
    _get(WARM_SYMBOL)
    reset_cache_stats()
    warm_samples = [_get(WARM_SYMBOL)[0] for _ in range(200)]
    warm_stats = get_cache_stats()
    warm = {
        "name": "warm_cache",
        "requests": 200,
        "note": "Cache was filled by one untimed request. These 200 should not call Yahoo.",
        **warm_stats,
        "upstream_reduction": _reduction(200, warm_stats["upstream_calls"]),
        "latency_ms": _percentile(warm_samples),
    }

    burst = _run_counted("burst_same_symbol", [WARM_SYMBOL] * 100)
    distinct = _run_counted("distinct_symbols", DISTINCT_SYMBOLS)
    spaced = _run_counted("spaced_6s", [WARM_SYMBOL] * 10, pause_s=6.0)
    cold_samples = []
    reset_cache_stats()
    for _ in range(8):
        _clear(WARM_SYMBOL)
        cold_samples.append(_get(WARM_SYMBOL)[0])
    cold_stats = get_cache_stats()
    cold = {
        "name": "cold_cache",
        "requests": 8,
        "note": "Redis key deleted before each request, so each one calls Yahoo Finance.",
        **cold_stats,
        "upstream_reduction": _reduction(8, cold_stats["upstream_calls"]),
        "latency_ms": _percentile(cold_samples),
    }

    results = {
        "endpoint": BASE,
        "cache_ttl_s": 30,
        "clock": "time.perf_counter around requests.get, including JSON parse",
        "warm_cache": warm,
        "burst_same_symbol": burst,
        "distinct_symbols": distinct,
        "spaced_6s": spaced,
        "cold_cache": cold,
    }
    out = Path("benchmarks/latency.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    main()
