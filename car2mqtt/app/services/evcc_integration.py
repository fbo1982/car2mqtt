from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from app.core.models import RuntimeMqttSettings, VehicleConfig
from app.mqtt.topic_builder import mapped_topic, normalize_plate


def _slug(value: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(value or "").strip().lower())
    return raw.strip("_") or "car2mqtt_vehicle"


def _unwrap(payload: Any) -> Any:
    # evcc removed the outer result wrapper in newer versions, but older versions still used it.
    if isinstance(payload, dict) and "result" in payload and len(payload) <= 2:
        return payload.get("result")
    return payload


def _as_bool_auth(value: Any) -> bool | None:
    """Interpret the flexible /api/auth/status responses seen across evcc versions."""
    value = _unwrap(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for key in ("authorized", "authenticated", "auth", "loggedIn", "logged_in", "ok"):
            if key in value:
                return bool(value.get(key))
        # Some versions return {"status": true} or {"result": true}.
        if "status" in value and isinstance(value.get("status"), bool):
            return bool(value.get("status"))
    return None


def _evcc_id_from_ref(ref: str) -> str:
    """Return the numeric config id required by /api/config/devices/<class>/<id>."""
    ref = str(ref or "").strip()
    m = re.match(r"^db:(\d+(?:\.\d+)?)$", ref, re.I)
    if m:
        return m.group(1)
    if re.match(r"^\d+(?:\.\d+)?$", ref):
        return ref
    return ""


def _evcc_name_from_item(item: dict[str, Any], fallback: str = "") -> str:
    if item.get("name"):
        return str(item.get("name"))
    if item.get("id") not in (None, ""):
        return f"db:{item.get('id')}"
    return fallback


def _evcc_onidentify_mode(cfg: dict[str, Any]) -> str:
    mode = str(cfg.get("evcc_onidentify_mode") or cfg.get("onidentify_mode") or "off").strip().lower()
    aliases = {
        "aus": "off", "off": "off",
        "pv": "pv",
        "min+pv": "minpv", "minpv": "minpv", "min_pv": "minpv", "min-pv": "minpv",
        "schnell": "now", "now": "now",
    }
    return aliases.get(mode, "off")


def build_evcc_vehicle_name(vehicle: VehicleConfig) -> str:
    return f"car2mqtt_{_slug(vehicle.manufacturer)}_{_slug(normalize_plate(vehicle.license_plate) or vehicle.id)}"



def _yaml_scalar(value: Any) -> str:
    text = str(value if value is not None else "")
    if re.match(r"^[A-Za-z0-9_.:/@+-]+$", text):
        return text
    return '"' + text.replace('\\', '\\\\').replace('\"', '\\"') + '"'


def evcc_payload_to_yaml(payload: dict[str, Any]) -> str:
    """Render a YAML fragment for evcc user-defined custom vehicles.

    This mirrors the configuration EVCC's Benutzerdefiniertes Gerät editor
    expects. Custom vehicles need the MQTT plugin blocks to actually read data.
    """
    lines: list[str] = []
    for key in ("name", "title", "type", "icon", "capacity", "phases"):
        if key in payload and payload.get(key) not in (None, ""):
            lines.append(f"{key}: {_yaml_scalar(payload.get(key))}")
    if payload.get("identifiers"):
        lines.append("identifiers:")
        for item in payload.get("identifiers") or []:
            lines.append(f"  - {_yaml_scalar(item)}")
    for key in ("soc", "range", "odometer", "limitsoc"):
        cfg = payload.get(key)
        if isinstance(cfg, dict) and cfg.get("source") and cfg.get("topic"):
            lines.append(f"{key}:")
            lines.append(f"  source: {_yaml_scalar(cfg.get('source'))}")
            lines.append(f"  topic: {_yaml_scalar(cfg.get('topic'))}")
            if cfg.get("timeout"):
                lines.append(f"  timeout: {_yaml_scalar(cfg.get('timeout'))}")
    oi = payload.get("onIdentify")
    if isinstance(oi, dict) and oi.get("mode"):
        lines.append("onIdentify:")
        lines.append(f"  mode: {_yaml_scalar(oi.get('mode'))}")
    status = payload.get("status")
    if isinstance(status, dict):
        lines.append("status:")
        lines.append(f"  source: {_yaml_scalar(status.get('source') or 'combined')}")
        for key in ("plugged", "charging"):
            cfg = status.get(key)
            if isinstance(cfg, dict) and cfg.get("source") and cfg.get("topic"):
                lines.append(f"  {key}:")
                lines.append(f"    source: {_yaml_scalar(cfg.get('source'))}")
                lines.append(f"    topic: {_yaml_scalar(cfg.get('topic'))}")
                if cfg.get("timeout"):
                    lines.append(f"    timeout: {_yaml_scalar(cfg.get('timeout'))}")
    return "\n".join(lines) + "\n"

def build_evcc_custom_vehicle_payload(vehicle: VehicleConfig, mqtt_settings: RuntimeMqttSettings, mapped_root: str | None = None) -> dict[str, Any]:
    root = (mapped_root or mapped_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)).rstrip("/")
    cfg = vehicle.provider_config or {}
    try:
        cap = float(str(cfg.get("capacity_kwh") or cfg.get("capacityKwh") or "0") or 0)
    except Exception:
        cap = 0

    # Keep this intentionally close to evcc's documented YAML syntax for
    # custom MQTT vehicles. User-defined devices in EVCC need the MQTT plugin
    # blocks; the API sync below sends this either as native custom payload or
    # as the YAML text used by EVCC's custom-device editor.
    timeout = str(cfg.get("evcc_timeout") or "24h")
    payload: dict[str, Any] = {
        "name": str(cfg.get("evcc_name") or build_evcc_vehicle_name(vehicle)),
        "title": str(cfg.get("evcc_title") or vehicle.label or vehicle.license_plate),
        "type": "custom",
        "icon": str(cfg.get("evcc_icon") or "car"),
        "capacity": cap,
        "soc": {"source": "mqtt", "topic": f"{root}/soc", "timeout": timeout},
        "range": {"source": "mqtt", "topic": f"{root}/range", "timeout": timeout},
        "odometer": {"source": "mqtt", "topic": f"{root}/odometer", "timeout": timeout},
        "limitsoc": {"source": "mqtt", "topic": f"{root}/limitSoc", "timeout": timeout},
        "status": {
            "source": "combined",
            "plugged": {"source": "mqtt", "topic": f"{root}/plugged", "timeout": timeout},
            "charging": {"source": "mqtt", "topic": f"{root}/charging", "timeout": timeout},
        },
        "onIdentify": {"mode": _evcc_onidentify_mode(cfg)},
    }
    phases = str(cfg.get("evcc_phases") or cfg.get("phases") or "").strip()
    if phases:
        try:
            payload["phases"] = int(phases)
        except Exception:
            payload["phases"] = phases
    identifiers_raw = cfg.get("evcc_identifiers") or cfg.get("identifiers") or ""
    identifiers = identifiers_raw if isinstance(identifiers_raw, list) else re.split(r"[\n,;]+", str(identifiers_raw or ""))
    identifiers = [str(x).strip() for x in identifiers if str(x).strip()]
    if identifiers:
        payload["identifiers"] = identifiers
    return payload


def build_evcc_config_device_payload(custom_payload: dict[str, Any]) -> dict[str, Any]:
    """Convert car2mqtt's YAML-style custom vehicle into evcc Config UI device JSON.

    Note: evcc 0.30x accepts native `type: custom` vehicles in YAML-like form
    for the vehicle factory, but the guided Config UI endpoints primarily work
    with template devices. We keep this helper for template-compatible fallback
    attempts, while custom MQTT vehicles are sent flat first.
    """
    cfg = dict(custom_payload or {})
    device_type = str(cfg.pop("type", "custom") or "custom")
    return {"type": device_type, "config": cfg}




def build_evcc_config_api_vehicle_payload(custom_payload: dict[str, Any]) -> dict[str, Any]:
    """Conservative payload for evcc DB/UI Config API.

    The full car2mqtt EVCC helper contains MQTT plugin blocks (soc, range,
    odometer, limitsoc). EVCC 0.30x rejects those blocks on the DB/UI Config
    API for custom vehicle updates with errors like "config template not found"
    or plugin.Config decode failures. For API sync we only send EVCC vehicle
    metadata. The MQTT values are still published by car2mqtt and the full YAML
    helper is still available separately.
    """
    src = dict(custom_payload or {})
    out: dict[str, Any] = {
        "type": "custom",
        "name": str(src.get("name") or ""),
        "title": str(src.get("title") or src.get("name") or ""),
        "icon": str(src.get("icon") or "car"),
    }
    if src.get("capacity") not in (None, "", 0, 0.0):
        out["capacity"] = src.get("capacity")
    if src.get("phases") not in (None, ""):
        out["phases"] = src.get("phases")
    if src.get("identifiers"):
        out["identifiers"] = src.get("identifiers")
    oi = src.get("onIdentify")
    if isinstance(oi, dict) and oi.get("mode"):
        out["onIdentify"] = {"mode": str(oi.get("mode"))}
    if not out.get("name"):
        out.pop("name", None)
    return out


def build_evcc_custom_vehicle_payload_from_card(card: dict[str, Any], mqtt_settings: RuntimeMqttSettings, link_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(card.get("evcc_config") or {})
    cfg.update(dict(link_cfg or {}))
    metrics = card.get("metrics") or {}
    if metrics.get("capacityKwh") not in (None, "") and not cfg.get("capacity_kwh"):
        cfg["capacity_kwh"] = metrics.get("capacityKwh")
    if cfg.get("evcc_title") in (None, ""):
        cfg["evcc_title"] = card.get("label") or card.get("license_plate") or "car2mqtt Fahrzeug"
    vehicle = VehicleConfig(
        id=str(card.get("id") or ""),
        label=str(card.get("label") or card.get("license_plate") or "Remote Fahrzeug"),
        manufacturer=str(card.get("manufacturer") or "").lower(),
        license_plate=str(card.get("license_plate") or ""),
        enabled=True,
        provider_config=cfg,
        device_tracker_enabled=bool(card.get("device_tracker_enabled", False)),
    )
    return build_evcc_custom_vehicle_payload(vehicle, mqtt_settings, str(card.get("mapped_topic") or "").rstrip("/") or None)


@dataclass
class EvccClient:
    base_url: str
    password: str = ""
    timeout: int = 8

    def __post_init__(self):
        self.base_url = (self.base_url or "").rstrip("/")
        self.session = requests.Session()
        self._auth_checked = False
        if self.password:
            self.login()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api" + (path if path.startswith("/") else "/" + path)

    def _parse_response(self, r: requests.Response) -> Any:
        if not r.text:
            return None
        try:
            return _unwrap(r.json())
        except Exception:
            return r.text

    def login(self) -> None:
        r = self.session.post(self._url("/auth/login"), json={"password": self.password}, timeout=self.timeout)
        if r.status_code not in (200, 204):
            raise RuntimeError(f"EVCC Login fehlgeschlagen ({r.status_code}): {r.text[:200]}")
        self._auth_checked = True

    def auth_status(self) -> bool | None:
        try:
            r = self.session.get(self._url("/auth/status"), timeout=self.timeout)
            if not r.ok:
                return None
            return _as_bool_auth(self._parse_response(r))
        except Exception:
            return None

    def ensure_config_auth(self) -> None:
        if self._auth_checked:
            return
        status = self.auth_status()
        if status is True:
            self._auth_checked = True
            return
        if self.password:
            self.login()
            return
        if status is False:
            raise RuntimeError("EVCC erfordert eine Anmeldung. Bitte in den car2mqtt-Einstellungen das EVCC Passwort eintragen und speichern.")
        # Unknown auth status: allow one request; request() will report 401 clearly.
        self._auth_checked = True

    def get(self, path: str, auth: bool = False) -> Any:
        if auth or path.startswith("/config"):
            self.ensure_config_auth()
        r = self.session.get(self._url(path), timeout=self.timeout)
        if not r.ok:
            if r.status_code == 401:
                raise RuntimeError("EVCC meldet Unauthorized (401). Bitte EVCC Passwort in car2mqtt eintragen oder prüfen.")
            raise RuntimeError(f"GET {path} fehlgeschlagen ({r.status_code}): {r.text[:200]}")
        return self._parse_response(r)

    def request(self, method: str, path: str, payload: Any | None = None, auth: bool = False) -> Any:
        if auth or path.startswith("/config"):
            self.ensure_config_auth()
        r = self.session.request(method.upper(), self._url(path), json=payload, timeout=self.timeout)
        if not r.ok:
            if r.status_code == 401:
                raise RuntimeError(f"{method.upper()} {path} fehlgeschlagen (401): EVCC Passwort fehlt oder ist falsch.")
            raise RuntimeError(f"{method.upper()} {path} fehlgeschlagen ({r.status_code}): {r.text[:300]}")
        return self._parse_response(r)

    def status(self) -> dict[str, Any]:
        data = self.get("/state")
        return data if isinstance(data, dict) else {"state": data}

    def _append_vehicle_items(self, out: list[dict[str, Any]], data: Any) -> None:
        def add(ref: Any, title: Any, raw: Any, path_id: Any = None) -> None:
            ref_s = str(ref or "").strip()
            title_s = str(title or ref_s or "").strip()
            if ref_s and not any(v.get("ref") == ref_s for v in out):
                item = {"ref": ref_s, "name": ref_s, "title": title_s, "raw": raw}
                if path_id not in (None, ""):
                    item["id"] = str(path_id)
                out.append(item)

        data = _unwrap(data)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    ref = _evcc_name_from_item(item)
                    cfg = item.get("config") if isinstance(item.get("config"), dict) else {}
                    title = item.get("title") or cfg.get("title") or item.get("deviceProduct") or ref
                    add(ref, title, item, item.get("id"))
                elif item:
                    add(item, item, item)
        elif isinstance(data, dict):
            for key in ("vehicles", "vehicle", "items", "devices", "result"):
                if key in data and data.get(key) is not data:
                    self._append_vehicle_items(out, data.get(key))
            for key, item in data.items():
                if key in ("vehicles", "vehicle", "items", "devices", "result"):
                    continue
                if isinstance(item, dict):
                    ref = _evcc_name_from_item(item, str(key))
                    cfg = item.get("config") if isinstance(item.get("config"), dict) else {}
                    title = item.get("title") or cfg.get("title") or item.get("deviceProduct") or key
                    if any(k in item for k in ("name", "title", "vehicle", "id", "instance", "config", "type")):
                        add(ref, title, item, item.get("id"))
                elif str(key).startswith("db:"):
                    add(key, item or key, {key: item}, _evcc_id_from_ref(str(key)))

    def list_vehicles(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            self._append_vehicle_items(out, self.get("/config/devices/vehicle", auth=True))
            if out:
                return out
        except Exception:
            pass
        try:
            state = self.status()
            self._append_vehicle_items(out, state.get("vehicles", []) if isinstance(state, dict) else [])
            if isinstance(state, dict):
                for lp in state.get("loadpoints", []) or []:
                    if isinstance(lp, dict) and (lp.get("vehicleName") or lp.get("vehicle")):
                        self._append_vehicle_items(out, [{
                            "name": lp.get("vehicleName") or lp.get("vehicle"),
                            "title": lp.get("vehicleTitle") or lp.get("vehicleName") or lp.get("vehicle"),
                            "loadpoint": lp.get("title") or lp.get("name"),
                        }])
        except Exception:
            pass
        return out

    def _vehicle_request_candidates(self, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Payload variants for EVCC vehicle config API.

        EVCC versions differ here: template devices are JSON forms, while
        user-defined/custom devices are edited as YAML in the web UI. Try the
        YAML-editor shape first, then native custom JSON. This keeps the full
        working custom configuration (soc/range/odometer/limitsoc/status).
        """
        full = dict(payload or {})
        yaml_text = evcc_payload_to_yaml(full)
        return [
            ("custom-yaml-config", {"type": "custom", "config": yaml_text}),
            ("custom-yaml-yaml", {"type": "custom", "yaml": yaml_text}),
            ("custom-yaml-value", {"type": "custom", "value": yaml_text}),
            ("custom-json-flat", full),
            ("custom-json-wrapped", build_evcc_config_device_payload(full)),
            ("custom-metadata", build_evcc_config_api_vehicle_payload(full)),
        ]

    def upsert_vehicle(self, payload: dict[str, Any], evcc_ref: str = "") -> dict[str, Any]:
        ref = str(evcc_ref or "").strip()
        path_id = _evcc_id_from_ref(ref)
        errors: list[str] = []

        if path_id:
            for label, candidate in self._vehicle_request_candidates(payload):
                try:
                    res = self.request("PUT", f"/config/devices/vehicle/{quote(path_id, safe='')}", candidate, auth=True)
                    return {"action": "updated", "ref": f"db:{path_id}", "variant": label, "response": res}
                except Exception as exc:
                    errors.append(f"{label}: {exc}")

            # Sicherheitsregel: Wenn ein bestehendes EVCC-Fahrzeug verknüpft ist,
            # darf car2mqtt bei fehlgeschlagenem Update NICHT heimlich ein Ersatz-
            # fahrzeug anlegen. Die Zuordnung bleibt erhalten und der Nutzer sieht
            # den konkreten EVCC-Fehler.
            raise RuntimeError("EVCC Fahrzeug konnte nicht aktualisiert werden. Es wurde kein neues Fahrzeug angelegt. " + " | ".join(errors[-6:]))

        for label, candidate in self._vehicle_request_candidates(payload):
            try:
                res = self.request("POST", "/config/devices/vehicle", candidate, auth=True)
                new_id = self._extract_created_vehicle_ref(res, payload)
                return {"action": "created", "ref": new_id or ref or str(payload.get("name") or ""), "variant": label, "response": res}
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        raise RuntimeError("EVCC Fahrzeug konnte nicht angelegt/aktualisiert werden. " + " | ".join(errors[-6:]))

    def _extract_created_vehicle_ref(self, res: Any, payload: dict[str, Any]) -> str:
        new_id = ""
        if isinstance(res, dict):
            new_id = str(res.get("name") or (f"db:{res.get('id')}" if res.get("id") not in (None, "") else "") or res.get("instance") or "")
        if not new_id:
            title = str(payload.get("title") or "")
            name = str(payload.get("name") or "")
            for item in self.list_vehicles():
                raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
                cfg = raw.get("config") if isinstance(raw.get("config"), dict) else {}
                if title and (item.get("title") == title or cfg.get("title") == title):
                    new_id = str(item.get("ref") or "")
                    break
                if name and (cfg.get("name") == name or item.get("name") == name):
                    new_id = str(item.get("ref") or "")
                    break
        return new_id

    def delete_vehicle(self, evcc_ref: str) -> dict[str, Any]:
        path_id = _evcc_id_from_ref(evcc_ref)
        if not path_id:
            return {"action": "skipped", "message": "Keine gültige EVCC-DB-ID gespeichert. Erwartet z. B. db:19."}
        return {"action": "deleted", "ref": f"db:{path_id}", "response": self.request("DELETE", f"/config/devices/vehicle/{quote(path_id, safe='')}", auth=True)}
