from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class Manufacturer(str, Enum):
    BMW = "bmw"
    GWM = "gwm"


class VehicleStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class MQTTSettings(BaseModel):
    host: str = "core-mosquitto"
    port: int = 1883
    username: str = ""
    password: str = ""
    base_topic: str = "car"
    qos: int = 1
    retain: bool = True


class VehicleConfig(BaseModel):
    id: str
    label: str
    manufacturer: Manufacturer
    license_plate: str
    enabled: bool = True
    provider_config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "label", "license_plate")
    @classmethod
    def value_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value


class VehicleRecord(BaseModel):
    config: VehicleConfig
    status: VehicleStatus = VehicleStatus.STOPPED
    last_seen: Optional[datetime] = None
    message: str = "Not started"


class AppState(BaseModel):
    version: str = "0.1.0"
    mqtt: MQTTSettings = Field(default_factory=MQTTSettings)
    vehicles: List[VehicleConfig] = Field(default_factory=list)


class ProviderField(BaseModel):
    key: str
    label: str
    kind: str
    required: bool = True
    placeholder: str = ""
    help_text: str = ""
    secret: bool = False


class ProviderSchema(BaseModel):
    manufacturer: Manufacturer
    name: str
    auth_mode: str
    description: str
    fields: List[ProviderField]


class HealthSnapshot(BaseModel):
    vehicle_id: str
    status: VehicleStatus
    last_seen: Optional[datetime]
    message: str


class CanonicalMapping(BaseModel):
    soc: Optional[float] = None
    soc_ts: Optional[str] = None
    plugged: Optional[bool] = None
    plugged_ts: Optional[str] = None
    odometer: Optional[float] = None
    odometer_ts: Optional[str] = None
    range: Optional[float] = None
    range_ts: Optional[str] = None
    limitSoc: Optional[float] = None
    limitSoc_ts: Optional[str] = None
    charging: Optional[bool] = None
    charging_ts: Optional[str] = None
    longitude: Optional[float] = None
    longitude_ts: Optional[str] = None
    latitude: Optional[float] = None
    latitude_ts: Optional[str] = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
