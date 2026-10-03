import asyncio
import json
from contextlib import contextmanager

import pandas as pd

from app.services.price_service import STAT_HITS, STAT_MISSES, STAT_UPSTREAM, get_latest_price


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        value = self.store.get(key)
        if value is None:
            return None
        if isinstance(value, int):
            return str(value).encode()
        return value

    def setex(self, key, ttl, value):
        self.store[key] = value.encode() if isinstance(value, str) else value

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)


def test_cache_hit_skips_yfinance(monkeypatch):
    fake = FakeRedis()
    fake.store["AAPL:yfinance"] = json.dumps(
        {"symbol": "AAPL", "price": 10.0, "timestamp": "t"}
    ).encode()
    monkeypatch.setattr("app.services.price_service.redis_client", fake)

    def fail_ticker(symbol):
        raise AssertionError(f"upstream call for {symbol}")

    monkeypatch.setattr("app.services.price_service.yf.Ticker", fail_ticker)
    result = asyncio.run(get_latest_price("AAPL"))
    assert result["price"] == 10.0
    assert fake.store[STAT_HITS] == 1
    assert STAT_UPSTREAM not in fake.store


def test_cache_miss_calls_yfinance_once_and_stores_result(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("app.services.price_service.redis_client", fake)
    calls = []

    class FakeTicker:
        def __init__(self, symbol):
            calls.append(symbol)

        def history(self, period="1d"):
            return pd.DataFrame({"Close": [101.239]})

    class FakeSession:
        def add(self, obj):
            return None

        def flush(self):
            return None

    @contextmanager
    def fake_scope():
        yield FakeSession()

    monkeypatch.setattr("app.services.price_service.yf.Ticker", FakeTicker)
    monkeypatch.setattr("app.services.price_service.session_scope", fake_scope)
    monkeypatch.setattr("app.services.price_service.send_to_kafka", lambda **kwargs: None)

    result = asyncio.run(get_latest_price("AAPL"))
    assert calls == ["AAPL"]
    assert result["price"] == 101.24
    assert fake.store[STAT_MISSES] == 1
    assert fake.store[STAT_UPSTREAM] == 1
    assert "AAPL:yfinance" in fake.store
