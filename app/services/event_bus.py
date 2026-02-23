import json
import os
from collections import defaultdict, deque
from threading import Lock
from typing import Any, Deque, Dict, List, Optional


class InMemoryQueueClient:
    def __init__(self):
        self._topics: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        self._lock = Lock()

    def publish(self, topic: str, event: Dict[str, Any]) -> None:
        with self._lock:
            self._topics[topic].append(event)

    def publish_many(self, topic: str, events: List[Dict[str, Any]]) -> int:
        published = 0
        with self._lock:
            for event in events:
                if isinstance(event, dict):
                    self._topics[topic].append(event)
                    published += 1
        return published

    def size(self, topic: str) -> Optional[int]:
        with self._lock:
            return len(self._topics[topic])

    def pop_all(self, topic: str) -> List[Dict[str, Any]]:
        with self._lock:
            events = list(self._topics[topic])
            self._topics[topic].clear()
        return events

    def consume_batch(self, topic: str, max_messages: int = 50, wait_seconds: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            queue = self._topics[topic]
            count = min(max_messages, len(queue))
            return [queue.popleft() for _ in range(count)]


class KafkaQueueClient:
    def __init__(self, brokers: str, client_id: str = "health-service"):
        try:
            from confluent_kafka import Producer
        except ImportError as exc:
            raise RuntimeError("Kafka backend requires 'confluent-kafka' package") from exc

        self._producer = Producer({"bootstrap.servers": brokers, "client.id": client_id})
        self._brokers = brokers
        self._client_id = client_id
        self._consumer = None
        self._consumer_topic = None

    def publish_many(self, topic: str, events: List[Dict[str, Any]]) -> int:
        published = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            payload = json.dumps(event).encode("utf-8")
            self._producer.produce(topic=topic, value=payload)
            published += 1
        self._producer.flush()
        return published

    def size(self, topic: str) -> Optional[int]:
        return None

    def consume_batch(self, topic: str, max_messages: int = 50, wait_seconds: int = 2) -> List[Dict[str, Any]]:
        try:
            from confluent_kafka import Consumer
        except ImportError as exc:
            raise RuntimeError("Kafka consumer requires 'confluent-kafka' package") from exc

        if self._consumer is None:
            group_id = os.getenv("QUEUE_KAFKA_GROUP_ID", "health-service-worker")
            auto_offset_reset = os.getenv("QUEUE_KAFKA_AUTO_OFFSET_RESET", "latest")
            self._consumer = Consumer(
                {
                    "bootstrap.servers": self._brokers,
                    "group.id": group_id,
                    "auto.offset.reset": auto_offset_reset,
                    "enable.auto.commit": True,
                }
            )

        if self._consumer_topic != topic:
            self._consumer.subscribe([topic])
            self._consumer_topic = topic

        events: List[Dict[str, Any]] = []
        timeout = max(0.1, float(wait_seconds))
        while len(events) < max_messages:
            msg = self._consumer.poll(timeout=timeout)
            if msg is None:
                break
            if msg.error():
                continue
            try:
                payload = json.loads(msg.value().decode("utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events


class GcpPubSubQueueClient:
    def __init__(self, project_id: str, topic_prefix: str = ""):
        try:
            from google.cloud import pubsub_v1
        except ImportError as exc:
            raise RuntimeError("GCP Pub/Sub backend requires 'google-cloud-pubsub' package") from exc

        self._publisher = pubsub_v1.PublisherClient()
        self._subscriber = pubsub_v1.SubscriberClient()
        self._project_id = project_id
        self._topic_prefix = topic_prefix
        self._auto_create = os.getenv("QUEUE_GCP_AUTO_CREATE", "false").strip().lower() == "true"
        subscriptions_raw = os.getenv("QUEUE_GCP_SUBSCRIPTIONS", "{}").strip()
        try:
            self._subscription_map = json.loads(subscriptions_raw) if subscriptions_raw else {}
        except Exception:
            self._subscription_map = {}

    def _topic_id(self, topic: str) -> str:
        normalized = topic.replace(".", "-")
        return f"{self._topic_prefix}{normalized}" if self._topic_prefix else normalized

    def _subscription_id(self, topic: str) -> str:
        mapped = self._subscription_map.get(topic) or self._subscription_map.get("default")
        if mapped:
            return mapped
        return f"{self._topic_id(topic)}-sub"

    def _ensure_topic(self, topic_id: str) -> str:
        topic_path = self._publisher.topic_path(self._project_id, topic_id)
        if not self._auto_create:
            return topic_path
        try:
            self._publisher.get_topic(request={"topic": topic_path})
        except Exception:
            self._publisher.create_topic(request={"name": topic_path})
        return topic_path

    def _ensure_subscription(self, subscription_id: str, topic_path: str) -> str:
        subscription_path = self._subscriber.subscription_path(self._project_id, subscription_id)
        if not self._auto_create:
            return subscription_path
        try:
            self._subscriber.get_subscription(request={"subscription": subscription_path})
        except Exception:
            self._subscriber.create_subscription(request={"name": subscription_path, "topic": topic_path})
        return subscription_path

    def publish_many(self, topic: str, events: List[Dict[str, Any]]) -> int:
        topic_id = self._topic_id(topic)
        topic_path = self._ensure_topic(topic_id)
        published = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            payload = json.dumps(event).encode("utf-8")
            self._publisher.publish(topic_path, payload).result(timeout=10)
            published += 1
        return published

    def size(self, topic: str) -> Optional[int]:
        return None

    def consume_batch(self, topic: str, max_messages: int = 50, wait_seconds: int = 2) -> List[Dict[str, Any]]:
        topic_id = self._topic_id(topic)
        topic_path = self._ensure_topic(topic_id)
        subscription_id = self._subscription_id(topic)
        subscription_path = self._ensure_subscription(subscription_id, topic_path)
        response = self._subscriber.pull(
            request={"subscription": subscription_path, "max_messages": max_messages},
            timeout=max(1, wait_seconds),
        )

        ack_ids = []
        events: List[Dict[str, Any]] = []
        for message in response.received_messages:
            ack_ids.append(message.ack_id)
            try:
                payload = json.loads(message.message.data.decode("utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict):
                events.append(payload)

        if ack_ids:
            self._subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": ack_ids})

        return events


class AwsSqsQueueClient:
    def __init__(self, queue_url_map: Dict[str, str], region_name: Optional[str] = None):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("AWS SQS backend requires 'boto3' package") from exc

        self._client = boto3.client("sqs", region_name=region_name)
        self._queue_url_map = queue_url_map

    def _queue_url_for(self, topic: str) -> str:
        if topic in self._queue_url_map:
            return self._queue_url_map[topic]
        if "default" in self._queue_url_map:
            return self._queue_url_map["default"]
        raise RuntimeError(f"No SQS queue URL mapped for topic '{topic}'")

    def publish_many(self, topic: str, events: List[Dict[str, Any]]) -> int:
        queue_url = self._queue_url_for(topic)
        published = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            self._client.send_message(QueueUrl=queue_url, MessageBody=json.dumps(event))
            published += 1
        return published

    def size(self, topic: str) -> Optional[int]:
        try:
            queue_url = self._queue_url_for(topic)
            attrs = self._client.get_queue_attributes(
                QueueUrl=queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
            return int(attrs["Attributes"].get("ApproximateNumberOfMessages", "0"))
        except Exception:
            return None

    def consume_batch(self, topic: str, max_messages: int = 10, wait_seconds: int = 2) -> List[Dict[str, Any]]:
        queue_url = self._queue_url_for(topic)
        response = self._client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max(1, min(max_messages, 10)),
            WaitTimeSeconds=max(0, min(wait_seconds, 20)),
        )
        messages = response.get("Messages", [])
        events: List[Dict[str, Any]] = []
        for msg in messages:
            body = msg.get("Body")
            receipt_handle = msg.get("ReceiptHandle")
            if not body or not receipt_handle:
                continue
            try:
                payload = json.loads(body)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                events.append(payload)
            self._client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        return events


def create_queue_client_from_env(logger=None):
    backend = os.getenv("QUEUE_BACKEND", "memory").strip().lower()
    fallback_to_memory = os.getenv("QUEUE_FALLBACK_TO_MEMORY", "true").strip().lower() == "true"

    try:
        if backend == "memory":
            return InMemoryQueueClient()

        if backend == "kafka":
            brokers = os.getenv("QUEUE_KAFKA_BROKERS", "localhost:9092")
            client_id = os.getenv("QUEUE_KAFKA_CLIENT_ID", "health-service")
            return KafkaQueueClient(brokers=brokers, client_id=client_id)

        if backend == "gcp_pubsub":
            project_id = os.getenv("QUEUE_GCP_PROJECT_ID", "").strip()
            if not project_id:
                raise RuntimeError("QUEUE_GCP_PROJECT_ID is required for gcp_pubsub backend")
            topic_prefix = os.getenv("QUEUE_GCP_TOPIC_PREFIX", "").strip()
            return GcpPubSubQueueClient(project_id=project_id, topic_prefix=topic_prefix)

        if backend == "aws_sqs":
            queue_urls_raw = os.getenv("QUEUE_AWS_SQS_TOPIC_URLS", "{}").strip()
            queue_url_map = json.loads(queue_urls_raw) if queue_urls_raw else {}
            if not isinstance(queue_url_map, dict) or not queue_url_map:
                single_url = os.getenv("QUEUE_AWS_SQS_URL", "").strip()
                if single_url:
                    queue_url_map = {"default": single_url}
            if not queue_url_map:
                raise RuntimeError("QUEUE_AWS_SQS_TOPIC_URLS or QUEUE_AWS_SQS_URL is required for aws_sqs backend")
            region = os.getenv("QUEUE_AWS_REGION", "").strip() or None
            return AwsSqsQueueClient(queue_url_map=queue_url_map, region_name=region)

        raise RuntimeError(f"Unsupported QUEUE_BACKEND '{backend}'")
    except Exception as exc:
        if logger:
            logger.warning(f"Queue backend init failed ({backend}): {exc}")
        if fallback_to_memory:
            if logger:
                logger.warning("Falling back to in-memory queue backend")
            return InMemoryQueueClient()
        raise


# Backward compatibility alias
InMemoryEventBus = InMemoryQueueClient
