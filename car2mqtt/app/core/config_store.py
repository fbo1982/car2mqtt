from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from app.core.models import AppConfig, VehicleConfig


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
