from typing import Any, Dict, Optional


class GoogleFitPushService:
    def __init__(self, logger):
        self.logger = logger

    def is_valid_verification_code(self, code: Optional[str]) -> bool:
        return False

    def ingest_notifications(self, body: Any) -> Dict[str, Any]:
        self.logger.info(f"[google_push] notification received: {body}")
        return {
            "status": "not_supported",
            "provider": "google",
            "detail": "Google Fit push webhook flow is not configured in this service",
        }
