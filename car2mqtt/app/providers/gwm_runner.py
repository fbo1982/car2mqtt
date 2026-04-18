from __future__ import annotations

import os
import shutil
import ssl
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import paho.mqtt.client as mqtt

from app.core.models import VehicleConfig
from app.core.runtime_settings import RuntimeMqttSettings
from app.providers.gwm_config import ensure_ora_runtime_config, render_ora2mqtt_yaml, merge_ora_tokens


class GwmIntegratedWorker:
    def _is_waiting_for_code(self, text: str) -> bool:
        lowered = (text or "").lower()
        return "ora_waiting_for_code" in lowered or "verification code required" in lowered or "incorrect verification code" in lowered

    def _is_permanent_auth_error(self, text: str) -> bool:
        lowered = (text or "").lower()
        markers = [
            "username or password is incorrect",
            "account will be locked",
            "verification code request is too frequently",
            "sharprompt requires an interactive environment",
            "ora verification code required",
        ]
        return any(m in lowered for m in markers)

    def __init__(
        self,
        vehicle: VehicleConfig,
        mqtt_settings: RuntimeMqttSettings,
        vehicle_dir: Path,
        on_connect: Callable[[], None],
        on_disconnect: Callable[[str], None],
        on_error: Callable[[str], None],
        on_waiting: Callable[[str], None],
        on_detail: Callable[[str], None],
        on_message: Callable[[str, str], None],
        log_callback: Callable[[str], None],
    ) -> None:
        self.vehicle = vehicle
        self.settings = mqtt_settings
        self.vehicle_dir = vehicle_dir
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        self.on_waiting = on_waiting
        self.on_detail = on_detail
        self.on_message = on_message
        self.log = log_callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._monitor_client: mqtt.Client | None = None
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"gwm-{self.vehicle.id}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._monitor_client:
            try:
                self._monitor_client.loop_stop()
                self._monitor_client.disconnect()
            except Exception:
                pass
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=10)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _source_topics(self) -> tuple[str, str]:
        vehicle_id = str(self.vehicle.provider_config.get("vehicle_id", "")).strip() or self.vehicle.id
        base = str(self.vehicle.provider_config.get("source_topic_base", "")).strip() or f"GWM/{vehicle_id}"
        return f"{base}/status/items/+/value", base

    def _ora_bin(self) -> Path:
        return Path("/opt/ora2mqtt/ora2mqtt")

    def _prepare_runtime_files(self) -> Path:
        self.vehicle_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.vehicle_dir / "ora2mqtt.yml"
        runtime = ensure_ora_runtime_config(self.vehicle.provider_config, self.settings)
        config_path.write_text(render_ora2mqtt_yaml(self.vehicle.provider_config, self.settings), encoding="utf-8")
        return config_path

    def _run_configure(self, config_path: Path) -> None:
        env = os.environ.copy()
        env["ORA_ACCOUNT"] = str(self.vehicle.provider_config.get("account", ""))
        env["ORA_PASSWORD"] = str(self.vehicle.provider_config.get("password", ""))
        env["ORA_COUNTRY"] = str(self.vehicle.provider_config.get("country", "DE"))
        code_file = self.vehicle_dir / "verification_code.txt"
        verification_code = code_file.read_text(encoding="utf-8").strip() if code_file.exists() else ""
        env["ORA_VERIFICATION_CODE"] = verification_code
        env["MQTT_HOST"] = self.settings.host
        env["MQTT_USERNAME"] = self.settings.username
        env["MQTT_PASSWORD"] = self.settings.password
        env["MQTT_TLS"] = "true" if self.settings.tls else "false"
        env["OPENSSL_CONF"] = "/opt/ora2mqtt/openssl.cnf"
        self.log("ORA configure wird ausgeführt")
        proc = subprocess.run(
            [str(self._ora_bin()), "configure", "-c", str(config_path)],
            cwd="/opt/ora2mqtt",
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        combined = []
        if proc.stdout:
            for line in proc.stdout.splitlines():
                self.log(f"[ora2mqtt configure] {line}")
                combined.append(line)
        icu_error = False
        if proc.stderr:
            for line in proc.stderr.splitlines():
                self.log(f"[ora2mqtt configure][stderr] {line}")
                combined.append(line)
                if "valid ICU package" in line or "libicu" in line:
                    icu_error = True
        code_file = self.vehicle_dir / "verification_code.txt"
        if code_file.exists() and (proc.returncode == 0 or combined):
            try:
                code_file.unlink()
                self.log("Temporärer ORA Verifikationscode verworfen")
            except Exception:
                pass
        if proc.returncode != 0:
            joined = "\n".join(combined)
            if icu_error:
                raise RuntimeError("ora2mqtt configure fehlgeschlagen: ICU/libicu fehlt im Container")
            if self._is_waiting_for_code(joined):
                raise RuntimeError("ORA_WAITING_FOR_CODE::Verifikationscode angefordert. Bitte Code eingeben und senden.")
            if self._is_permanent_auth_error(joined):
                raise RuntimeError(f"ORA_AUTH_FATAL::{joined.splitlines()[0] if joined else 'Authentifizierungsfehler'}")
            raise RuntimeError(f"ora2mqtt configure fehlgeschlagen (rc={proc.returncode})")
        merge_ora_tokens(self.vehicle.provider_config, config_path)
        self.log("ORA configure erfolgreich abgeschlossen")

    def _start_monitor(self, source_topic: str, source_base: str) -> None:
        client = mqtt.Client(client_id=f"car2mqtt-gwmmon-{uuid.uuid4().hex[:8]}")
        self._monitor_client = client
        if self.settings.username:
            client.username_pw_set(self.settings.username, self.settings.password)
        if self.settings.tls:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        def _on_connect(_client, _userdata, _flags, rc, _properties=None):
            if rc == 0:
                self.log("ORA MQTT Monitor verbunden")
                _client.subscribe(source_topic, qos=self.settings.qos)
                self.log(f"ORA MQTT Subscribe gesendet: {source_topic}")
                self.on_connect()
            else:
                self.on_error(f"ORA MQTT Monitor Verbindung fehlgeschlagen (rc={rc})")

        def _on_disconnect(_client, _userdata, rc, _properties=None):
            if self._stop.is_set():
                return
            self.log(f"ORA MQTT Monitor getrennt (rc={rc})")
            self.on_disconnect(str(rc))

        def _on_message(_client, _userdata, msg):
            payload = msg.payload.decode("utf-8", errors="ignore")
            self.on_message(msg.topic, payload)

        client.on_connect = _on_connect
        client.on_disconnect = _on_disconnect
        client.on_message = _on_message
        client.connect(self.settings.host, self.settings.port, 30)
        client.loop_start()
        self.log(f"ORA Source Base Topic: {source_base}")
        self.log(f"ORA Subscribe Topic: {source_topic}")

    def _start_run(self, config_path: Path) -> None:
        env = os.environ.copy()
        env["OPENSSL_CONF"] = "/opt/ora2mqtt/openssl.cnf"
        interval = str(int(self.vehicle.provider_config.get("poll_interval", 60) or 60))
        self.log(f"ORA Runner wird gestartet (Intervall {interval}s)")
        self._proc = subprocess.Popen(
            [str(self._ora_bin()), "run", "-c", str(config_path), "-i", interval],
            cwd="/opt/ora2mqtt",
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def _stream_runner_logs(self) -> None:
        assert self._proc is not None
        if self._proc.stdout is None:
            return
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            self.log(f"[ora2mqtt run] {line.rstrip()}")

    def _run(self) -> None:
        backoff = 30
        while not self._stop.is_set():
            try:
                config_path = self._prepare_runtime_files()
                if not self.vehicle.provider_config.get("access_token") or not self.vehicle.provider_config.get("refresh_token"):
                    self.on_detail("ORA Konfiguration und Login wird aufgebaut")
                    self._run_configure(config_path)
                else:
                    self.log("ORA Tokens bereits vorhanden - configure wird übersprungen")
                source_topic, source_base = self._source_topics()
                self._start_monitor(source_topic, source_base)
                self._start_run(config_path)
                self._stream_runner_logs()
                if self._stop.is_set():
                    break
                rc = self._proc.wait(timeout=1) if self._proc else -1
                self.log(f"ORA Runner beendet (rc={rc})")
                self.on_disconnect(str(rc))
            except Exception as exc:
                self.log(f"ORA Worker Fehler: {exc}")
                message = str(exc)
                if message.startswith("ORA_WAITING_FOR_CODE::"):
                    final_message = message.split("::", 1)[1]
                    self.on_waiting(final_message)
                    self.log("ORA wartet auf Verifikationscode - kein automatischer Retry")
                    break
                if message.startswith("ORA_AUTH_FATAL::"):
                    final_message = message.split("::", 1)[1]
                    self.on_error(final_message)
                    self.log("ORA Fatalfehler erkannt - kein automatischer Retry")
                    break
                self.on_error(message)
            finally:
                if self._monitor_client:
                    try:
                        self._monitor_client.loop_stop()
                        self._monitor_client.disconnect()
                    except Exception:
                        pass
                    self._monitor_client = None
                self._proc = None
            if self._stop.wait(backoff):
                break
            self.on_detail("ORA Verbindung wird erneut aufgebaut")
