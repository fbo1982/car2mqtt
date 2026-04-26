from __future__ import annotations

from typing import Any
import requests


class AcconiaSilenceApi:
    """Small read-only client based on lorenzo-deluca/homeassistant-silence."""

    FIREBASE_VERIFY_PASSWORD = "https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword"
    SCOOTERS_URL = "https://api.connectivity.silence.eco/api/v1/me/scooters?details=true&dynamic=true&pollIfNecessary=true"

    def __init__(self, account: str, password: str, api_key: str, timeout: int = 30):
        self.account = account
        self.password = password
        self.api_key = api_key
        self.timeout = timeout
        self._token = ""

    def _login(self) -> str:
        payload = {
            "email": self.account,
            "returnSecureToken": True,
            "password": self.password,
        }
        headers = {
            "content-type": "application/json",
            "accept": "*/*",
            "x-ios-bundle-identifier": "eco.silence.my",
            "x-client-version": "iOS/FirebaseSDK/8.8.0/FirebaseCore-iOS",
            "user-agent": "FirebaseAuth.iOS/8.8.0 eco.silence.my/1.2.1 iPhone/15.6.1 hw/iPhone9_3",
        }
        res = requests.post(f"{self.FIREBASE_VERIFY_PASSWORD}?key={self.api_key}", json=payload, headers=headers, timeout=self.timeout)
        data = res.json()
        if res.status_code >= 400 or "error" in data or "idToken" not in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            message = None
            if isinstance(err, dict):
                message = err.get("message")
            if not message and isinstance(data, dict):
                message = data.get("error_description")
            raise RuntimeError(f"Silence Login fehlgeschlagen: {message or res.status_code}")
        self._token = "Bearer " + str(data["idToken"])
        return self._token

    def fetch_scooters(self) -> list[dict[str, Any]]:
        if not self._token:
            self._login()
        headers = {
            "accept": "*/*",
            "user-agent": "Silence/220 CFNetwork/1220.1 Darwin/20.3.0",
            "authorization": self._token,
        }
        res = requests.get(self.SCOOTERS_URL, headers=headers, timeout=self.timeout)
        if res.status_code in {401, 403}:
            self._token = ""
            self._login()
            headers["authorization"] = self._token
            res = requests.get(self.SCOOTERS_URL, headers=headers, timeout=self.timeout)
        data = res.json()
        if res.status_code >= 400:
            raise RuntimeError(f"Silence API Fehler: HTTP {res.status_code}")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        return []
