from typing import Any, Dict, Optional


class AppleHealthPushService:
    def __init__(self, logger):
        self.logger = logger

    def is_valid_verification_code(self, code: Optional[str]) -> bool:
        return False

    def ingest_notifications(self, body: Any) -> Dict[str, Any]:
        self.logger.info(f"[apple_push] notification received: {body}")
        return {
            "status": "not_supported",
            "provider": "apple",
            "detail": "Apple Health push is device-mediated; use upload endpoint",
        }
