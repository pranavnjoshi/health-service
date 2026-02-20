import os
from typing import Dict
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

    def fetch_sleep(self, start_date: str, end_date: Optional[str] = None) -> Dict[str, Any]:
        """Fetch sleep for a single date or a date range.

        - If only `start_date` is provided, calls `/sleep/date/{date}.json`.
        - If `end_date` is provided, calls `/sleep/date/{start_date}/{end_date}.json`.

        Returns the parsed JSON response from Fitbit (contains a `sleep` list).
        """
        self._refresh_if_needed()
        if end_date:
            url = f"https://api.fitbit.com/1.2/user/-/sleep/date/{start_date}/{end_date}.json"
        else:
            url = f"https://api.fitbit.com/1.2/user/-/sleep/date/{start_date}.json"
        resp = requests.get(url, headers=self._auth_header())
        resp.raise_for_status()
        return resp.json()

    def fetch_hrv_range(self, start_date: str, end_date: str) -> dict:
        """
        Fetch HRV data for each day in the date range [start_date, end_date] (inclusive).
        Returns a dict keyed by date with the HRV data for each day.
        """
        import datetime
        results = {}
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
        cur = start_dt
        while cur <= end_dt:
            date_str = cur.strftime("%Y-%m-%d")
            results[date_str] = self.fetch_hrv(date_str)
            cur += datetime.timedelta(days=1)
        return results
    
    def fetch_hrv(self, date: str) -> Dict[str, Any]:
        """Fitbit HRV endpoints are limited; attempt to fetch HRV for date"""
        self._refresh_if_needed()
        url = f"https://api.fitbit.com/1/user/-/hrv/date/{date}.json"
        resp = requests.get(url, headers=self._auth_header())
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    def fetch_intraday_steps(self, date: str) -> List[Dict[str, Any]]:
        """Fetch minute-level step counts for a single date (YYYY-MM-DD).

        Returns a list of datapoints like {"time": "HH:MM:SS", "value": N}.
        """
        self._refresh_if_needed()
        url = f"https://api.fitbit.com/1/user/-/activities/steps/date/{date}/1d/1min.json"
        resp = requests.get(url, headers=self._auth_header())
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return data.get("activities-steps-intraday", {}).get("dataset", [])

    def fetch_intraday_heart(self, date: str, start_time: Optional[str] = None, end_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch minute-level heart rate for a single date.

        If `start_time` and `end_time` are provided they should be `HH:MM` or `HH:MM:SS`.
        Returns a list of datapoints like {"time": "HH:MM:SS", "value": N}.
        """
        self._refresh_if_needed()
        if start_time and end_time:
            url = f"https://api.fitbit.com/1/user/-/activities/heart/date/{date}/1d/1min/time/{start_time}/{end_time}.json"
        else:
            url = f"https://api.fitbit.com/1/user/-/activities/heart/date/{date}/1d/1min.json"
        resp = requests.get(url, headers=self._auth_header())
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return data.get("activities-heart-intraday", {}).get("dataset", [])

    def subscribe(self, collection: str, subscription_id: str) -> dict:
        """
        Register a subscription for a user (activities, foods, sleep, body).
        collection: e.g. 'activities', 'foods', 'sleep', 'body'
        subscription_id: unique string for this subscription (e.g. user_id)
        """
        url = f"https://api.fitbit.com/1/user/-/{collection}/apiSubscriptions/{subscription_id}.json"
        resp = requests.post(url, headers=self._auth_header())
        resp.raise_for_status()
        return resp.json() if resp.content else {"status": resp.status_code}

    def unsubscribe(self, collection: str, subscription_id: str) -> dict:
        """
        Remove a subscription for a user.
        """
        url = f"https://api.fitbit.com/1/user/-/{collection}/apiSubscriptions/{subscription_id}.json"
        resp = requests.delete(url, headers=self._auth_header())
        resp.raise_for_status()
        return {"status": resp.status_code}