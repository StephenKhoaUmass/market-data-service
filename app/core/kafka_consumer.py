from confluent_kafka import Consumer, KafkaError, KafkaException
import json
from app.models.db import session_scope
from app.models.market_data import PricePoint, SymbolAverage
from app.services.utils import calculate_moving_average

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
            # The topic is created on the first publish, so a fresh broker
            # reports this until the API has sent a price.
            if msg.error().code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
                continue
            raise KafkaException(msg.error())
        
        data = json.loads(msg.value().decode("utf-8"))
        symbol = data["symbol"]

        with session_scope() as db:
            prices = (
                db.query(PricePoint.price)
                .filter(PricePoint.symbol == symbol)
                .order_by(PricePoint.timestamp.desc())
                .limit(5)
                .all()
            )
            price_list = [p[0] for p in prices]
            avg = calculate_moving_average(price_list)
            existing = db.query(SymbolAverage).filter_by(symbol=symbol).first()
            if existing:
                existing.average = avg
            else:
                db.add(SymbolAverage(symbol=symbol, average=avg))
        print(f"[✅] Stored moving average for {symbol}: {avg}")

except KeyboardInterrupt:
    print("Shutting down consumer...")
finally:
    consumer.close()
