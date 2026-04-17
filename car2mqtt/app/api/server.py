from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.auth_store import AuthStore
from app.core.config_store import ConfigStore
from app.core.models import AuthSession, VehicleConfig
from app.core.runtime_settings import load_runtime_mqtt_settings
from app.core.state_store import StateStore
from app.mqtt.client import test_connection
from app.mqtt.topic_builder import base_vehicle_topic, mapped_topic
from app.providers.bmw.oauth import poll_device_flow, save_token_file, start_device_flow
from app.providers.registry import ProviderRegistry
from app.services.worker_manager import WorkerManager


class VehiclePayload(BaseModel):
    id: str
    label: str
    manufacturer: str
    license_plate: str
    enabled: bool = True
    provider_config: dict = {}
    auth_session_id: str | None = None


class BmwAuthStartPayload(BaseModel):
    client_id: str
    vin: str
    license_plate: str


class BmwAuthPollPayload(BaseModel):
    session_id: str


def _vehicle_card(vehicle: VehicleConfig, runtime_state: Dict[str, Any] | None, base_topic: str) -> dict:
    metrics = (runtime_state or {}).get("metrics", {})
    provider_meta = (runtime_state or {}).get("provider_meta", {})
    return {
        "id": vehicle.id,
        "label": vehicle.label,
        "manufacturer": vehicle.manufacturer.upper(),
        "license_plate": vehicle.license_plate,
        "topic": base_vehicle_topic(base_topic, vehicle.manufacturer, vehicle.license_plate),
        "mapped_topic": mapped_topic(base_topic, vehicle.manufacturer, vehicle.license_plate),
        "status": (runtime_state or {}).get("connection_state", "idle"),
        "status_detail": (runtime_state or {}).get("connection_detail", vehicle.provider_state.auth_message or "Noch keine Live-Daten"),
        "auth_state": vehicle.provider_state.auth_state,
        "metrics": {
            "soc": metrics.get("soc"),
            "range": metrics.get("range"),
            "charging": metrics.get("charging"),
            "plugged": metrics.get("plugged"),
            "odometer": metrics.get("odometer"),
            "limitSoc": metrics.get("limitSoc"),
            "latitude": metrics.get("latitude"),
            "longitude": metrics.get("longitude"),
        },
        "live": {
            "vin": vehicle.provider_config.get("vin", provider_meta.get("vin", "")),
            "mqtt_username": vehicle.provider_state.mqtt_username or provider_meta.get("mqtt_username", ""),
        },
        "last_update": (runtime_state or {}).get("last_update", ""),
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Car2MQTT")
    root = Path(__file__).resolve().parent.parent
    templates = Jinja2Templates(directory=str(root / "templates"))

    data_dir = os.getenv("APP_DATA_DIR", "/config/car2mqtt")
    store = ConfigStore(data_dir)
    state_store = StateStore(data_dir)
    auth_store = AuthStore(data_dir)
    registry = ProviderRegistry()
    worker_manager = WorkerManager(data_dir, store, state_store)

    @app.on_event("startup")
    async def startup_event():
        worker_manager.start_all()

    def build_cards() -> tuple[list[dict], dict]:
        config = store.load()
        mqtt_settings = load_runtime_mqtt_settings()
        runtime_states = {k: v.model_dump(mode="json") for k, v in state_store.get_all().items()}
        cards = [_vehicle_card(vehicle, runtime_states.get(vehicle.id), mqtt_settings.base_topic) for vehicle in config.vehicles]
        return cards, mqtt_settings.model_dump(mode="json")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        cards, mqtt_settings = build_cards()
        providers = [provider.model_dump(mode="json") for provider in registry.all()]
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "cards": cards,
                "providers": providers,
                "version": "0.2.3",
                "mqtt_settings": mqtt_settings,
                "cards_json": json.dumps(cards, ensure_ascii=False),
            },
        )

    @app.get("/api/providers")
    async def get_providers():
        return [provider.model_dump(mode="json") for provider in registry.all()]

    @app.get("/api/dashboard")
    async def get_dashboard():
        cards, mqtt_settings = build_cards()
        return {"vehicles": cards, "mqtt": mqtt_settings}

    @app.post("/api/mqtt/test")
    async def mqtt_test():
        settings = load_runtime_mqtt_settings()
        if not settings.host:
            raise HTTPException(status_code=400, detail="MQTT Host ist nicht gesetzt")
        try:
            return test_connection(settings)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/providers/bmw/auth/start")
    async def bmw_auth_start(payload: BmwAuthStartPayload):
        try:
            session = start_device_flow(payload.client_id.strip(), payload.vin.strip().upper(), payload.license_plate.strip())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"BMW Device Flow konnte nicht gestartet werden: {exc}") from exc
        auth_store.upsert(session)
        return session.model_dump(mode="json")

    @app.post("/api/providers/bmw/auth/poll")
    async def bmw_auth_poll(payload: BmwAuthPollPayload):
        session = auth_store.get(payload.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Auth-Session nicht gefunden")
        try:
            result = poll_device_flow(session)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"BMW Token-Abfrage fehlgeschlagen: {exc}") from exc
        if isinstance(result, AuthSession):
            auth_store.upsert(result)
            return result.model_dump(mode="json")
        session.state = "authorized"
        session.message = "BMW Anmeldung erfolgreich abgeschlossen."
        auth_store.upsert(session)
        token_file = Path(data_dir) / "providers" / f"tmp-{session.session_id}" / "bmw_tokens.json"
        save_token_file(token_file, result)
        return {
            "state": "authorized",
            "message": session.message,
            "session_id": session.session_id,
            "mqtt_username": result.get("gcid", ""),
        }

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

        if payload.manufacturer == "bmw":
            if not payload.auth_session_id:
                raise HTTPException(status_code=400, detail="BMW Auth fehlt. Bitte zuerst BMW verbinden.")
            auth_session = auth_store.get(payload.auth_session_id)
            if not auth_session or auth_session.state != "authorized":
                raise HTTPException(status_code=400, detail="BMW Auth ist noch nicht abgeschlossen.")
            tmp_file = Path(data_dir) / "providers" / f"tmp-{auth_session.session_id}" / "bmw_tokens.json"
            if not tmp_file.exists():
                raise HTTPException(status_code=400, detail="BMW Token-Datei wurde nicht gefunden.")
            tokens = json.loads(tmp_file.read_text(encoding="utf-8"))
            target_file = Path(data_dir) / "providers" / vehicle.id / "bmw_tokens.json"
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
            vehicle.provider_state.auth_state = "authorized"
            vehicle.provider_state.auth_message = "BMW Login abgeschlossen"
            vehicle.provider_state.mqtt_username = tokens.get("gcid", "")
            vehicle.provider_state.user_code = auth_session.user_code
            vehicle.provider_state.verification_url = auth_session.verification_uri_complete

        store.upsert_vehicle(vehicle)
        worker_manager.publish_vehicle_saved_meta(vehicle.id)
        if payload.manufacturer == "bmw" and mqtt_settings.host:
            worker_manager.start_or_restart_vehicle(vehicle.id, mqtt_settings)
        return {"status": "ok", "vehicle_id": vehicle.id}

    @app.post("/api/vehicles/{vehicle_id}/restart")
    async def restart_vehicle(vehicle_id: str):
        settings = load_runtime_mqtt_settings()
        worker_manager.start_or_restart_vehicle(vehicle_id, settings)
        return {"status": "ok", "vehicle_id": vehicle_id}

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.2.3"}

    return app
