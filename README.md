# Fitness & Sleep Data microservice

This is a FastAPI microservice that reads fitness/sleep metrics (steps, calories, weight, sleep, HRV) from providers and stores/retrieves OAuth tokens in Firebase.

Providers included:
- Fitbit: implemented client with token refresh and example endpoints
- Google Fit: example client for the Fitness REST API (requires OAuth tokens)
- Apple Health: placeholder (HealthKit doesn't provide a server-side API; see notes below)

Quick start

1. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Set environment variables (see `.env.example`) and provide Firebase service account JSON path in `FIREBASE_CREDENTIALS`.

3. Run the app:

```bash
uvicorn app.main:app --reload --port 8000
```

Endpoints
- `POST /connect/{provider}/{user_id}` : store OAuth tokens (body `access_token`, `refresh_token`, `expires_at`)
- `GET /data/{provider}/{user_id}` : fetch metrics for the user. Query params: `start`, `end`, `metrics` (comma-separated)

Queue-first ingestion (cloud-agnostic)

- Fitbit webhook notifications are enqueued first and acknowledged quickly.
- Queue backend is configured by environment variable `QUEUE_BACKEND`:
	- `memory` (default, local dev)
	- `kafka`
	- `gcp_pubsub`
	- `aws_sqs`
- Configure backend-specific variables in `.env` (see `.env.example`).
- If backend initialization fails and `QUEUE_FALLBACK_TO_MEMORY=true`, service falls back to in-memory queue.

Optional backend dependencies

- Kafka: `pip install confluent-kafka`
- GCP Pub/Sub: `pip install google-cloud-pubsub`
- AWS SQS: `pip install boto3`

Notes
- Apple Health: there is no public server-side HealthKit API. To ingest Apple Watch data you'll need to sync from-device (HealthKit) to your backend (e.g., via an iOS app) or use HealthKit export. This repo includes a placeholder showing how to wire a device upload.
- For production, implement secure OAuth flows and validate tokens. Tokens are stored in Firestore under `oauth_tokens` collection by default.

Connecting Fitbit (quick)

1. Register an application at https://dev.fitbit.com and set the redirect URI to:

	`http://127.0.0.1:8000/auth/fitbit/callback`

2. Set environment variables in your environment or `.env`:

	- `FIREBASE_CREDENTIALS` = path to Firebase service account JSON
	- `FITBIT_CLIENT_ID` and `FITBIT_CLIENT_SECRET`
	- (optional) `FITBIT_REDIRECT_URI` if you used a different redirect

3. Start the microservice and open in a browser:

	`http://127.0.0.1:8000/auth/fitbit/start/<your_user_id>`

	Fitbit will prompt you to authorize; after granting access you'll be redirected back to `/auth/fitbit/callback` and tokens will be saved in Firestore under document id `fitbit_<your_user_id>`.

4. Fetch data via the API (example):

	`GET http://127.0.0.1:8000/data/fitbit/<your_user_id>?start=2026-02-01&end=2026-02-17&metrics=steps,calories,sleep`

