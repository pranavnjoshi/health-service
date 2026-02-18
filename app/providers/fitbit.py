import os
import base64
import time
from typing import Dict, Any, List, Optional
import requests

from app.firebase_client import save_tokens


class FitbitClient:
    TOKEN_URL = "https://api.fitbit.com/oauth2/token"

    def __init__(self, tokens: Dict[str, Any], provider: str = "fitbit", user_id: Optional[str] = None, persist_on_refresh: bool = False):
        self.tokens = tokens
        self.client_id = os.getenv("FITBIT_CLIENT_ID")
        self.client_secret = os.getenv("FITBIT_CLIENT_SECRET")
        self.provider = provider
        self.user_id = user_id
        self.persist_on_refresh = persist_on_refresh

    def _auth_header(self):
        return {"Authorization": f"Bearer {self.tokens['access_token']}"}

    def _refresh_if_needed(self):
        expires_at = self.tokens.get("expires_at")
        if expires_at and time.time() > expires_at - 60:
            self._refresh_token()

    def _refresh_token(self):
        if not self.tokens.get("refresh_token"):
            raise RuntimeError("No refresh token available")
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}
        data = {"grant_type": "refresh_token", "refresh_token": self.tokens["refresh_token"]}
        resp = requests.post(self.TOKEN_URL, headers=headers, data=data)
        resp.raise_for_status()
        tok = resp.json()
        # Update local tokens (caller should persist via Firebase)
        self.tokens.update({
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token", self.tokens.get("refresh_token")),
            "expires_at": int(time.time()) + tok.get("expires_in", 3600),
        })
        # Persist if configured and user_id is known
        if self.persist_on_refresh and self.user_id:
            try:
                save_tokens(self.provider, self.user_id, self.tokens)
            except Exception:
                # Silently ignore persistence errors here; caller can opt to re-save
                pass

    def fetch_steps(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Fetch daily step totals between dates (YYYY-MM-DD)."""
        self._refresh_if_needed()
        url = f"https://api.fitbit.com/1/user/-/activities/steps/date/{start_date}/{end_date}.json"
        resp = requests.get(url, headers=self._auth_header())
        resp.raise_for_status()
        data = resp.json()
        # Fitbit returns list of date/value
        return data.get("activities-steps", [])

    def fetch_calories(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        self._refresh_if_needed()
        url = f"https://api.fitbit.com/1/user/-/activities/calories/date/{start_date}/{end_date}.json"
        resp = requests.get(url, headers=self._auth_header())
        resp.raise_for_status()
        return resp.json().get("activities-calories", [])

    def fetch_weight(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        self._refresh_if_needed()
        url = f"https://api.fitbit.com/1/user/-/body/log/weight/date/{start_date}/{end_date}.json"
        resp = requests.get(url, headers=self._auth_header())
        resp.raise_for_status()
        return resp.json().get("weight", [])

    def fetch_sleep(self, date: str) -> Dict[str, Any]:
        """Fetch sleep for a particular date (YYYY-MM-DD)"""
        self._refresh_if_needed()
        url = f"https://api.fitbit.com/1.2/user/-/sleep/date/{date}.json"
        resp = requests.get(url, headers=self._auth_header())
        resp.raise_for_status()
        return resp.json()

    def fetch_hrv(self, date: str) -> Dict[str, Any]:
        """Fitbit HRV endpoints are limited; attempt to fetch HRV for date"""
        self._refresh_if_needed()
        url = f"https://api.fitbit.com/1/user/-/hrv/date/{date}.json"
        resp = requests.get(url, headers=self._auth_header())
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
