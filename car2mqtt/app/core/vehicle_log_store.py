from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class VehicleLogStore:
    def __init__(self, data_dir: str) -> None:
        self.logs_dir = Path(data_dir) / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _file(self, vehicle_id: str) -> Path:
        return self.logs_dir / f"{vehicle_id}.log"

    def append(self, vehicle_id: str, message: str) -> None:
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        with self._file(vehicle_id).open('a', encoding='utf-8') as fh:
            fh.write(f"[{ts}] {message}\n")

    def read(self, vehicle_id: str, max_lines: int = 300) -> str:
        path = self._file(vehicle_id)
        if not path.exists():
            return "Noch keine fahrzeugspezifischen Logs vorhanden."
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        return "\n".join(lines[-max_lines:])

    def delete(self, vehicle_id: str) -> None:
        path = self._file(vehicle_id)
        if path.exists():
            path.unlink()
