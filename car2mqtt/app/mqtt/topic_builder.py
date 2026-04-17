from __future__ import annotations


def normalize_plate(license_plate: str) -> str:
    return license_plate.strip().replace(" ", "-")


def vehicle_root_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{base_topic}/{manufacturer}/{normalize_plate(license_plate)}"


def raw_vehicle_topic(base_topic: str, manufacturer: str, license_plate: str, vin: str = "", append_vin: bool = False) -> str:
    root = vehicle_root_topic(base_topic, manufacturer, license_plate)
    if append_vin and vin:
        return f"{root}/{vin}"
    return root


def mapped_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{vehicle_root_topic(base_topic, manufacturer, license_plate)}/mapped"


def meta_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{vehicle_root_topic(base_topic, manufacturer, license_plate)}/_meta"
