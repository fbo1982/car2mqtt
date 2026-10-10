from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger("uvicorn.error")


class BackgroundJob:
    """Run blocking integration work without holding up the ASGI event loop.

    A single daemon owns each operation, including retries and cleanup. A
    timed-out shutdown never starts a second copy of an in-flight operation.
    """

    def __init__(self, name: str, operation: Callable[[], None], *,
                 interval: float | None = None, retry_interval: float = 15.0,
                 cleanup: Callable[[], None] | None = None):
        self.name = name
        self.operation = operation
        self.interval = interval
        self.retry_interval = retry_interval
        self.cleanup = cleanup
        self.state = "pending"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name=f"car2mqtt-{self.name}", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.state = "running"
                logger.debug("Car2MQTT Hintergrund: %s startet", self.name)
                try:
                    self.operation()
                except Exception:
                    self.state = "retrying"
                    logger.exception(
                        "Car2MQTT Hintergrund: %s fehlgeschlagen; neuer Versuch in %.0f s",
                        self.name, self.retry_interval,
                    )
                    delay = self.retry_interval
                else:
                    self.state = "ready"
                    if self.interval is None:
                        logger.info("Car2MQTT Hintergrund: %s bereit", self.name)
                        if self.cleanup:
                            self._stop.wait()
                        return
                    delay = self.interval
                if self._stop.wait(delay):
                    return
        finally:
            try:
                if self.cleanup:
                    self.cleanup()
            except Exception:
                logger.exception("Car2MQTT Hintergrund: %s konnte nicht sauber stoppen", self.name)
            self.state = "stopped"


class ActionQueue:
    """One daemon executes follow-up actions in order, outside HTTP requests."""

    def __init__(self, name):
        from collections import deque
        self.name = name
        self._pending = deque()
        self._condition = threading.Condition()
        self._stopped = False
        self._thread = None
        self.idle = threading.Event()
        self.idle.set()

    def submit(self, name, operation):
        with self._condition:
            if self._stopped:
                raise RuntimeError("Car2MQTT wird beendet")
            self._pending.append((name, operation))
            self.idle.clear()
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name=f"car2mqtt-{self.name}", daemon=True)
                self._thread.start()
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._stopped = True
            self._pending.clear()
            self._condition.notify_all()

    def _run(self):
        import time
        while True:
            with self._condition:
                while not self._pending and not self._stopped:
                    self.idle.set()
                    self._condition.wait()
                if self._stopped:
                    self.idle.set()
                    return
                name, operation = self._pending.popleft()
            started = time.monotonic()
            logger.info("Car2MQTT: %s beginnt", name)
            try:
                operation()
            except Exception:
                logger.exception("Car2MQTT: %s fehlgeschlagen", name)
            else:
                logger.info("Car2MQTT: %s abgeschlossen (%.2f s)", name, time.monotonic() - started)
