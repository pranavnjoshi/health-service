from typing import Optional


class GoogleFitPullService:
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
        if not start or not end:
            raise ValueError("Google Fit requires start and end in epoch millis")

        try:
            start_ms = int(start)
            end_ms = int(end)
        except ValueError as exc:
            raise ValueError("start/end must be integer millis for Google Fit") from exc

        aggregate = client.example_steps_aggregate(start_ms * 1000000, end_ms * 1000000)
        return {"provider": provider, "user_id": user_id, "aggregate": aggregate}
