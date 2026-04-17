from __future__ import annotations

from typing import Any, Dict
import uuid
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
