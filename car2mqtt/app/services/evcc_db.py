from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any


DB_NAMES = {"evcc.db", "evcc.sqlite", "evcc.sqlite3"}
SEARCH_ROOTS = [
    Path("/addons"),              # legacy/HAOS add-on data mapping, if available
    Path("/addon_configs"),       # newer HA add-on config mapping
    Path("/config/addons_config"),
    Path("/config"),
    Path("/share"),
    Path("/backup"),
    Path("/data"),                # own car2mqtt add-on data only
]


def _safe_cell(value: Any, max_len: int = 500) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return f"<binary {len(value)} bytes>"
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "…"
    return value


def normalize_db_path(path: str | None) -> str:
    return str(path or "/data/evcc.db").strip() or "/data/evcc.db"


def _looks_like_evcc_db(path: Path) -> bool:
    name = path.name.lower()
    return name in DB_NAMES or ("evcc" in name and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"})


def find_evcc_db_candidates(max_depth: int = 9, max_files: int = 25000) -> list[str]:
    """Find EVCC sqlite DB candidates visible inside the car2mqtt add-on container.

    Important: /data/evcc.db is normally only the path inside the EVCC add-on.
    car2mqtt can only see it if Home Assistant exposes the legacy add-on data
    directory through /addons or if the DB is stored in /addon_configs, /share,
    /config, etc.
    """
    found: list[str] = []
    seen: set[str] = set()
    scanned = 0
    for root in SEARCH_ROOTS:
        if not root.exists() or not root.is_dir():
            continue
        try:
            for base, dirs, files in os.walk(root):
                scanned += len(files)
                if scanned > max_files:
                    break
                try:
                    rel_depth = len(Path(base).relative_to(root).parts)
                except Exception:
                    rel_depth = 99
                if rel_depth >= max_depth:
                    dirs[:] = []
                # keep scan cheap and avoid unrelated huge dirs
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", "tmp", "cache"}]
                for filename in files:
                    child = Path(base) / filename
                    if not _looks_like_evcc_db(child):
                        continue
                    resolved = str(child)
                    if resolved not in seen:
                        seen.add(resolved)
                        found.append(resolved)
        except Exception:
            continue
    # prefer explicit evcc.db and paths that look like EVCC add-on/config folders
    def score(p: str) -> tuple[int, str]:
        low = p.lower()
        s = 0
        if low.endswith("/evcc.db"):
            s -= 20
        if "/evcc" in low:
            s -= 10
        if low.startswith("/addons"):
            s -= 5
        if low.startswith("/addon_configs"):
            s -= 4
        if low.startswith("/share"):
            s -= 3
        return (s, p)
    found.sort(key=score)
    return found


def resolve_evcc_db_path(path: str | None) -> tuple[str, list[str], bool]:
    requested = normalize_db_path(path)
    candidates = find_evcc_db_candidates()
    if Path(requested).exists():
        return requested, candidates, False
    if candidates:
        return candidates[0], candidates, True
    return requested, candidates, False


def _connect_readonly(path: str) -> sqlite3.Connection:
    uri = "file:" + Path(path).absolute().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=3)
    con.row_factory = sqlite3.Row
    return con


def _unreachable_hint(requested_path: str, candidates: list[str]) -> str:
    return (
        f"EVCC Datenbank nicht gefunden: {requested_path}. "
        "Wichtig: /data/evcc.db ist normalerweise nur innerhalb des EVCC-Add-ons sichtbar. "
        "car2mqtt kann diese Datei nur sehen, wenn Home Assistant den EVCC-Add-on-Datenordner unter /addons freigibt "
        "oder wenn die EVCC-Datenbank in einem gemeinsamen Pfad liegt, z. B. /share/evcc.db oder /addon_configs/<evcc>/evcc.db. "
        f"Gefundene Kandidaten: {', '.join(candidates) or '-'}"
    )


def inspect_evcc_db(path: str | None = None, sample_limit: int = 5) -> dict[str, Any]:
    requested_path = normalize_db_path(path)
    db_path, db_candidates, used_auto_path = resolve_evcc_db_path(path)
    p = Path(db_path)
    result: dict[str, Any] = {
        "requested_path": requested_path,
        "path": db_path,
        "used_auto_path": used_auto_path,
        "found_paths": db_candidates,
        "search_roots": [str(r) for r in SEARCH_ROOTS if r.exists()],
        "exists": p.exists(),
        "readable": os.access(db_path, os.R_OK) if p.exists() else False,
        "size_bytes": p.stat().st_size if p.exists() else 0,
        "tables": [],
        "candidates": [],
    }
    if not p.exists():
        result["error"] = _unreachable_hint(requested_path, db_candidates)
        return result
    if not os.access(db_path, os.R_OK):
        result["error"] = "EVCC Datenbankdatei ist nicht lesbar: " + db_path
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
    requested_path = normalize_db_path(path)
    db_path, db_candidates, used_auto_path = resolve_evcc_db_path(path)
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(_unreachable_hint(requested_path, db_candidates))
    if not os.access(db_path, os.R_OK):
        raise PermissionError(f"EVCC Datenbank nicht lesbar: {db_path}")
    target_dir = Path(backup_dir or src.parent / "car2mqtt-evcc-backups")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{src.name}.car2mqtt-backup-{stamp}"
    shutil.copy2(src, target)
    return {"status": "ok", "requested_path": requested_path, "source": str(src), "used_auto_path": used_auto_path, "found_paths": db_candidates, "backup": str(target), "size_bytes": target.stat().st_size}
