from __future__ import annotations

import json
import os
import shutil
import re
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict
import time
import ssl

import requests
import paho.mqtt.client as mqtt

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.auth_store import AuthStore
from app.core.config_store import ConfigStore
from app.core.models import AuthSession, VehicleConfig, MqttForwardClientConfig, AppConfig
from app.core.runtime_settings import load_runtime_mqtt_settings
from app.core.state_store import StateStore
from app.core.vehicle_log_store import VehicleLogStore
from app.mqtt.client import LocalMqttClient, test_connection
from app.mqtt.topic_builder import mapped_topic, raw_vehicle_topic
from app.providers.bmw.oauth import poll_device_flow, save_token_file, start_device_flow
from app.providers.registry import ProviderRegistry
from app.providers.gwm_config import (
    render_ora2mqtt_yaml,
    merge_ora_tokens,
    apply_ora_token_bundle,
    extract_ora_token_bundle,
    publish_ora_token_backup,
    clear_ora_token_bundle,
    clear_ora_token_backup,
)
from app.services.worker_manager import WorkerManager

logger = logging.getLogger("car2mqtt.server")


class VehiclePayload(BaseModel):
    id: str
    label: str
    manufacturer: str
    license_plate: str
    enabled: bool = True
    provider_config: dict = {}
    auth_session_id: str | None = None
    mqtt_client_ids: list[str] = []
    device_tracker_enabled: bool = False


class MqttClientPayload(BaseModel):
    id: str | None = None
    name: str = ""
    host: str
    port: int = 1883
    username: str = ""
    password: str = ""
    base_topic: str = ""
    enabled: bool = True
    send_raw: bool = False


class BmwAuthStartPayload(BaseModel):
    client_id: str
    vin: str
    license_plate: str


class BmwAuthPollPayload(BaseModel):
    session_id: str


class GwmVerificationPayload(BaseModel):
    verification_code: str


class HomeZoneSettingsPayload(BaseModel):
    helper_home_zone_entity_id: str = ""
    device_tracker_enabled: bool = False


def _normalize_vehicle_id(license_plate: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", (license_plate or "").upper())
    return cleaned





def _extract_assignment_value(line: str, key: str) -> str | None:
    m = re.match(rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", line)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")




def _extract_zone_entity_id(value: str | None) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    m = re.search(r"state_attr\(\s*['\"](zone\.[A-Za-z0-9_]+)['\"]\s*,", text)
    if m:
        return m.group(1)
    m = re.search(r"\b(zone\.[A-Za-z0-9_]+)\b", text)
    return m.group(1) if m else ''
def _homezone_payload_from_entity(entity_id: str) -> dict[str, Any]:
    entity_id = str(entity_id or '').strip()
    if not entity_id:
        return {}
    return {
        'found': True,
        'home_lat': "{{ state_attr('%s', 'latitude') | float(0) }}" % entity_id,
        'home_lon': "{{ state_attr('%s', 'longitude') | float(0) }}" % entity_id,
        'source': f'settings:{entity_id}',
        'checked_paths': [],
        'entity_id': entity_id,
    }


def _ha_supervisor_headers() -> dict[str, str]:
    token = os.getenv('SUPERVISOR_TOKEN', '').strip()
    if not token:
        return {}
    return {'Authorization': f'Bearer {token}', 'X-Supervisor-Token': token, 'Content-Type': 'application/json'}


def pretty_zone_name(entity_id: str) -> str:
    raw = str(entity_id or '').strip()
    if not raw:
        return ''
    base = raw[5:] if raw.startswith('zone.') else raw
    parts = [p for p in base.split('_') if p]
    return ' '.join(p[:1].upper() + p[1:] for p in parts) or raw


def _load_homeassistant_zones() -> list[dict[str, str]]:
    headers = _ha_supervisor_headers()
    if not headers:
        return []

    urls = [
        os.getenv('SUPERVISOR_CORE_STATES_URL', '').strip(),
        'http://supervisor/core/api/states',
        'http://supervisor/core/states',
        'http://supervisor/homeassistant/api/states',
    ]

    def _extract_items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [i for i in payload if isinstance(i, dict)]
        if isinstance(payload, dict):
            for key in ('result', 'data', 'states'):
                value = payload.get(key)
                if isinstance(value, list):
                    return [i for i in value if isinstance(i, dict)]
        return []

    seen_urls: set[str] = set()
    zone_map: dict[str, dict[str, str]] = {}

    for url in [u for u in urls if u]:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if not resp.ok:
                continue
            items = _extract_items(resp.json())
            if not items:
                continue
            for item in items:
                entity_id = str(item.get('entity_id', '')).strip()
                if not entity_id.startswith('zone.'):
                    continue
                attrs = item.get('attributes') or {}
                name = str(attrs.get('friendly_name') or attrs.get('name') or entity_id).strip()
                zone_map[entity_id] = {'entity_id': entity_id, 'name': name or entity_id}
            if zone_map:
                break
        except Exception:
            continue

    zones = list(zone_map.values())
    zones.sort(key=lambda z: (z['name'].lower(), z['entity_id'].lower()))
    return zones


def _read_detected_homezone() -> dict[str, Any]:
    default_home_lat = "{{ state_attr('zone.home', 'latitude') | float(0) }}"
    default_home_lon = "{{ state_attr('zone.home', 'longitude') | float(0) }}"
    checked_paths: list[str] = []

    def _extract_from_lines(lines: list[str]) -> tuple[str | None, str | None]:
        in_target = False
        current_indent: int | None = None
        in_variables = False
        variables_indent: int | None = None
        active_lat = None
        active_lon = None

        for raw_line in lines:
            if not raw_line.strip():
                continue

            line_indent = len(raw_line) - len(raw_line.lstrip(' '))
            stripped = raw_line.strip()

            if re.match(r"^\s*-\s+alias\s*:", raw_line):
                if in_target and current_indent is not None and line_indent <= current_indent:
                    break
                if not in_target:
                    current_indent = line_indent

            if re.match(r"^\s*(?:-\s*)?id\s*:\s*daheimladen_start_ha_vehicle_decision\s*$", raw_line):
                in_target = True
                current_indent = min(line_indent, current_indent if current_indent is not None else line_indent)
                in_variables = False
                continue

            if not in_target:
                continue

            if stripped.startswith('#'):
                continue

            if re.match(r"^\s*variables\s*:\s*$", raw_line):
                in_variables = True
                variables_indent = line_indent
                continue

            if in_variables:
                if line_indent <= (variables_indent or 0):
                    break
                if active_lat is None:
                    active_lat = _extract_assignment_value(raw_line, 'home_lat')
                if active_lon is None:
                    active_lon = _extract_assignment_value(raw_line, 'home_lon')
                if active_lat and active_lon:
                    return active_lat, active_lon

        return active_lat, active_lon

    def _candidate_config_paths() -> list[Path]:
        roots = []
        for p in [os.getenv('HA_CONFIG_DIR'), '/config', '/homeassistant', '/homeassistant/config', '/data']:
            if p:
                roots.append(Path(p))
        paths: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            for cfg in (root / 'configuration.yaml',):
                key = str(cfg)
                if key not in seen:
                    seen.add(key)
                    paths.append(cfg)
        return paths

    def _resolve_automation_paths() -> list[Path]:
        result: list[Path] = []
        seen: set[str] = set()
        for cfg_path in _candidate_config_paths():
            checked_paths.append(str(cfg_path))
            if not cfg_path.exists() or not cfg_path.is_file():
                continue
            try:
                cfg_text = cfg_path.read_text(encoding='utf-8')
            except Exception:
                continue
            for line in cfg_text.splitlines():
                m = re.match(r"^\s*automation\s*:\s*!include\s+(.+?)\s*$", line)
                if not m:
                    continue
                rel = m.group(1).strip().strip('"').strip("'")
                if not rel:
                    continue
                candidate = (cfg_path.parent / rel)
                key = str(candidate)
                if key not in seen:
                    seen.add(key)
                    result.append(candidate)
        for extra in [Path('/config/automations.yaml'), Path('/homeassistant/automations.yaml')]:
            key = str(extra)
            if key not in seen:
                seen.add(key)
                result.append(extra)
        return result

    for path in _resolve_automation_paths():
        checked_paths.append(str(path))
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except Exception:
            continue
        active_lat, active_lon = _extract_from_lines(lines)
        if active_lat and active_lon:
            entity_id = _extract_zone_entity_id(active_lat) or _extract_zone_entity_id(active_lon)
            return {
                'found': True,
                'home_lat': active_lat,
                'home_lon': active_lon,
                'source': str(path),
                'checked_paths': checked_paths,
                'selected_via_settings': False,
                'entity_id': entity_id,
            }

    return {
        'found': False,
        'home_lat': default_home_lat,
        'home_lon': default_home_lon,
        'source': '',
        'checked_paths': checked_paths,
        'selected_via_settings': False,
        'entity_id': '',
    }


def _read_existing_homezone(config: AppConfig | None = None) -> dict[str, Any]:
    detected = _read_detected_homezone()
    settings_entity = ''
    if config is not None:
        settings_entity = str(getattr(getattr(config, 'ui_settings', None), 'helper_home_zone_entity_id', '') or '').strip()
    if settings_entity:
        payload = _homezone_payload_from_entity(settings_entity)
        if payload:
            payload['selected_via_settings'] = True
            payload['detected_entity_id'] = detected.get('entity_id', '')
            payload['detected_source'] = detected.get('source', '')
            payload['checked_paths'] = detected.get('checked_paths', [])
            return payload
    return detected

def _vehicle_card(vehicle: VehicleConfig, runtime_state: Dict[str, Any] | None, base_topic: str) -> dict:
    metrics = (runtime_state or {}).get("metrics", {})
    provider_meta = (runtime_state or {}).get("provider_meta", {})
    raw_topic = (runtime_state or {}).get("raw_topic") or raw_vehicle_topic(
        base_topic,
        vehicle.manufacturer,
        vehicle.license_plate,
    )
    effective_status = (runtime_state or {}).get("connection_state", "idle")
    effective_detail = (runtime_state or {}).get("connection_detail", vehicle.provider_state.auth_message or "Noch keine Live-Daten")
    if vehicle.manufacturer == "gwm":
        reauth_text = " ".join([
            str(effective_status or ""),
            str(effective_detail or ""),
            str(vehicle.provider_state.last_error or ""),
            str(vehicle.provider_state.auth_message or ""),
        ]).lower()
        if "reauth erforderlich" in reauth_text or "refresh token abgelaufen" in reauth_text:
            effective_status = "reauth_required"
            effective_detail = vehicle.provider_state.auth_message or "ReAuth erforderlich - Refresh Token abgelaufen"
    return {
        "id": vehicle.id,
        "label": vehicle.label,
        "manufacturer": vehicle.manufacturer.upper(),
        "license_plate": vehicle.license_plate,
        "topic": raw_topic,
        "mapped_topic": (runtime_state or {}).get("mapped_topic") or mapped_topic(base_topic, vehicle.manufacturer, vehicle.license_plate),
        "status": effective_status,
        "status_detail": effective_detail,
        "auth_state": vehicle.provider_state.auth_state,
        "metrics": {
            "soc": metrics.get("soc"),
            "range": metrics.get("range"),
            "charging": metrics.get("charging"),
            "plugged": metrics.get("plugged"),
            "odometer": metrics.get("odometer"),
            "limitSoc": metrics.get("limitSoc"),
            "capacityKwh": metrics.get("capacityKwh"),
            "fuelLevel": metrics.get("fuelLevel"),
            "fuelRange": metrics.get("fuelRange"),
            "vehicleType": metrics.get("vehicleType") or ('ev' if vehicle.manufacturer in {'gwm','acconia'} else None),
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
        "manufacturer_note": "ORA Runner vorbereitet" if vehicle.manufacturer == "gwm" else ("Acconia/Silence API vorbereitet" if vehicle.manufacturer == "acconia" else ""),
        "source_topic_base": vehicle.provider_config.get("source_topic_base", "") if vehicle.manufacturer in {"gwm"} else "",
        "device_tracker_enabled": bool(getattr(vehicle, 'device_tracker_enabled', False)),
    }



def _parse_mqtt_scalar(value: str) -> Any:
    text = str(value or '').strip()
    if text.lower() == 'true':
        return True
    if text.lower() == 'false':
        return False
    try:
        if re.fullmatch(r'-?\d+', text):
            return int(text)
        if re.fullmatch(r'-?\d+\.\d+', text):
            return float(text)
    except Exception:
        pass
    return text


def _discover_remote_vehicle_snapshots(mqtt_settings, local_server_name: str, local_vehicles: list[VehicleConfig]) -> list[dict[str, Any]]:
    if not getattr(mqtt_settings, 'host', ''):
        return []
    base = str(getattr(mqtt_settings, 'base_topic', 'car') or 'car').strip('/') or 'car'
    local_server_name = str(local_server_name or '').strip().lower()
    local_keys = {(v.manufacturer.lower(), ''.join(ch for ch in v.license_plate.upper().strip() if ch.isalnum())) for v in local_vehicles}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    connected = False

    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal connected
        if rc == 0:
            connected = True
            client.subscribe(f"{base}/+/+/_meta/#", qos=0)
            client.subscribe(f"{base}/+/+/mapped/#", qos=0)

    def on_message(client, userdata, msg):
        topic = str(msg.topic or '').strip('/')
        parts = topic.split('/')
        if len(parts) < 5 or parts[0].lower() != base.lower():
            return
        manufacturer = parts[1].lower()
        plate = ''.join(ch for ch in parts[2].upper().strip() if ch.isalnum())
        section = parts[3]
        key = '/'.join(parts[4:])
        if manufacturer not in {'bmw', 'gwm', 'acconia', 'hyundai', 'mg', 'vag', 'vw', 'vwcv', 'audi', 'skoda', 'seat', 'cupra'} or not plate:
            return
        entry = grouped.setdefault((manufacturer, plate), {'manufacturer': manufacturer, 'license_plate': plate, 'meta': {}, 'metrics': {}})
        payload = msg.payload.decode('utf-8', errors='ignore')
        if section == '_meta':
            entry['meta'][key] = payload
        elif section == 'mapped' and key and '/' not in key:
            entry['metrics'][key] = _parse_mqtt_scalar(payload)

    client = mqtt.Client(client_id=f"car2mqtt-remote-{int(time.time()*1000)%100000}")
    if getattr(mqtt_settings, 'username', ''):
        client.username_pw_set(mqtt_settings.username, mqtt_settings.password)
    if getattr(mqtt_settings, 'tls', False):
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(mqtt_settings.host, int(mqtt_settings.port or 1883), 20)
        client.loop_start()
        deadline = time.time() + 1.5
        while time.time() < deadline:
            time.sleep(0.05)
        client.disconnect()
        client.loop_stop()
    except Exception:
        try:
            client.loop_stop()
        except Exception:
            pass
        return []

    cards: list[dict[str, Any]] = []
    for (manufacturer, plate), payload in grouped.items():
        meta = payload.get('meta', {}) or {}
        server_name = str(meta.get('server_name') or '').strip()
        if not server_name:
            continue
        if local_server_name and server_name.lower() == local_server_name:
            continue
        label = str(meta.get('label') or meta.get('title') or meta.get('display_name') or meta.get('name') or plate).strip() or plate
        metrics = payload.get('metrics', {}) or {}
        key = (manufacturer, plate)
        # allow remote duplicate even if same plate exists locally but from other server
        card_id = f"remote::{manufacturer}::{plate}::{server_name}"
        cards.append({
            'id': card_id,
            'label': label,
            'manufacturer': manufacturer.upper(),
            'license_plate': str(meta.get('license_plate') or plate).strip() or plate,
            'topic': str(meta.get('raw_topic') or raw_vehicle_topic(base, manufacturer, plate)),
            'mapped_topic': str(meta.get('mapped_topic') or mapped_topic(base, manufacturer, plate)),
            'status': 'remote',
            'status_detail': f'Remote von {server_name}',
            'auth_state': str(meta.get('auth_state') or 'authorized'),
            'metrics': {
                'soc': metrics.get('soc'),
                'range': metrics.get('range'),
                'charging': metrics.get('charging'),
                'plugged': metrics.get('plugged'),
                'odometer': metrics.get('odometer'),
                'limitSoc': metrics.get('limitSoc'),
                'capacityKwh': metrics.get('capacityKwh'),
                'fuelLevel': metrics.get('fuelLevel'),
                'fuelRange': metrics.get('fuelRange'),
                'vehicleType': metrics.get('vehicleType') or ('ev' if manufacturer in {'gwm','acconia'} else None),
                'latitude': metrics.get('latitude'),
                'longitude': metrics.get('longitude'),
                'latitude_ts': metrics.get('latitude_ts'),
                'longitude_ts': metrics.get('longitude_ts'),
            },
            'live': {
                'vin': str(meta.get('vin') or meta.get('vehicle_vin') or ''),
                'mqtt_username': '',
                'vehicle_id': '',
                'gcid': '',
                'append_vin': False,
            },
            'vin': str(meta.get('vin') or meta.get('vehicle_vin') or ''),
            'last_update': str(meta.get('last_update') or ''),
            'enabled': True,
            'manufacturer_note': f'Remote Server: {server_name}',
            'source_topic_base': '',
            'remote': True,
            'remote_server_name': server_name,
        })
    cards.sort(key=lambda c: (str(c.get('label','')).lower(), str(c.get('license_plate','')).lower(), str(c.get('remote_server_name','')).lower()))
    return cards


def _remote_vehicle_payload_from_card(card: dict[str, Any]) -> dict[str, Any]:
    manufacturer = str(card.get('manufacturer','')).lower()
    return {
        'id': card.get('id',''),
        'label': card.get('label',''),
        'manufacturer': manufacturer,
        'license_plate': card.get('license_plate',''),
        'enabled': True,
        'remote': True,
        'provider_config': {
            'vin': (card.get('vin') or ((card.get('live') or {}).get('vin') or '')),
        },
        'provider_state': {
            'auth_state': card.get('auth_state','authorized'),
            'auth_message': card.get('status_detail',''),
            'last_error': '',
        },
        'status': card.get('status','connected'),
        'status_detail': card.get('status_detail',''),
        'mqtt_client_ids': [],
        'device_tracker_enabled': bool(card.get('device_tracker_enabled', False)),
        'remote_server_name': card.get('remote_server_name',''),
    }




def _slugify_identifier(text: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_]+", "_", str(text or '').strip().lower())
    return raw.strip('_') or 'item'


def _device_tracker_slug(card: dict[str, Any]) -> str:
    manufacturer = _slugify_identifier(card.get('manufacturer') or 'vehicle')
    plate = _slugify_identifier(card.get('license_plate') or card.get('label') or 'vehicle')
    server = _slugify_identifier(card.get('remote_server_name') or card.get('server_name') or 'local')
    return f"car2mqtt_{manufacturer}_{plate}_{server}"


def _card_device_tracker_enabled(card: dict[str, Any], cfg: AppConfig) -> bool:
    if card.get('remote'):
        ids = set(getattr(getattr(cfg, 'ui_settings', None), 'remote_device_tracker_ids', []) or [])
        return str(card.get('id') or '') in ids
    vehicle = next((v for v in (cfg.vehicles or []) if v.id == card.get('id')), None)
    return bool(getattr(vehicle, 'device_tracker_enabled', False)) if vehicle else False


def _device_tracker_token(card: dict[str, Any]) -> str:
    metrics = dict(card.get('metrics') or {})
    return json.dumps({
        'enabled': bool(card.get('device_tracker_enabled')),
        'lat_ts': metrics.get('latitude_ts') or '',
        'lon_ts': metrics.get('longitude_ts') or '',
        'lat': metrics.get('latitude'),
        'lon': metrics.get('longitude'),
        'server': card.get('remote_server_name') or '',
        'label': card.get('label') or '',
        'plate': card.get('license_plate') or '',
    }, sort_keys=True, ensure_ascii=False)


def _publish_device_trackers(cards: list[dict[str, Any]], mqtt_settings, enabled: bool) -> None:
    if not getattr(mqtt_settings, 'host', ''):
        logger.warning("Device Tracker: kein MQTT Host konfiguriert")
        return
    client = LocalMqttClient(mqtt_settings)
    published = 0
    try:
        client.connect()
        logger.info("Device Tracker: MQTT verbunden zu %s:%s", mqtt_settings.host, mqtt_settings.port)
        for card in cards:
            slug = _device_tracker_slug(card)
            config_topic = f"homeassistant/device_tracker/{slug}/config"
            state_topic = f"{getattr(mqtt_settings, 'base_topic', 'car')}/_device_tracker/{slug}/state"
            attrs_topic = f"{getattr(mqtt_settings, 'base_topic', 'car')}/_device_tracker/{slug}/attributes"
            if not enabled or not bool(card.get('device_tracker_enabled')):
                client.publish(config_topic, '', retain=True)
                logger.info("Device Tracker: Discovery entfernt für %s", slug)
                continue
            metrics = dict(card.get('metrics') or {})
            lat = metrics.get('latitude')
            lon = metrics.get('longitude')
            label = str(card.get('label') or card.get('license_plate') or slug).strip() or slug
            manufacturer = str(card.get('manufacturer') or '').strip() or 'Vehicle'
            vin = str(card.get('vin') or ((card.get('live') or {}).get('vin') or '')).strip()
            license_plate = str(card.get('license_plate') or '').strip()
            attrs = {}
            if lat not in (None, '') and lon not in (None, ''):
                attrs['latitude'] = lat
                attrs['longitude'] = lon
                attrs['gps_accuracy'] = 0
            if vin:
                attrs['vin'] = vin
            if license_plate:
                attrs['license_plate'] = license_plate
            if card.get('remote_server_name'):
                attrs['server_name'] = card.get('remote_server_name')
            state = 'not_home' if 'latitude' in attrs and 'longitude' in attrs else 'unknown'
            device_payload = {
                'name': label,
                'object_id': slug,
                'unique_id': slug,
                'state_topic': state_topic,
                'json_attributes_topic': attrs_topic,
                'source_type': 'gps',
                'payload_home': 'home',
                'payload_not_home': 'not_home',
                'icon': 'mdi:car',
                'device': {
                    'identifiers': [slug],
                    'name': label,
                    'manufacturer': manufacturer,
                    'model': license_plate or label,
                },
            }
            logger.info("Device Tracker: veröffentliche Discovery für %s via %s", slug, config_topic)
            client.publish(config_topic, device_payload, retain=True)
            client.publish(attrs_topic, attrs, retain=True)
            client.publish(state_topic, state, retain=True)
            published += 1
        logger.info("Device Tracker: %s Tracker veröffentlicht", published)
    except Exception:
        logger.exception("Device Tracker Publish fehlgeschlagen")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


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

    app.state.device_tracker_task = None
    app.state.device_tracker_tokens = {}

    async def _device_tracker_sync_loop():
        while True:
            try:
                cfg = store.load()
                cards, mqtt_settings = build_cards()
                global_enabled = bool(getattr(getattr(cfg, "ui_settings", None), "device_tracker_enabled", False))
                tokens = {}
                changed = False
                for card in cards:
                    token = _device_tracker_token(card)
                    tokens[str(card.get('id') or '')] = token
                    if app.state.device_tracker_tokens.get(str(card.get('id') or '')) != token:
                        changed = True
                if changed or set(app.state.device_tracker_tokens.keys()) != set(tokens.keys()):
                    _publish_device_trackers(cards, load_runtime_mqtt_settings(), global_enabled)
                    app.state.device_tracker_tokens = tokens
            except Exception:
                logger.exception("Device Tracker Sync Loop fehlgeschlagen")
            await asyncio.sleep(15)

    @app.on_event("startup")
    async def startup_event():
        worker_manager.start_all()
        cfg = store.load()
        if bool(getattr(getattr(cfg, "ui_settings", None), "device_tracker_enabled", False)):
            try:
                cards, mqtt_settings = build_cards()
                _publish_device_trackers(cards, load_runtime_mqtt_settings(), True)
                app.state.device_tracker_tokens = {str(card.get('id') or ''): _device_tracker_token(card) for card in cards}
            except Exception:
                logger.exception("Device Tracker Initialpublish fehlgeschlagen")
        app.state.device_tracker_task = asyncio.create_task(_device_tracker_sync_loop())

    @app.on_event("shutdown")
    async def shutdown_event():
        task = getattr(app.state, "device_tracker_task", None)
        if task:
            task.cancel()

    def build_cards() -> tuple[list[dict], dict]:
        config = store.load()
        mqtt_settings = load_runtime_mqtt_settings()
        runtime_states = {k: v.model_dump(mode="json") for k, v in state_store.get_all().items()}
        cards = [_vehicle_card(vehicle, runtime_states.get(vehicle.id), mqtt_settings.base_topic) for vehicle in config.vehicles]
        remote_cards = _discover_remote_vehicle_snapshots(mqtt_settings, worker_manager._resolve_server_name(), config.vehicles)
        cards.extend(remote_cards)
        for card in cards:
            card['device_tracker_enabled'] = _card_device_tracker_enabled(card, config)
        cards.sort(key=lambda c: (str(c.get('label','')).lower(), str(c.get('license_plate','')).lower(), 1 if c.get('remote') else 0))
        return cards, mqtt_settings.model_dump(mode="json")

    def mqtt_client_status(client: MqttForwardClientConfig) -> str:
        if not client.enabled:
            return "disabled"
        try:
            settings = load_runtime_mqtt_settings()
            from app.core.models import RuntimeMqttSettings
            test_settings = RuntimeMqttSettings(host=client.host, port=client.port, username=client.username, password=client.password, password_set=bool(client.password), base_topic=client.base_topic or settings.base_topic, qos=settings.qos, retain=settings.retain, tls=settings.tls)
            test_connection(test_settings)
            return "online"
        except Exception:
            return "offline"

    def build_mqtt_clients() -> list[dict[str, Any]]:
        cfg = store.load()
        return [dict(client.model_dump(mode="json"), status=mqtt_client_status(client)) for client in cfg.mqtt_clients]

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        cards, mqtt_settings = build_cards()
        providers = [provider.model_dump(mode="json") for provider in registry.all()]
        cfg = store.load()
        helper_homezone = _read_existing_homezone(cfg)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "cards": cards,
                "providers": providers,
                "version": "1.1.86",
                "mqtt_settings": mqtt_settings,
                "cards_json": json.dumps(cards, ensure_ascii=False),
                "helper_homezone_json": json.dumps(helper_homezone, ensure_ascii=False),
                "ui_settings_json": json.dumps(cfg.ui_settings.model_dump(mode="json"), ensure_ascii=False),
                "zones_json": json.dumps(_load_homeassistant_zones(), ensure_ascii=False),
                "mqtt_clients_json": json.dumps(build_mqtt_clients(), ensure_ascii=False),
            },
        )

    @app.get("/api/helper/homezone")
    async def get_helper_homezone():
        return _read_existing_homezone(store.load())

    @app.get("/api/settings")
    async def get_settings():
        cfg = store.load()
        effective = _read_existing_homezone(cfg)
        zones = _load_homeassistant_zones()
        detected_entity = str(effective.get('detected_entity_id') or effective.get('entity_id') or '').strip()
        if detected_entity and not any(z.get('entity_id') == detected_entity for z in zones):
            zones.append({'entity_id': detected_entity, 'name': pretty_zone_name(detected_entity)})
        zones.sort(key=lambda z: (str(z.get('name','')).lower(), str(z.get('entity_id','')).lower()))
        return {
            "ui_settings": cfg.ui_settings.model_dump(mode="json"),
            "zones": zones,
            "effective_homezone": effective,
        }

    @app.post("/api/settings/homezone")
    async def save_homezone_settings(payload: HomeZoneSettingsPayload):
        cfg = store.load()
        cfg.ui_settings.helper_home_zone_entity_id = str(payload.helper_home_zone_entity_id or '').strip()
        cfg.ui_settings.device_tracker_enabled = bool(payload.device_tracker_enabled)
        store.save(cfg)
        try:
            cards, _ = build_cards()
            _publish_device_trackers(cards, load_runtime_mqtt_settings(), bool(cfg.ui_settings.device_tracker_enabled))
            app.state.device_tracker_tokens = {str(card.get('id') or ''): _device_tracker_token(card) for card in cards}
        except Exception:
            pass
        return {
            "status": "ok",
            "ui_settings": cfg.ui_settings.model_dump(mode="json"),
            "effective_homezone": _read_existing_homezone(cfg),
        }



    @app.get("/api/mqtt-clients")
    async def get_mqtt_clients():
        return {"clients": build_mqtt_clients()}

    @app.post("/api/mqtt-clients")
    async def save_mqtt_client(payload: MqttClientPayload):
        cfg = store.load()
        client_id = str(payload.id or '').strip() or _normalize_vehicle_id(payload.name or payload.host or 'mqttclient').lower()
        if not client_id:
            client_id = 'mqttclient'
        client = MqttForwardClientConfig(
            id=client_id,
            name=str(payload.name or '').strip() or client_id,
            host=str(payload.host or '').strip(),
            port=int(payload.port or 1883),
            username=str(payload.username or '').strip(),
            password=str(payload.password or ''),
            base_topic=str(payload.base_topic or '').strip(),
            enabled=bool(payload.enabled),
            send_raw=bool(payload.send_raw),
        )
        replaced=False
        for idx, existing in enumerate(cfg.mqtt_clients):
            if existing.id == client.id:
                cfg.mqtt_clients[idx] = client
                replaced=True
                break
        if not replaced:
            cfg.mqtt_clients.append(client)
        store.save(cfg)
        for vehicle in cfg.vehicles:
            if client.id in (vehicle.mqtt_client_ids or []):
                worker_manager.sync_vehicle_to_forward_clients(vehicle.id)
        try:
            cards, _ = build_cards()
            _publish_device_trackers(cards, load_runtime_mqtt_settings(), bool(getattr(getattr(cfg, "ui_settings", None), "device_tracker_enabled", False)))
        except Exception:
            pass
        return {"status": "ok", "client": dict(client.model_dump(mode="json"), status=mqtt_client_status(client)), "clients": build_mqtt_clients()}

    @app.delete("/api/mqtt-clients/{client_id}")
    async def delete_mqtt_client(client_id: str):
        cfg = store.load()
        cfg.mqtt_clients = [c for c in cfg.mqtt_clients if c.id != client_id]
        for vehicle in cfg.vehicles:
            vehicle.mqtt_client_ids = [cid for cid in (vehicle.mqtt_client_ids or []) if cid != client_id]
        store.save(cfg)
        return {"status": "ok", "clients": build_mqtt_clients()}

    @app.post("/api/remote-vehicles/{vehicle_id}/device-tracker")
    async def set_remote_vehicle_device_tracker(vehicle_id: str, payload: dict):
        cfg = store.load()
        cards, _ = build_cards()
        card = next((c for c in cards if str(c.get('id')) == vehicle_id and c.get('remote')), None)
        if not card:
            raise HTTPException(status_code=404, detail="Remote-Fahrzeug nicht gefunden")
        enabled = bool((payload or {}).get('device_tracker_enabled'))
        ids = set(getattr(cfg.ui_settings, 'remote_device_tracker_ids', []) or [])
        if enabled:
            ids.add(vehicle_id)
        else:
            ids.discard(vehicle_id)
        cfg.ui_settings.remote_device_tracker_ids = sorted(ids)
        store.save(cfg)
        cards, _ = build_cards()
        try:
            _publish_device_trackers(cards, load_runtime_mqtt_settings(), bool(getattr(getattr(cfg, 'ui_settings', None), 'device_tracker_enabled', False)))
            app.state.device_tracker_tokens = {str(card.get('id') or ''): _device_tracker_token(card) for card in cards}
        except Exception:
            pass
        return {'status':'ok','vehicle_id':vehicle_id,'device_tracker_enabled': enabled}

    @app.get("/api/providers")
    async def get_providers():
        return [provider.model_dump(mode="json") for provider in registry.all()]

    @app.get("/api/dashboard")
    async def get_dashboard():
        cards, mqtt_settings = build_cards()
        return {"vehicles": cards, "mqtt": mqtt_settings}

    @app.get("/api/vehicles/{vehicle_id}")
    async def get_vehicle(vehicle_id: str):
        if str(vehicle_id).startswith('remote::'):
            cards, _ = build_cards()
            for card in cards:
                if str(card.get('id')) == vehicle_id and card.get('remote'):
                    return _remote_vehicle_payload_from_card(card)
            raise HTTPException(status_code=404, detail="Remote-Fahrzeug nicht gefunden")
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
            mqtt_client_ids=list(payload.mqtt_client_ids or []),
            device_tracker_enabled=bool(payload.device_tracker_enabled),
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

        if payload.manufacturer == "acconia":
            vehicle.provider_config["license_plate"] = vehicle.license_plate
            vehicle.provider_config["vehicle_id"] = _normalize_vehicle_id(vehicle.license_plate)
            vehicle.provider_config.pop("source_topic_base", None)
            vehicle.provider_state.auth_state = "authorized"
            vehicle.provider_state.auth_message = "Acconia/Silence API vorbereitet"
            log_store.append(vehicle.id, "Acconia/Silence API-Konfiguration gespeichert")

        if payload.manufacturer in {"hyundai", "mg"}:
            vehicle.provider_config["license_plate"] = vehicle.license_plate
            vehicle.provider_config["vehicle_id"] = _normalize_vehicle_id(vehicle.license_plate)
            vehicle.provider_config["brand"] = payload.manufacturer
            vehicle.provider_config.pop("source_topic_base", None)
            vehicle.provider_state.auth_state = "authorized"
            vehicle.provider_state.auth_message = "Hersteller-Grundstruktur vorbereitet - API-Connector folgt im nächsten Schritt"
            log_store.append(vehicle.id, "Hersteller-Grundstruktur gespeichert")

        if payload.manufacturer in {"vag", "vw", "vwcv", "audi", "skoda", "seat", "cupra"}:
            vehicle.provider_config["license_plate"] = vehicle.license_plate
            vehicle.provider_config["vehicle_id"] = _normalize_vehicle_id(vehicle.license_plate)
            vehicle.provider_config.pop("source_topic_base", None)
            vehicle.provider_state.auth_state = "authorized"
            vehicle.provider_state.auth_message = "Marken-Grundstruktur vorbereitet - API-Connector folgt im nächsten Schritt"
            log_store.append(vehicle.id, "Marken-Grundstruktur gespeichert")

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
        worker_manager.sync_vehicle_to_forward_clients(vehicle.id)
        try:
            cards, _ = build_cards()
            _publish_device_trackers(cards, load_runtime_mqtt_settings(), bool(getattr(getattr(store.load(), "ui_settings", None), "device_tracker_enabled", False)))
        except Exception:
            pass
        if not vehicle.enabled:
            vehicle.provider_state.auth_message = "Fahrzeug ist inaktiv"
            worker_manager.stop_vehicle(vehicle.id)
            worker_manager.publish_vehicle_saved_meta(vehicle.id)
            return {"status": "ok", "vehicle_id": vehicle.id}

        if payload.manufacturer == "bmw" and mqtt_settings.host and vehicle.provider_state.auth_state == "authorized":
            worker_manager.start_or_restart_vehicle(vehicle.id, mqtt_settings)
        if payload.manufacturer == "acconia":
            if vehicle.enabled and mqtt_settings.host:
                log_store.append(vehicle.id, "Acconia/Silence Fahrzeug gespeichert - API Polling gestartet")
                worker_manager.start_or_restart_vehicle(vehicle.id, mqtt_settings)
            else:
                log_store.append(vehicle.id, "Acconia/Silence Fahrzeug gespeichert - kein automatischer Start")
                worker_manager.publish_vehicle_saved_meta(vehicle.id)
        if payload.manufacturer in {"hyundai", "mg"}:
            log_store.append(vehicle.id, f"{payload.manufacturer.upper()} Fahrzeug gespeichert - noch kein Live-Login in dieser Grundversion")
            worker_manager.publish_vehicle_saved_meta(vehicle.id)
        if payload.manufacturer in {"vag", "vw", "vwcv", "audi", "skoda", "seat", "cupra"}:
            log_store.append(vehicle.id, "Marken-Fahrzeug gespeichert - noch kein Live-Login in dieser Grundversion")
            worker_manager.publish_vehicle_saved_meta(vehicle.id)
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



    @app.post("/api/vehicles/{vehicle_id}/gwm/reauth/start")
    async def gwm_reauth_start(vehicle_id: str):
        vehicle = store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer != "gwm":
            raise HTTPException(status_code=404, detail="ORA Fahrzeug nicht gefunden")
        if not vehicle.enabled:
            raise HTTPException(status_code=400, detail="Fahrzeug ist inaktiv. Bitte zuerst aktivieren.")
        account = str(vehicle.provider_config.get("account", "")).strip()
        password = str(vehicle.provider_config.get("password", "")).strip()
        if not account or not password:
            raise HTTPException(status_code=400, detail="ORA Benutzerkonto und Passwort müssen gesetzt sein")

        settings = load_runtime_mqtt_settings()
        worker_manager.stop_vehicle(vehicle.id)

        provider_dir = Path(data_dir) / "providers" / vehicle.id
        provider_dir.mkdir(parents=True, exist_ok=True)
        config_path = provider_dir / "ora2mqtt.yml"
        verification_path = provider_dir / "verification_code.txt"
        for path in (config_path, verification_path):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

        clear_ora_token_bundle(vehicle.provider_config)
        clear_ora_token_backup(settings, vehicle.id, lambda message: log_store.append(vehicle_id, message))
        vehicle.provider_state.auth_state = "error"
        vehicle.provider_state.auth_message = "ReAuth erforderlich - neue ORA Anmeldung wird aufgebaut"
        vehicle.provider_state.last_error = "Refresh Token abgelaufen"
        store.upsert_vehicle(vehicle)
        log_store.append(vehicle_id, "ORA ReAuth angefordert - gespeicherte Tokens entfernt")

        if settings.host:
            worker_manager.start_or_restart_vehicle(vehicle.id, settings)

        return {"status": "ok", "vehicle_id": vehicle_id, "message": "ORA ReAuth gestartet - bitte ggf. Verifikationscode eingeben."}


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
