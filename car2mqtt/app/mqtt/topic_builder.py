from __future__ import annotations


def base_vehicle_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{base_topic}/{manufacturer}/{license_plate}"


def mapped_topic(base_topic: str, manufacturer: str, license_plate: str) -> str:
    return f"{base_vehicle_topic(base_topic, manufacturer, license_plate)}/mapped"
