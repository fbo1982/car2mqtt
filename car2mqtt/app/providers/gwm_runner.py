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
from app.mqtt.topic_builder import gwm_direct_source_root, gwm_direct_status_topic
from app.providers.gwm_config import (
    ensure_ora_runtime_config,
    render_ora2mqtt_yaml,
    merge_ora_tokens,
    has_usable_ora_tokens,
    publish_ora_token_backup,
    restore_ora_tokens_from_mqtt,
)


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
            "you have acquired verification code too many times",
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

    def _session_marker_path(self) -> Path:
        return self.vehicle_dir / ".ora_session_ready"


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
        base_topic = str(getattr(self.settings, "base_topic", "car") or "car").strip().strip("/") or "car"
        return (
            gwm_direct_status_topic(base_topic, self.vehicle.license_plate),
            gwm_direct_source_root(base_topic, self.vehicle.license_plate),
        )

    def _ora_bin(self) -> Path:
        return Path("/opt/ora2mqtt/ora2mqtt")

    def _prepare_runtime_files(self) -> Path:
        self.vehicle_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.vehicle_dir / "ora2mqtt.yml"

        # Reuse already persisted ORA tokens/session data before overwriting the config file.
        usable, missing = has_usable_ora_tokens(self.vehicle.provider_config)
        if config_path.exists() and not usable:
            try:
                merge_ora_tokens(self.vehicle.provider_config, config_path)
                usable, missing = has_usable_ora_tokens(self.vehicle.provider_config)
                if usable:
                    self.log("ORA Tokens aus bestehender ora2mqtt.yml übernommen")
                else:
                    self.log(f"ORA Token-Übernahme aus bestehender Config unvollständig - fehlend: {', '.join(missing)}")
            except Exception as exc:
                self.log(f"ORA Token-Übernahme aus bestehender Config fehlgeschlagen: {exc}")

        if not usable:
            restored = restore_ora_tokens_from_mqtt(self.vehicle.provider_config, self.settings, self.vehicle.id, self.log)
            if restored:
                usable, missing = has_usable_ora_tokens(self.vehicle.provider_config)

        ensure_ora_runtime_config(self.vehicle.provider_config, self.settings, license_plate=self.vehicle.license_plate)
        config_path.write_text(render_ora2mqtt_yaml(self.vehicle.provider_config, self.settings, license_plate=self.vehicle.license_plate), encoding="utf-8")
        if usable:
            publish_ora_token_backup(self.vehicle.provider_config, self.settings, self.vehicle.id, self.log)
        return config_path

    def _run_configure(self, config_path: Path) -> None:
        env = os.environ.copy()
        env["ORA_ACCOUNT"] = str(self.vehicle.provider_config.get("account", ""))
        env["ORA_PASSWORD"] = str(self.vehicle.provider_config.get("password", ""))
        env["ORA_COUNTRY"] = str(self.vehicle.provider_config.get("country", "DE"))
        code_file = self.vehicle_dir / "verification_code.txt"
        verification_code = code_file.read_text(encoding="utf-8").strip() if code_file.exists() else ""
        if code_file.exists():
            try:
                code_file.unlink()
                self.log("ORA Verifikationscode-Datei nach einmaliger Verwendung entfernt")
            except Exception:
                pass
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
        publish_ora_token_backup(self.vehicle.provider_config, self.settings, self.vehicle.id, self.log)
        self.log("ORA configure erfolgreich abgeschlossen")

    def _start_monitor(self, source_topic: str, source_base: str) -> None:
        client = mqtt.Client(client_id=f"car2mqtt-gwmmon-{uuid.uuid4().hex[:8]}")
        self._monitor_client = client
        if self.settings.username:
            client.username_pw_set(self.settings.username, self.settings.password)
        if self.settings.tls:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        subscribed_event = threading.Event()

        def _on_connect(_client, _userdata, _flags, rc, _properties=None):
            if rc == 0:
                self.log("ORA MQTT Monitor verbunden")
                _client.subscribe(source_topic, qos=self.settings.qos)
                self.log(f"ORA MQTT Subscribe gesendet: {source_topic}")
                subscribed_event.set()
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
        if not subscribed_event.wait(10):
            raise RuntimeError(f"ORA MQTT Monitor Subscribe Timeout für {source_topic}")
        time.sleep(0.5)

    def _start_run(self, config_path: Path) -> None:
        env = os.environ.copy()
        env["OPENSSL_CONF"] = "/opt/ora2mqtt/openssl.cnf"
        polling_enabled = self.vehicle.provider_config.get("polling_enabled", True)
        interval = str(int(self.vehicle.provider_config.get("poll_interval", 60) or 60))
        cmd = [str(self._ora_bin()), "run", "-c", str(config_path)]
        if polling_enabled:
            cmd.extend(["-i", interval])
            self.log(f"ORA Runner wird gestartet (Polling aktiv, Intervall {interval}s)")
        else:
            self.log("ORA Runner wird gestartet (Polling deaktiviert, nur Event-/Live-basiert)")
        if self.vehicle.provider_config.get("fallback_on_silence", True):
            self.log("ORA Fallback bei ausbleibenden Events: aktiv")
        else:
            self.log("ORA Fallback bei ausbleibenden Events: deaktiviert")
        self._proc = subprocess.Popen(
            cmd,
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
        while not self._stop.is_set():
            auto_reconnect = self.vehicle.provider_config.get("auto_reconnect", True)
            delayed_retry_enabled = self.vehicle.provider_config.get("delayed_retry_enabled", True)
            retry_delay_minutes = int(self.vehicle.provider_config.get("retry_delay_minutes", 55) or 55)
            retry_delay_minutes = max(15, min(60, retry_delay_minutes))
            backoff = retry_delay_minutes * 60 if delayed_retry_enabled else 30

            try:
                config_path = self._prepare_runtime_files()
                code_file = self.vehicle_dir / "verification_code.txt"
                has_tokens, missing = has_usable_ora_tokens(self.vehicle.provider_config)

                # configure only when explicitly needed:
                # 1) verification code was manually provided
                # 2) there are no reusable tokens
                should_configure = code_file.exists() or (not has_tokens)

                if should_configure:
                    if code_file.exists():
                        self.log("ORA configure nötig - Verifikationscode liegt vor")
                    else:
                        self.log(f"ORA configure nötig - keine gültigen Tokens vorhanden (fehlend: {', '.join(missing)})")
                    self.on_detail("ORA Konfiguration und Login wird aufgebaut")
                    self._run_configure(config_path)
                else:
                    self.log("ORA Start ohne configure - Tokens vorhanden")

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
                message = str(exc)
                if "ORA_WAITING_FOR_CODE" in message or "ORA_AUTH_FATAL" in message:
                    try:
                        self._session_marker_path().unlink(missing_ok=True)
                    except Exception:
                        pass
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
                if not auto_reconnect:
                    self.log("ORA Auto-Reconnect ist deaktiviert - Worker wird beendet")
                    break
            finally:
                if self._monitor_client:
                    try:
                        self._monitor_client.loop_stop()
                        self._monitor_client.disconnect()
                    except Exception:
                        pass
                    self._monitor_client = None
                if self._proc and self._proc.poll() is None:
                    try:
                        self._proc.terminate()
                        self._proc.wait(timeout=5)
                    except Exception:
                        pass
                self._proc = None

            if not auto_reconnect:
                break
            if delayed_retry_enabled:
                self.log(f"ORA Retry mit Delay aktiv - nächster Versuch in {retry_delay_minutes} Minuten")
            else:
                self.log("ORA Retry ohne Delay aktiv - nächster Versuch in 30 Sekunden")
            if self._stop.wait(backoff):
                break
            self.on_detail("ORA Verbindung wird erneut aufgebaut")
