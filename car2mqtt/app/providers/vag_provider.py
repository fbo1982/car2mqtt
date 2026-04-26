from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider

VAG_BRANDS = {"vw", "vwcv", "audi", "skoda", "seat", "cupra"}
VAG_POWERTRAINS = {"electric", "hybrid", "combustion", "unknown"}
VAG_API_MODES = {"official_fleet", "brand_app"}


class VagProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="vag",
            name="Volkswagen Konzern",
            category="API",
            auth_mode="account",
            badge="VAG",
            notes=(
                "Gemeinsame VAG-Grundstruktur für Volkswagen, Volkswagen Nutzfahrzeuge, Audi, Škoda, "
                "SEAT und CUPRA. Dieser Schritt legt UI, Konfiguration und ein einheitliches Mapping "
                "für Elektro, Hybrid und Verbrenner an. Die markenspezifischen API-Connectoren werden "
                "darauf aufbauend schrittweise ergänzt."
            ),
            setup_steps=[
                "Marke, API-Modus, Login und Antriebsart wählen.",
                "Kennzeichen wird als interne Vehicle-ID und MQTT-Fahrzeugkennung verwendet.",
                "Das Mapping verwendet dasselbe Fahrzeugtyp-Konzept wie BMW: electric, hybrid, combustion.",
            ],
            fields=[
                {"name": "brand", "label": "Marke", "type": "select", "required": True},
                {"name": "api_mode", "label": "API-Modus", "type": "select", "required": True, "default": "brand_app"},
                {"name": "account", "label": "Benutzerkonto / E-Mail", "type": "text", "required": True},
                {"name": "password", "label": "Passwort", "type": "password", "required": True},
                {"name": "country", "label": "Land", "type": "text", "required": False, "default": "DE"},
                {"name": "powertrain", "label": "Antrieb", "type": "select", "required": True, "default": "unknown"},
                {"name": "poll_interval", "label": "Polling-Intervall (Sekunden)", "type": "number", "required": False, "default": 60},
                {"name": "capacity_kwh", "label": "Akkukapazität (kWh)", "type": "number", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        brand = str(provider_config.get("brand", "") or "").strip().lower()
        if brand not in VAG_BRANDS:
            raise ValueError("Bitte eine gültige VAG-Marke wählen.")
        api_mode = str(provider_config.get("api_mode", "brand_app") or "brand_app").strip().lower()
        if api_mode not in VAG_API_MODES:
            raise ValueError("Bitte einen gültigen VAG API-Modus wählen.")
        account = str(provider_config.get("account", "") or provider_config.get("username", "")).strip()
        password = str(provider_config.get("password", "") or "")
        if not account:
            raise ValueError("VAG Benutzerkonto fehlt.")
        if not password:
            raise ValueError("VAG Passwort fehlt.")
        powertrain = str(provider_config.get("powertrain", "unknown") or "unknown").strip().lower()
        if powertrain not in VAG_POWERTRAINS:
            raise ValueError("Bitte eine gültige Antriebsart wählen.")
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
            "brand": brand,
            "api_mode": api_mode,
            "account": account,
            "password": password,
            "country": str(provider_config.get("country", "DE") or "DE").strip().upper(),
            "powertrain": powertrain,
            "poll_interval": poll_interval,
            "capacity_kwh": capacity_kwh,
            "license_plate": str(provider_config.get("license_plate", "")).strip(),
            "vehicle_id": str(provider_config.get("vehicle_id", "")).strip(),
        }
