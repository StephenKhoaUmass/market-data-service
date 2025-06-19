from confluent_kafka import Consumer, KafkaException
import json
from sqlalchemy.orm import Session
from app.models.db import get_db_session
from app.models.market_data import PricePoint, SymbolAverage
from app.services.utils import calculate_moving_average

import time

conf = {
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'price-consumer-group',
    'auto.offset.reset': 'earliest',
}

consumer = Consumer(conf)
consumer.subscribe(['price-events'])

print("[👂] Listening to price-events...")

try:
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            raise KafkaException(msg.error())
        
        data = json.loads(msg.value().decode("utf-8"))
        symbol = data["symbol"]

        # Get DB session
        db: Session = next(get_db_session())

        # Fetch latest 5 prices
        prices = (
            db.query(PricePoint.price)
            .filter(PricePoint.symbol == symbol)
            .order_by(PricePoint.timestamp.desc())
            .limit(5)
            .all()
        )
        price_list = [p[0] for p in prices]

        # Compute and store moving average
        avg = calculate_moving_average(price_list)
        existing = db.query(SymbolAverage).filter_by(symbol=symbol).first()

        if existing:
            existing.average = avg
        else:
            new_avg = SymbolAverage(symbol=symbol, average=avg)
            db.add(new_avg)

        db.commit()
        print(f"[✅] Stored moving average for {symbol}: {avg}")

except KeyboardInterrupt:
    print("Shutting down consumer...")
finally:
    consumer.close()
