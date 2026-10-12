from __future__ import annotations

from typing import Any

import requests
from app.providers.silence_http_trace import SilenceHttpTrace


class AcconiaSilenceApi:
    """Read-only client for the ACCIONA/Silence MySilence cloud API."""

    FIREBASE_VERIFY_PASSWORD = "https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword"
    SCOOTERS_URL = "https://api.connectivity.silence.eco/api/v1/me/scooters?details=true&dynamic=true&pollIfNecessary=true"
    DEFAULT_FIREBASE_API_KEY = "AIzaSyAVnxe4u3oKETFWGiWcSb-43IsBunDDSVI"

    def __init__(self, account: str, password: str, api_key: str = "", timeout: int = 30, trace: SilenceHttpTrace | None = None):
        self.account = str(account or "").strip()
        self.password = str(password or "")
        self.api_key = str(api_key or self.DEFAULT_FIREBASE_API_KEY).strip()
        self.timeout = max(5, int(timeout or 30))
        self.trace = trace
        self._token = ""

    def _request(self, method: str, url: str, **kwargs):
        """Trace HTTP before JSON decoding; preserve requests behavior when off."""
        if self.trace is None:
            return (requests.get if method == "GET" else requests.post)(url, timeout=self.timeout, **kwargs)
        return self.trace.request(method, url, timeout=self.timeout, **kwargs)

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
        try:
            res = self._request("POST", f"{self.FIREBASE_VERIFY_PASSWORD}?key={self.api_key}", json=payload, headers=headers)
            data = res.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"MySilence Login nicht erreichbar: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("MySilence Login lieferte keine gültige JSON-Antwort") from exc

        if res.status_code >= 400 or not isinstance(data, dict) or "error" in data or "idToken" not in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            message = err.get("message") if isinstance(err, dict) else None
            if not message and isinstance(data, dict):
                message = data.get("error_description")
            raise RuntimeError(f"MySilence Login fehlgeschlagen: {message or f'HTTP {res.status_code}'}")

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
        try:
            res = self._request("GET", self.SCOOTERS_URL, headers=headers)
            if res.status_code in {401, 403}:
                self._token = ""
                self._login()
                headers["authorization"] = self._token
                res = self._request("GET", self.SCOOTERS_URL, headers=headers)
            data = res.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"MySilence API nicht erreichbar: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("MySilence API lieferte keine gültige JSON-Antwort") from exc

        if res.status_code >= 400:
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("message") or data.get("error") or "").strip()
            raise RuntimeError(f"MySilence API Fehler: HTTP {res.status_code}{f' ({detail})' if detail else ''}")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        return []
