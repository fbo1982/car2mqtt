from __future__ import annotations

import json
import os
import shutil
import re
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.auth_store import AuthStore
from app.core.config_store import ConfigStore
from app.core.models import AuthSession, VehicleConfig
from app.core.runtime_settings import load_runtime_mqtt_settings
from app.core.state_store import StateStore
from app.core.vehicle_log_store import VehicleLogStore
from app.mqtt.client import test_connection
from app.mqtt.topic_builder import mapped_topic, raw_vehicle_topic
from app.providers.bmw.oauth import poll_device_flow, save_token_file, start_device_flow
from app.providers.registry import ProviderRegistry
from app.providers.gwm_config import (
    render_ora2mqtt_yaml,
    merge_ora_tokens,
    apply_ora_token_bundle,
    extract_ora_token_bundle,
    publish_ora_token_backup,
)
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


class GwmVerificationPayload(BaseModel):
    verification_code: str


def _normalize_vehicle_id(license_plate: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", (license_plate or "").upper())
    return cleaned



def _vehicle_card(vehicle: VehicleConfig, runtime_state: Dict[str, Any] | None, base_topic: str) -> dict:
    metrics = (runtime_state or {}).get("metrics", {})
    provider_meta = (runtime_state or {}).get("provider_meta", {})
    raw_topic = (runtime_state or {}).get("raw_topic") or raw_vehicle_topic(
        base_topic,
        vehicle.manufacturer,
        vehicle.license_plate,
    )
    return {
        "id": vehicle.id,
        "label": vehicle.label,
        "manufacturer": vehicle.manufacturer.upper(),
        "license_plate": vehicle.license_plate,
        "topic": raw_topic,
        "mapped_topic": (runtime_state or {}).get("mapped_topic") or mapped_topic(base_topic, vehicle.manufacturer, vehicle.license_plate),
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
            "capacityKwh": metrics.get("capacityKwh"),
            "latitude": metrics.get("latitude"),
            "longitude": metrics.get("longitude"),
        },
        "live": {
            "vin": vehicle.provider_config.get("vin", provider_meta.get("vin", "")),
            "mqtt_username": vehicle.provider_config.get("mqtt_username", provider_meta.get("mqtt_username", "")),
            "vehicle_id": vehicle.provider_config.get("vehicle_id", provider_meta.get("vehicle_id", "")),
            "gcid": provider_meta.get("gcid", ""),
            "append_vin": bool(vehicle.provider_config.get("append_vin", False)),
        },
        "last_update": (runtime_state or {}).get("last_update", ""),
        "enabled": vehicle.enabled,
        "manufacturer_note": "ORA Runner vorbereitet" if vehicle.manufacturer == "gwm" else "",
        "source_topic_base": vehicle.provider_config.get("source_topic_base", "") if vehicle.manufacturer == "gwm" else "",
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Car2MQTT")
    root = Path(__file__).resolve().parent.parent
    templates = Jinja2Templates(directory=str(root / "templates"))

    data_dir = os.getenv("APP_DATA_DIR", "/config/car2mqtt")
    store = ConfigStore(data_dir)
    state_store = StateStore(data_dir)
    auth_store = AuthStore(data_dir)
    log_store = VehicleLogStore(data_dir)
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
                "version": "1.1.12",
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

    @app.get("/api/vehicles/{vehicle_id}")
    async def get_vehicle(vehicle_id: str):
        vehicle = store.get_vehicle(vehicle_id)
        if not vehicle:
            raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")
        payload = vehicle.model_dump(mode="json")
        if payload.get("manufacturer") == "gwm":
            source_base = str(payload.get("provider_config", {}).get("source_topic_base", "")).strip()
            if not source_base or source_base.upper().startswith("GWM/"):
                payload["provider_config"]["source_topic_base"] = "GWM"
        return payload

    @app.get("/api/vehicles/{vehicle_id}/logs", response_class=PlainTextResponse)
    async def get_vehicle_logs(vehicle_id: str):
        if not store.get_vehicle(vehicle_id):
            raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")
        return log_store.read(vehicle_id)

    @app.post("/api/vehicles/{vehicle_id}/logs/clear")
    async def clear_vehicle_logs(vehicle_id: str):
        if not store.get_vehicle(vehicle_id):
            raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")
        log_store.delete(vehicle_id)
        return {"status": "ok", "vehicle_id": vehicle_id}

    @app.get("/api/vehicles/{vehicle_id}/ora/config", response_class=PlainTextResponse)
    async def get_ora_config(vehicle_id: str):
        vehicle = store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer != "gwm":
            raise HTTPException(status_code=404, detail="ORA Fahrzeug nicht gefunden")
        settings = load_runtime_mqtt_settings()
        provider_config = dict(vehicle.provider_config)
        provider_config["license_plate"] = vehicle.license_plate
        return render_ora2mqtt_yaml(provider_config, settings, license_plate=vehicle.license_plate)

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
        if session.vehicle_id:
            vehicle = store.get_vehicle(session.vehicle_id)
            if vehicle and vehicle.manufacturer == "bmw":
                target_file = Path(data_dir) / "providers" / vehicle.id / "bmw_tokens.json"
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
                vehicle.provider_state.auth_state = "authorized"
                vehicle.provider_state.auth_message = "BMW Re-Auth abgeschlossen"
                vehicle.provider_state.mqtt_username = result.get("gcid", vehicle.provider_state.mqtt_username)
                vehicle.provider_config["mqtt_username"] = result.get("gcid", vehicle.provider_config.get("mqtt_username", ""))
                vehicle.provider_state.user_code = session.user_code
                vehicle.provider_state.verification_url = session.verification_uri_complete
                store.upsert_vehicle(vehicle)
                log_store.append(vehicle.id, "BMW Re-Auth erfolgreich abgeschlossen")
                settings = load_runtime_mqtt_settings()
                if settings.host:
                    worker_manager.start_or_restart_vehicle(vehicle.id, settings)
        return {"state": "authorized", "message": session.message, "session_id": session.session_id, "gcid": result.get("gcid", "")}

    def _save_vehicle(payload: VehiclePayload, vehicle_id_to_replace: str | None = None):
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

        existing = store.get_vehicle(vehicle_id_to_replace or payload.id)
        if existing:
            vehicle.provider_state = existing.provider_state

        if payload.manufacturer == "bmw":
            if payload.auth_session_id:
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
                vehicle.provider_config["mqtt_username"] = tokens.get("gcid", vehicle.provider_config.get("mqtt_username", ""))
                vehicle.provider_state.user_code = auth_session.user_code
                vehicle.provider_state.verification_url = auth_session.verification_uri_complete
                log_store.append(vehicle.id, "BMW Login erstmalig abgeschlossen")
            elif existing and existing.manufacturer == "bmw":
                src = Path(data_dir) / "providers" / existing.id / "bmw_tokens.json"
                dst = Path(data_dir) / "providers" / vehicle.id / "bmw_tokens.json"
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if src.resolve() != dst.resolve():
                        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        if payload.manufacturer == "gwm":
            vehicle.provider_config["license_plate"] = vehicle.license_plate
            # Preserve persisted ORA session/token data so saving the form does not trigger a new verify each time.
            token_bundle = {}
            if existing and existing.manufacturer == "gwm":
                apply_ora_token_bundle(token_bundle, extract_ora_token_bundle(existing.provider_config))
            source_cfg_id = vehicle_id_to_replace or payload.id
            existing_cfg = Path(data_dir) / "providers" / source_cfg_id / "ora2mqtt.yml"
            if existing_cfg.exists():
                try:
                    merge_ora_tokens(token_bundle, existing_cfg)
                    log_store.append(vehicle.id, "ORA Tokens aus bestehender ora2mqtt.yml zur Speicherung übernommen")
                except Exception as exc:
                    log_store.append(vehicle.id, f"ORA Token-Übernahme vor dem Speichern fehlgeschlagen: {exc}")
            apply_ora_token_bundle(vehicle.provider_config, token_bundle)

            source_base = str(vehicle.provider_config.get("source_topic_base", "")).strip()
            if (not source_base) or source_base.upper().startswith("GWM/"):
                vehicle.provider_config["source_topic_base"] = "GWM"
            target_dir = Path(data_dir) / "providers" / vehicle.id
            target_dir.mkdir(parents=True, exist_ok=True)
            settings = load_runtime_mqtt_settings()
            ora_config = render_ora2mqtt_yaml(vehicle.provider_config, settings, license_plate=vehicle.license_plate)
            (target_dir / "ora2mqtt.yml").write_text(ora_config, encoding="utf-8")
            publish_ora_token_backup(vehicle.provider_config, settings, vehicle.id, lambda msg: log_store.append(vehicle.id, msg))
            vehicle.provider_state.auth_state = "authorized"
            vehicle.provider_state.auth_message = "ORA Runner vorbereitet"
            if not vehicle.provider_config.get("source_topic_base"):
                vehicle.provider_config["source_topic_base"] = "GWM"
            log_store.append(vehicle.id, "ORA Konfiguration erzeugt: providers/%s/ora2mqtt.yml" % vehicle.id)

        if vehicle_id_to_replace and vehicle_id_to_replace != vehicle.id:
            if payload.manufacturer == "gwm":
                src_cfg = Path(data_dir) / "providers" / vehicle_id_to_replace / "ora2mqtt.yml"
                dst_cfg = Path(data_dir) / "providers" / vehicle.id / "ora2mqtt.yml"
                if src_cfg.exists():
                    dst_cfg.parent.mkdir(parents=True, exist_ok=True)
                    if src_cfg.resolve() != dst_cfg.resolve():
                        dst_cfg.write_text(src_cfg.read_text(encoding="utf-8"), encoding="utf-8")
            config = store.load()
            config.vehicles = [v for v in config.vehicles if v.id != vehicle_id_to_replace]
            store.save(config)
            worker_manager.stop_vehicle(vehicle_id_to_replace)
            log_store.append(vehicle.id, f"Fahrzeug-ID geändert von {vehicle_id_to_replace} auf {vehicle.id}")
        store.upsert_vehicle(vehicle)
        worker_manager.publish_vehicle_saved_meta(vehicle.id)
        if not vehicle.enabled:
            vehicle.provider_state.auth_message = "Fahrzeug ist inaktiv"
            worker_manager.stop_vehicle(vehicle.id)
            worker_manager.publish_vehicle_saved_meta(vehicle.id)
            return {"status": "ok", "vehicle_id": vehicle.id}

        if payload.manufacturer == "bmw" and mqtt_settings.host and vehicle.provider_state.auth_state == "authorized":
            worker_manager.start_or_restart_vehicle(vehicle.id, mqtt_settings)
        if payload.manufacturer == "gwm":
            if vehicle.enabled and mqtt_settings.host:
                log_store.append(vehicle.id, "ORA Fahrzeug gespeichert - automatischer Start aktiviert")
                worker_manager.start_or_restart_vehicle(vehicle.id, mqtt_settings)
            else:
                log_store.append(vehicle.id, "ORA Fahrzeug gespeichert - kein automatischer Start")
                worker_manager.publish_vehicle_saved_meta(vehicle.id)
        return {"status": "ok", "vehicle_id": vehicle.id}

    @app.post("/api/vehicles")
    async def create_vehicle(payload: VehiclePayload):
        payload.id = _normalize_vehicle_id(payload.license_plate)
        if not payload.id:
            raise HTTPException(status_code=400, detail="Kennzeichen konnte nicht in eine interne ID umgewandelt werden.")
        if store.get_vehicle(payload.id):
            raise HTTPException(status_code=400, detail="Fahrzeug existiert bereits. Bitte bearbeiten oder anderes Kennzeichen verwenden.")
        return _save_vehicle(payload)

    @app.put("/api/vehicles/{vehicle_id}")
    async def update_vehicle(vehicle_id: str, payload: VehiclePayload):
        if not store.get_vehicle(vehicle_id):
            raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")
        payload.id = _normalize_vehicle_id(payload.license_plate)
        if not payload.id:
            raise HTTPException(status_code=400, detail="Kennzeichen konnte nicht in eine interne ID umgewandelt werden.")
        existing = store.get_vehicle(payload.id)
        if existing and payload.id != vehicle_id:
            raise HTTPException(status_code=400, detail="Ein anderes Fahrzeug mit diesem Kennzeichen existiert bereits.")
        return _save_vehicle(payload, vehicle_id_to_replace=vehicle_id)

    @app.post("/api/vehicles/{vehicle_id}/reauth/start")
    async def reauth_start_vehicle(vehicle_id: str):
        vehicle = store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer != "bmw":
            raise HTTPException(status_code=404, detail="BMW Fahrzeug nicht gefunden")
        if not vehicle.enabled:
            raise HTTPException(status_code=400, detail="Fahrzeug ist inaktiv. Bitte zuerst aktivieren.")
        client_id = str(vehicle.provider_config.get("client_id", "")).strip()
        vin = str(vehicle.provider_config.get("vin", "")).strip().upper()
        if not client_id or not vin:
            raise HTTPException(status_code=400, detail="Client ID und VIN müssen für Re-Auth gesetzt sein")
        try:
            session = start_device_flow(client_id, vin, vehicle.license_plate.strip())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"BMW Re-Auth konnte nicht gestartet werden: {exc}") from exc
        session.vehicle_id = vehicle_id
        auth_store.upsert(session)
        log_store.append(vehicle_id, "BMW Re-Auth gestartet")
        return session.model_dump(mode="json")



    @app.post("/api/vehicles/{vehicle_id}/gwm/test-map")
    async def gwm_test_map(vehicle_id: str):
        vehicle = store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer != "gwm":
            raise HTTPException(status_code=404, detail="ORA Fahrzeug nicht gefunden")
        settings = load_runtime_mqtt_settings()
        if not settings.host:
            raise HTTPException(status_code=400, detail="MQTT ist nicht konfiguriert")
        result = worker_manager.test_map_gwm_from_upstream(vehicle_id, settings)
        return {"status": "ok", "processed": result["count"], "vehicle_id": vehicle_id}

    @app.post("/api/vehicles/{vehicle_id}/gwm/submit-code")
    async def gwm_submit_code(vehicle_id: str, payload: GwmVerificationPayload):
        vehicle = store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer != "gwm":
            raise HTTPException(status_code=404, detail="ORA Fahrzeug nicht gefunden")
        code = payload.verification_code.strip()
        if not code:
            raise HTTPException(status_code=400, detail="Verifikationscode fehlt")
        target_dir = Path(data_dir) / "providers" / vehicle.id
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "verification_code.txt").write_text(code, encoding="utf-8")
        vehicle.provider_state.auth_message = "Verifikationscode übernommen"
        store.upsert_vehicle(vehicle)
        log_store.append(vehicle_id, "ORA Verifikationscode übernommen (temporär) - Worker wird manuell fortgesetzt")
        settings = load_runtime_mqtt_settings()
        if vehicle.enabled and settings.host:
            worker_manager.start_or_restart_vehicle(vehicle.id, settings)
        return {"status": "ok", "vehicle_id": vehicle_id}

    @app.delete("/api/vehicles/{vehicle_id}")
    async def delete_vehicle(vehicle_id: str):
        vehicle = store.get_vehicle(vehicle_id)
        if not vehicle:
            raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")
        config = store.load()
        config.vehicles = [v for v in config.vehicles if v.id != vehicle_id]
        store.save(config)
        worker_manager.delete_vehicle(vehicle_id)
        provider_dir = Path(data_dir) / "providers" / vehicle_id
        if provider_dir.exists():
            shutil.rmtree(provider_dir, ignore_errors=True)
        return {"status": "ok", "vehicle_id": vehicle_id}

    return app
