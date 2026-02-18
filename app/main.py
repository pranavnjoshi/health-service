from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.requests import Request
import base64
import requests
from fastapi.responses import RedirectResponse
from typing import Optional, List
import os
import urllib.parse
import base64
import requests
from app.models import TokenModel, MetricsResponse
from app.firebase_client import save_tokens, get_tokens
from app.providers.fitbit import FitbitClient
from app.providers.google_fit import GoogleFitClient
from app.providers.apple_health import upload_healthkit_payload
from pydantic import BaseModel


app = FastAPI(title="Fitness Data Microservice")


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


@app.get("/data/{provider}/{user_id}")
def get_data(provider: str, user_id: str, start: Optional[str] = Query(None), end: Optional[str] = Query(None), metrics: Optional[str] = Query(None)):
    tokens = get_tokens(provider, user_id)
    if not tokens:
        raise HTTPException(status_code=404, detail="No tokens for user/provider")

    metrics_list = (metrics.split(",") if metrics else ["steps", "calories", "weight", "sleep", "hrv"])[:]

    if provider.lower() == "fitbit":
        # persist_on_refresh=True so refreshed tokens are saved back to Firebase
        client = FitbitClient(tokens, provider=provider, user_id=user_id, persist_on_refresh=True)
        resp = MetricsResponse(provider=provider, user_id=user_id)
        if "steps" in metrics_list and start and end:
            items = client.fetch_steps(start, end)
            resp.metrics["steps"] = [{"timestamp": idx, "value": int(x.get("value", 0))} for idx, x in enumerate(items)]
        if "calories" in metrics_list and start and end:
            items = client.fetch_calories(start, end)
            resp.metrics["calories"] = [{"timestamp": idx, "value": float(x.get("value", 0))} for idx, x in enumerate(items)]
        if "weight" in metrics_list and start and end:
            items = client.fetch_weight(start, end)
            resp.metrics["weight"] = [{"timestamp": idx, "value": float(x.get("weight", 0))} for idx, x in enumerate(items)]
        if "sleep" in metrics_list and start:
            sleep = client.fetch_sleep(start)
            # This returns full sleep structure; attach raw as sleep segments simplified
            segments = []
            for s in sleep.get("sleep", []):
                if "startTime" in s and "endTime" in s:
                    segments.append({"start_time": s.get("startTime"), "end_time": s.get("endTime"), "type": s.get("type", "unknown")})
            resp.sleep = segments
        if "hrv" in metrics_list and start:
            resp.metrics["hrv"] = [client.fetch_hrv(start)]
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
