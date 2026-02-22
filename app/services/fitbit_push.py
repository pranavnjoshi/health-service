import os
from typing import Any, Dict, List


class FitbitPushService:
    def __init__(self, event_bus, logger, topic: str = "fitbit.notifications.raw"):
        self.event_bus = event_bus
        self.logger = logger
        self.topic = topic

    def is_valid_verification_code(self, code: str | None) -> bool:
        verify_codes_raw = os.getenv("FITBIT_SUBSCRIPTION_VERIFY_CODE", "")
        verify_codes = {item.strip() for item in verify_codes_raw.split(",") if item.strip()}
        return bool(code and code in verify_codes)

    def ingest_notifications(self, body: Any) -> Dict[str, Any]:
        notifications: List[Dict[str, Any]]
        if isinstance(body, list):
            notifications = [item for item in body if isinstance(item, dict)]
        elif isinstance(body, dict):
            notifications = [body]
        else:
            notifications = []

        published = self.event_bus.publish_many(self.topic, notifications)
        queue_depth = None
        if hasattr(self.event_bus, "size"):
            queue_depth = self.event_bus.size(self.topic)

        self.logger.info(f"[webhook] Fitbit notification received: {body}")
        self.logger.info(
            f"[webhook] queued_notifications={published}, queue_depth={queue_depth}, topic={self.topic}"
        )

        return {
            "status": "received",
            "queued": published,
            "topic": self.topic,
            "queue_depth": queue_depth,
        }
