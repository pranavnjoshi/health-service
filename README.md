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

GCP Pub/Sub setup (queue-first)

1. Create/select GCP project and enable Pub/Sub API:

```bash
gcloud config set project <YOUR_PROJECT_ID>
gcloud services enable pubsub.googleapis.com
```

2. Create a service account for this app:

```bash
gcloud iam service-accounts create health-service-queue --display-name="health-service-queue"
```

3. Grant minimal Pub/Sub permissions:

```bash
gcloud projects add-iam-policy-binding <YOUR_PROJECT_ID> \
	--member="serviceAccount:health-service-queue@<YOUR_PROJECT_ID>.iam.gserviceaccount.com" \
	--role="roles/pubsub.publisher"

gcloud projects add-iam-policy-binding <YOUR_PROJECT_ID> \
	--member="serviceAccount:health-service-queue@<YOUR_PROJECT_ID>.iam.gserviceaccount.com" \
	--role="roles/pubsub.subscriber"

gcloud projects add-iam-policy-binding <YOUR_PROJECT_ID> \
	--member="serviceAccount:health-service-queue@<YOUR_PROJECT_ID>.iam.gserviceaccount.com" \
	--role="roles/pubsub.viewer"
```

4. Create and download credentials key JSON:

```bash
gcloud iam service-accounts keys create ./secrets/gcp-pubsub-sa.json \
	--iam-account=health-service-queue@<YOUR_PROJECT_ID>.iam.gserviceaccount.com
```

5. Configure environment variables (`.env.local`):

```dotenv
QUEUE_BACKEND=gcp_pubsub
QUEUE_FALLBACK_TO_MEMORY=false
QUEUE_GCP_PROJECT_ID=<YOUR_PROJECT_ID>
QUEUE_GCP_TOPIC_PREFIX=healthsvc-
QUEUE_GCP_SUBSCRIPTIONS={"fitbit.notifications.raw":"healthsvc-fitbit-raw-sub","fitbit.notifications.retry":"healthsvc-fitbit-retry-sub","fitbit.notifications.dlq":"healthsvc-fitbit-dlq-sub"}
QUEUE_GCP_AUTO_CREATE=false
GOOGLE_APPLICATION_CREDENTIALS=./secrets/gcp-pubsub-sa.json
```

6. Automated topic/subscription setup (recommended):

```bash
python scripts/setup_gcp_pubsub.py --env-file .env.local
```

You can also override from CLI:

```bash
python scripts/setup_gcp_pubsub.py --project-id <YOUR_PROJECT_ID> --topics fitbit.notifications.raw,fitbit.notifications.retry,fitbit.notifications.dlq
```

7. Run API and worker using the same backend config:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
python scripts/run_fitbit_worker.py
```

8. Validate health endpoint:

```bash
GET /health/worker
```

Notes:
- Use `QUEUE_FALLBACK_TO_MEMORY=false` in GCP mode so startup fails fast if Pub/Sub config is wrong.
- `QUEUE_GCP_AUTO_CREATE=true` can auto-create topics/subscriptions at runtime, but explicit setup is preferred for production.

Worker process (modular stages + retry/DLQ)

- Run one worker process:

```bash
python scripts/run_fitbit_worker.py
```

- Worker stages are modular:
	- parse event
	- dedupe event
	- fetch provider details
	- persist processed output
- Default topics/queues:
	- raw: `fitbit.notifications.raw`
	- retry: `fitbit.notifications.retry`
	- dlq: `fitbit.notifications.dlq`
- Retry behavior:
	- failed events are sent to retry topic until `WORKER_MAX_RETRIES`
	- events exceeding retry limit are sent to DLQ topic

Worker logging + timing instrumentation

- Configure worker log verbosity:
	- `WORKER_LOG_LEVEL=INFO` (or `DEBUG`, `WARNING`, `ERROR`)
- Enable/disable timing logs:
	- `WORKER_TIMING_ENABLED=true`
- Control timing log level:
	- `WORKER_TIMING_LOG_LEVEL=INFO`
- Slow-call threshold (ms) for warning escalation:
	- `WORKER_TIMING_WARN_MS=1000`

Instrumentation currently logs duration for:
- queue consume calls per topic
- parse stage
- dedupe stage
- fetch details stage
- persist stage
- total event processing wrapper

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

