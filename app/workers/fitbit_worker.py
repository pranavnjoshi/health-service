import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from app.firebase_client import get_tokens
from app.providers.fitbit import FitbitClient
from app.services.event_bus import create_queue_client_from_env
from app.services.instrumentation import timed_call


class ParseStage:
    def run(self, event: Dict[str, Any]) -> Dict[str, Any]:
        context = {
            "event": event,
            "received_at": datetime.utcnow().isoformat() + "Z",
            "retry_count": int(event.get("retry_count", 0) or 0),
            "provider": "fitbit",
        }
        return context


class DedupeStage:
    def __init__(self):
        self._seen = set()

    def _key(self, event: Dict[str, Any]) -> str:
        parts = [
            "fitbit",
            str(event.get("ownerId", "")),
            str(event.get("subscriptionId", "")),
            str(event.get("collectionType", "")),
            str(event.get("date", "")),
        ]
        return "|".join(parts)

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        event = context["event"]
        key = self._key(event)
        context["dedupe_key"] = key
        context["is_duplicate"] = key in self._seen
        if not context["is_duplicate"]:
            self._seen.add(key)
        return context


class FetchDetailsStage:
    def _infer_user_id(self, event: Dict[str, Any]) -> str:
        subscription_id = str(event.get("subscriptionId", "")).strip()
        if subscription_id and "-" in subscription_id:
            return subscription_id.split("-")[0]
        return os.getenv("WORKER_DEFAULT_USER_ID", "me")

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        event = context["event"]
        collection = str(event.get("collectionType", "")).lower()
        event_date = str(event.get("date", ""))
        user_id = self._infer_user_id(event)

        tokens = get_tokens("fitbit", user_id)
        if not tokens:
            raise RuntimeError(f"No Fitbit tokens found for user_id={user_id}")

        client = FitbitClient(tokens, provider="fitbit", user_id=user_id, persist_on_refresh=True)

        details: Dict[str, Any] = {
            "user_id": user_id,
            "collectionType": collection,
            "date": event_date,
        }

        if collection == "activities":
            if event_date:
                details["steps"] = client.fetch_steps(event_date, event_date)
                details["calories"] = client.fetch_calories(event_date, event_date)
                details["hrv"] = client.fetch_hrv(event_date)
        elif collection == "sleep":
            if event_date:
                details["sleep"] = client.fetch_sleep(event_date)
        elif collection == "body":
            if event_date:
                details["weight"] = client.fetch_weight(event_date, event_date)
        else:
            details["note"] = f"No fetch strategy for collectionType={collection}"

        context["details"] = details
        return context


class PersistStage:
    def __init__(self, output_file: Optional[str] = None):
        path = output_file or os.getenv("WORKER_OUTPUT_FILE", "worker_processed_events.jsonl")
        self.output_path = Path(path)

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "processed_at": datetime.utcnow().isoformat() + "Z",
            "event": context.get("event"),
            "details": context.get("details"),
            "dedupe_key": context.get("dedupe_key"),
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return context


class FitbitEventWorker:
    def __init__(self, logger):
        self.logger = logger
        self.queue = create_queue_client_from_env(logger=logger)

        self.raw_topic = os.getenv("WORKER_TOPIC_RAW", "fitbit.notifications.raw")
        self.retry_topic = os.getenv("WORKER_TOPIC_RETRY", "fitbit.notifications.retry")
        self.dlq_topic = os.getenv("WORKER_TOPIC_DLQ", "fitbit.notifications.dlq")

        self.max_retries = int(os.getenv("WORKER_MAX_RETRIES", "3"))
        self.batch_size = int(os.getenv("WORKER_BATCH_SIZE", "25"))
        self.poll_seconds = int(os.getenv("WORKER_POLL_SECONDS", "2"))
        self.timing_enabled = os.getenv("WORKER_TIMING_ENABLED", "true").strip().lower() == "true"
        self.timing_log_level = os.getenv("WORKER_TIMING_LOG_LEVEL", "info").strip().lower()
        self.timing_warn_ms = float(os.getenv("WORKER_TIMING_WARN_MS", "1000"))

        self.parse_stage = ParseStage()
        self.dedupe_stage = DedupeStage()
        self.fetch_stage = FetchDetailsStage()
        self.persist_stage = PersistStage()

    def _timed(self, operation: str, fn, *args, **kwargs):
        return timed_call(
            self.logger,
            operation,
            fn,
            *args,
            enabled=self.timing_enabled,
            log_level=self.timing_log_level,
            warn_threshold_ms=self.timing_warn_ms,
            **kwargs,
        )

    @staticmethod
    def _is_idle_timeout_error(exc: Exception) -> bool:
        name = exc.__class__.__name__.lower()
        msg = str(exc).lower()
        return (
            "deadlineexceeded" in name
            or "timeoutexceeded" in name
            or "deadline exceeded" in msg
            or "timed out" in msg
        )

    def _process_event(self, event: Dict[str, Any]) -> None:
        context = self._timed("worker.stage.parse", self.parse_stage.run, event)
        context = self._timed("worker.stage.dedupe", self.dedupe_stage.run, context)

        if context.get("is_duplicate"):
            self.logger.info(f"[worker] duplicate skipped: {context.get('dedupe_key')}")
            return

        context = self._timed("worker.stage.fetch_details", self.fetch_stage.run, context)
        self._timed("worker.stage.persist", self.persist_stage.run, context)
        self.logger.info(f"[worker] processed event: {context.get('dedupe_key')}")

    def _handle_failure(self, event: Dict[str, Any], exc: Exception) -> None:
        retry_count = int(event.get("retry_count", 0) or 0)
        updated = dict(event)
        updated["retry_count"] = retry_count + 1
        updated["last_error"] = str(exc)

        if retry_count < self.max_retries:
            self.queue.publish_many(self.retry_topic, [updated])
            self.logger.warning(
                f"[worker] event failed; queued to retry topic={self.retry_topic}, retry_count={updated['retry_count']}, error={exc}"
            )
            return

        self.queue.publish_many(self.dlq_topic, [updated])
        self.logger.error(
            f"[worker] event moved to DLQ topic={self.dlq_topic}, retry_count={updated['retry_count']}, error={exc}"
        )

    def _drain_topic(self, topic: str) -> int:
        consume = getattr(self.queue, "consume_batch", None)
        if not consume:
            raise RuntimeError("Configured queue backend does not support consume_batch required by worker")

        try:
            events = self._timed(
                f"worker.queue.consume.{topic}",
                consume,
                topic,
                max_messages=self.batch_size,
                wait_seconds=self.poll_seconds,
                suppress_error_fn=self._is_idle_timeout_error,
            )
        except Exception as exc:
            if self._is_idle_timeout_error(exc):
                self.logger.debug(f"[worker] idle poll timeout for topic={topic}")
            else:
                self.logger.warning(f"[worker] consume error for topic={topic}: {exc}")
            return 0
        processed = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            try:
                self._timed("worker.event.process", self._process_event, event)
            except Exception as exc:
                self._handle_failure(event, exc)
            processed += 1
        return processed

    def run_forever(self) -> None:
        self.logger.info(
            f"[worker] starting with topics raw={self.raw_topic}, retry={self.retry_topic}, dlq={self.dlq_topic}"
        )
        while True:
            processed_raw = self._drain_topic(self.raw_topic)
            processed_retry = self._drain_topic(self.retry_topic)
            if processed_raw == 0 and processed_retry == 0:
                time.sleep(self.poll_seconds)


def run_worker(logger):
    load_dotenv(".env.local")
    worker = FitbitEventWorker(logger=logger)
    worker.run_forever()
