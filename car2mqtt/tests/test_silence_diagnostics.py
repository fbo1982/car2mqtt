import json
import threading
import time

import pytest
import requests
from fastapi.testclient import TestClient

from app.providers import acconia_diagnostics as diag


class Response:
    def __init__(self, status, data=None):
        self.status_code = status
        self.data = data
        self.closed = False
    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data
    def close(self):
        self.closed = True


def test_variants_compare_authenticated_calls_without_exposing_data(monkeypatch):
    calls, responses, logs = [], [], []
    secret = 'SECRET-BEARER-TOKEN'
    monkeypatch.setattr(diag.AcconiaSilenceApi, '_login', lambda self: secret)
    def get(url, **kwargs):
        calls.append((url, kwargs))
        response = Response(401) if len(calls) == 1 else Response(200, [{
            'frameNo': 'PRIVATE-VIN', 'imei': 'PRIVATE-IMEI', 'batterySoc': 73,
            'lastLocation': {'latitude': 48.123456, 'longitude': 11.654321},
        }])
        responses.append(response)
        return response
    monkeypatch.setattr(diag.requests, 'get', get)
    result = diag.run_silence_diagnostics({'account': 'PRIVATE-EMAIL', 'password': 'PRIVATE-PASSWORD'}, logs.append)
    assert len(calls) == 4
    assert 'authorization' not in calls[0][1]['headers']
    for (_, kwargs) in calls[1:]:
        assert kwargs['headers']['authorization'] == secret
        assert kwargs['timeout'] == (5, 30)
        assert kwargs['allow_redirects'] is False
    assert calls[1][0].endswith('details=true&dynamic=false&pollIfNecessary=false')
    assert calls[2][0].endswith('details=true&dynamic=true&pollIfNecessary=false')
    assert calls[3][0] == diag.AcconiaSilenceApi.SCOOTERS_URL
    assert all(response.closed for response in responses)
    assert all(step['vehicle_count'] == 1 and step['has_location'] for step in result[1:])
    report = json.dumps(result) + '\n'.join(logs)
    for private in [secret, 'PRIVATE-VIN', 'PRIVATE-IMEI', 'PRIVATE-EMAIL', 'PRIVATE-PASSWORD', '48.123456', '11.654321']:
        assert private not in report


def test_timeout_is_sanitized_and_other_variants_still_run(monkeypatch):
    logs, calls = [], []
    monkeypatch.setattr(diag.AcconiaSilenceApi, '_login', lambda self: 'token')
    def get(url, **kwargs):
        calls.append(url)
        if len(calls) == 2:
            raise requests.ReadTimeout('SECRET request content')
        return Response(401 if len(calls) == 1 else 200, [])
    monkeypatch.setattr(diag.requests, 'get', get)
    steps = diag.run_silence_diagnostics({}, logs.append)
    assert len(calls) == 4
    assert steps[1]['error'] == 'Zeitüberschreitung'
    assert 'SECRET' not in json.dumps(steps) + ''.join(logs)


@pytest.mark.parametrize('status', [401, 403, 429])
def test_rejected_authenticated_request_stops_further_probes(monkeypatch, status):
    calls, logs = [], []
    monkeypatch.setattr(diag.AcconiaSilenceApi, '_login', lambda self: 'token')
    def get(url, **kwargs):
        calls.append(url)
        return Response(status)
    monkeypatch.setattr(diag.requests, 'get', get)
    steps = diag.run_silence_diagnostics({}, logs.append)
    assert len(calls) == 2
    assert steps[-1]['http_status'] == status


def test_failed_login_is_sanitized_and_stops(monkeypatch):
    calls, logs = [], []
    monkeypatch.setattr(diag.requests, 'get', lambda *args, **kwargs: (calls.append(1) or Response(401)))
    def fail(self):
        raise RuntimeError('SECRET PASSWORD')
    monkeypatch.setattr(diag.AcconiaSilenceApi, '_login', fail)
    diag.run_silence_diagnostics({}, logs.append)
    assert calls == [1]
    assert 'SECRET' not in ''.join(logs)
    assert any('Anmeldung: Keine erfolgreiche Antwort' in line for line in logs)


def test_cancel_stops_before_login(monkeypatch):
    calls = []
    monkeypatch.setattr(diag.requests, 'get', lambda *args, **kwargs: (calls.append(1) or Response(401)))
    def unexpected(self):
        pytest.fail('Login after cancellation')
    monkeypatch.setattr(diag.AcconiaSilenceApi, '_login', unexpected)
    diag.run_silence_diagnostics({}, lambda msg: None, cancelled=lambda: bool(calls))
    assert calls == [1]


def test_json_error_or_error_object_is_not_counted_as_vehicle(monkeypatch):
    for payload, expected in [(ValueError('PRIVATE RESPONSE'), None), ({'message': 'PRIVATE RESPONSE'}, 0)]:
        response = Response(200, payload)
        logs = []
        monkeypatch.setattr(diag.requests, 'get', lambda *args, **kwargs: response)
        result = diag._probe('Test', diag.BASE_URL, {}, logs.append)
        assert result.get('vehicle_count') == expected
        assert 'PRIVATE RESPONSE' not in ''.join(logs)
        assert response.closed


def test_diagnostic_route_returns_immediately_and_prevents_duplicate_runs(tmp_path, monkeypatch):
    import app.api.server as server
    from app.core.config_store import ConfigStore
    from app.core.models import AppConfig, VehicleConfig
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MQTT_HOST', '')
    store = ConfigStore(str(tmp_path))
    store.save(AppConfig(vehicles=[VehicleConfig(id='TEST', label='Test', manufacturer='acconia',
        license_plate='TEST', provider_config={'account': 'private-account', 'password': 'private-password'})]))
    before = store.config_file.read_bytes()
    entered, release = threading.Event(), threading.Event()
    def blocked(config, log, cancelled):
        assert config['password'] == 'private-password'
        entered.set()
        release.wait(2)
        log('MySilence Diagnose: Test beendet')
    monkeypatch.setattr(server, 'run_silence_diagnostics', blocked)
    app = server.create_app()
    client = TestClient(app)
    try:
        started = time.monotonic()
        result = client.post('/api/vehicles/TEST/mysilence/diagnostics')
        assert result.status_code == 202
        assert time.monotonic() - started < 0.5
        assert entered.wait(1)
        assert client.post('/api/vehicles/TEST/mysilence/diagnostics').status_code == 409
        assert client.post('/api/vehicles/MISSING/mysilence/diagnostics').status_code == 404
        started = time.monotonic()
        assert client.get('/api/dashboard').status_code == 200
        assert client.get('/api/vehicles/TEST/logs').status_code == 200
        assert time.monotonic() - started < 0.5
        assert store.config_file.read_bytes() == before
        assert not (tmp_path/'state.json').exists()
        app.state.stopping = True
        assert client.post('/api/vehicles/TEST/mysilence/diagnostics').status_code == 503
    finally:
        release.set()
        app.state.silence_diagnostic_job._thread.join(3)
        client.close()
    assert 'private-' not in server.VehicleLogStore(str(tmp_path)).read('TEST')
