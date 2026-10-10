from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import logging
import threading
import time


class ForwardBuffer:
    """Bounded latest-value buffer; each destination owns its network thread."""

    def __init__(self, name, send, *, retry_seconds=30.0, max_topics=2000):
        self.send = send
        self.retry_seconds = retry_seconds
        self.max_topics = max_topics
        self._pending = OrderedDict()
        self._condition = threading.Condition()
        self._stopped = False
        self._retry_at = 0.0
        self.idle = threading.Event()
        self.idle.set()
        self._thread = threading.Thread(target=self._run, name=f"mqtt-forward-{name}", daemon=True)
        self._thread.start()

    def submit(self, messages):
        with self._condition:
            if self._stopped:
                return
            for key, value in messages:
                self._pending[key] = deepcopy(value)
                self._pending.move_to_end(key)
            self._trim()
            if self._pending:
                self.idle.clear()
            self._condition.notify_all()

    def _trim(self):
        while len(self._pending) > self.max_topics:
            self._pending.popitem(last=False)

    def stop(self):
        with self._condition:
            self._stopped = True
            self._pending.clear()
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                while not self._stopped:
                    if not self._pending:
                        self.idle.set()
                        self._condition.wait()
                        continue
                    delay = self._retry_at - time.monotonic()
                    if delay > 0:
                        self._condition.wait(delay)
                        continue
                    batch = self._pending
                    self._pending = OrderedDict()
                    break
                if self._stopped:
                    self.idle.set()
                    return
            try:
                self.send(batch)
            except Exception:
                logging.getLogger(__name__).debug("MQTT Weiterleitung wartet auf erneuten Versuch", exc_info=True)
                with self._condition:
                    if not self._stopped:
                        # Values received during the failed attempt supersede its snapshot.
                        for key, value in self._pending.items():
                            batch[key] = value
                            batch.move_to_end(key)
                        self._pending = batch
                        self._trim()
                        self._retry_at = time.monotonic() + self.retry_seconds
            else:
                self._retry_at = 0.0
