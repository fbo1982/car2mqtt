from types import SimpleNamespace

from app.providers.bmw import streaming


class _StopAfter:
    def __init__(self, waits):
        self.waits = waits
        self.calls = 0

    def is_set(self):
        return False

    def wait(self, _seconds):
        self.calls += 1
        return self.calls > self.waits

    def set(self):
        pass

    def clear(self):
        pass


class _FakeClient:
    def __init__(self, connect_results, token_expiring=False, refresh_error=None):
        self.connect_results = list(connect_results)
        self.token_expiring = token_expiring
        self.refresh_error = refresh_error
        self.connected = False
        self.connect_calls = 0
        self.refresh_calls = 0
        self.mqtt_username = "test-gcid"
        self.subscribe_topic = ""
        self.wildcard_topic = ""
        self.subscribe_wildcard = False

    def set_message_callback(self, _callback):
        pass

    def set_connect_callback(self, _callback):
        pass

    def set_disconnect_callback(self, _callback):
        pass

    def connect_mqtt(self):
        self.connect_calls += 1
        result = self.connect_results.pop(0)
        if isinstance(result, Exception):
            self.connected = False
            raise result
        self.connected = bool(result)
        return self.connected

    def is_connected(self):
        return self.connected

    def _is_token_expiring(self, _token_key, minutes=5):
        return self.token_expiring

    def refresh_tokens(self):
        self.refresh_calls += 1
        if self.refresh_error:
            raise self.refresh_error
        return True


def _worker(logs=None, errors=None):
    vehicle = SimpleNamespace(
        id="bmw-test",
        provider_config={
            "client_id": "client-id",
            "vin": "WBA00000000000000",
            "auto_reconnect": True,
        },
        provider_state=SimpleNamespace(mqtt_username="test-gcid"),
    )
    return streaming.BMWStreamWorker(
        vehicle=vehicle,
        mqtt_settings=None,
        state_store=None,
        local_mqtt_client_factory=None,
        on_payload=lambda _topic, _data: None,
        on_error=(errors.append if errors is not None else None),
        log_callback=(logs.append if logs is not None else None),
    )


def _run_with_fake_client(monkeypatch, worker, fake_client):
    monkeypatch.setattr(streaming.Path, "exists", lambda _path: True)
    monkeypatch.setattr(streaming, "BMWCarDataClient", lambda **_kwargs: fake_client)
    worker._run()


def test_connection_reset_is_retried_without_ending_worker(monkeypatch):
    logs = []
    errors = []
    worker = _worker(logs, errors)
    worker.stop_event = _StopAfter(waits=1)
    worker.RECONNECT_BACKOFF_SECONDS = (0,)
    client = _FakeClient([ConnectionResetError(104, "Connection reset by peer"), True])

    _run_with_fake_client(monkeypatch, worker, client)

    assert client.connect_calls == 2
    assert client.is_connected()
    assert any("Connection reset by peer" in message for message in errors)
    assert any("neuer Versuch in 0 Sekunden" in message for message in logs)


def test_idle_stream_does_not_trigger_message_watchdog_reconnect(monkeypatch):
    worker = _worker()
    worker.stop_event = _StopAfter(waits=1)
    worker.last_message_at = 1.0
    client = _FakeClient([True], token_expiring=False)

    _run_with_fake_client(monkeypatch, worker, client)

    assert client.connect_calls == 1


def test_token_refresh_exception_does_not_end_worker(monkeypatch):
    errors = []
    worker = _worker(errors=errors)
    worker.stop_event = _StopAfter(waits=1)
    client = _FakeClient(
        [True],
        token_expiring=True,
        refresh_error=ConnectionError("temporary token endpoint failure"),
    )

    _run_with_fake_client(monkeypatch, worker, client)

    assert client.refresh_calls == 1
    assert worker.next_token_refresh_at > 0
    assert any("temporary token endpoint failure" in message for message in errors)
