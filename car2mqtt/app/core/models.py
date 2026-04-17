from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

Manufacturer = Literal["bmw", "gwm"]


class MqttConfig(BaseModel):
    base_topic: str = "car"
    qos: int = 1
    retain: bool = True


class MappingConfig(BaseModel):
    enabled: bool = True


class VehicleConfig(BaseModel):
    id: str
    label: str
    manufacturer: Manufacturer
    license_plate: str
    enabled: bool = True
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    provider_config: Dict[str, Any] = Field(default_factory=dict)
    mapping: MappingConfig = Field(default_factory=MappingConfig)


class AppConfig(BaseModel):
    vehicles: List[VehicleConfig] = Field(default_factory=list)


class ProviderDescriptor(BaseModel):
    id: str
    name: str
    auth_mode: str
    fields: List[Dict[str, Any]]
    notes: Optional[str] = None
