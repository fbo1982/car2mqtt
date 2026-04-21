from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from app.core.models import AppConfig, VehicleConfig, AdditionalMqttBroker, VehicleGroup


class ConfigStore:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "vehicles.json"

    def load(self) -> AppConfig:
        if not self.config_file.exists():
            return AppConfig()
        raw = json.loads(self.config_file.read_text(encoding="utf-8"))
        return AppConfig.model_validate(raw)

    def save(self, config: AppConfig) -> AppConfig:
        self.config_file.write_text(
            json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return config

    def get_vehicle(self, vehicle_id: str) -> Optional[VehicleConfig]:
        config = self.load()
        for vehicle in config.vehicles:
            if vehicle.id == vehicle_id:
                return vehicle
        return None

    def upsert_vehicle(self, vehicle: VehicleConfig) -> AppConfig:
        config = self.load()
        replaced = False
        for index, existing in enumerate(config.vehicles):
            if existing.id == vehicle.id:
                config.vehicles[index] = vehicle
                replaced = True
                break
        if not replaced:
            config.vehicles.append(vehicle)
        return self.save(config)


    def list_brokers(self) -> list[AdditionalMqttBroker]:
        return self.load().mqtt_brokers

    def get_broker(self, broker_id: str) -> Optional[AdditionalMqttBroker]:
        config = self.load()
        for broker in config.mqtt_brokers:
            if broker.id == broker_id:
                return broker
        return None

    def upsert_broker(self, broker: AdditionalMqttBroker) -> AppConfig:
        config = self.load()
        replaced = False
        for index, existing in enumerate(config.mqtt_brokers):
            if existing.id == broker.id:
                config.mqtt_brokers[index] = broker
                replaced = True
                break
        if not replaced:
            config.mqtt_brokers.append(broker)
        return self.save(config)

    def delete_broker(self, broker_id: str) -> AppConfig:
        config = self.load()
        config.mqtt_brokers = [broker for broker in config.mqtt_brokers if broker.id != broker_id]
        return self.save(config)

    def list_groups(self) -> list[VehicleGroup]:
        return self.load().vehicle_groups

    def get_group(self, group_id: str) -> Optional[VehicleGroup]:
        config = self.load()
        for group in config.vehicle_groups:
            if group.id == group_id:
                return group
        return None

    def upsert_group(self, group: VehicleGroup) -> AppConfig:
        config = self.load()
        replaced = False
        for index, existing in enumerate(config.vehicle_groups):
            if existing.id == group.id:
                config.vehicle_groups[index] = group
                replaced = True
                break
        if not replaced:
            config.vehicle_groups.append(group)
        return self.save(config)

    def delete_group(self, group_id: str) -> AppConfig:
        config = self.load()
        config.vehicle_groups = [group for group in config.vehicle_groups if group.id != group_id]
        for broker in config.mqtt_brokers:
            broker.group_ids = [gid for gid in broker.group_ids if gid != group_id]
        return self.save(config)
