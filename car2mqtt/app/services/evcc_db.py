from __future__ import annotations

import io
import json
import os
import shutil
import socket
import sqlite3
import tarfile
import time
from pathlib import Path
from typing import Any


DB_NAMES = {"evcc.db", "evcc.sqlite", "evcc.sqlite3"}
SEARCH_ROOTS = [
    Path("/addons"),
    Path("/addon_configs"),
    Path("/config/addons_config"),
    Path("/config"),
    Path("/share"),
    Path("/backup"),
    Path("/data"),
]
DOCKER_SOCKETS = [Path("/var/run/docker.sock"), Path("/run/docker.sock")]
DOCKER_EVCC_REMOTE_PATHS = ["/data/evcc.db", "/config/evcc.db", "/share/evcc.db"]
DOCKER_SNAPSHOT_DIR = Path("/data/car2mqtt-evcc-docker-snapshots")


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


def _decode_chunked(data: bytes) -> bytes:
    out = bytearray()
    pos = 0
    while True:
        end = data.find(b"\r\n", pos)
        if end < 0:
            break
        size_line = data[pos:end].split(b";", 1)[0].strip()
        try:
            size = int(size_line, 16)
        except ValueError:
            break
        pos = end + 2
        if size == 0:
            break
        out.extend(data[pos:pos + size])
        pos += size + 2
    return bytes(out)


def _docker_socket_path() -> Path | None:
    for sock in DOCKER_SOCKETS:
        if sock.exists():
            return sock
    return None


def docker_diagnostics(max_containers: int = 20) -> dict[str, Any]:
    diag: dict[str, Any] = {
        "sockets": [str(s) for s in DOCKER_SOCKETS],
        "socket": str(_docker_socket_path() or ""),
        "socket_available": _docker_socket_path() is not None,
        "containers": [],
    }
    if not diag["socket_available"]:
        diag["error"] = "Docker API Socket nicht verfügbar. docker_api wird im Add-on offenbar nicht gemappt."
        return diag
    try:
        containers = _docker_json("GET", "/containers/json?all=1")
        for c in (containers or [])[:max_containers]:
            diag["containers"].append({
                "id": str(c.get("Id", ""))[:12],
                "names": c.get("Names") or [],
                "image": c.get("Image", ""),
                "state": c.get("State", ""),
                "status": c.get("Status", ""),
                "labels": c.get("Labels") or {},
            })
        diag["container_count"] = len(containers or [])
    except Exception as exc:
        diag["error"] = str(exc)
    return diag


def _docker_http(method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 10.0) -> tuple[int, dict[str, str], bytes]:
    socket_path = _docker_socket_path()
    if not socket_path:
        raise FileNotFoundError("Docker API Socket nicht verfügbar: /var/run/docker.sock oder /run/docker.sock")
    headers = dict(headers or {})
    body = body or b""
    headers.setdefault("Host", "docker")
    headers.setdefault("Connection", "close")
    headers.setdefault("Content-Length", str(len(body)))
    request = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(socket_path))
        sock.sendall(request.encode("utf-8") + body)
        chunks: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    raw = b"".join(chunks)
    head, sep, payload = raw.partition(b"\r\n\r\n")
    if not sep:
        raise RuntimeError("Ungültige Docker API Antwort")
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    status = 0
    if lines:
        parts = lines[0].split()
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])
    out_headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            out_headers[k.strip().lower()] = v.strip()
    if out_headers.get("transfer-encoding", "").lower() == "chunked":
        payload = _decode_chunked(payload)
    return status, out_headers, payload


def _docker_json(method: str, path: str) -> Any:
    status, _headers, body = _docker_http(method, path)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Docker API {method} {path} fehlgeschlagen ({status}): {body[:500].decode('utf-8', errors='replace')}")
    return json.loads(body.decode("utf-8") or "null")


def _find_evcc_container() -> dict[str, Any] | None:
    try:
        containers = _docker_json("GET", "/containers/json?all=1")
    except Exception:
        return None
    best = None
    best_score = 999
    for c in containers or []:
        labels = c.get("Labels") or {}
        names = c.get("Names") or []
        text = " ".join([
            str(c.get("Id", "")),
            str(c.get("Image", "")),
            str(c.get("ImageID", "")),
            " ".join(names),
            " ".join(f"{k}={v}" for k, v in labels.items()) if isinstance(labels, dict) else str(labels),
            str(c.get("Command", "")),
        ]).lower()
        score = 999
        if "evcc" in text:
            score = 0
        if any("evcc" in str(n).lower() for n in names):
            score -= 5
        if "addon" in text and "evcc" in text:
            score -= 5
        if "car2mqtt" in text:
            score += 100
        if score < best_score:
            best = c
            best_score = score
    return best if best_score < 999 else None

def _try_copy_file_from_container(container: dict[str, Any], remote_path: str) -> dict[str, Any]:
    cid = container.get("Id")
    import urllib.parse
    archive_path = urllib.parse.quote(remote_path, safe="")
    status, _headers, body = _docker_http("GET", f"/containers/{cid}/archive?path={archive_path}", timeout=20.0)
    base = {
        "container_id": str(cid)[:12],
        "container_name": ", ".join(container.get("Names") or []),
        "container_image": container.get("Image", ""),
        "remote_path": remote_path,
        "docker_socket": str(_docker_socket_path() or ""),
    }
    if status < 200 or status >= 300:
        base["error"] = f"Docker konnte {remote_path} nicht aus dem EVCC-Container lesen ({status})."
        try:
            base["response"] = body[:500].decode("utf-8", errors="replace")
        except Exception:
            pass
        return base
    DOCKER_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = DOCKER_SNAPSHOT_DIR / f"evcc.db.snapshot-{stamp}"
    try:
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:*") as tf:
            member = next((m for m in tf.getmembers() if Path(m.name).name.lower() in DB_NAMES and m.isfile()), None)
            if member is None:
                base["error"] = "Docker-Archiv enthielt keine evcc.db/evcc.sqlite-Datei."
                return base
            src = tf.extractfile(member)
            if src is None:
                base["error"] = "EVCC DB konnte aus Docker-Archiv nicht gelesen werden."
                return base
            with target.open("wb") as fh:
                shutil.copyfileobj(src, fh)
    except Exception as exc:
        base["error"] = f"Docker-Snapshot konnte nicht extrahiert werden: {exc}"
        return base
    base.update({"snapshot_path": str(target), "size_bytes": target.stat().st_size})
    return base


def copy_evcc_db_from_docker() -> dict[str, Any] | None:
    diag = docker_diagnostics()
    container = _find_evcc_container()
    if not container:
        return {
            "error": "Kein EVCC Docker-Container gefunden.",
            "docker_socket": diag.get("socket", ""),
            "socket_available": diag.get("socket_available", False),
            "containers_seen": [
                {"id": c.get("id"), "names": c.get("names"), "image": c.get("image"), "state": c.get("state")}
                for c in diag.get("containers", [])
            ],
        }
    if not container.get("Id"):
        return {"error": "EVCC Docker-Container ohne Container-ID gefunden.", "docker_diagnostics": diag}

    errors: list[str] = []
    remote_paths = list(DOCKER_EVCC_REMOTE_PATHS)
    try:
        info = _docker_json("GET", f"/containers/{container.get('Id')}/json")
        for m in info.get("Mounts") or []:
            dest = str(m.get("Destination") or "")
            if dest:
                for name in DB_NAMES:
                    candidate = dest.rstrip("/") + "/" + name
                    if candidate not in remote_paths:
                        remote_paths.append(candidate)
    except Exception as exc:
        errors.append(f"Container-Inspect fehlgeschlagen: {exc}")

    for remote_path in remote_paths:
        res = _try_copy_file_from_container(container, remote_path)
        if res.get("snapshot_path"):
            if errors:
                res["previous_errors"] = errors
            return res
        if res.get("error"):
            errors.append(str(res.get("error")) + ((" · " + str(res.get("response"))) if res.get("response") else ""))

    return {
        "container_id": str(container.get("Id", ""))[:12],
        "container_name": ", ".join(container.get("Names") or []),
        "container_image": container.get("Image", ""),
        "docker_socket": str(_docker_socket_path() or ""),
        "remote_paths_tried": remote_paths,
        "error": "EVCC-Container gefunden, aber keine EVCC-DB konnte aus dem Container kopiert werden. " + " | ".join(errors[-8:]),
    }

def find_evcc_db_candidates(max_depth: int = 9, max_files: int = 25000) -> list[str]:
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
        "/data/evcc.db ist normalerweise nur innerhalb des EVCC-Add-ons sichtbar und kann aus einem anderen Add-on nicht direkt geöffnet werden. "
        "Wenn auch der Docker-Fallback keinen EVCC-Container sieht, hat car2mqtt technisch keinen Zugriff auf die EVCC-DB. "
        "Für direktes DB-Schreiben muss die EVCC-DB in einen gemeinsam sichtbaren Pfad gelegt werden, z. B. /share/evcc.db, und EVCC muss diese DB verwenden. "
        "Alternativ bleibt nur EVCC-API/YAML-Helper. "
        f"Gefundene Kandidaten: {', '.join(candidates) or '-'}"
    )

def _inspect_sqlite(db_path: str, sample_limit: int, result: dict[str, Any]) -> dict[str, Any]:
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


def inspect_evcc_db(path: str | None = None, sample_limit: int = 5) -> dict[str, Any]:
    requested_path = normalize_db_path(path)
    db_path, db_candidates, used_auto_path = resolve_evcc_db_path(path)
    docker_snapshot = None
    if not Path(db_path).exists():
        docker_snapshot = copy_evcc_db_from_docker()
        if docker_snapshot and docker_snapshot.get("snapshot_path") and Path(str(docker_snapshot["snapshot_path"])).exists():
            db_path = str(docker_snapshot["snapshot_path"])
            used_auto_path = True
    p = Path(db_path)
    result: dict[str, Any] = {
        "requested_path": requested_path,
        "path": db_path,
        "used_auto_path": used_auto_path,
        "found_paths": db_candidates,
        "docker_snapshot": docker_snapshot,
        "search_roots": [str(r) for r in SEARCH_ROOTS if r.exists()],
        "exists": p.exists(),
        "readable": os.access(db_path, os.R_OK) if p.exists() else False,
        "size_bytes": p.stat().st_size if p.exists() else 0,
        "tables": [],
        "candidates": [],
    }
    if not p.exists():
        result["error"] = _unreachable_hint(requested_path, db_candidates)
        if docker_snapshot and docker_snapshot.get("error"):
            result["error"] += " Docker-Fallback: " + str(docker_snapshot.get("error"))
        return result
    if not os.access(db_path, os.R_OK):
        result["error"] = "EVCC Datenbankdatei ist nicht lesbar: " + db_path
        return result
    return _inspect_sqlite(db_path, sample_limit, result)


def backup_evcc_db(path: str | None = None, backup_dir: str | None = None) -> dict[str, Any]:
    requested_path = normalize_db_path(path)
    db_path, db_candidates, used_auto_path = resolve_evcc_db_path(path)
    docker_snapshot = None
    if not Path(db_path).exists():
        docker_snapshot = copy_evcc_db_from_docker()
        if docker_snapshot and docker_snapshot.get("snapshot_path") and Path(str(docker_snapshot["snapshot_path"])).exists():
            db_path = str(docker_snapshot["snapshot_path"])
            used_auto_path = True
    src = Path(db_path)
    if not src.exists():
        msg = _unreachable_hint(requested_path, db_candidates)
        if docker_snapshot and docker_snapshot.get("error"):
            msg += " Docker-Fallback: " + str(docker_snapshot.get("error"))
        raise FileNotFoundError(msg)
    if not os.access(db_path, os.R_OK):
        raise PermissionError(f"EVCC Datenbank nicht lesbar: {db_path}")
    target_dir = Path(backup_dir or Path("/data/car2mqtt-evcc-backups"))
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{src.name}.car2mqtt-backup-{stamp}"
    shutil.copy2(src, target)
    return {"status": "ok", "requested_path": requested_path, "source": str(src), "used_auto_path": used_auto_path, "found_paths": db_candidates, "docker_snapshot": docker_snapshot, "backup": str(target), "size_bytes": target.stat().st_size}
