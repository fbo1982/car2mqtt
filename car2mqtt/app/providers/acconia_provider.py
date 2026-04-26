from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider


class AcconiaProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="acconia",
            name="Acconia / Silence S04",
            category="API",
            auth_mode="account",
            badge="S04",
            notes="Read-only Cloud-Login für Silence S04 über die Acconia/Silence API. Car2MQTT normalisiert GPS, Ladezustand, Ladezustand/charging sowie Fahrzeuge mit einer oder zwei Batterien.",
            setup_steps=[
                "E-Mail, Passwort und Firebase API-Key der Silence App eintragen.",
                "Kennzeichen wird als interne Vehicle-ID und als MQTT-Fahrzeugkennung verwendet.",
                "Batterieanzahl wählen, damit S04-Varianten mit einer oder zwei Batterien korrekt gemapped werden.",
            ],
            fields=[
                {"name": "account", "label": "Benutzerkonto / E-Mail", "type": "text", "required": True},
                {"name": "password", "label": "Passwort", "type": "password", "required": True},
                {"name": "api_key", "label": "Firebase API-Key", "type": "password", "required": True},
                {"name": "battery_count", "label": "Batterieanzahl", "type": "number", "required": False, "default": 2},
                {"name": "poll_interval", "label": "Polling-Intervall (Sekunden)", "type": "number", "required": False, "default": 60},
                {"name": "capacity_kwh", "label": "Akkukapazität gesamt (kWh)", "type": "number", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        account = str(provider_config.get("account", "") or provider_config.get("username", "")).strip()
        password = str(provider_config.get("password", "") or "")
        api_key = str(provider_config.get("api_key", "") or provider_config.get("apikey", "") or "").strip()
        if not account:
            raise ValueError("Acconia/Silence Benutzerkonto fehlt.")
        if not password:
            raise ValueError("Acconia/Silence Passwort fehlt.")
        if not api_key:
            raise ValueError("Acconia/Silence Firebase API-Key fehlt.")
        try:
            battery_count = int(provider_config.get("battery_count", 2) or 2)
        except Exception as exc:
            raise ValueError("Batterieanzahl muss 1 oder 2 sein.") from exc
        if battery_count not in {1, 2}:
            raise ValueError("Batterieanzahl muss 1 oder 2 sein.")
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
        return {
            "account": account,
            "password": password,
            "api_key": api_key,
            "battery_count": battery_count,
            "poll_interval": poll_interval,
            "capacity_kwh": capacity_kwh,
            "license_plate": str(provider_config.get("license_plate", "")).strip(),
        }
