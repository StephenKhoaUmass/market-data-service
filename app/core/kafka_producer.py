from confluent_kafka import Producer
import json

producer_conf = {
    'bootstrap.servers': 'localhost:9092'
}

producer = Producer(producer_conf)

def delivery_report(err, msg):
    if err is not None:
        print(f"[❌] Delivery failed: {err}")
    else:
        print(f"[✅] Message delivered to {msg.topic()} [{msg.partition()}]")

def send_to_kafka(topic: str, key: str, value: dict):
    try:
        producer.produce(
            topic=topic,
            key=key,
            value=json.dumps(value),
            callback=delivery_report
        )
        producer.poll(0)
    except Exception as e:
        print(f"[ERROR] Failed to send message to Kafka: {e}")
