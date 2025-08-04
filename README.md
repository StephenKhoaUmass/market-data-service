Market Data Service: A backend service that fetches real-time stock prices, stores them in a PostgreSQL database, caches responses with Redis, publishes updates to Kafka, and calculates moving averages.

1. Features:

- API Endpoint: /prices/latest?symbol=AAPL&provider=yfinance
- Providers: Supports real-time data from yfinance
- Database: Stores raw and processed data in PostgreSQL
- Cache: Uses Redis for response caching
- Stream Processing: Publishes to Kafka and consumes to compute moving averages
- CI/CD: Automated testing via GitHub Actions
- Testing: Postman collection included with test scripts

2. Architecture Overview:

User --> FastAPI --> PostgreSQL
                  |--> Redis (cache)
                  |--> Kafka (produces "price-events")
Kafka   -->   Consumer --> Moving Average --> PostgreSQL

- FastAPI: Serves the core API
- PostgreSQL: Stores raw market data + price points + symbol averages
- Redis: Caches recent API results for performance
- Kafka: Sends price updates to a consumer which computes moving averages

3. Setup Instructions:

3.1. Clone the repo: git clone https://github.com/YOUR_USERNAME/market-data-service.git

cd market-data-service

3.2. Set up virtual environment: 
python3 -m venv marketdata

source marketdata/bin/activate

pip install -r requirements.txt

3.3. Start the stack with Docker: docker-compose up -d

3.4. Initialize the database: python3 app/models/init_db.py

3.5. Run the API: uvicorn main:app --reload

3.6 Open another terminal, activate the virtual environment again and run the Kafka Consumer:
python3 app/core/kafka_consumer.py

4. Link to video recording of the project: https://drive.google.com/file/d/17ZS61rFsG7BVnmIkzYTLTHOsfr9mWaZX/view?usp=sharing

5. API Documentation: 

GET /prices/latest: Fetches the latest price for a given stock symbol.

Params:
- symbol (e.g. AAPL)
- provider: yfinance (default)

Example: GET http://localhost:8000/prices/latest?symbol=AAPL&provider=yfinance

Response: {
  "symbol": "AAPL",
  "price": 196.58,
  "timestamp": "2025-06-19T00:01:09.688642+00:00"
}

6. Testing:

✅ Postman Collection: 

- Included in /docs/market-data-service.postman_collection.json
- Includes test scripts:
  - Status code = 200
  - price is a number

✅ CI/CD via GitHub Actions:

- Located in .github/workflows/ci.yml
- Runs pytest on push to main
- Launches PostgreSQL and Redis as services in CI
