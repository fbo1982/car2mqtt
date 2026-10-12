from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.server as server
from app.core.config_store import ConfigStore
from app.core.models import AppConfig, VehicleConfig
from app.providers import silence_http_trace as trace
from app.providers.acconia_provider import AcconiaProvider

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def trace_client(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MQTT_HOST', '')
    monkeypatch.setattr(trace, 'TRACE_DIR', tmp_path / 'traces')
    monkeypatch.setattr(server.WorkerManager, '_resolve_server_name', lambda self: 'local')
    for method in ('start_or_restart_vehicle', 'stop_vehicle', '_publish_meta', 'sync_vehicle_to_forward_clients'):
        monkeypatch.setattr(server.WorkerManager, method, lambda *args, **kwargs: None)
    monkeypatch.setattr(server, 'publish_vehicle_discovery', lambda *args, **kwargs: 0)
    store = ConfigStore(str(tmp_path))
    store.save(AppConfig(vehicles=[
        VehicleConfig(id='TEST', label='Silence', manufacturer='acconia', license_plate='TEST',
                      provider_config={'account': 'test@example.invalid', 'password': 'dummy'}),
        VehicleConfig(id='BMW', label='BMW', manufacturer='bmw', license_plate='BMW'),
    ]))
    app = server.create_app()
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, store


def test_all_html_ids_are_unique_and_controls_belong_to_their_dialogs():
    class IdParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = []
            self.dialog = None
            self.owners = {}
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'dialog':
                self.dialog = attrs.get('id')
            if 'id' in attrs:
                self.ids.append(attrs['id'])
                self.owners[attrs['id']] = self.dialog
        def handle_endtag(self, tag):
            if tag == 'dialog':
                self.dialog = None
    parser = IdParser()
    parser.feed((ROOT / 'app/templates/index.html').read_text(encoding='utf-8'))
    assert not [key for key, count in Counter(parser.ids).items() if count > 1]
    assert parser.owners['acconiaHttpRawDebug'] == 'wizardDialog'
    for key in ('editAcconiaHttpRawDebug', 'silenceRawLogBtn', 'silenceRawLogDownloadBtn', 'silenceRawLogViewer'):
        assert parser.owners[key] == 'editDialog'


@pytest.mark.parametrize('download', [False, True])
def test_missing_log_has_explicit_status_and_is_not_a_download(trace_client, download):
    client, store = trace_client
    before = store.config_file.read_bytes()
    response = client.get('/api/vehicles/TEST/mysilence/http-trace', params={'download': download})
    assert response.status_code == 404
    assert response.headers['x-car2mqtt-trace-status'] == 'missing'
    assert 'Noch keine HTTP-Diagnoselogdatei' in response.text
    assert 'nächsten Poll' in response.text
    assert 'content-disposition' not in response.headers
    assert response.headers['cache-control'] == 'no-store'
    assert not trace.TRACE_DIR.exists()
    assert store.config_file.read_bytes() == before


@pytest.mark.parametrize('text,state', [('', 'empty'), ('Anfrage: äöü\n<script>alert(1)</script>\n', 'available')])
@pytest.mark.parametrize('download', [False, True])
def test_existing_log_is_plain_text_with_optional_attachment(trace_client, text, state, download):
    client, _ = trace_client
    trace.TRACE_DIR.mkdir()
    (trace.TRACE_DIR / 'TEST.log').write_text(text, encoding='utf-8', newline='\n')
    response = client.get('/api/vehicles/TEST/mysilence/http-trace', params={'download': download})
    assert response.status_code == 200
    assert response.text == text
    assert response.headers['content-type'] == 'text/plain; charset=utf-8'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-car2mqtt-trace-status'] == state
    assert ('content-disposition' in response.headers) is download
    if download:
        assert response.headers['content-disposition'] == 'attachment; filename="mysilence-http-diagnose.log"'


@pytest.mark.parametrize('vehicle_id', ['MISSING', 'BMW'])
def test_unknown_or_wrong_provider_is_not_reported_as_missing_file(trace_client, vehicle_id):
    client, _ = trace_client
    response = client.get(f'/api/vehicles/{vehicle_id}/mysilence/http-trace')
    assert response.status_code == 404
    assert response.text == 'MySilence Fahrzeug nicht gefunden'
    assert 'x-car2mqtt-trace-status' not in response.headers


def test_unreadable_log_returns_safe_error(trace_client, monkeypatch):
    client, _ = trace_client
    def fail(vehicle_id):
        raise PermissionError('PRIVATE-PATH')
    monkeypatch.setattr(server, 'read_trace', fail)
    response = client.get('/api/vehicles/TEST/mysilence/http-trace?download=true')
    assert response.status_code == 500
    assert response.headers['x-car2mqtt-trace-status'] == 'error'
    assert 'PRIVATE-PATH' not in response.text
    assert 'content-disposition' not in response.headers


def test_read_trace_missing_empty_and_safe_identifier(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, 'TRACE_DIR', tmp_path / 'logs')
    assert trace.read_trace('TEST') is None
    assert not trace.TRACE_DIR.exists()
    trace.TRACE_DIR.mkdir()
    (trace.TRACE_DIR / 'TEST.log').write_bytes(b'')
    assert trace.read_trace('TEST') == ''
    (trace.TRACE_DIR / '___OUTSIDE.log').write_bytes(b'local\xff')
    (tmp_path / 'OUTSIDE.log').write_text('outside')
    assert trace.read_trace('../OUTSIDE') == 'local\ufffd'


def test_diagnostic_toggle_persists_both_values(trace_client):
    client, store = trace_client
    for enabled in (True, False):
        payload = client.get('/api/vehicles/TEST').json()
        payload['provider_config']['http_raw_debug'] = enabled
        response = client.put('/api/vehicles/TEST', json=payload)
        assert response.status_code == 200, response.text
        assert store.get_vehicle('TEST').provider_config['http_raw_debug'] is enabled
        assert client.get('/api/vehicles/TEST').json()['provider_config']['http_raw_debug'] is enabled


@pytest.mark.parametrize('value,expected', [(True, True), (False, False), (None, False), ('true', False), ('false', False), (1, False)])
def test_diagnostic_config_requires_explicit_boolean_opt_in(value, expected):
    config = AcconiaProvider().validate_config({'account': 'test@example.invalid', 'password': 'dummy',
                                               'http_raw_debug': value})
    assert config['http_raw_debug'] is expected


def test_new_vehicle_persists_diagnostic_opt_in(trace_client):
    client, store = trace_client
    response = client.post('/api/vehicles', json={
        'id': 'NEW', 'label': 'New Silence', 'manufacturer': 'acconia', 'license_plate': 'NEW',
        'provider_config': {'account': 'test@example.invalid', 'password': 'dummy', 'http_raw_debug': True},
    })
    assert response.status_code == 200, response.text
    assert store.get_vehicle('NEW').provider_config['http_raw_debug'] is True
