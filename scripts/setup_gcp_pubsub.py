import argparse
import json
import os
from typing import Dict, List

from dotenv import load_dotenv


def topic_id_for(topic: str, prefix: str) -> str:
    normalized = topic.replace('.', '-')
    return f"{prefix}{normalized}" if prefix else normalized


def default_subscription_id(topic_id: str) -> str:
    return f"{topic_id}-sub"


def ensure_topic(publisher, project_id: str, topic_id: str) -> str:
    topic_path = publisher.topic_path(project_id, topic_id)
    try:
        publisher.get_topic(request={"topic": topic_path})
        print(f"Topic exists: {topic_path}")
    except Exception:
        publisher.create_topic(request={"name": topic_path})
        print(f"Created topic: {topic_path}")
    return topic_path


def ensure_subscription(subscriber, project_id: str, subscription_id: str, topic_path: str) -> str:
    subscription_path = subscriber.subscription_path(project_id, subscription_id)
    try:
        subscriber.get_subscription(request={"subscription": subscription_path})
        print(f"Subscription exists: {subscription_path}")
    except Exception:
        subscriber.create_subscription(request={"name": subscription_path, "topic": topic_path})
        print(f"Created subscription: {subscription_path}")
    return subscription_path


def load_subscription_map() -> Dict[str, str]:
    raw = os.getenv("QUEUE_GCP_SUBSCRIPTIONS", "{}").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("QUEUE_GCP_SUBSCRIPTIONS must be valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("QUEUE_GCP_SUBSCRIPTIONS must be a JSON object")
    return {str(k): str(v) for k, v in value.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create GCP Pub/Sub topics/subscriptions for the queue-first worker")
    parser.add_argument("--project-id", default=None, help="GCP project id. Falls back to QUEUE_GCP_PROJECT_ID")
    parser.add_argument(
        "--topics",
        default="fitbit.notifications.raw,fitbit.notifications.retry,fitbit.notifications.dlq",
        help="Comma-separated logical topic names",
    )
    parser.add_argument("--topic-prefix", default=None, help="Optional prefix for topic names")
    parser.add_argument("--env-file", default=".env.local", help="Env file to load before setup")
    args = parser.parse_args()

    load_dotenv(args.env_file)

    project_id = args.project_id or os.getenv("QUEUE_GCP_PROJECT_ID", "").strip()
    if not project_id:
        raise RuntimeError("Missing project id. Provide --project-id or QUEUE_GCP_PROJECT_ID")

    topic_prefix = args.topic_prefix if args.topic_prefix is not None else os.getenv("QUEUE_GCP_TOPIC_PREFIX", "").strip()
    subscription_map = load_subscription_map()

    try:
        from google.cloud import pubsub_v1
    except ImportError as exc:
        raise RuntimeError("Install google-cloud-pubsub before running setup script") from exc

    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()

    topics: List[str] = [item.strip() for item in args.topics.split(",") if item.strip()]
    if not topics:
        raise RuntimeError("No topics provided")

    print(f"Setting up Pub/Sub resources in project: {project_id}")
    print(f"Logical topics: {topics}")

    for logical_topic in topics:
        topic_id = topic_id_for(logical_topic, topic_prefix)
        topic_path = ensure_topic(publisher, project_id, topic_id)

        subscription_id = subscription_map.get(logical_topic) or subscription_map.get("default") or default_subscription_id(topic_id)
        ensure_subscription(subscriber, project_id, subscription_id, topic_path)

    print("Setup complete.")


if __name__ == "__main__":
    main()
