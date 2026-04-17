from __future__ import annotations

import json
from pathlib import Path

from .config import STATE_FILE, default_state, ensure_data_dir
from .models import AppState


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or STATE_FILE
        ensure_data_dir()

    def load(self) -> AppState:
        if not self.path.exists():
            state = default_state()
            self.save(state)
            return state

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return AppState.model_validate(data)
        except Exception:
            state = default_state()
            self.save(state)
            return state

    def save(self, state: AppState) -> None:
        ensure_data_dir()
        self.path.write_text(
            json.dumps(state.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
