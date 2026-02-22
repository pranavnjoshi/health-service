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


class KafkaQueueClient:
    def __init__(self, brokers: str, client_id: str = "health-service"):
        try:
            from confluent_kafka import Producer
        except ImportError as exc:
            raise RuntimeError("Kafka backend requires 'confluent-kafka' package") from exc

        self._producer = Producer({"bootstrap.servers": brokers, "client.id": client_id})

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


class GcpPubSubQueueClient:
    def __init__(self, project_id: str, topic_prefix: str = ""):
        try:
            from google.cloud import pubsub_v1
        except ImportError as exc:
            raise RuntimeError("GCP Pub/Sub backend requires 'google-cloud-pubsub' package") from exc

        self._publisher = pubsub_v1.PublisherClient()
        self._project_id = project_id
        self._topic_prefix = topic_prefix

    def _topic_id(self, topic: str) -> str:
        normalized = topic.replace(".", "-")
        return f"{self._topic_prefix}{normalized}" if self._topic_prefix else normalized

    def publish_many(self, topic: str, events: List[Dict[str, Any]]) -> int:
        topic_path = self._publisher.topic_path(self._project_id, self._topic_id(topic))
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
