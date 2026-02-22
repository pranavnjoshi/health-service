from typing import Callable, Optional

from app.models import FitbitSleepLog, MetricPoint, MetricsResponse, SleepSegment


class FitbitPullService:
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
        to_unix_timestamp: Callable[[object], int],
    ) -> MetricsResponse:
        return build_fitbit_metrics_response(
            provider=provider,
            user_id=user_id,
            client=client,
            metrics_list=metrics_list,
            start=start,
            end=end,
            time_start=time_start,
            time_end=time_end,
            logger=self.logger,
            to_unix_timestamp=to_unix_timestamp,
        )


def build_fitbit_metrics_response(
    *,
    provider: str,
    user_id: str,
    client,
    metrics_list: list[str],
    start: Optional[str],
    end: Optional[str],
    time_start: Optional[str],
    time_end: Optional[str],
    logger,
    to_unix_timestamp: Callable[[object], int],
) -> MetricsResponse:
    resp = MetricsResponse(provider=provider, user_id=user_id)

    if "steps" in metrics_list and start and end:
        items = client.fetch_steps(start, end)
        resp.metrics["steps"] = [MetricPoint(timestamp=idx, value=float(x.get("value", 0))) for idx, x in enumerate(items)]

    if "calories" in metrics_list and start and end:
        items = client.fetch_calories(start, end)
        resp.metrics["calories"] = [MetricPoint(timestamp=idx, value=float(x.get("value", 0))) for idx, x in enumerate(items)]

    if "weight" in metrics_list and start and end:
        items = client.fetch_weight(start, end)
        resp.metrics["weight"] = [MetricPoint(timestamp=idx, value=float(x.get("weight", 0))) for idx, x in enumerate(items)]

    if "sleep" in metrics_list and start:
        logger.info(f"Fetching sleep for user_id={user_id}")

        resp.metrics["sleep_stages"] = []
        resp.sleep = []

        sleep_data = client.fetch_sleep(start, end)
        raw_logs = sleep_data.get("sleep", [])

        formatted_logs = []
        segments = []

        for log in raw_logs:
            try:
                formatted_logs.append(FitbitSleepLog(**log))
            except Exception as exc:
                logger.warning(f"Validation failed for log {log.get('logId')}: {exc}")

            st_ts = to_unix_timestamp(log.get("startTime"))
            et_ts = to_unix_timestamp(log.get("endTime"))

            if st_ts > 0 and et_ts > 0:
                segments.append(
                    SleepSegment(
                        start_time=st_ts,
                        end_time=et_ts,
                        type=log.get("type", "unknown"),
                    )
                )

        resp.metrics["sleep_stages"] = formatted_logs
        resp.sleep = segments

    if "hrv" in metrics_list and start:
        hrv_data = client.fetch_hrv(start)
        if isinstance(hrv_data, dict) and "value" in hrv_data:
            resp.metrics["hrv"] = [MetricPoint(timestamp=0, value=float(hrv_data["value"]))]
        else:
            resp.metrics["hrv"] = [hrv_data]

    if "steps_minute" in metrics_list and start:
        items = client.fetch_intraday_steps(start)
        resp.metrics["steps_minute"] = [MetricPoint(timestamp=idx, value=float(x.get("value", 0))) for idx, x in enumerate(items)]

    if "heart_minute" in metrics_list and start:
        items = client.fetch_intraday_heart(start, start_time=time_start, end_time=time_end)
        resp.metrics["heart_minute"] = [MetricPoint(timestamp=idx, value=float(x.get("value", 0))) for idx, x in enumerate(items)]

    return resp
