from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict
from app.core.models import VehicleRuntimeState


class StateStore:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "state.json"
        self._lock = threading.Lock()

    def load(self) -> Dict[str, VehicleRuntimeState]:
        if not self.state_file.exists():
            return {}
        raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        return {key: VehicleRuntimeState.model_validate(value) for key, value in raw.items()}

    def save(self, state: Dict[str, VehicleRuntimeState]) -> None:
        self.state_file.write_text(
            json.dumps({k: v.model_dump(mode="json") for k, v in state.items()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def upsert(self, runtime_state: VehicleRuntimeState) -> VehicleRuntimeState:
        with self._lock:
            state = self.load()
            state[runtime_state.vehicle_id] = runtime_state
            self.save(state)
        return runtime_state

    def get_all(self) -> Dict[str, VehicleRuntimeState]:
        with self._lock:
            return self.load()


    def delete(self, vehicle_id: str) -> None:
        with self._lock:
            state = self.load()
            if vehicle_id in state:
                del state[vehicle_id]
                self.save(state)
