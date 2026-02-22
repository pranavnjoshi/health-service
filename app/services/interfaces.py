from typing import Any, Dict, Optional, Protocol


class ProviderPushService(Protocol):
    def is_valid_verification_code(self, code: Optional[str]) -> bool:
        ...

    def ingest_notifications(self, body: Any) -> Dict[str, Any]:
        ...


class ProviderPullService(Protocol):
    def fetch_metrics(
        self,
        *,
        provider: str,
        user_id: str,
        client: Any,
        metrics_list: list[str],
        start: Optional[str],
        end: Optional[str],
        time_start: Optional[str],
        time_end: Optional[str],
    ) -> Any:
        ...
