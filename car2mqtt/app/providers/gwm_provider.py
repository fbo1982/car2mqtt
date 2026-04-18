from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider


class GwmProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="gwm",
            name="GWM / ORA",
            category="API",
            auth_mode="config_wizard",
            badge="ORA",
            notes="Automatisiert ora2mqtt configure + ora2mqtt run im Add-on und verwaltet die ora2mqtt.yml im Fahrzeugordner.",
            setup_steps=[
                "Zusätzlichen ORA/GWM Account verwenden und Fahrzeug für diesen Account freigeben.",
                "Die Eingaben im Wizard speichern, damit eine ora2mqtt.yml erzeugt wird.",
                "Die erzeugte Konfiguration später für die eigentliche ORA-Laufzeit verwenden.",
            ],
            fields=[
                {"name": "account", "label": "Benutzerkonto", "type": "text", "required": True},
                {"name": "password", "label": "Passwort", "type": "password", "required": True},
                {"name": "country", "label": "Land", "type": "text", "required": True},
                {"name": "language", "label": "Sprache", "type": "text", "required": True},
                {"name": "poll_interval", "label": "Polling-Intervall", "type": "number", "required": True},
                {"name": "vehicle_id", "label": "Vehicle ID", "type": "text", "required": False},
                {"name": "capacity_kwh", "label": "Akkukapazität (kWh)", "type": "number", "required": False},
                {"name": "source_topic_base", "label": "Source Topic Base", "type": "text", "required": False},
                {"name": "verification_code", "label": "Verifikationscode", "type": "text", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        account = str(provider_config.get("account", "")).strip()
        password = str(provider_config.get("password", "")).strip()
        if not account:
            raise ValueError("ORA Benutzerkonto ist erforderlich.")
        if not password:
            raise ValueError("ORA Passwort ist erforderlich.")
        country = str(provider_config.get("country", "DE")).strip().upper() or "DE"
        language = str(provider_config.get("language", "de")).strip().lower() or "de"
        vehicle_id = str(provider_config.get("vehicle_id", "")).strip()
        poll_interval_raw = provider_config.get("poll_interval", 60)
        try:
            poll_interval = int(poll_interval_raw)
        except Exception as exc:
            raise ValueError("Polling-Intervall muss eine Zahl sein.") from exc
        if poll_interval < 10:
            raise ValueError("Polling-Intervall muss mindestens 10 Sekunden sein.")
        capacity_raw = str(provider_config.get("capacity_kwh", "")).strip()
        capacity_kwh = ""
        if capacity_raw:
            try:
                capacity_kwh = float(capacity_raw)
            except Exception as exc:
                raise ValueError("Akkukapazität muss eine Zahl sein.") from exc
        return {
            "account": account,
            "password": password,
            "country": country,
            "language": language,
            "poll_interval": poll_interval,
            "vehicle_id": vehicle_id,
            "capacity_kwh": capacity_kwh,
            "source_topic_base": str(provider_config.get("source_topic_base", "")).strip(),
            "verification_code": str(provider_config.get("verification_code", "")).strip(),
        }
