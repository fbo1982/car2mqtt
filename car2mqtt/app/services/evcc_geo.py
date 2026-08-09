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
    exit_radius_m: float | None = None,
    previous_at_site: bool | None = None,
) -> EvccGeoDecision:
    """Calculate the EVCC A/B/C status without modifying manufacturer metrics.

    A = disconnected, B = connected, C = charging. With geo filtering enabled,
    B/C are emitted only when the current vehicle coordinates are inside the
    selected local Home Assistant zone. Presence uses hysteresis: a vehicle
    enters at ``radius_m`` and leaves only beyond ``exit_radius_m``. Missing
    zone/GPS data fails closed for EVCC status but returns ``at_site=None`` so
    external relay automation does not act on an unknown position.
    """
    plugged = _as_bool(metrics.get("plugged")) is True
    charging = _as_bool(metrics.get("charging")) is True

    if not geo_enabled:
        status = "C" if charging else ("B" if plugged else "A")
        return EvccGeoDecision(status=status, at_site=None, distance_m=None, reason="geo_disabled")

    if zone is None:
        return EvccGeoDecision("A", None, None, "zone_unavailable")

    lat = _as_float(metrics.get("latitude"))
    lon = _as_float(metrics.get("longitude"))
    if lat is None or lon is None or not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return EvccGeoDecision("A", None, None, "gps_missing")

    distance = haversine_distance_m(zone.latitude, zone.longitude, lat, lon)
    enter_radius = max(1.0, float(radius_m))
    leave_radius = max(enter_radius, float(exit_radius_m if exit_radius_m is not None else enter_radius))
    threshold = leave_radius if previous_at_site is True else enter_radius
    at_site = distance <= threshold

    if not (plugged or charging):
        return EvccGeoDecision("A", at_site, distance, "not_plugged")
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
        self._exit_radius_m = 50.0
        self._presence_by_root: dict[str, bool] = {}
        self._relay_enabled = False
        self._relay_vehicle_root = ""
        self._relay_host = ""
        self._relay_switch_id = 0
        self._relay_power_off_threshold_w = 50.0
        self._relay_pending_on = False
        self._relay_pending_off = False
        self._relay_last_action = ""
        self._relay_last_error = ""
        self._relay_last_power_w: float | None = None
        self._relay_last_output: bool | None = None
        self._zone_thread: threading.Thread | None = None
        self._relay_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._mqtt_settings: RuntimeMqttSettings | None = None

    def _load_feature_settings(self) -> None:
        cfg = self.config_loader()
        ui = cfg.ui_settings
        self._geo_enabled = bool(getattr(ui, "evcc_geo_filter_enabled", False))
        self._radius_m = max(1.0, float(getattr(ui, "evcc_geo_radius_m", 30.0) or 30.0))
        self._exit_radius_m = max(
            self._radius_m,
            float(getattr(ui, "evcc_geo_exit_radius_m", 50.0) or 50.0),
        )
        self._relay_enabled = bool(getattr(ui, "geo_shelly_enabled", False))
        self._relay_vehicle_root = str(getattr(ui, "geo_shelly_vehicle_mapped_topic", "") or "").strip().rstrip("/")
        self._relay_host = str(getattr(ui, "geo_shelly_host", "") or "").strip().rstrip("/")
        self._relay_switch_id = max(0, int(getattr(ui, "geo_shelly_switch_id", 0) or 0))
        self._relay_power_off_threshold_w = max(0.0, float(getattr(ui, "geo_shelly_power_off_threshold_w", 50.0) or 50.0))
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
                    "EVCC Geo: Zone %s geladen (%.6f, %.6f), Eintritt %.1f m / Austritt %.1f m",
                    zone.entity_id,
                    zone.latitude,
                    zone.longitude,
                    self._radius_m,
                    self._exit_radius_m,
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

    def _shelly_base_url(self) -> str:
        host = str(self._relay_host or "").strip().rstrip("/")
        if not host:
            return ""
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        return host

    def _read_shelly_status(self) -> tuple[bool, float]:
        base = self._shelly_base_url()
        if not base:
            raise RuntimeError("Shelly Host fehlt")
        resp = requests.get(
            f"{base}/rpc/Switch.GetStatus",
            params={"id": self._relay_switch_id},
            timeout=3.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        output = bool(payload.get("output", False))
        power = _as_float(payload.get("apower")) or 0.0
        with self._lock:
            self._relay_last_output = output
            self._relay_last_power_w = power
        return output, power

    def _set_shelly_output(self, enabled: bool) -> None:
        base = self._shelly_base_url()
        if not base:
            raise RuntimeError("Shelly Host fehlt")
        resp = requests.get(
            f"{base}/rpc/Switch.Set",
            params={"id": self._relay_switch_id, "on": "true" if enabled else "false"},
            timeout=3.0,
        )
        resp.raise_for_status()
        with self._lock:
            self._relay_last_output = bool(enabled)
            self._relay_last_action = "on" if enabled else "off"
            self._relay_last_error = ""
        logger.info("EVCC Geo Shelly: Ausgang %s -> %s", self._relay_switch_id, "EIN" if enabled else "AUS")

    def _schedule_relay_edge(self, root: str, previous: bool | None, current: bool | None) -> None:
        with self._lock:
            if not self._relay_enabled or not self._relay_vehicle_root or root.rstrip("/") != self._relay_vehicle_root:
                return
            if current is None:
                return
            # First known inside state behaves like arrival so a service restart
            # while the vehicle is parked on-site can restore the socket. A first
            # known outside state intentionally does nothing to avoid switching
            # off a socket another vehicle may currently use.
            if current is True and previous is not True:
                self._relay_pending_off = False
                self._relay_pending_on = True
                logger.info("EVCC Geo Shelly: Ankunft erkannt für %s", root)
            elif previous is True and current is False:
                self._relay_pending_on = False
                self._relay_pending_off = True
                logger.info("EVCC Geo Shelly: Abfahrt erkannt für %s", root)

    def _process_relay_once(self) -> None:
        with self._lock:
            enabled = self._relay_enabled and self._geo_enabled
            pending_on = self._relay_pending_on
            pending_off = self._relay_pending_off
            threshold = self._relay_power_off_threshold_w
            configured = bool(self._relay_vehicle_root and self._relay_host)
        if not enabled or not configured or not (pending_on or pending_off):
            return

        output, power = self._read_shelly_status()
        if pending_on:
            if not output:
                self._set_shelly_output(True)
            with self._lock:
                self._relay_pending_on = False
            return

        if not pending_off:
            return
        if not output:
            with self._lock:
                self._relay_pending_off = False
            return
        if abs(power) > threshold:
            logger.info(
                "EVCC Geo Shelly: AUS zurückgestellt, Leistung %.1f W > %.1f W",
                power,
                threshold,
            )
            return
        self._set_shelly_output(False)
        with self._lock:
            self._relay_pending_off = False

    def _relay_control_loop(self) -> None:
        while not self._stop_event.wait(2.0):
            try:
                self._process_relay_once()
            except Exception as exc:
                with self._lock:
                    self._relay_last_error = str(exc)
                logger.warning("EVCC Geo Shelly: Steuerung fehlgeschlagen: %s", exc)

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
        with self._lock:
            self._presence_by_root = {}
            self._relay_pending_on = False
            self._relay_pending_off = False
        self._zone_thread = threading.Thread(target=self._zone_refresh_loop, name="car2mqtt-evcc-geo-zone", daemon=True)
        self._zone_thread.start()
        self._relay_thread = threading.Thread(target=self._relay_control_loop, name="car2mqtt-evcc-geo-shelly", daemon=True)
        self._relay_thread.start()
        logger.info(
            "EVCC Geo: lokaler Filter gestartet (geo=%s, zone=%s, Eintritt=%.1fm, Austritt=%.1fm, shelly=%s)",
            self._geo_enabled,
            self._zone_entity_id,
            self._radius_m,
            self._exit_radius_m,
            self._relay_enabled,
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
        threads = [self._zone_thread, self._relay_thread]
        self._zone_thread = None
        self._relay_thread = None
        for thread in threads:
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
            exit_radius_m = self._exit_radius_m
            previous_at_site = self._presence_by_root.get(root)
        decision = calculate_evcc_geo_decision(
            metrics,
            geo_enabled=geo_enabled,
            zone=zone,
            radius_m=radius_m,
            exit_radius_m=exit_radius_m,
            previous_at_site=previous_at_site,
        )
        if decision.at_site is not None:
            with self._lock:
                self._presence_by_root[root] = decision.at_site
        self._schedule_relay_edge(root, previous_at_site, decision.at_site)
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
                "exit_radius_m": self._exit_radius_m,
                "vehicles_seen": len(self._snapshots),
                "shelly": {
                    "enabled": self._relay_enabled,
                    "vehicle_mapped_topic": self._relay_vehicle_root,
                    "host": self._relay_host,
                    "switch_id": self._relay_switch_id,
                    "power_off_threshold_w": self._relay_power_off_threshold_w,
                    "pending_on": self._relay_pending_on,
                    "pending_off": self._relay_pending_off,
                    "last_action": self._relay_last_action,
                    "last_error": self._relay_last_error,
                    "last_power_w": self._relay_last_power_w,
                    "last_output": self._relay_last_output,
                },
            }
