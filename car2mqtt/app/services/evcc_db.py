from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any


def _safe_cell(value: Any, max_len: int = 500) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return f"<binary {len(value)} bytes>"
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "…"
    return value


def normalize_db_path(path: str | None) -> str:
    return str(path or "/data/evcc.db").strip() or "/data/evcc.db"


def _connect_readonly(path: str) -> sqlite3.Connection:
    # URI mode keeps the diagnostic read-only. If that fails, sqlite will raise
    # a clear error which we pass back to the UI.
    uri = "file:" + Path(path).absolute().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=3)
    con.row_factory = sqlite3.Row
    return con


def inspect_evcc_db(path: str | None = None, sample_limit: int = 5) -> dict[str, Any]:
    db_path = normalize_db_path(path)
    p = Path(db_path)
    result: dict[str, Any] = {
        "path": db_path,
        "exists": p.exists(),
        "readable": os.access(db_path, os.R_OK) if p.exists() else False,
        "size_bytes": p.stat().st_size if p.exists() else 0,
        "tables": [],
        "candidates": [],
    }
    if not p.exists():
        result["error"] = "EVCC Datenbankdatei existiert nicht."
        return result
    if not os.access(db_path, os.R_OK):
        result["error"] = "EVCC Datenbankdatei ist nicht lesbar."
        return result

    with _connect_readonly(db_path) as con:
        rows = con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name").fetchall()
        for row in rows:
            name = row["name"]
            if str(name).startswith("sqlite_"):
                continue
            columns = con.execute(f"PRAGMA table_info({name!r})").fetchall()
            count = None
            try:
                count = con.execute(f"SELECT COUNT(*) AS c FROM {name!r}").fetchone()["c"]
            except Exception:
                pass
            table_info = {
                "name": name,
                "type": row["type"],
                "count": count,
                "columns": [{"name": c["name"], "type": c["type"], "pk": bool(c["pk"])} for c in columns],
            }
            result["tables"].append(table_info)
            lower = str(name).lower()
            col_names = {str(c["name"]).lower() for c in columns}
            if any(token in lower for token in ("vehicle", "device", "config")) or {"class", "type", "name", "title"} & col_names:
                try:
                    samples = con.execute(f"SELECT * FROM {name!r} LIMIT ?", (int(sample_limit),)).fetchall()
                    table_info["sample_rows"] = [dict((k, _safe_cell(v)) for k, v in dict(sample).items()) for sample in samples]
                    result["candidates"].append(table_info)
                except Exception as exc:
                    table_info["sample_error"] = str(exc)
                    result["candidates"].append(table_info)
    return result


def backup_evcc_db(path: str | None = None, backup_dir: str | None = None) -> dict[str, Any]:
    db_path = normalize_db_path(path)
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"EVCC Datenbank nicht gefunden: {db_path}")
    if not os.access(db_path, os.R_OK):
        raise PermissionError(f"EVCC Datenbank nicht lesbar: {db_path}")
    target_dir = Path(backup_dir or src.parent / "car2mqtt-evcc-backups")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{src.name}.car2mqtt-backup-{stamp}"
    shutil.copy2(src, target)
    return {"status": "ok", "source": str(src), "backup": str(target), "size_bytes": target.stat().st_size}
