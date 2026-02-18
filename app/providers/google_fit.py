import os
from typing import Dict, Any, List
import requests


class GoogleFitClient:
    BASE = "https://www.googleapis.com/fitness/v1"

    def __init__(self, tokens: Dict[str, Any]):
        self.tokens = tokens

    def _headers(self):
        return {"Authorization": f"Bearer {self.tokens['access_token']}", "Content-Type": "application/json"}

    def fetch_aggregated(self, body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.BASE}/users/me/dataset:aggregate"
        resp = requests.post(url, headers=self._headers(), json=body)
        if resp.status_code == 401 and self.tokens.get("refresh_token"):
            # Token refresh should be implemented by caller; here we just return error
            raise RuntimeError("Token expired: refresh externally and retry")
        resp.raise_for_status()
        return resp.json()

    def example_steps_aggregate(self, start_ns: int, end_ns: int) -> Dict[str, Any]:
        # dataTypeName: com.google.step_count.delta
        body = {
            "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
            "bucketByTime": {"durationMillis": (end_ns - start_ns) // 1000000},
            "startTimeMillis": start_ns // 1000000,
            "endTimeMillis": end_ns // 1000000,
        }
        return self.fetch_aggregated(body)
