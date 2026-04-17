from __future__ import annotations

from typing import Any, Dict


def render_ora2mqtt_yaml(provider_config: Dict[str, Any], mqtt_settings) -> str:
    vehicle_id = str(provider_config.get("vehicle_id", "")).strip() or "<vehicleId>"
    country = str(provider_config.get("country", "DE")).strip().upper() or "DE"
    language = str(provider_config.get("language", "de")).strip().lower() or "de"
    interval = int(provider_config.get("poll_interval", 60) or 60)
    account = str(provider_config.get("account", "")).strip()
    password = str(provider_config.get("password", "")).strip()
    capacity = provider_config.get("capacity_kwh", "")
    lines = [
        "# Car2MQTT generated ORA bootstrap config",
        "# This file is intended as a helper for ora2mqtt-style setup.",
        "# Adjust keys as needed for your environment and future runtime integration.",
        "",
        "account:",
        f"  username: \"{account}\"",
        f"  password: \"{password}\"",
        f"  country: \"{country}\"",
        f"  language: \"{language}\"",
        "",
        "vehicle:",
        f"  vehicle_id: \"{vehicle_id}\"",
    ]
    if capacity not in ("", None):
        lines.append(f"  capacity_kwh: {capacity}")
    lines.extend([
        "",
        "polling:",
        f"  interval_seconds: {interval}",
        "",
        "mqtt:",
        f"  host: \"{mqtt_settings.host}\"",
        f"  port: {mqtt_settings.port}",
        f"  username: \"{mqtt_settings.username}\"",
        f"  password: \"{mqtt_settings.password if getattr(mqtt_settings, 'password_set', False) else ''}\"",
        f"  base_topic: \"{mqtt_settings.base_topic}/gwm/{vehicle_id}\"",
        f"  qos: {mqtt_settings.qos}",
        f"  retain: {'true' if mqtt_settings.retain else 'false'}",
        "",
        "notes:",
        "  - Generated from the Car2MQTT vehicle wizard.",
        "  - The upstream ora2mqtt project documents that ora2mqtt.yml must exist before the container/binary is started.",
        "  - Linux setups also need gwm_root.pem and openssl.cnf prepared in the runtime environment.",
        "",
    ])
    return "\n".join(lines)
