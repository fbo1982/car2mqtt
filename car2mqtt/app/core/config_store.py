from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional
from app.core.models import AppConfig, VehicleConfig


class ConfigStore:
    _locks_guard = threading.Lock()
    _locks: dict[str, object] = {}

    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "vehicles.json"
        with self._locks_guard:
            self._lock = self._locks.setdefault(str(self.config_file.resolve()), threading.RLock())

    def load(self) -> AppConfig:
        with self._lock:
            if not self.config_file.exists():
                return AppConfig()
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for vehicle in raw.get("vehicles", []) or []:
                    if isinstance(vehicle, dict) and "manufacturer" in vehicle:
                        vehicle["manufacturer"] = str(vehicle.get("manufacturer") or "").strip().lower()
            return AppConfig.model_validate(raw)

    def save(self, config: AppConfig) -> AppConfig:
        with self._lock:
            fd, temporary = tempfile.mkstemp(prefix="vehicles-", suffix=".tmp", dir=self.data_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(config.model_dump(mode="json"), stream, indent=2, ensure_ascii=False)
                os.replace(temporary, self.config_file)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return config

    def get_vehicle(self, vehicle_id: str) -> Optional[VehicleConfig]:
        config = self.load()
        for vehicle in config.vehicles:
            if vehicle.id == vehicle_id:
                return vehicle
        return None

    def upsert_vehicle(self, vehicle: VehicleConfig) -> AppConfig:
        with self._lock:
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
