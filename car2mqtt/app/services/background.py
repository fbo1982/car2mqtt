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
