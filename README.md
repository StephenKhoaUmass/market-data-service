Market Data Service: A backend service that fetches real-time stock prices, stores them in a PostgreSQL database, caches responses with Redis, publishes updates to Kafka, and calculates moving averages.

1. Features:

API Endpoint: /prices/latest?symbol=AAPL&provider=yfinance
Providers: Supports real-time data from yfinance
Database: Stores raw and processed data in PostgreSQL
Cache: Uses Redis for response caching
Stream Processing: Publishes to Kafka and consumes to compute moving averages
Analytics: GET /analytics/{symbol} stores 5y of daily closes and reports 20-day volatility, 2σ move flags, and a next-day direction model scored on a chronological holdout
CI/CD: Automated testing via GitHub Actions
Testing: pytest for the moving average, cache behavior, and analytics

2. Architecture Overview:

User --> FastAPI --> PostgreSQL
                  |--> Redis (cache)
                  |--> Kafka (produces "price-events")
Kafka --> Consumer --> Moving Average --> PostgreSQL

- FastAPI: Serves the core API
- PostgreSQL: Stores raw market data + price points + symbol averages
- Redis: Caches recent API results for performance
- Kafka: Sends price updates to a consumer which computes moving averages
- Daily bars: Adjusted daily closes, separate from live quotes, used by the analytics endpoint

3. Setup Instructions:

3.1. Clone the repo: git clone https://github.com/YOUR_USERNAME/market-data-service.git
cd market-data-service

3.2. Set up virtual environment: 
python3 -m venv marketdata
source marketdata/bin/activate
pip install -r requirements.txt

3.3. Start the stack with Docker: docker compose up -d

This starts Postgres 15 on port 6543, Redis, Kafka, and Zookeeper. That is the database and broker the app uses.

`bitnami/kafka` and `bitnami/zookeeper` were removed from Docker Hub in 2025. The Compose file pins `bitnamilegacy/kafka:3.5.1` and `bitnamilegacy/zookeeper:3.8`, the archived copies of the images it originally used.

3.4. Initialize the database: python3 app/models/init_db.py

3.5. Run the API: uvicorn main:app --reload

3.6 Open another terminal, activate the virtual environment again and run the Kafka Consumer:
python3 app/core/kafka_consumer.py

4. API Documentation: 

GET /prices/latest: Fetches the latest price for a given stock symbol.

Params:
symbol (e.g. AAPL)
provider: yfinance (default)

Example: GET http://localhost:8000/prices/latest?symbol=AAPL&provider=yfinance
Response: {
  "symbol": "AAPL",
  "price": 196.58,
  "timestamp": "2025-06-19T00:01:09.688642+00:00"
}

5. Testing

✅ Postman Collection: 

Included in /docs/market-data-service.postman_collection.json
Includes test scripts:
- Status code = 200
- price is a number

✅ CI/CD via GitHub Actions:

Located in .github/workflows/ci.yml
Runs pytest on push to main
Launches PostgreSQL and Redis as services in CI

6. Measured results

Re-run with `PYTHONPATH=. python scripts/benchmark_latency.py` (API on port 8000), `python scripts/benchmark_index.py`, and `python scripts/run_analysis.py`. Raw output is in `benchmarks/`.

6.1. HTTP latency of GET /prices/latest

Clock is `time.perf_counter` around `requests.get`. Percentiles use NumPy's linear method. Kafka was not running; cache hits do not publish, and a miss only calls `producer.poll(0)`.

| Workload | n | Upstream calls | Median | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|---:|
| Warm cache, same symbol | 200 | 0 | 5.9 ms | 8.4 ms | 13.3 ms | 21.1 ms |
| Cold cache, key deleted each time | 8 | 8 | 119.9 ms | 368.6 ms | 388.5 ms | 393.5 ms |

A warm lookup is under 100ms at the max of this sample. A cold lookup is not: the median is already 120ms, and the slow ones are the Yahoo Finance call.

6.2. How many upstream calls Redis removes

The TTL is 30 seconds and the key is `symbol:provider`. Reduction is `1 - upstream_calls / requests`, counted in Redis, not estimated.

| Workload | Requests | Upstream calls | Reduction |
|---|---:|---:|---:|
| 100 requests, same symbol, no delay | 100 | 1 | 99% |
| Same symbol every 6 seconds, 10 requests | 10 | 2 | 80% |
| 5 different symbols, one request each | 5 | 5 | 0% |

The 80% figure is this 6-second poll. It is `1 - 6/30` for a 30s TTL. It is not a property of the cache in general. Inside one TTL window, repeat lookups make no upstream call at all.

The same count on a mixed watchlist (AAPL, MSFT, GOOGL, AMZN, NVDA, SPY), re-run with `python scripts/benchmark_cache_strategies.py`:

| Strategy | User requests | Upstream calls | Reduction | User hit rate |
|---|---:|---:|---:|---:|
| 8 immediate passes, TTL 30s | 48 | 6 | 87.5% | |
| 8 immediate passes, TTL 120s | 48 | 6 | 87.5% | |
| 4 passes, 20s apart, TTL 30s | 24 | 12 | 50% | 50% |
| 4 passes, 20s apart, TTL 120s | 24 | 6 | 75% | 75% |
| 4 passes, 20s apart, TTL 30s, warm the list every 30s | 24 | 12 | 50% | 100% |

A longer TTL does nothing for a burst that already finishes inside 30s. On the 20-second refresh it cuts upstream calls from 12 to 6, and the median user request drops from 38ms to 1.4ms. Warming does not cut the Yahoo total below the 30s TTL; those 12 calls move to the warmer, and every user request then hits (median 1.1ms, max 6.1ms). `CACHE_TTL` overrides the 30s default. `POST /prices/warm?symbols=AAPL,MSFT&interval=30` refreshes a list on a schedule.

6.3. Composite index

Query: `WHERE symbol = ? ORDER BY ts DESC LIMIT 5`, on 1,000,000 rows (50 symbols, 20,000 each). Run against the Postgres 15 container from `docker compose up`. Parallel workers disabled. Median of 20 `EXPLAIN ANALYZE` execution times, first run discarded.

| Index | Plan | Median | p95 | Max |
|---|---|---:|---:|---:|
| None | Seq scan, then top-N heapsort | 72.7 ms | 78.1 ms | 81.0 ms |
| `(symbol)` | Index scan, then top-N heapsort | 5.1 ms | 5.2 ms | 5.9 ms |
| `(symbol, ts DESC)` | Index scan, no sort | 0.013 ms | 0.019 ms | 0.019 ms |

The symbol-only index was already what the model had. The composite index is the change: Postgres reads the newest rows in order instead of sorting that symbol's 20,000 rows. On a small live table this difference will not show up.

6.4. Direction model, 5y daily closes, chronological 70/30 split

Features known at the close: last return, 5-day mean return, 20-day return volatility. Label is whether the next close is higher. "Beats baseline" means the accuracy gap is larger than two standard errors.

| Symbol | Test days | Accuracy | Majority baseline | Gap |
|---|---:|---:|---:|---:|
| AAPL | 371 | 52.6% | 53.9% | -1.3 pp |
| MSFT | 371 | 47.7% | 52.6% | -4.9 pp |
| SPY | 371 | 51.8% | 55.3% | -3.5 pp |

None of the three beat the baseline. The holdout was scored once; features and the model were not changed after seeing it. Latest 20-day annualized volatility was 23.1% (AAPL), 22.4% (MSFT), and 10.4% (SPY). About 7% of eligible days were flagged at `|z| >= 2` against the prior 20 returns; a normal distribution would flag about 4.6%.

A second pass tried a longer horizon and a confidence cutoff without using that holdout to choose. The first 50% of days fits the logistic regression. The next 20% compares next-day, 5-day, and 10-day direction, plus rules that abstain unless the predicted class probability is at least 0.55 or 0.60. A rule is kept only if it covers at least 30% of the validation periods, scores at least 30 non-overlapping periods, and beats always-up by more than two standard errors. Otherwise the original next-day rule stays.

On that middle slice, every eligible rule was at or below always-up. The confidence rules mostly abstained: for AAPL, probability above 0.55 covered 4% of validation days, and above 0.60 covered 1%. The 10-day rule had only 25 non-overlapping periods, under the minimum of 30. No new rule was adopted, so the test table above is unchanged.

6.5. Kafka

`bitnami/kafka` and `bitnami/zookeeper` were removed from Docker Hub. Compose now uses `bitnamilegacy/kafka:3.5.1` and `bitnamilegacy/zookeeper:3.8`. Re-run with `python scripts/benchmark_kafka.py` while those two containers are up.

| Clock | n | Median | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|
| `poll(0)`, queue only, which is what the API does | 200 | 0.003 ms | 0.004 ms | 0.011 ms | 0.25 ms |
| `flush`, wait for the broker ack | 50 | 2.1 ms | 3.7 ms | 9.1 ms | 14.1 ms |
| Produce until the moving average is committed | 30 | 5.4 ms | 6.9 ms | 36.7 ms | 48.7 ms |

The request does not wait for Kafka. The moving-average write happens on the consumer, about 5ms later. That does not change the cache-hit latency or the upstream-call reduction.