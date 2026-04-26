from __future__ import annotations
import json, re
from typing import Any
from app.core.models import AppConfig, VehicleConfig, RuntimeMqttSettings
from app.mqtt.client import LocalMqttClient
from app.mqtt.topic_builder import mapped_topic, normalize_plate

def _slug(value: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip().lower())
    return raw.strip("_") or "vehicle"

def _entity_slug(vehicle: VehicleConfig) -> str:
    return f"car2mqtt_{_slug(vehicle.manufacturer)}_{_slug(normalize_plate(vehicle.license_plate) or vehicle.id)}"

def _device(vehicle: VehicleConfig) -> dict[str, Any]:
    return {"identifiers":[f"car2mqtt_{vehicle.id}"],"manufacturer":str(vehicle.manufacturer).upper(),"name":vehicle.label,"model":str((vehicle.provider_config or {}).get("model") or "Vehicle"),"sw_version":"car2mqtt"}

def _topic(prefix: str, component: str, uid: str) -> str:
    return f"{prefix.rstrip('/')}/{component}/{uid}/config"

def build_discovery_configs(vehicle: VehicleConfig, settings: RuntimeMqttSettings, discovery_prefix: str="homeassistant") -> list[tuple[str, dict[str, Any]]]:
    root = mapped_topic(settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
    base = _entity_slug(vehicle); dev = _device(vehicle); configs=[]
    def add_sensor(key,name,unit="",device_class="",state_class="",icon=""):
        uid=f"{base}_{key}"; cfg={"name":name,"unique_id":uid,"state_topic":f"{root}/{key}","device":dev}
        if unit: cfg["unit_of_measurement"]=unit
        if device_class: cfg["device_class"]=device_class
        if state_class: cfg["state_class"]=state_class
        if icon: cfg["icon"]=icon
        configs.append((_topic(discovery_prefix,"sensor",uid),cfg))
    def add_binary(key,name,device_class="",icon=""):
        uid=f"{base}_{key}"; cfg={"name":name,"unique_id":uid,"state_topic":f"{root}/{key}","payload_on":"true","payload_off":"false","device":dev}
        if device_class: cfg["device_class"]=device_class
        if icon: cfg["icon"]=icon
        configs.append((_topic(discovery_prefix,"binary_sensor",uid),cfg))
    def add_number(key,name,min_v=0,max_v=100,step=1,unit="%"):
        uid=f"{base}_{key}_set"; cfg={"name":name,"unique_id":uid,"state_topic":f"{root}/{key}","command_topic":f"{root}/{key}/set","min":min_v,"max":max_v,"step":step,"unit_of_measurement":unit,"mode":"slider","device":dev}
        configs.append((_topic(discovery_prefix,"number",uid),cfg))
    def add_button(key,name,command):
        uid=f"{base}_{key}"; cfg={"name":name,"unique_id":uid,"command_topic":f"{settings.base_topic}/{vehicle.manufacturer}/{normalize_plate(vehicle.license_plate)}/_cmd/{command}","payload_press":"PRESS","device":dev}
        configs.append((_topic(discovery_prefix,"button",uid),cfg))
    for key,name,unit,dc,sc,icon in [
        ("soc","SoC","%","battery","measurement",""),("range","Reichweite","km","distance","measurement",""),("odometer","Kilometerstand","km","distance","total_increasing",""),("limitSoc","Ladelimit","%","battery","measurement",""),("capacityKwh","Akkukapazität","kWh","energy","measurement",""),("fuelLevel","Tankstand","%","","measurement","mdi:gas-station"),("fuelRange","Tankreichweite","km","distance","measurement",""),("vehicleType","Antrieb","","","","mdi:car-info"),("latitude","Latitude","","","","mdi:latitude"),("longitude","Longitude","","","","mdi:longitude"),("plugged_ts","Angesteckt Zeitstempel","","timestamp","",""),("latitude_ts","Latitude Zeitstempel","","timestamp","",""),("longitude_ts","Longitude Zeitstempel","","timestamp","","")]: add_sensor(key,name,unit,dc,sc,icon)
    add_binary("charging","Lädt","battery_charging"); add_binary("plugged","Angesteckt","plug"); add_binary("connected","Verbunden","connectivity"); add_binary("doorsLocked","Türen verriegelt","lock"); add_binary("windowsOpen","Fenster offen","window")
    add_number("limitSoc","Ladelimit setzen",40,100,1,"%")
    add_button("refresh","Aktualisieren","refresh"); add_button("wake","Aufwecken","wake"); add_button("lock","Verriegeln","lock"); add_button("unlock","Entriegeln","unlock")
    uid=f"{base}_tracker"; configs.append((_topic(discovery_prefix,"device_tracker",uid),{"name":f"{vehicle.label} Standort","unique_id":uid,"json_attributes_topic":f"{root}/device_tracker","state_topic":f"{root}/device_tracker/state","source_type":"gps","device":dev}))
    return configs

def publish_vehicle_discovery(vehicle: VehicleConfig, settings: RuntimeMqttSettings, *, discovery_prefix="homeassistant", retain=True) -> int:
    if not settings.host: raise RuntimeError("MQTT Host ist nicht gesetzt")
    client=LocalMqttClient(settings); count=0
    try:
        client.connect()
        for topic,cfg in build_discovery_configs(vehicle,settings,discovery_prefix): client.publish(topic,json.dumps(cfg,ensure_ascii=False),retain=retain,qos=1); count+=1
    finally: client.disconnect()
    return count

def clear_vehicle_discovery(vehicle: VehicleConfig, settings: RuntimeMqttSettings, *, discovery_prefix="homeassistant") -> int:
    if not settings.host: return 0
    client=LocalMqttClient(settings); count=0
    try:
        client.connect()
        for topic,_ in build_discovery_configs(vehicle,settings,discovery_prefix): client.publish(topic,"",retain=True,qos=1); count+=1
    finally: client.disconnect()
    return count

def publish_all_discovery(config: AppConfig, settings: RuntimeMqttSettings) -> int:
    ui=config.ui_settings
    if not getattr(ui,"ha_discovery_enabled",True): return 0
    return sum(publish_vehicle_discovery(v,settings,discovery_prefix=ui.ha_discovery_prefix or "homeassistant",retain=bool(ui.ha_discovery_retain)) for v in config.vehicles if v.enabled)
