import os
from typing import Optional, Dict, Any
import firebase_admin
from firebase_admin import credentials, firestore


_db = None


def init_firebase():
    global _db
    if _db:
        return _db
    cred_path = os.getenv("FIREBASE_CREDENTIALS")
    if not cred_path:
        raise RuntimeError("FIREBASE_CREDENTIALS environment variable not set")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
    _db = firestore.client()
    return _db


def save_tokens(provider: str, user_id: str, token_data: Dict[str, Any]):
    db = init_firebase()
    doc_id = f"{provider}_{user_id}"
    db.collection("oauth_tokens").document(doc_id).set(token_data)


def get_tokens(provider: str, user_id: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()
    doc_id = f"{provider}_{user_id}"
    doc = db.collection("oauth_tokens").document(doc_id).get()
    if not doc.exists:
        return None
    return doc.to_dict()
