from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider


class AcconiaProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="acconia",
            name="Acconia / Silence S04",
            category="MQTT",
            auth_mode="mqtt_source",
            badge="S04",
            notes="Read-only MQTT-Quelle für Silence S04. Car2MQTT subscribed auf den konfigurierten Quellpfad und normalisiert GPS, Ladestand, 1/2 Batterien und Ladezustand.",
            setup_steps=[
                "Cloudconnector so konfigurieren, dass er die Silence-S04-Daten nach MQTT schreibt.",
                "Quell-Topic-Basis eintragen, z. B. acconia/MEINKENNZEICHEN.",
                "Batterieanzahl wählen, damit Fahrzeuge mit einer oder zwei Batterien sauber dargestellt werden.",
            ],
            fields=[
                {"name": "source_topic_base", "label": "MQTT Quell-Topic-Basis", "type": "text", "required": True},
                {"name": "vehicle_id", "label": "Vehicle ID", "type": "text", "required": False},
                {"name": "battery_count", "label": "Batterieanzahl", "type": "number", "required": False, "default": 2},
                {"name": "capacity_kwh", "label": "Akkukapazität gesamt (kWh)", "type": "number", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        source = str(provider_config.get("source_topic_base", "")).strip().strip("/")
        vehicle_id = str(provider_config.get("vehicle_id", "")).strip()
        try:
            battery_count = int(provider_config.get("battery_count", 2) or 2)
        except Exception as exc:
            raise ValueError("Batterieanzahl muss 1 oder 2 sein.") from exc
        if battery_count not in {1, 2}:
            raise ValueError("Batterieanzahl muss 1 oder 2 sein.")
        capacity_raw = str(provider_config.get("capacity_kwh", "")).strip()
        capacity_kwh = ""
        if capacity_raw:
            try:
                capacity_kwh = float(capacity_raw.replace(",", "."))
            except Exception as exc:
                raise ValueError("Akkukapazität muss eine Zahl sein.") from exc
        if not source:
            raise ValueError("MQTT Quell-Topic-Basis für Acconia/Silence fehlt.")
        return {
            "source_topic_base": source,
            "vehicle_id": vehicle_id,
            "battery_count": battery_count,
            "capacity_kwh": capacity_kwh,
            "license_plate": str(provider_config.get("license_plate", "")).strip(),
        }
