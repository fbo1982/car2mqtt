from __future__ import annotations

import re


def normalize_plate(license_plate: str) -> str:
    value = (license_plate or "").strip().upper()
    value = re.sub(r"[^A-Z0-9]+", "-", value)
    return value.strip("-")


def derive_vehicle_id(license_plate: str) -> str:
    value = (license_plate or "").strip().upper()
    return re.sub(r"[^A-Z0-9]+", "", value)


def vehicle_root_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{base_topic}/{manufacturer}/{normalize_plate(license_plate)}"


def raw_vehicle_topic(base_topic: str, manufacturer: str, license_plate: str, vin: str = "", append_vin: bool = False) -> str:
    # VIN is intentionally not appended in Car2MQTT >= 0.7.1
    return vehicle_root_topic(base_topic, manufacturer, license_plate)


def mapped_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{vehicle_root_topic(base_topic, manufacturer, license_plate)}/mapped"


def meta_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{vehicle_root_topic(base_topic, manufacturer, license_plate)}/_meta"
