from __future__ import annotations

from typing import Any, Dict

from app.core.models import ProviderDescriptor
from app.providers.acconia_api import AcconiaSilenceApi
from app.providers.base import BaseProvider


class AcconiaProvider(BaseProvider):
    """Provider descriptor kept under the historic id ``acconia`` for compatibility."""

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="acconia",
            name="ACCIONA / Silence (MySilence)",
            category="API",
            auth_mode="account",
            badge="Silence",
            notes=(
                "Read-only Cloud-Anbindung an die MySilence App. Car2MQTT liest GPS-Position, "
                "Ladezustand und Restreichweite aus und veröffentlicht die Werte im einheitlichen MQTT-Schema."
            ),
            setup_steps=[
                "E-Mail-Adresse und Passwort der MySilence App eintragen.",
                "Bei mehreren Fahrzeugen optional FrameNo, IMEI oder Fahrzeugname als Auswahl eintragen.",
                "Der integrierte Firebase API-Key wird automatisch verwendet; ein eigener Key ist nur bei API-Änderungen nötig.",
            ],
            fields=[
                {"name": "account", "label": "MySilence E-Mail", "type": "text", "required": True},
                {"name": "password", "label": "MySilence Passwort", "type": "password", "required": True},
                {"name": "scooter_id", "label": "FrameNo / IMEI / Name", "type": "text", "required": False},
                {"name": "poll_interval", "label": "Polling-Intervall (Sekunden)", "type": "number", "required": False, "default": 60},
                {"name": "capacity_kwh", "label": "Akkukapazität gesamt (kWh)", "type": "number", "required": False},
                {"name": "api_key", "label": "Firebase API-Key (optional)", "type": "password", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        account = str(provider_config.get("account", "") or provider_config.get("username", "")).strip()
        password = str(provider_config.get("password", "") or "")
        api_key = str(provider_config.get("api_key", "") or provider_config.get("apikey", "") or AcconiaSilenceApi.DEFAULT_FIREBASE_API_KEY).strip()
        scooter_id = str(provider_config.get("scooter_id", "") or provider_config.get("frame_no", "") or provider_config.get("imei", "")).strip()
        if not account:
            raise ValueError("MySilence Benutzerkonto fehlt.")
        if not password:
            raise ValueError("MySilence Passwort fehlt.")
        if not api_key:
            api_key = AcconiaSilenceApi.DEFAULT_FIREBASE_API_KEY

        try:
            poll_interval = int(provider_config.get("poll_interval", 60) or 60)
        except Exception as exc:
            raise ValueError("Polling-Intervall muss eine Zahl sein.") from exc
        poll_interval = max(30, min(3600, poll_interval))

        capacity_raw = str(provider_config.get("capacity_kwh", "") or "").strip()
        capacity_kwh: float | str = ""
        if capacity_raw:
            try:
                capacity_kwh = float(capacity_raw.replace(",", "."))
            except Exception as exc:
                raise ValueError("Akkukapazität muss eine Zahl sein.") from exc
            if capacity_kwh <= 0:
                raise ValueError("Akkukapazität muss größer als 0 sein.")

        return {
            "account": account,
            "password": password,
            "api_key": api_key,
            "scooter_id": scooter_id,
            "poll_interval": poll_interval,
            "capacity_kwh": capacity_kwh,
        }
