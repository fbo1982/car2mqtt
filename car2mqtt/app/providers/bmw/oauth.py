from __future__ import annotations

# Based on the public BMW CarData OAuth2 device-flow approach described in
# bausi2k/bmw-python-streaming-mqtt-bridge and its bundled client library.

import base64
import hashlib
import secrets
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import requests

from app.core.models import AuthSession

DEVICE_CODE_URL = "https://customer.bmwgroup.com/gcdm/oauth/device/code"
TOKEN_URL = "https://customer.bmwgroup.com/gcdm/oauth/token"
SCOPE = "authenticate_user openid cardata:streaming:read cardata:api:read"


def generate_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).decode("utf-8").rstrip("=")
    return verifier, challenge


def start_device_flow(client_id: str, vin: str, license_plate: str) -> AuthSession:
    verifier, challenge = generate_pkce_pair()
    payload = {
        "client_id": client_id,
        "response_type": "device_code",
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(DEVICE_CODE_URL, data=payload, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    verification_uri = data["verification_uri"]
    verification_uri_complete = data.get("verification_uri_complete") or f"{verification_uri}?user_code={data['user_code']}"
    return AuthSession(
        session_id=uuid.uuid4().hex,
        provider_id="bmw",
        client_id=client_id,
        vin=vin,
        license_plate=license_plate,
        code_verifier=verifier,
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_uri=verification_uri,
        verification_uri_complete=verification_uri_complete,
        interval=int(data.get("interval", 5)),
        expires_at=time.time() + int(data.get("expires_in", 600)),
        message="Warte auf BMW-Anmeldung…",
    )


def poll_device_flow(session: AuthSession) -> AuthSession | Dict[str, Any]:
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    payload = {
        "client_id": session.client_id,
        "device_code": session.device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "code_verifier": session.code_verifier,
    }
    response = requests.post(TOKEN_URL, data=payload, headers=headers, timeout=30)
    if response.status_code == 200:
        return _store_tokens(session, response.json())
    if response.status_code in (400, 403):
        data = response.json()
        error = data.get("error", "")
        if error == "authorization_pending":
            session.state = "pending"
            session.message = "Anmeldung läuft noch. Bitte BMW-Seite abschließen."
            return session
        if error == "access_denied":
            session.state = "denied"
            session.message = "BMW-Zugriff wurde abgelehnt."
            return session
        if error == "slow_down":
            session.state = "pending"
            session.message = "BMW verlangt langsameres Polling. Bitte in wenigen Sekunden erneut prüfen."
            return session
        session.state = "error"
        session.message = f"BMW meldet Fehler: {error or response.text}"
        return session
    response.raise_for_status()
    return session


def _store_tokens(session: AuthSession, tokens: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.utcnow()
    stored = {
        "refresh_token": {
            "token": tokens.get("refresh_token", ""),
            "expires_at": (now + timedelta(days=14)).isoformat(),
        },
        "id_token": {
            "token": tokens.get("id_token", ""),
            "expires_at": (now + timedelta(seconds=int(tokens.get("expires_in", 3600)))).isoformat(),
        },
        "access_token": {
            "token": tokens.get("access_token", ""),
            "expires_at": (now + timedelta(seconds=int(tokens.get("expires_in", 3600)))).isoformat(),
        },
        "gcid": tokens.get("gcid", ""),
        "scope": tokens.get("scope", ""),
    }
    return stored


def save_token_file(token_file: Path, tokens: Dict[str, Any]) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(__import__("json").dumps(tokens, indent=2), encoding="utf-8")
