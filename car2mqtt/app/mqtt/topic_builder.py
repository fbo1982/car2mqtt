from __future__ import annotations


def normalize_plate(license_plate: str) -> str:
    return "".join(ch for ch in license_plate.upper().strip() if ch.isalnum())


def vehicle_root_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{base_topic}/{manufacturer}/{normalize_plate(license_plate)}"


def raw_vehicle_topic(base_topic: str, manufacturer: str, license_plate: str, vin: str = "", append_vin: bool = False) -> str:
    return vehicle_root_topic(base_topic, manufacturer, license_plate)


def mapped_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{vehicle_root_topic(base_topic, manufacturer, license_plate)}/mapped"


def gwm_direct_source_root(base_topic: str, license_plate: str, source_id: str = "+") -> str:
    return f"{vehicle_root_topic(base_topic, 'gwm', license_plate)}/{source_id}"


def gwm_direct_status_topic(base_topic: str, license_plate: str, source_id: str = "+") -> str:
    return f"{gwm_direct_source_root(base_topic, license_plate, source_id)}/status/#"


def meta_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{vehicle_root_topic(base_topic, manufacturer, license_plate)}/_meta"
