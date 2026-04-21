from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

Manufacturer = Literal["bmw", "gwm"]
AuthState = Literal["not_started", "pending", "authorized", "error"]


class MqttConfig(BaseModel):
    base_topic: str = "car"
    qos: int = 1
    retain: bool = True


class MappingConfig(BaseModel):
    enabled: bool = True


class ProviderState(BaseModel):
    provider_user: str = ""
    auth_state: AuthState = "not_started"
    auth_message: str = ""
    last_error: str = ""
    mqtt_username: str = ""
    verification_url: str = ""
    user_code: str = ""


class VehicleConfig(BaseModel):
    id: str
    label: str
    manufacturer: Manufacturer
    license_plate: str
    enabled: bool = True
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    provider_config: Dict[str, Any] = Field(default_factory=dict)
    mapping: MappingConfig = Field(default_factory=MappingConfig)
    provider_state: ProviderState = Field(default_factory=ProviderState)




class AdditionalMqttBroker(BaseModel):
    id: str
    name: str
    host: str
    port: int = 1883
    username: str = ""
    password: str = ""
    password_set: bool = False
    tls: bool = False
    enabled: bool = True
    raw_enabled: bool = False
    base_topic: str = "car"
    qos: int = 1
    retain: bool = True
    vehicle_ids: List[str] = Field(default_factory=list)
    group_ids: List[str] = Field(default_factory=list)


class VehicleGroup(BaseModel):
    id: str
    name: str
    vehicle_ids: List[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    vehicles: List[VehicleConfig] = Field(default_factory=list)
    mqtt_brokers: List[AdditionalMqttBroker] = Field(default_factory=list)
    vehicle_groups: List[VehicleGroup] = Field(default_factory=list)


class ProviderDescriptor(BaseModel):
    id: str
    name: str
    category: str = "API"
    auth_mode: str
    fields: List[Dict[str, Any]]
    notes: Optional[str] = None
    setup_steps: List[str] = Field(default_factory=list)
    badge: Optional[str] = None


class RuntimeMqttSettings(BaseModel):
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    password_set: bool = False
    base_topic: str = "car"
    qos: int = 1
    retain: bool = True
    tls: bool = False


class VehicleRuntimeState(BaseModel):
    vehicle_id: str
    connection_state: str = "idle"
    connection_detail: str = "Nicht gestartet"
    auth_state: AuthState = "not_started"
    last_update: str = ""
    raw_topic: str = ""
    mapped_topic: str = ""
    metrics: Dict[str, Any] = Field(default_factory=dict)
    provider_meta: Dict[str, Any] = Field(default_factory=dict)


class AuthSession(BaseModel):
    session_id: str
    provider_id: str
    vehicle_id: Optional[str] = None
    client_id: str
    vin: str
    license_plate: str
    code_verifier: str
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    interval: int
    expires_at: float
    state: Literal["pending", "authorized", "denied", "error"] = "pending"
    message: str = ""
