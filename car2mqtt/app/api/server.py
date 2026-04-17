from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.config_store import ConfigStore
from app.core.models import VehicleConfig
from app.core.runtime_settings import load_runtime_mqtt_settings
from app.providers.registry import ProviderRegistry
from app.mqtt.topic_builder import base_vehicle_topic, mapped_topic


class VehiclePayload(BaseModel):
    id: str
    label: str
    manufacturer: str
    license_plate: str
    enabled: bool = True
    provider_config: dict = {}


def _vehicle_card(vehicle: VehicleConfig, base_topic: str) -> dict:
    manufacturer_label = vehicle.manufacturer.upper()
    mapped = vehicle.provider_config or {}
    return {
        "id": vehicle.id,
        "label": vehicle.label,
        "manufacturer": manufacturer_label,
        "license_plate": vehicle.license_plate,
        "topic": base_vehicle_topic(base_topic, vehicle.manufacturer, vehicle.license_plate),
        "mapped_topic": mapped_topic(base_topic, vehicle.manufacturer, vehicle.license_plate),
        "enabled": vehicle.enabled,
        "status": "bereit" if vehicle.enabled else "deaktiviert",
        "stats": [
            {"label": "Kennzeichen", "value": vehicle.license_plate},
            {"label": "Hersteller", "value": manufacturer_label},
            {"label": "Mapping", "value": "aktiv" if vehicle.mapping.enabled else "aus"},
            {"label": "Topic-Basis", "value": base_topic},
        ],
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Car2MQTT")
    root = Path(__file__).resolve().parent.parent
    templates = Jinja2Templates(directory=str(root / "templates"))
    app.mount("/static", StaticFiles(directory=str(root / "static")), name="static")

    data_dir = os.getenv("APP_DATA_DIR", "/config/car2mqtt")
    store = ConfigStore(data_dir)
    registry = ProviderRegistry()

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        config = store.load()
        mqtt_settings = load_runtime_mqtt_settings()
        providers = [provider.model_dump(mode="json") for provider in registry.all()]
        cards = [_vehicle_card(vehicle, mqtt_settings.base_topic) for vehicle in config.vehicles]
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "cards": cards,
                "providers": providers,
                "version": "0.2.0",
                "mqtt_settings": mqtt_settings.model_dump(mode="json"),
            },
        )

    @app.get("/api/providers")
    async def get_providers():
        return [provider.model_dump(mode="json") for provider in registry.all()]

    @app.get("/api/vehicles")
    async def get_vehicles():
        return store.load().model_dump(mode="json")

    @app.get("/api/system")
    async def get_system_settings():
        return {"mqtt": load_runtime_mqtt_settings().model_dump(mode="json")}

    @app.post("/api/vehicles")
    async def create_vehicle(payload: VehiclePayload):
        try:
            provider = registry.get(payload.manufacturer)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            validated_provider = provider.validate_config(payload.provider_config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        mqtt_settings = load_runtime_mqtt_settings()
        vehicle = VehicleConfig(
            id=payload.id,
            label=payload.label,
            manufacturer=payload.manufacturer,
            license_plate=payload.license_plate,
            enabled=payload.enabled,
            provider_config=validated_provider,
        )
        vehicle.mqtt.base_topic = mqtt_settings.base_topic
        vehicle.mqtt.qos = mqtt_settings.qos
        vehicle.mqtt.retain = mqtt_settings.retain
        config = store.upsert_vehicle(vehicle)
        return config.model_dump(mode="json")

    @app.get("/api/providers/{provider_id}/example-mapping")
    async def get_example_mapping(provider_id: str):
        try:
            provider = registry.get(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return provider.map_example()

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.2.0"}

    return app
