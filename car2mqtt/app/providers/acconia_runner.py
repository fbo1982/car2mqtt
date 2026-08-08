from __future__ import annotations

import threading
from typing import Any, Callable

from app.providers.acconia_api import AcconiaSilenceApi


class AcconiaPollingWorker:
    """Small stoppable polling worker for the MySilence cloud API."""

    def __init__(
        self,
        vehicle,
        on_payload: Callable[[dict[str, Any]], None],
        on_connect: Callable[[], None],
        on_error: Callable[[str], None],
        on_detail: Callable[[str], None],
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.vehicle = vehicle
        self.on_payload = on_payload
        self.on_connect = on_connect
        self.on_error = on_error
        self.on_detail = on_detail
        self.log_callback = log_callback or (lambda _message: None)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=f"mysilence-{self.vehicle.id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    @staticmethod
    def _normalize(value: Any) -> str:
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    def _select_scooter(self, scooters: list[dict[str, Any]]) -> dict[str, Any]:
        if not scooters:
            raise RuntimeError("Im MySilence Konto wurde kein Fahrzeug gefunden")

        cfg = self.vehicle.provider_config or {}
        selector_value = cfg.get("scooter_id") or cfg.get("frame_no") or cfg.get("imei") or cfg.get("vehicle_id")
        selector = self._normalize(selector_value)
        if not selector:
            if len(scooters) > 1:
                self.log_callback("Mehrere MySilence Fahrzeuge gefunden; erstes Fahrzeug wird verwendet. Für eine feste Auswahl FrameNo, IMEI oder Name eintragen.")
            return scooters[0]

        candidate_keys = ("frameNo", "frame_no", "imei", "name", "id", "vehicleId", "scooterId")
        for scooter in scooters:
            values = [self._normalize(scooter.get(key)) for key in candidate_keys]
            if selector in values:
                return scooter

        available = ", ".join(
            str(s.get("name") or s.get("frameNo") or s.get("imei") or "unbekannt") for s in scooters
        )
        raise RuntimeError(f"MySilence Fahrzeug '{selector_value}' nicht gefunden. Verfügbar: {available}")

    def _run(self) -> None:
        cfg = self.vehicle.provider_config or {}
        api = AcconiaSilenceApi(
            account=str(cfg.get("account") or cfg.get("username") or ""),
            password=str(cfg.get("password", "")),
            api_key=str(cfg.get("api_key") or cfg.get("apikey") or ""),
        )
        try:
            interval = int(cfg.get("poll_interval", 60) or 60)
        except (TypeError, ValueError):
            interval = 60
        interval = max(30, min(3600, interval))
        self.on_detail("MySilence Login und erster Datenabruf werden gestartet")
        self.log_callback(f"MySilence Worker gestartet (Polling alle {interval} Sekunden)")

        while not self._stop_event.is_set():
            try:
                scooters = api.fetch_scooters()
                scooter = self._select_scooter(scooters)
                self.on_payload(scooter)
                if not self._connected:
                    self._connected = True
                    self.on_connect()
                    self.log_callback("MySilence Verbindung hergestellt")
            except Exception as exc:
                self._connected = False
                message = str(exc) or exc.__class__.__name__
                self.log_callback(f"MySilence Fehler: {message}")
                self.on_error(message)

            if self._stop_event.wait(interval):
                break

        self.log_callback("MySilence Worker beendet")
