from fastapi import Request as FastAPIRequest
# Fitbit Webhook endpoint for Subscriptions API
@app.api_route("/webhook/fitbit", methods=["GET", "POST"])
async def fitbit_webhook(request: FastAPIRequest):
    # Verification: Fitbit sends a GET with a verify code
    if request.method == "GET":
        verify_code = os.getenv("FITBIT_SUBSCRIPTION_VERIFY_CODE", "")
        code = request.query_params.get("verify")
        if code and code == verify_code:
            logger.info(f"[webhook] Fitbit verification succeeded")
            return HTMLResponse(content=code, status_code=204)
        logger.warning(f"[webhook] Fitbit verification failed: {code}")
        return HTMLResponse(content="Invalid verification code", status_code=404)
    # Notification: Fitbit sends a POST with JSON body
    body = await request.json()
    logger.info(f"[webhook] Fitbit notification received: {body}")
    # TODO: Add your coaching/processing logic here
    return {"status": "received"}
from statistics import mean
import dateutil
from fastapi import FastAPI, HTTPException, Body, Query
from dotenv import load_dotenv
load_dotenv(".env.local")
import logging
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.requests import Request
import base64
import requests
import time
from fastapi.responses import RedirectResponse
from typing import Optional, List
import os
import urllib.parse
import base64
import requests
from app.models import TokenModel, MetricsResponse, SleepSegment, MetricPoint, FitbitSleepLog
from app.firebase_client import save_tokens, get_tokens
from app.providers.fitbit import FitbitClient
from app.providers.google_fit import GoogleFitClient
from app.providers.apple_health import upload_healthkit_payload
from pydantic import BaseModel
import logging
from logging.handlers import RotatingFileHandler

# Log to both file and console
log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
file_handler = RotatingFileHandler('app.log', maxBytes=2*1024*1024, backupCount=2)
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logger = logging.getLogger("fitbit_debug")
logger.setLevel(logging.INFO)
logger.handlers = []  # Remove any default handlers
logger.addHandler(file_handler)
logger.addHandler(console_handler)
app = FastAPI(title="Fitness Data Microservice")

# Define this at the top level of main.py
def to_unix_timestamp(val):
    """Converts Fitbit ISO strings to Unix integer timestamps."""
    if not val: return 0
    if isinstance(val, (int, float)): return int(val)
    try:
        # Handles format like '2026-02-18T23:16:30.000'
        dt = dateutil.parser.isoparse(val)
        return int(calendar.timegm(dt.utctimetuple()))
    except Exception:
        return 0
    
class ConnectBody(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[int] = None
    scope: Optional[str] = None
    token_type: Optional[str] = None


@app.post("/connect/{provider}/{user_id}")
def connect_provider(provider: str, user_id: str, body: ConnectBody):
    # Validate simple
    token = body.dict()
    save_tokens(provider, user_id, token)
    return {"status": "saved", "provider": provider, "user_id": user_id}


@app.get("/auth/fitbit/start/{user_id}")
def fitbit_auth_start(user_id: str, redirect: Optional[str] = None):
    """Begin OAuth flow for Fitbit. Register redirect URI in the Fitbit app as
    `FITBIT_REDIRECT_URI` (default http://127.0.0.1:8000/auth/fitbit/callback).
    Use `state` to carry `user_id` so callback can persist tokens for that user.
    """
    client_id = os.getenv("FITBIT_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="FITBIT_CLIENT_ID not set")
    redirect_uri = os.getenv("FITBIT_REDIRECT_URI", "http://127.0.0.1:8000/auth/fitbit/callback")
    scope = os.getenv("FITBIT_SCOPES", "activity sleep heartrate weight profile")
    state = user_id
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": scope,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    from urllib.parse import urlencode

    url = f"https://www.fitbit.com/oauth2/authorize?{urlencode(params)}"
    return RedirectResponse(url)


@app.get("/auth/fitbit/callback")
def fitbit_auth_callback(request: Request):
    """Callback endpoint Fitbit redirects to with `code` and `state`.

    Exchanges authorization `code` for tokens and persists them with `save_tokens`.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    if error:
        return HTMLResponse(content=f"<h3>Fitbit OAuth error: {error}</h3>", status_code=400)
    if not code or not state:
        return HTMLResponse(content="<h3>Missing code or state in callback</h3>", status_code=400)

    client_id = os.getenv("FITBIT_CLIENT_ID")
    client_secret = os.getenv("FITBIT_CLIENT_SECRET")
    redirect_uri = os.getenv("FITBIT_REDIRECT_URI", "http://127.0.0.1:8000/auth/fitbit/callback")
    if not client_id or not client_secret:
        return HTMLResponse(content="<h3>Fitbit client credentials not configured on server</h3>", status_code=500)

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    try:
        resp = requests.post("https://api.fitbit.com/oauth2/token", headers=headers, data=data)
        resp.raise_for_status()
        tok = resp.json()
    except requests.RequestException as exc:
        return HTMLResponse(content=f"<h3>Token exchange failed: {exc}</h3>", status_code=500)

    # Normalize token payload we store
    token_payload = {
        "access_token": tok.get("access_token"),
        "refresh_token": tok.get("refresh_token"),
        "expires_at": int(time.time()) + int(tok.get("expires_in", 3600)),
        "scope": tok.get("scope"),
        "token_type": tok.get("token_type"),
    }
    try:
        save_tokens("fitbit", state, token_payload)
    except Exception as exc:
        return HTMLResponse(content=f"<h3>Failed saving tokens: {exc}</h3>", status_code=500)

    return HTMLResponse(content=f"<h3>Fitbit connected for user {state}</h3>")

# Heart rate statistics endpoint
import time as _time

# Heart rate statistics endpoint
@app.get("/data/{provider}/{user_id}/heart_stats")
def get_heart_stats(provider: str, user_id: str, start: str = Query(...), end: Optional[str] = Query(None)):
    """
    Returns daily heart rate statistics (average, max, min, resting) for a given date or date range.
    If end is not provided, only the start date is used.
    """
    import datetime
    logger.info(f"[heart_stats] Request: provider={provider}, user_id={user_id}, start={start}, end={end}")
    t0 = _time.time()
    tokens = get_tokens(provider, user_id)
    if not tokens:
        logger.error(f"[heart_stats] No tokens for provider={provider}, user_id={user_id}")
        raise HTTPException(status_code=404, detail="No tokens for user/provider")
    if provider.lower() != "fitbit":
        logger.error(f"[heart_stats] Unsupported provider: {provider}")
        raise HTTPException(status_code=400, detail="Only Fitbit is supported for heart rate stats")
    client = FitbitClient(tokens, provider=provider, user_id=user_id, persist_on_refresh=True)
    # Build date list
    date_list = []
    start_dt = datetime.datetime.strptime(start, "%Y-%m-%d")
    if end:
        end_dt = datetime.datetime.strptime(end, "%Y-%m-%d")
        cur = start_dt
        while cur <= end_dt:
            date_list.append(cur.strftime("%Y-%m-%d"))
            cur += datetime.timedelta(days=1)
    else:
        date_list = [start_dt.strftime("%Y-%m-%d")]
    results = []
    for date_str in date_list:
        logger.info(f"[heart_stats] Fetching heart data for {date_str}")
        t1 = _time.time()
        heart_data = client.fetch_intraday_heart(date_str)
        values = [x["value"] for x in heart_data if "value" in x]
        fetch_ms = int((_time.time() - t1) * 1000)
        logger.info(f"[heart_stats] {date_str}: fetched {len(values)} points in {fetch_ms} ms")
        if not values:
            stats = {"date": date_str, "average": None, "max": None, "min": None, "resting": None}
        else:
            # Try to get resting heart rate from summary if available
            resting = None
            url = f"https://api.fitbit.com/1/user/-/activities/heart/date/{date_str}/1d.json"
            t2 = _time.time()
            resp = requests.get(url, headers=client._auth_header())
            summary_ms = int((_time.time() - t2) * 1000)
            if resp.ok:
                try:
                    summary = resp.json().get("activities-heart", [{}])[0].get("value", {})
                    resting = summary.get("restingHeartRate")
                except Exception:
                    resting = None
            logger.info(f"[heart_stats] {date_str}: resting HR fetch in {summary_ms} ms")
            stats = {
                "date": date_str,
                "average": round(mean(values), 2) if values else None,
                "max": max(values) if values else None,
                "min": min(values) if values else None,
                "resting": resting
            }
        results.append(stats)
    total_ms = int((_time.time() - t0) * 1000)
    logger.info(f"[heart_stats] Completed for user_id={user_id}, provider={provider}, days={len(date_list)}, total_time_ms={total_ms}")
    return {"provider": provider, "user_id": user_id, "heart_rate_stats": results, "duration_ms": total_ms}

@app.get("/data/{provider}/{user_id}")
def get_data(provider: str, user_id: str, start: Optional[str] = Query(None), end: Optional[str] = Query(None), time_start: Optional[str] = Query(None), time_end: Optional[str] = Query(None), metrics: Optional[str] = Query(None)):
    tokens = get_tokens(provider, user_id)
    if not tokens:
        logger.error(f"No tokens for provider={provider}, user_id={user_id}")
        raise HTTPException(status_code=404, detail="No tokens for user/provider")

    metrics_list = (metrics.split(",") if metrics else ["steps", "calories", "weight", "sleep", "hrv"] )[:]

    if provider.lower() == "fitbit":
        client = FitbitClient(tokens, provider=provider, user_id=user_id, persist_on_refresh=True)
        resp = MetricsResponse(provider=provider, user_id=user_id)
        try:
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
                
                # Initialize explicitly to handle empty responses
                resp.metrics["sleep_stages"] = []
                resp.sleep = []
                
                sleep_data = client.fetch_sleep(start, end)
                raw_logs = sleep_data.get("sleep", [])
                
                formatted_logs = []
                segments = []
                
                for log in raw_logs:
                    # 1. Parse full Fitbit log
                    try:
                        formatted_logs.append(FitbitSleepLog(**log))
                    except Exception as e:
                        logger.warning(f"Validation failed for log {log.get('logId')}: {e}")

                    # 2. Parse into simplified SleepSegments
                    st_ts = to_unix_timestamp(log.get("startTime"))
                    et_ts = to_unix_timestamp(log.get("endTime"))
                    
                    if st_ts > 0 and et_ts > 0:
                        segments.append(SleepSegment(
                            start_time=st_ts, 
                            end_time=et_ts, 
                            type=log.get("type", "unknown")
                        ))
                
                resp.metrics["sleep_stages"] = formatted_logs
                resp.sleep = segments
            if "hrv" in metrics_list and start:
                # If you have a MetricPoint model for HRV, use it; else keep as dict
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
        except Exception as exc:
            logger.exception(f"Error fetching data for provider={provider}, user_id={user_id}, metrics={metrics_list}, start={start}, end={end}: {exc}")
            raise HTTPException(status_code=500, detail=f"Error fetching data: {exc}")
        return resp


@app.get("/oauth/fitbit/start/{user_id}")
def fitbit_oauth_start(user_id: str, redirect_uri: Optional[str] = Query(None)):
    client_id = os.getenv("FITBIT_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="FITBIT_CLIENT_ID not configured")
    scope = "activity heartrate sleep profile weight"
    redirect = redirect_uri or os.getenv("FITBIT_REDIRECT_URI")
    if not redirect:
        raise HTTPException(status_code=400, detail="redirect_uri required")
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "scope": scope,
        "state": user_id,
    }
    url = f"https://www.fitbit.com/oauth2/authorize?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)


@app.get("/oauth/fitbit/callback")
def fitbit_oauth_callback(code: str = Query(...), state: Optional[str] = Query(None), redirect_uri: Optional[str] = Query(None)):
    client_id = os.getenv("FITBIT_CLIENT_ID")
    client_secret = os.getenv("FITBIT_CLIENT_SECRET")
    redirect = redirect_uri or os.getenv("FITBIT_REDIRECT_URI")
    if not client_id or not client_secret or not redirect:
        raise HTTPException(status_code=500, detail="Fitbit OAuth not configured")
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"client_id": client_id, "grant_type": "authorization_code", "redirect_uri": redirect, "code": code}
    resp = requests.post("https://api.fitbit.com/oauth2/token", headers=headers, data=data)
    resp.raise_for_status()
    tok = resp.json()
    # Save tokens in Firebase (state holds user_id)
    save_tokens("fitbit", state or "unknown", tok)
    return {"status": "saved", "provider": "fitbit", "user_id": state, "tokens": tok}


@app.get("/oauth/google/start/{user_id}")
def google_oauth_start(user_id: str, redirect_uri: Optional[str] = Query(None)):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")
    redirect = redirect_uri or os.getenv("GOOGLE_REDIRECT_URI")
    if not redirect:
        raise HTTPException(status_code=400, detail="redirect_uri required")
    scope = "https://www.googleapis.com/auth/fitness.activity.read https://www.googleapis.com/auth/fitness.heart_rate.read https://www.googleapis.com/auth/fitness.sleep.read https://www.googleapis.com/auth/fitness.body.read"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "state": user_id,
        "prompt": "consent",
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)


@app.get("/oauth/google/callback")
def google_oauth_callback(code: str = Query(...), state: Optional[str] = Query(None), redirect_uri: Optional[str] = Query(None)):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect = redirect_uri or os.getenv("GOOGLE_REDIRECT_URI")
    if not client_id or not client_secret or not redirect:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }
    resp = requests.post(token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp.raise_for_status()
    tok = resp.json()
    save_tokens("google", state or "unknown", tok)
    return {"status": "saved", "provider": "google", "user_id": state, "tokens": tok}

    if provider.lower() == "google":
        client = GoogleFitClient(tokens)
        # Example requires start/end in milliseconds (or nanos). This endpoint is flexible — caller provides params.
        # For demonstration we require start/end to be epoch milliseconds passed as strings.
        if not start or not end:
            raise HTTPException(status_code=400, detail="Google Fit requires start and end (millis)")
        try:
            start_ms = int(start)
            end_ms = int(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="start/end must be integer millis for Google Fit")
        # Example: aggregate steps
        agg = client.example_steps_aggregate(start_ms * 1000000, end_ms * 1000000)
        return {"provider": provider, "user_id": user_id, "aggregate": agg}

    if provider.lower() == "apple":
        # Apple Health flows are device-driven; accept uploads
        raise HTTPException(status_code=501, detail="Use the device-upload endpoint for Apple Health")

    raise HTTPException(status_code=400, detail="Unknown provider")


@app.post("/apple/upload/{user_id}")
def apple_upload(user_id: str, payload: dict = Body(...)):
    # This endpoint acts as an ingestion point for HealthKit exports or device uploads
    result = upload_healthkit_payload(user_id, payload)
    return result
