from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any
import requests
from app.core.models import VehicleConfig, RuntimeMqttSettings
from app.mqtt.topic_builder import mapped_topic, normalize_plate

def _slug(value: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(value or "").strip().lower())
    return raw.strip("_") or "car2mqtt_vehicle"

def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "result" in payload and len(payload) <= 2:
        return payload.get("result")
    return payload

def build_evcc_vehicle_name(vehicle: VehicleConfig) -> str:
    return f"car2mqtt_{_slug(vehicle.manufacturer)}_{_slug(normalize_plate(vehicle.license_plate) or vehicle.id)}"

def build_evcc_custom_vehicle_payload(vehicle: VehicleConfig, mqtt_settings: RuntimeMqttSettings, mapped_root: str | None = None) -> dict[str, Any]:
    root=(mapped_root or mapped_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)).rstrip('/')
    cfg=vehicle.provider_config or {}
    try:
        cap=float(str(cfg.get("capacity_kwh") or cfg.get("capacityKwh") or "0") or 0)
    except Exception:
        cap=0
    return {
        "name":str(cfg.get("evcc_name") or build_evcc_vehicle_name(vehicle)),
        "title":str(cfg.get("evcc_title") or vehicle.label or vehicle.license_plate),
        "type":"custom",
        "icon":str(cfg.get("evcc_icon") or "car"),
        "capacity":cap,
        "phases":int(cfg.get("evcc_phases") or 3),
        "identifiers":[normalize_plate(vehicle.license_plate) or vehicle.id],
        "soc":{"source":"mqtt","topic":f"{root}/soc","timeout":"24h"},
        "range":{"source":"mqtt","topic":f"{root}/range","timeout":"24h"},
        "odometer":{"source":"mqtt","topic":f"{root}/odometer","timeout":"24h"},
        "limitsoc":{"source":"mqtt","topic":f"{root}/limitSoc","timeout":"24h"},
        "status":{"source":"combined","plugged":{"source":"mqtt","topic":f"{root}/plugged","timeout":"24h"},"charging":{"source":"mqtt","topic":f"{root}/charging","timeout":"24h"}},
        "onIdentify":{"mode":"pv"},
        "source":"car2mqtt",
        "car2mqttVehicleId":vehicle.id,
    }

def build_evcc_custom_vehicle_payload_from_card(card: dict[str, Any], mqtt_settings: RuntimeMqttSettings, link_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(link_cfg or {})
    metrics = card.get('metrics') or {}
    if metrics.get('capacityKwh') not in (None, '') and not cfg.get('capacity_kwh'):
        cfg['capacity_kwh'] = metrics.get('capacityKwh')
    if cfg.get('evcc_title') in (None, ''):
        cfg['evcc_title'] = card.get('label') or card.get('license_plate') or 'car2mqtt Fahrzeug'
    vehicle = VehicleConfig(
        id=str(card.get('id') or ''),
        label=str(card.get('label') or card.get('license_plate') or 'Remote Fahrzeug'),
        manufacturer=str(card.get('manufacturer') or '').lower(),
        license_plate=str(card.get('license_plate') or ''),
        enabled=True,
        provider_config=cfg,
        device_tracker_enabled=bool(card.get('device_tracker_enabled', False)),
    )
    return build_evcc_custom_vehicle_payload(vehicle, mqtt_settings, str(card.get('mapped_topic') or '').rstrip('/') or None)

@dataclass
class EvccClient:
    base_url: str
    password: str = ""
    timeout: int = 8
    def __post_init__(self):
        self.base_url=(self.base_url or "").rstrip("/"); self.session=requests.Session()
        if self.password: self.login()
    def _url(self,path:str)->str:
        return f"{self.base_url}/api" + (path if path.startswith("/") else "/"+path)
    def login(self):
        r=self.session.post(self._url("/auth/login"),json={"password":self.password},timeout=self.timeout)
        if r.status_code not in (200,204): raise RuntimeError(f"EVCC Login fehlgeschlagen ({r.status_code}): {r.text[:200]}")
    def get(self,path:str)->Any:
        r=self.session.get(self._url(path),timeout=self.timeout)
        if not r.ok: raise RuntimeError(f"GET {path} fehlgeschlagen ({r.status_code}): {r.text[:200]}")
        try: return _unwrap(r.json())
        except Exception: return r.text
    def request(self,method:str,path:str,payload:Any|None=None)->Any:
        r=self.session.request(method.upper(),self._url(path),json=payload,timeout=self.timeout)
        if not r.ok: raise RuntimeError(f"{method.upper()} {path} fehlgeschlagen ({r.status_code}): {r.text[:300]}")
        if not r.text: return None
        try: return _unwrap(r.json())
        except Exception: return r.text
    def status(self)->dict[str,Any]:
        data=self.get("/state"); return data if isinstance(data,dict) else {"state":data}
    def _append_vehicle_items(self, out:list[dict[str,Any]], data:Any) -> None:
        def add(ref:Any, title:Any, raw:Any):
            ref_s=str(ref or '').strip(); title_s=str(title or ref_s or '').strip()
            if ref_s and not any(v.get('ref') == ref_s for v in out):
                out.append({"ref":ref_s,"name":ref_s,"title":title_s,"raw":raw})
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    add(item.get("name") or item.get("id") or item.get("instance") or item.get("device") or item.get("ref"), item.get("title") or item.get("label") or item.get("name"), item)
                elif item:
                    add(item, item, item)
        elif isinstance(data, dict):
            for key in ("vehicles", "vehicle", "items", "devices", "result"):
                if key in data and data.get(key) is not data:
                    self._append_vehicle_items(out, data.get(key))
            for key, item in data.items():
                if isinstance(item, dict) and key not in ("vehicles", "vehicle", "items", "devices", "result"):
                    if any(k in item for k in ("name", "title", "vehicle", "id", "instance")):
                        ref = item.get("name") or item.get("id") or item.get("instance") or item.get("vehicle") or key
                        add(ref, item.get("title") or item.get("label") or item.get("name") or key, item)
                elif str(key).startswith('db:'):
                    add(key, item or key, {key:item})
    def list_vehicles(self)->list[dict[str,Any]]:
        out=[]
        for path in ("/config/devices/vehicle", "/config/devices/vehicle/"):
            try:
                self._append_vehicle_items(out, self.get(path))
                if out: return out
            except Exception:
                pass
        try:
            state=self.status()
            self._append_vehicle_items(out, state.get("vehicles", []) if isinstance(state,dict) else [])
            if isinstance(state, dict):
                for lp in state.get('loadpoints', []) or []:
                    if isinstance(lp, dict) and (lp.get('vehicleName') or lp.get('vehicle')):
                        self._append_vehicle_items(out, [{"name": lp.get('vehicleName') or lp.get('vehicle'), "title": lp.get('vehicleTitle') or lp.get('vehicleName') or lp.get('vehicle'), "loadpoint": lp.get('title') or lp.get('name')}])
        except Exception:
            pass
        return out
    def upsert_vehicle(self,payload:dict[str,Any],evcc_ref:str="")->dict[str,Any]:
        ref=str(evcc_ref or payload.get("name") or "").strip(); errors=[]
        if ref:
            for method,path in (("PUT",f"/config/devices/vehicle/{ref}"),("PATCH",f"/config/devices/vehicle/{ref}")):
                try: return {"action":"updated","ref":ref,"response":self.request(method,path,payload)}
                except Exception as exc: errors.append(str(exc))
        for method,path in (("POST","/config/devices/vehicle"),("PUT",f"/config/devices/vehicle/{payload.get('name','')}") ):
            try:
                res=self.request(method,path,payload); new_ref=ref or str((res or {}).get("name") or (res or {}).get("id") or (res or {}).get("instance") or payload.get("name") or "")
                return {"action":"created","ref":new_ref,"response":res}
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError("EVCC Fahrzeug konnte nicht angelegt/aktualisiert werden. "+" | ".join(errors[-4:]))
    def delete_vehicle(self,evcc_ref:str)->dict[str,Any]:
        ref=str(evcc_ref or "").strip()
        if not ref: return {"action":"skipped","message":"Keine EVCC-ID gespeichert"}
        return {"action":"deleted","ref":ref,"response":self.request("DELETE",f"/config/devices/vehicle/{ref}")}
