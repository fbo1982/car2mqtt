from __future__ import annotations

import json
import logging
import math
import os
import ssl
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import paho.mqtt.client as mqtt
import requests

from app.core.models import AppConfig, RuntimeMqttSettings

logger = logging.getLogger("car2mqtt.evcc_geo")


@dataclass(frozen=True)
class ZonePosition:
    entity_id: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class EvccGeoDecision:
    status: str
    at_site: bool | None
    distance_m: float | None
    reason: str


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "connected", "plugged", "charging"}:
        return True
    if text in {"0", "false", "no", "off", "disconnected", "unplugged", "not_charging", "not charging"}:
        return False
    return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def parse_mqtt_scalar(payload: bytes | str) -> Any:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
    text = text.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        return text


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return radius * (2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a))))


def calculate_evcc_geo_decision(
    metrics: dict[str, Any],
    *,
    geo_enabled: bool,
    zone: ZonePosition | None,
    radius_m: float,
) -> EvccGeoDecision:
    """Calculate the EVCC A/B/C status without modifying manufacturer metrics.

    A = disconnected, B = connected, C = charging.  With geo filtering enabled,
    B/C are emitted only when the current vehicle coordinates are inside the
    selected local Home Assistant zone radius. Missing zone/GPS data fails closed.
    """
    plugged = _as_bool(metrics.get("plugged")) is True
    charging = _as_bool(metrics.get("charging")) is True

    if not geo_enabled:
        status = "C" if charging else ("B" if plugged else "A")
        return EvccGeoDecision(status=status, at_site=None, distance_m=None, reason="geo_disabled")

    if not (plugged or charging):
        # No vehicle connection to expose to EVCC. Distance is still useful when
        # coordinates are present, but it must not turn the vehicle into B/C.
        if zone is None:
            return EvccGeoDecision("A", None, None, "not_plugged")
        lat = _as_float(metrics.get("latitude"))
        lon = _as_float(metrics.get("longitude"))
        if lat is None or lon is None:
            return EvccGeoDecision("A", None, None, "not_plugged")
        distance = haversine_distance_m(zone.latitude, zone.longitude, lat, lon)
        return EvccGeoDecision("A", distance <= radius_m, distance, "not_plugged")

    if zone is None:
        return EvccGeoDecision("A", None, None, "zone_unavailable")

    lat = _as_float(metrics.get("latitude"))
    lon = _as_float(metrics.get("longitude"))
    if lat is None or lon is None or not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return EvccGeoDecision("A", None, None, "gps_missing")

    distance = haversine_distance_m(zone.latitude, zone.longitude, lat, lon)
    at_site = distance <= max(1.0, float(radius_m))
    if not at_site:
        return EvccGeoDecision("A", False, distance, "outside_radius")
    if charging:
        return EvccGeoDecision("C", True, distance, "at_site_charging")
    return EvccGeoDecision("B", True, distance, "at_site_plugged")


class HomeAssistantZoneResolver:
    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout

    @staticmethod
    def _headers() -> dict[str, str]:
        token = os.getenv("SUPERVISOR_TOKEN", "").strip()
        if not token:
            return {}
        return {
            "Authorization": f"Bearer {token}",
            "X-Supervisor-Token": token,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _from_item(item: Any, entity_id: str) -> ZonePosition | None:
        if not isinstance(item, dict) or str(item.get("entity_id") or "").strip() != entity_id:
            return None
        attrs = item.get("attributes") or {}
        lat = _as_float(attrs.get("latitude"))
        lon = _as_float(attrs.get("longitude"))
        if lat is None or lon is None:
            return None
        return ZonePosition(entity_id=entity_id, latitude=lat, longitude=lon)

    def resolve(self, entity_id: str) -> ZonePosition | None:
        entity_id = str(entity_id or "zone.home").strip() or "zone.home"
        headers = self._headers()
        if not headers:
            logger.warning("EVCC Geo: SUPERVISOR_TOKEN fehlt, Home-Assistant-Zone kann nicht gelesen werden")
            return None

        encoded = quote(entity_id, safe="")
        single_urls = [
            f"http://supervisor/core/api/states/{encoded}",
            f"http://supervisor/homeassistant/api/states/{encoded}",
        ]
        for url in single_urls:
            try:
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                if resp.ok:
                    zone = self._from_item(resp.json(), entity_id)
                    if zone:
                        return zone
            except Exception:
                continue

        list_urls = [
            "http://supervisor/core/api/states",
            "http://supervisor/core/states",
            "http://supervisor/homeassistant/api/states",
        ]
        for url in list_urls:
            try:
                resp = requests.get(url, headers=headers, timeout=self.timeout)
                if not resp.ok:
                    continue
                payload = resp.json()
                items = payload if isinstance(payload, list) else payload.get("result") or payload.get("data") or payload.get("states") or []
                for item in items if isinstance(items, list) else []:
                    zone = self._from_item(item, entity_id)
                    if zone:
                        return zone
            except Exception:
                continue
        return None


class EvccGeoFilterService:
    """Local-only derived EVCC status for local and forwarded remote vehicles.

    The service subscribes to the local broker, so each Car2MQTT installation
    computes its own status against its own Home Assistant zone. Derived topics
    are published directly to the local broker and are therefore not propagated
    by Car2MQTT's forward-client pipeline.
    """

    WATCHED_KEYS = {"plugged", "charging", "latitude", "longitude"}

    def __init__(
        self,
        config_loader: Callable[[], AppConfig],
        mqtt_settings_loader: Callable[[], RuntimeMqttSettings],
        zone_resolver: HomeAssistantZoneResolver | None = None,
        zone_entity_loader: Callable[[AppConfig], str] | None = None,
    ) -> None:
        self.config_loader = config_loader
        self.mqtt_settings_loader = mqtt_settings_loader
        self.zone_resolver = zone_resolver or HomeAssistantZoneResolver()
        self.zone_entity_loader = zone_entity_loader
        self._client: mqtt.Client | None = None
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._zone: ZonePosition | None = None
        self._zone_entity_id = "zone.home"
        self._geo_enabled = False
        self._radius_m = 30.0
        self._zone_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._mqtt_settings: RuntimeMqttSettings | None = None

    def _load_feature_settings(self) -> None:
        cfg = self.config_loader()
        ui = cfg.ui_settings
        self._geo_enabled = bool(getattr(ui, "evcc_geo_filter_enabled", False))
        self._radius_m = max(1.0, float(getattr(ui, "evcc_geo_radius_m", 30.0) or 30.0))
        if self.zone_entity_loader is not None:
            resolved_entity = self.zone_entity_loader(cfg)
        else:
            resolved_entity = str(getattr(ui, "helper_home_zone_entity_id", "") or "zone.home")
        self._zone_entity_id = str(resolved_entity or "zone.home").strip() or "zone.home"

    def _refresh_zone(self) -> None:
        self._load_feature_settings()
        zone = self.zone_resolver.resolve(self._zone_entity_id) if self._geo_enabled else None
        with self._lock:
            self._zone = zone
        if self._geo_enabled:
            if zone:
                logger.info(
                    "EVCC Geo: Zone %s geladen (%.6f, %.6f), Radius %.1f m",
                    zone.entity_id,
                    zone.latitude,
                    zone.longitude,
                    self._radius_m,
                )
            else:
                logger.warning("EVCC Geo: Zone %s nicht verfügbar; Status fällt sicher auf A zurück", self._zone_entity_id)
        self._republish_all()

    def _zone_refresh_loop(self) -> None:
        while not self._stop_event.wait(60.0):
            try:
                self._refresh_zone()
            except Exception:
                logger.exception("EVCC Geo: Zonenaktualisierung fehlgeschlagen")

    def start(self) -> None:
        if self._running:
            return
        settings = self.mqtt_settings_loader()
        if not settings.host:
            logger.info("EVCC Geo: kein MQTT Host gesetzt, Dienst nicht gestartet")
            return
        self._mqtt_settings = settings
        self._load_feature_settings()
        if self._geo_enabled:
            self._zone = self.zone_resolver.resolve(self._zone_entity_id)
        else:
            self._zone = None

        client = mqtt.Client(client_id=f"car2mqtt-evcc-geo-{uuid.uuid4().hex[:8]}")
        if settings.username:
            client.username_pw_set(settings.username, settings.password)
        if settings.tls:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.connect(settings.host, settings.port, 30)
        client.loop_start()
        self._client = client
        self._running = True
        self._stop_event.clear()
        self._zone_thread = threading.Thread(target=self._zone_refresh_loop, name="car2mqtt-evcc-geo-zone", daemon=True)
        self._zone_thread.start()
        logger.info(
            "EVCC Geo: lokaler Filter gestartet (geo=%s, zone=%s, radius=%.1fm)",
            self._geo_enabled,
            self._zone_entity_id,
            self._radius_m,
        )

    def stop(self) -> None:
        self._stop_event.set()
        client = self._client
        self._client = None
        self._running = False
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass
        thread = self._zone_thread
        self._zone_thread = None
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def restart(self) -> None:
        self.stop()
        self.start()

    def _on_connect(self, client, _userdata, _flags, rc, _properties=None) -> None:
        if rc != 0 or not self._mqtt_settings:
            logger.warning("EVCC Geo: MQTT connect rc=%s", rc)
            return
        base = str(self._mqtt_settings.base_topic or "car").strip("/") or "car"
        client.subscribe(f"{base}/+/+/mapped/+", qos=0)

    def _on_disconnect(self, _client, _userdata, rc, _properties=None) -> None:
        if rc:
            logger.warning("EVCC Geo: MQTT Verbindung getrennt (rc=%s)", rc)

    def _parse_topic(self, topic: str) -> tuple[str, str] | None:
        settings = self._mqtt_settings
        if not settings:
            return None
        base = str(settings.base_topic or "car").strip("/") or "car"
        prefix = base + "/"
        if not topic.startswith(prefix):
            return None
        parts = topic[len(prefix):].split("/")
        if len(parts) != 4 or parts[2] != "mapped":
            return None
        key = parts[3]
        if key not in self.WATCHED_KEYS:
            return None
        root = f"{base}/{parts[0]}/{parts[1]}/mapped"
        return root, key

    def _on_message(self, _client, _userdata, msg) -> None:
        parsed = self._parse_topic(str(msg.topic or ""))
        if not parsed:
            return
        root, key = parsed
        value = parse_mqtt_scalar(msg.payload)
        with self._lock:
            snapshot = self._snapshots.setdefault(root, {})
            snapshot[key] = value
            current = dict(snapshot)
        self._publish_decision(root, current)

    @staticmethod
    def _mqtt_payload(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _publish_decision(self, root: str, metrics: dict[str, Any]) -> None:
        client = self._client
        if client is None:
            return
        with self._lock:
            zone = self._zone
            geo_enabled = self._geo_enabled
            radius_m = self._radius_m
        decision = calculate_evcc_geo_decision(metrics, geo_enabled=geo_enabled, zone=zone, radius_m=radius_m)
        payloads: dict[str, Any] = {
            "evccStatus": decision.status,
            "evccAtSite": decision.at_site if decision.at_site is not None else False,
            "evccDistance": round(decision.distance_m, 1) if decision.distance_m is not None else "unknown",
            "evccGeoReason": decision.reason,
        }
        for key, value in payloads.items():
            client.publish(f"{root}/{key}", self._mqtt_payload(value), qos=1, retain=True)

    def _republish_all(self) -> None:
        with self._lock:
            snapshots = [(root, dict(metrics)) for root, metrics in self._snapshots.items()]
        for root, metrics in snapshots:
            self._publish_decision(root, metrics)

    def status(self) -> dict[str, Any]:
        with self._lock:
            zone = self._zone
            return {
                "running": self._running,
                "geo_filter_enabled": self._geo_enabled,
                "zone_entity_id": self._zone_entity_id,
                "zone_available": zone is not None,
                "zone_latitude": zone.latitude if zone else None,
                "zone_longitude": zone.longitude if zone else None,
                "radius_m": self._radius_m,
                "vehicles_seen": len(self._snapshots),
            }
