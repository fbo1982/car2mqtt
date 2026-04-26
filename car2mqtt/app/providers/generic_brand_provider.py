from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider

COMMON_POWERTRAINS = {"electric", "hybrid", "combustion", "unknown"}

BRAND_DEFINITIONS: dict[str, dict[str, str]] = {
    "byd": {
        "name": "BYD",
        "badge": "BYD",
        "api_mode": "byd_cloud",
        "api_label": "BYD Cloud / Diplus",
        "source": "Community-Referenz: pyBYD / hass-byd-vehicle bzw. BYD Diplus API. Keine offiziell öffentliche Endkunden-API bekannt.",
    },
    "citroen": {
        "name": "Citroën",
        "badge": "Citroën",
        "api_mode": "stellantis_connected_car",
        "api_label": "Stellantis Connected Car / PSA",
        "source": "Community-Referenz: psa-connected-car-client / psa_car_controller für Citroën, Peugeot, Opel/Vauxhall und DS.",
    },
    "kia": {
        "name": "Kia",
        "badge": "Kia",
        "api_mode": "kia_connect",
        "api_label": "Kia Connect / UVO",
        "source": "Community-Referenz: Hyundai-Kia-Connect API / kia_uvo für Kia Connect, Hyundai Bluelink und UVO.",
    },
    "lucid": {
        "name": "Lucid",
        "badge": "Lucid",
        "api_mode": "lucid_community",
        "api_label": "Lucid Motors Community API",
        "source": "Community-Referenz: ha-lucidmotors / python-lucidmotors. Keine offiziell öffentliche Endkunden-API bekannt.",
    },
    "mercedes": {
        "name": "Mercedes-Benz",
        "badge": "Mercedes-Benz",
        "api_mode": "mercedes_me",
        "api_label": "Mercedes me",
        "source": "Community-Referenz: mercedes_me_api für Mercedes me Datenabruf.",
    },
    "nissan": {
        "name": "Nissan",
        "badge": "Nissan",
        "api_mode": "nissanconnect",
        "api_label": "NissanConnect Services",
        "source": "Community-Referenz: NissanConnect/You+Nissan Bibliotheken und Home-Assistant-Integrationen; API je Modell/Region unterschiedlich.",
    },
    "opel": {
        "name": "Opel",
        "badge": "Opel",
        "api_mode": "stellantis_connected_car",
        "api_label": "Stellantis Connected Car / PSA",
        "source": "Community-Referenz: psa-connected-car-client / psa_car_controller für Citroën, Peugeot, Opel/Vauxhall und DS.",
    },
    "peugeot": {
        "name": "Peugeot",
        "badge": "Peugeot",
        "api_mode": "stellantis_connected_car",
        "api_label": "Stellantis Connected Car / PSA",
        "source": "Community-Referenz: psa-connected-car-client / psa_car_controller für Citroën, Peugeot, Opel/Vauxhall und DS.",
    },
    "renault": {
        "name": "Renault",
        "badge": "Renault",
        "api_mode": "myrenault",
        "api_label": "MyRenault / Kamereon",
        "source": "Community-Referenz: renault-api für die private MyRenault/Kamereon API.",
    },
    "tesla": {
        "name": "Tesla",
        "badge": "Tesla",
        "api_mode": "tesla_fleet_api",
        "api_label": "Tesla Fleet API",
        "source": "Offizielle Referenz: Tesla Fleet API / Fleet Telemetry. Für produktiven Zugriff sind OAuth, Partner-App/Fleet-Zugang und ggf. Vehicle Command Proxy/Virtual Key nötig.",
    },
    "toyota": {
        "name": "Toyota",
        "badge": "Toyota",
        "api_mode": "mytoyota",
        "api_label": "MyToyota / Toyota Connected Services",
        "source": "Community-Referenz: pytoyoda / ha_toyota für Toyota Connected Services Europe; keine offiziell öffentliche Endkunden-API.",
    },
    "volvo": {
        "name": "Volvo",
        "badge": "Volvo",
        "api_mode": "volvo_connected_vehicle",
        "api_label": "Volvo Cars Connected Vehicle API",
        "source": "Offizielle Referenz: Volvo Cars Developer Portal / Connected Vehicle APIs. Community-Referenzen: volvo-vehicle-exporter, volvo2mqtt.",
    },
}

ALLOWED_API_MODES = {
    "brand_app",
    "manual",
    "mercedes_me",
    "stellantis_connected_car",
    "myrenault",
    "kia_connect",
    "mytoyota",
    "nissanconnect",
    "byd_cloud",
    "lucid_community",
    "tesla_fleet_api",
    "volvo_connected_vehicle",
}


class GenericBrandProvider(BaseProvider):
    def __init__(self, brand_id: str) -> None:
        if brand_id not in BRAND_DEFINITIONS:
            raise KeyError(f"Unbekannte generische Marke: {brand_id}")
        self.brand_id = brand_id
        self.definition = BRAND_DEFINITIONS[brand_id]

    def descriptor(self) -> ProviderDescriptor:
        name = self.definition["name"]
        api_label = self.definition["api_label"]
        return ProviderDescriptor(
            id=self.brand_id,
            name=name,
            category="API",
            auth_mode="account",
            badge=self.definition.get("badge", name),
            notes=(
                f"{name}-Grundstruktur mit {api_label}-Vorbereitung. "
                "Login-Daten sind optional und können später im Fahrzeug nachgetragen werden. "
                "Das MQTT-Mapping ist wie bei BMW nach Elektro, Hybrid und Verbrenner vorbereitet. "
                f"{self.definition.get('source', '')}"
            ).strip(),
            setup_steps=[
                "Fahrzeug kann zunächst nur mit Anzeigename und Kennzeichen angelegt werden.",
                f"Login-Daten für {api_label} können später im Fahrzeug unter Bearbeiten ergänzt werden.",
                "Vehicle ID und MQTT Topics werden automatisch aus dem Kennzeichen erzeugt.",
            ],
            fields=[
                {"name": "api_mode", "label": "API-Modus", "type": "select", "required": True, "default": self.definition["api_mode"]},
                {"name": "account", "label": "Benutzerkonto / E-Mail", "type": "text", "required": False},
                {"name": "password", "label": "Passwort", "type": "password", "required": False},
                {"name": "country", "label": "Land", "type": "text", "required": False, "default": "DE"},
                {"name": "region", "label": "Region", "type": "select", "required": False, "default": "EU"},
                {"name": "pin", "label": "PIN / App-Code", "type": "password", "required": False},
                {"name": "powertrain", "label": "Antrieb", "type": "select", "required": True, "default": "unknown"},
                {"name": "poll_interval", "label": "Polling-Intervall (Sekunden)", "type": "number", "required": False, "default": 300},
                {"name": "capacity_kwh", "label": "Akkukapazität (kWh)", "type": "number", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        default_mode = self.definition["api_mode"]
        api_mode = str(provider_config.get("api_mode", default_mode) or default_mode).strip().lower()
        if api_mode not in ALLOWED_API_MODES:
            raise ValueError("Bitte einen gültigen API-Modus wählen.")
        account = str(provider_config.get("account", "") or provider_config.get("username", "")).strip()
        password = str(provider_config.get("password", "") or "")
        pin = str(provider_config.get("pin", "") or "")
        powertrain = str(provider_config.get("powertrain", "unknown") or "unknown").strip().lower()
        if powertrain not in COMMON_POWERTRAINS:
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
            "brand": self.brand_id,
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
