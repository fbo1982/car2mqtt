from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider

HYUNDAI_POWERTRAINS = {"electric", "hybrid", "combustion", "unknown"}
HYUNDAI_API_MODES = {"bluelink", "manual"}


class HyundaiProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="hyundai",
            name="Hyundai",
            category="API",
            auth_mode="account",
            badge="Hyundai",
            notes=(
                "Hyundai-Grundstruktur mit Bluelink-Vorbereitung. "
                "Login-Daten sind optional und können später im Fahrzeug nachgetragen werden. "
                "Das MQTT-Mapping ist wie bei BMW nach Elektro, Hybrid und Verbrenner vorbereitet."
            ),
            setup_steps=[
                "Fahrzeug kann zunächst nur mit Anzeigename und Kennzeichen angelegt werden.",
                "Login-Daten für Bluelink können später im Fahrzeug unter Bearbeiten ergänzt werden.",
                "Vehicle ID und MQTT Topics werden automatisch aus dem Kennzeichen erzeugt.",
            ],
            fields=[
                {"name": "api_mode", "label": "API-Modus", "type": "select", "required": True, "default": "bluelink"},
                {"name": "account", "label": "Benutzerkonto / E-Mail", "type": "text", "required": False},
                {"name": "password", "label": "Passwort", "type": "password", "required": False},
                {"name": "country", "label": "Land", "type": "text", "required": False, "default": "DE"},
                {"name": "region", "label": "Region", "type": "select", "required": False, "default": "EU"},
                {"name": "pin", "label": "Bluelink PIN", "type": "password", "required": False},
                {"name": "powertrain", "label": "Antrieb", "type": "select", "required": True, "default": "unknown"},
                {"name": "poll_interval", "label": "Polling-Intervall (Sekunden)", "type": "number", "required": False, "default": 300},
                {"name": "capacity_kwh", "label": "Akkukapazität (kWh)", "type": "number", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        api_mode = str(provider_config.get("api_mode", "bluelink") or "bluelink").strip().lower()
        if api_mode not in HYUNDAI_API_MODES:
            raise ValueError("Bitte einen gültigen Hyundai API-Modus wählen.")
        account = str(provider_config.get("account", "") or provider_config.get("username", "")).strip()
        password = str(provider_config.get("password", "") or "")
        pin = str(provider_config.get("pin", "") or "")
        powertrain = str(provider_config.get("powertrain", "unknown") or "unknown").strip().lower()
        if powertrain not in HYUNDAI_POWERTRAINS:
            raise ValueError("Bitte eine gültige Antriebsart wählen.")
        try:
            poll_interval = int(provider_config.get("poll_interval", 300) or 300)
        except Exception as exc:
            raise ValueError("Polling-Intervall muss eine Zahl sein.") from exc
        poll_interval = max(60, min(3600, poll_interval))
        capacity_raw = str(provider_config.get("capacity_kwh", "") or "").strip()
        capacity_kwh: float | str = ""
        if capacity_raw:
            try:
                capacity_kwh = float(capacity_raw.replace(",", "."))
            except Exception as exc:
                raise ValueError("Akkukapazität muss eine Zahl sein.") from exc
        return {
            "brand": "hyundai",
            "api_mode": api_mode,
            "account": account,
            "password": password,
            "pin": pin,
            "country": str(provider_config.get("country", "DE") or "DE").strip().upper(),
            "region": str(provider_config.get("region", "EU") or "EU").strip().upper(),
            "powertrain": powertrain,
            "poll_interval": poll_interval,
            "capacity_kwh": capacity_kwh,
            "license_plate": str(provider_config.get("license_plate", "")).strip(),
            "vehicle_id": str(provider_config.get("vehicle_id", "")).strip(),
        }
