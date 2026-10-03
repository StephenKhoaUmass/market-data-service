"""Measure what Kafka adds, once a broker is listening on localhost:9092.

Three clocks, all time.perf_counter, NumPy linear percentiles:
- poll(0): the call the API actually makes. It queues the record and returns.
- flush: time until the broker acknowledges that same record.
- stored: time from produce() until the consumer commits the moving average.
"""

import json
import time
from pathlib import Path

import numpy as np
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from app.models.db import session_scope
from app.models.market_data import PricePoint, SymbolAverage
from app.services.utils import calculate_moving_average

BOOTSTRAP = "localhost:9092"
TOPIC = "price-events"
SYMBOL = "KAFKA_BENCH"
N_POLL = 200
N_FLUSH = 50
N_E2E = 30


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


def _ensure_topic() -> None:
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    futures = admin.create_topics([NewTopic(TOPIC, num_partitions=1, replication_factor=1)])
    for future in futures.values():
        try:
            future.result()
        except Exception as exc:
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise


def _producer() -> Producer:
    return Producer({
        "bootstrap.servers": BOOTSTRAP,
        "acks": "all",
        "socket.timeout.ms": 5000,
        "message.timeout.ms": 10000,
    })


def _seed_prices() -> None:
    with session_scope() as db:
        for price in (100.0, 101.0, 99.0, 102.0, 98.0):
            db.add(PricePoint(symbol=SYMBOL, price=price))


def _handle(data: dict) -> None:
    symbol = data["symbol"]
    with session_scope() as db:
        prices = (
            db.query(PricePoint.price)
            .filter(PricePoint.symbol == symbol)
            .order_by(PricePoint.timestamp.desc())
            .limit(5)
            .all()
        )
        avg = calculate_moving_average([row[0] for row in prices])
        existing = db.query(SymbolAverage).filter_by(symbol=symbol).first()
        if existing:
            existing.average = avg
        else:
            db.add(SymbolAverage(symbol=symbol, average=avg))


def main() -> dict:
    _ensure_topic()
    _seed_prices()
    producer = _producer()

    poll_samples = []
    for i in range(N_POLL):
        started = time.perf_counter()
        producer.produce(TOPIC, key=SYMBOL, value=json.dumps({"symbol": SYMBOL, "i": i, "kind": "poll"}))
        producer.poll(0)
        poll_samples.append((time.perf_counter() - started) * 1000)
    producer.flush(10)

    flush_samples = []
    for i in range(N_FLUSH):
        started = time.perf_counter()
        producer.produce(TOPIC, key=SYMBOL, value=json.dumps({"symbol": SYMBOL, "i": i, "kind": "flush"}))
        producer.flush(10)
        flush_samples.append((time.perf_counter() - started) * 1000)

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": "kafka-bench-e2e",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([TOPIC])
    deadline = time.perf_counter() + 10
    while time.perf_counter() < deadline:
        if consumer.poll(0.2) is None and consumer.assignment():
            break

    e2e_samples = []
    for i in range(N_E2E):
        payload = {"symbol": SYMBOL, "i": i, "kind": "e2e"}
        started = time.perf_counter()
        producer.produce(TOPIC, key=SYMBOL, value=json.dumps(payload))
        producer.flush(10)
        found = False
        wait_until = time.perf_counter() + 5
        while time.perf_counter() < wait_until:
            msg = consumer.poll(0.05)
            if msg is None or msg.error():
                continue
            body = json.loads(msg.value().decode("utf-8"))
            if body.get("kind") != "e2e" or body.get("i") != i:
                continue
            _handle(body)
            e2e_samples.append((time.perf_counter() - started) * 1000)
            found = True
            break
        if not found:
            raise RuntimeError(f"consumer did not store event {i}")
    consumer.close()

    results = {
        "broker": BOOTSTRAP,
        "topic": TOPIC,
        "poll_0_queue_only_ms": _percentile(poll_samples),
        "broker_ack_flush_ms": _percentile(flush_samples),
        "produce_to_average_stored_ms": _percentile(e2e_samples),
        "note": (
            "poll(0) is the API path and does not wait for Kafka. "
            "flush waits for the broker ack. "
            "stored includes that ack plus the consumer's Postgres write."
        ),
    }
    out = Path("benchmarks/kafka.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    main()
