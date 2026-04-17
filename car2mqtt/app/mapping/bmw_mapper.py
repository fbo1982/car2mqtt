from __future__ import annotations

from typing import Any, Dict


def map_bmw_example(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "soc": raw.get("soc", 97),
        "plugged": raw.get("plugged", False),
        "odometer": raw.get("odometer", 1485),
        "range": raw.get("range", 61),
        "limitSoc": raw.get("limitSoc", 100),
        "charging": raw.get("charging", False),
        "longitude": raw.get("longitude", 8.4960091667),
        "latitude": raw.get("latitude", 49.82877),
    }
