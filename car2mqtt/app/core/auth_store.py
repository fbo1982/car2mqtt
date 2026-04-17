from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional
from app.core.models import AuthSession


class AuthStore:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.data_dir / "auth_sessions.json"
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, AuthSession]:
        if not self.file.exists():
            return {}
        raw = json.loads(self.file.read_text(encoding="utf-8"))
        return {k: AuthSession.model_validate(v) for k, v in raw.items()}

    def _save(self, state: Dict[str, AuthSession]) -> None:
        self.file.write_text(
            json.dumps({k: v.model_dump(mode="json") for k, v in state.items()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def upsert(self, session: AuthSession) -> AuthSession:
        with self._lock:
            state = self._load()
            state[session.session_id] = session
            self._save(state)
        return session

    def get(self, session_id: str) -> Optional[AuthSession]:
        with self._lock:
            return self._load().get(session_id)
