"""Time the consumer query with no index, a symbol index, and a composite index.

The table is synthetic and dropped at the end. Live price_points is too small
for an index to change anything you could put on a resume.
"""

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = "postgresql://khoaho:postgres@localhost:6543/market"
SYMBOLS = 50
ROWS_PER_SYMBOL = 20_000
REPEATS = 21
QUERY = """
EXPLAIN (ANALYZE, BUFFERS)
SELECT price
FROM bench_prices
WHERE symbol = %s
ORDER BY ts DESC
LIMIT 5
"""


def _execution_time_ms(plan_text: str) -> float:
    for line in plan_text.splitlines():
        if line.startswith("Execution Time:"):
            return float(line.split()[2])
    raise RuntimeError(f"no execution time in plan:\n{plan_text}")


def _plan_summary(plan_text: str) -> str:
    interesting = []
    for line in plan_text.splitlines():
        stripped = line.strip().lstrip(">").strip()
        if any(
            token in stripped
            for token in ("Seq Scan", "Index Scan", "Index Only Scan", "Sort Method", "Bitmap")
        ):
            interesting.append(stripped.split("(")[0].strip())
    return " | ".join(interesting)


def _measure(cur, symbol: str) -> dict:
    times = []
    summary = ""
    for _ in range(REPEATS):
        cur.execute(QUERY, (symbol,))
        plan = "\n".join(row[0] for row in cur.fetchall())
        times.append(_execution_time_ms(plan))
        summary = _plan_summary(plan)
        last_plan = plan
    sample = times[1:]
    return {
        "plan": summary,
        "plan_text": last_plan,
        "median_ms": round(statistics.median(sample), 3),
        "p95_ms": round(sorted(sample)[max(int(len(sample) * 0.95) - 1, 0)], 3),
        "max_ms": round(max(sample), 3),
        "repeats": len(sample),
    }


def main() -> dict:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS bench_prices")
    cur.execute(
        """
        CREATE TABLE bench_prices (
            id bigserial PRIMARY KEY,
            symbol text NOT NULL,
            ts timestamptz NOT NULL,
            price double precision NOT NULL
        )
        """
    )
    cur.execute("SET max_parallel_workers_per_gather = 0")

    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    for s in range(SYMBOLS):
        symbol = f"S{s:04d}"
        rows = [
            (symbol, start + timedelta(days=i), 100.0 + (i % 50))
            for i in range(ROWS_PER_SYMBOL)
        ]
        execute_values(
            cur,
            "INSERT INTO bench_prices (symbol, ts, price) VALUES %s",
            rows,
            page_size=5000,
        )
        print(f"loaded {symbol}", flush=True)

    cur.execute("ANALYZE bench_prices")
    target = "S0001"
    results = {
        "postgres": None,
        "rows": SYMBOLS * ROWS_PER_SYMBOL,
        "symbols": SYMBOLS,
        "rows_per_symbol": ROWS_PER_SYMBOL,
        "query": "WHERE symbol = ? ORDER BY ts DESC LIMIT 5",
        "parallel_workers": 0,
        "note": "First EXPLAIN of each setup is discarded. Times are server execution time.",
    }
    cur.execute("SELECT version()")
    results["postgres"] = cur.fetchone()[0]

    results["no_secondary_index"] = _measure(cur, target)

    cur.execute("CREATE INDEX bench_prices_symbol_idx ON bench_prices (symbol)")
    cur.execute("ANALYZE bench_prices")
    results["symbol_index"] = _measure(cur, target)

    cur.execute("DROP INDEX bench_prices_symbol_idx")
    cur.execute("CREATE INDEX bench_prices_symbol_ts_idx ON bench_prices (symbol, ts DESC)")
    cur.execute("ANALYZE bench_prices")
    results["composite_symbol_ts_desc"] = _measure(cur, target)

    cur.execute("DROP TABLE bench_prices")
    cur.close()
    conn.close()

    out = Path("benchmarks/index.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    main()
