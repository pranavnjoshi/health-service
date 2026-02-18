from typing import Dict, Any


def upload_healthkit_payload(user_id: str, payload: Dict[str, Any]):
    """Placeholder: Apple Health/HealthKit data is collected on-device.

    To ingest Apple Watch data you'll need an iOS app to read HealthKit and POST
    data to this service. This function represents a receiver for such uploads.
    """
    # This is intentionally minimal; implement validation + auth when using.
    # Example payload fields: steps, sleepSegments, heartRateSamples, weightEntries
    # Persist as needed (e.g., Firestore or another DB).
    return {"status": "received", "user_id": user_id, "items": len(payload.get("items", []))}
