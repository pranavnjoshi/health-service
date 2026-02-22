from typing import Optional


class AppleHealthPullService:
    def __init__(self, logger):
        self.logger = logger

    def fetch_metrics(
        self,
        *,
        provider: str,
        user_id: str,
        client,
        metrics_list: list[str],
        start: Optional[str],
        end: Optional[str],
        time_start: Optional[str],
        time_end: Optional[str],
    ):
        raise NotImplementedError("Apple Health pull is not supported server-side; use device uploads")
