from __future__ import annotations

from typing import Any, Dict, Optional
import json
import ssl
import time
import uuid

import paho.mqtt.client as mqtt
import yaml


def ensure_ora_runtime_config(provider_config: Dict[str, Any], mqtt_settings) -> Dict[str, Any]:
    device_id = str(provider_config.get("device_id", "")).strip() or uuid.uuid4().hex
    provider_config["device_id"] = device_id
    country = str(provider_config.get("country", "DE")).strip().upper() or "DE"

    account = {
        "AccessToken": str(provider_config.get("access_token", "")).strip(),
        "RefreshToken": str(provider_config.get("refresh_token", "")).strip(),
        "GwId": str(provider_config.get("gw_id", "")).strip(),
        "BeanId": str(provider_config.get("bean_id", "")).strip(),
    }
    mqtt = {
        "Host": mqtt_settings.host,
        "Username": mqtt_settings.username,
        "Password": mqtt_settings.password if getattr(mqtt_settings, "password_set", False) else "",
        "UseTls": bool(mqtt_settings.tls),
        "HomeAssistantDiscoveryTopic": None,
    }
    return {
        "DeviceId": device_id,
        "Country": country,
        "Account": account,
        "Mqtt": mqtt,
    }


def render_ora2mqtt_yaml(provider_config: Dict[str, Any], mqtt_settings) -> str:
    config = ensure_ora_runtime_config(provider_config, mqtt_settings)
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)


def merge_ora_tokens(provider_config: Dict[str, Any], config_yaml_path) -> Dict[str, Any]:
    import yaml
    data = yaml.safe_load(config_yaml_path.read_text(encoding="utf-8")) or {}
    account = data.get("Account", {}) or {}
    provider_config["device_id"] = data.get("DeviceId", provider_config.get("device_id", ""))
    provider_config["country"] = data.get("Country", provider_config.get("country", "DE"))
    provider_config["access_token"] = account.get("AccessToken", provider_config.get("access_token", ""))
    provider_config["refresh_token"] = account.get("RefreshToken", provider_config.get("refresh_token", ""))
    provider_config["gw_id"] = account.get("GwId", provider_config.get("gw_id", ""))
    provider_config["bean_id"] = account.get("BeanId", provider_config.get("bean_id", ""))
    return provider_config


ORA_TOKEN_KEYS = ("access_token", "refresh_token", "gw_id", "bean_id", "device_id", "country")


def has_usable_ora_tokens(provider_config: Dict[str, Any]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    access_token = str(provider_config.get("access_token", "")).strip()
    refresh_token = str(provider_config.get("refresh_token", "")).strip()
    if not access_token:
        missing.append("access_token")
    if not refresh_token:
        missing.append("refresh_token")
    return (len(missing) == 0, missing)


def extract_ora_token_bundle(provider_config: Dict[str, Any]) -> Dict[str, Any]:
    bundle: Dict[str, Any] = {}
    for key in ORA_TOKEN_KEYS:
        value = provider_config.get(key)
        if value not in (None, ""):
            bundle[key] = value
    return bundle


def apply_ora_token_bundle(provider_config: Dict[str, Any], bundle: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not bundle:
        return provider_config
    for key in ORA_TOKEN_KEYS:
        value = bundle.get(key)
        if value not in (None, ""):
            provider_config[key] = value
    return provider_config


def _ora_token_topic(vehicle_id: str, mqtt_settings) -> str:
    base = str(getattr(mqtt_settings, "base_topic", "car") or "car").strip().strip("/")
    return f"{base}/system/ora_tokens/{vehicle_id}"


def publish_ora_token_backup(provider_config: Dict[str, Any], mqtt_settings, vehicle_id: str, log_callback=None) -> bool:
    bundle = extract_ora_token_bundle(provider_config)
    ok, missing = has_usable_ora_tokens(bundle)
    if not ok:
        if log_callback:
            log_callback(f"ORA MQTT-Token-Backup übersprungen - fehlende Felder: {', '.join(missing)}")
        return False
    if not getattr(mqtt_settings, "host", ""):
        if log_callback:
            log_callback("ORA MQTT-Token-Backup übersprungen - kein MQTT Host konfiguriert")
        return False

    payload = json.dumps({"vehicle_id": vehicle_id, "updated_at": int(time.time()), "tokens": bundle}, ensure_ascii=False)
    topic = _ora_token_topic(vehicle_id, mqtt_settings)
    client = mqtt.Client(client_id=f"car2mqtt-gwmbackup-{uuid.uuid4().hex[:8]}")
    if getattr(mqtt_settings, "username", ""):
        client.username_pw_set(mqtt_settings.username, getattr(mqtt_settings, "password", ""))
    if getattr(mqtt_settings, "tls", False):
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    try:
        client.connect(mqtt_settings.host, int(getattr(mqtt_settings, "port", 1883)), 10)
        client.loop_start()
        info = client.publish(topic, payload, qos=int(getattr(mqtt_settings, "qos", 1)), retain=True)
        info.wait_for_publish(timeout=5)
        client.loop_stop()
        client.disconnect()
        if log_callback:
            log_callback(f"ORA Tokens zusätzlich im MQTT gesichert: {topic}")
        return True
    except Exception as exc:
        if log_callback:
            log_callback(f"ORA MQTT-Token-Backup fehlgeschlagen: {exc}")
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        return False


def restore_ora_tokens_from_mqtt(provider_config: Dict[str, Any], mqtt_settings, vehicle_id: str, log_callback=None, timeout: float = 3.0) -> bool:
    if not getattr(mqtt_settings, "host", ""):
        return False
    topic = _ora_token_topic(vehicle_id, mqtt_settings)
    client = mqtt.Client(client_id=f"car2mqtt-gwmrestore-{uuid.uuid4().hex[:8]}")
    if getattr(mqtt_settings, "username", ""):
        client.username_pw_set(mqtt_settings.username, getattr(mqtt_settings, "password", ""))
    if getattr(mqtt_settings, "tls", False):
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    result: Dict[str, Any] = {}

    def _on_connect(c, _u, _f, rc, _p=None):
        if rc == 0:
            c.subscribe(topic, qos=int(getattr(mqtt_settings, "qos", 1)))

    def _on_message(_c, _u, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="ignore") or "{}")
            result.update(payload.get("tokens") or {})
        except Exception:
            pass

    client.on_connect = _on_connect
    client.on_message = _on_message
    try:
        client.connect(mqtt_settings.host, int(getattr(mqtt_settings, "port", 1883)), 10)
        client.loop_start()
        end = time.time() + timeout
        while time.time() < end and not result:
            time.sleep(0.1)
        client.loop_stop()
        client.disconnect()
    except Exception as exc:
        if log_callback:
            log_callback(f"ORA Token-Restore aus MQTT fehlgeschlagen: {exc}")
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        return False

    if result:
        apply_ora_token_bundle(provider_config, result)
        if log_callback:
            log_callback(f"ORA Tokens aus MQTT wiederhergestellt: {topic}")
        return True
    return False
