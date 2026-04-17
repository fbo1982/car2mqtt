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
from app.providers.registry import ProviderRegistry
from app.mqtt.topic_builder import base_vehicle_topic, mapped_topic


class VehiclePayload(BaseModel):
    id: str
    label: str
    manufacturer: str
    license_plate: str
    enabled: bool = True
    provider_config: dict = {}



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
        providers = registry.all()
        cards = []
        for vehicle in config.vehicles:
            cards.append(
                {
                    "id": vehicle.id,
                    "label": vehicle.label,
                    "manufacturer": vehicle.manufacturer.upper(),
                    "license_plate": vehicle.license_plate,
                    "topic": base_vehicle_topic(vehicle.mqtt.base_topic, vehicle.manufacturer, vehicle.license_plate),
                    "mapped_topic": mapped_topic(vehicle.mqtt.base_topic, vehicle.manufacturer, vehicle.license_plate),
                    "enabled": vehicle.enabled,
                }
            )
        return templates.TemplateResponse(
            request,
            "index.html",
            {"cards": cards, "providers": providers, "version": "0.1.2"},
        )

    @app.get("/api/providers")
    async def get_providers():
        return registry.all()

    @app.get("/api/vehicles")
    async def get_vehicles():
        return store.load().model_dump(mode="json")

    @app.post("/api/vehicles")
    async def create_vehicle(payload: VehiclePayload):
        try:
            provider = registry.get(payload.manufacturer)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        validated_provider = provider.validate_config(payload.provider_config)
        vehicle = VehicleConfig(
            id=payload.id,
            label=payload.label,
            manufacturer=payload.manufacturer,
            license_plate=payload.license_plate,
            enabled=payload.enabled,
            provider_config=validated_provider,
        )
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
        return {"status": "ok", "version": "0.1.2"}

    return app
