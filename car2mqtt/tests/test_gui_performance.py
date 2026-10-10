import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import app.api.server as server
from app.core.config_store import ConfigStore
from app.core.models import AppConfig, VehicleConfig, RuntimeMqttSettings
from app.mqtt.client import LocalMqttClient
from app.services.background import ActionQueue


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('MQTT_HOST', 'test-broker.invalid')
    monkeypatch.setattr(server.WorkerManager, '_resolve_server_name', lambda self: 'local')
    monkeypatch.setattr(server.WorkerManager, 'start_or_restart_vehicle', lambda *args: None)
    monkeypatch.setattr(server.WorkerManager, 'stop_vehicle', lambda *args: None)
    monkeypatch.setattr(server.WorkerManager, '_publish_meta', lambda *args: None)
    monkeypatch.setattr(server.WorkerManager, 'sync_vehicle_to_forward_clients', lambda *args: None)
    monkeypatch.setattr(server.EvccGeoFilterService, 'start', lambda *args: None)
    monkeypatch.setattr(server.EvccGeoFilterService, 'stop', lambda *args: None)
    monkeypatch.setattr(server.EvccGeoFilterService, 'restart', lambda *args: None)
    monkeypatch.setattr(server, '_discover_remote_vehicle_snapshots', lambda *args: [])
    monkeypatch.setattr(server, '_load_homeassistant_zones', lambda: [])
    monkeypatch.setattr(server, '_read_detected_homezone', lambda: {'entity_id': 'zone.home'})
    monkeypatch.setattr(server, '_publish_device_trackers', lambda *args: None)
    monkeypatch.setattr(server, 'publish_all_discovery', lambda *args: 0)
    monkeypatch.setattr(server, 'publish_vehicle_discovery', lambda *args, **kwargs: 0)
    monkeypatch.setattr(server, 'clear_vehicle_discovery', lambda *args, **kwargs: 0)
    vehicle = VehicleConfig(id='SILENCE', label='Silence', manufacturer='acconia', license_plate='SILENCE', enabled=False,
                            provider_config={'account': 'test@example.invalid', 'password': 'dummy'})
    vehicle.provider_state.auth_state = 'authorized'
    cfg = AppConfig(vehicles=[vehicle])
    cfg.ui_settings.ha_discovery_enabled = True
    ConfigStore(str(tmp_path)).save(cfg)
    app = server.create_app()
    with TestClient(app) as client:
        yield app, client, ConfigStore(str(tmp_path)), monkeypatch
    for queue in getattr(app.state, 'action_queues', []):
        queue.stop()
        if queue._thread:
            queue._thread.join(3)
    for job in app.state.background_jobs:
        job._thread.join(3)


def payload(enabled=True):
    return {'id': 'SILENCE', 'label': 'Silence', 'manufacturer': 'acconia', 'license_plate': 'SILENCE',
            'enabled': enabled, 'provider_config': {'account': 'test@example.invalid', 'password': 'dummy'},
            'mqtt_client_ids': [], 'device_tracker_enabled': False, 'geo_shelly_trigger_enabled': False}


@pytest.mark.parametrize('step,enabled', [('start', True), ('stop', False), ('meta', True), ('forward', True), ('discovery', True)])
def test_vehicle_save_returns_while_network_followup_is_blocked(gui, step, enabled):
    app, client, store, monkeypatch = gui
    entered = threading.Event()
    release = threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        release.wait(2)
        return 0
    targets = {
        'start': (server.WorkerManager, 'start_or_restart_vehicle'),
        'stop': (server.WorkerManager, 'stop_vehicle'),
        'meta': (server.WorkerManager, '_publish_meta'),
        'forward': (server.WorkerManager, 'sync_vehicle_to_forward_clients'),
        'discovery': (server, 'publish_vehicle_discovery'),
    }
    monkeypatch.setattr(*targets[step], blocked)
    try:
        started = time.monotonic()
        response = client.put('/api/vehicles/SILENCE', json=payload(enabled))
        elapsed = time.monotonic() - started
        assert response.status_code == 200, response.text
        assert elapsed < 0.5, f'Save waited {elapsed:.3f}s for {step}'
        assert store.get_vehicle('SILENCE').enabled is enabled
        assert entered.wait(1), step
        for route in ('/', '/api/dashboard', '/api/vehicles/SILENCE/logs', '/api/settings'):
            started = time.monotonic()
            assert client.get(route).status_code == 200
            assert time.monotonic() - started < 0.5, route
    finally:
        release.set()
        for queue in getattr(app.state, 'action_queues', []):
            assert queue.idle.wait(3)


def test_toggle_does_not_restart_geo(gui):
    app, client, _, monkeypatch = gui
    calls = []
    monkeypatch.setattr(server.EvccGeoFilterService, 'restart', lambda self: calls.append(1))
    for enabled in (True, False):
        assert client.put('/api/vehicles/SILENCE', json=payload(enabled)).status_code == 200
        for queue in app.state.action_queues:
            assert queue.idle.wait(2)
    assert not calls


def test_changed_geo_selection_is_applied_in_background(gui):
    app, client, _, monkeypatch = gui
    calls = []
    monkeypatch.setattr(server.EvccGeoFilterService, 'restart', lambda self: calls.append(1))
    data = payload()
    data['geo_shelly_trigger_enabled'] = True
    assert client.put('/api/vehicles/SILENCE', json=data).status_code == 200
    for queue in app.state.action_queues:
        assert queue.idle.wait(2)
    assert calls == [1]


def test_settings_save_returns_before_geo_restart_finishes(gui):
    app, client, _, monkeypatch = gui
    release = threading.Event()
    entered = threading.Event()
    def blocked(self):
        entered.set()
        release.wait(2)
    monkeypatch.setattr(server.EvccGeoFilterService, 'restart', blocked)
    try:
        started = time.monotonic()
        response = client.post('/api/settings/homezone', json={'helper_home_zone_entity_id': 'zone.home'})
        assert response.status_code == 200, response.text
        assert time.monotonic() - started < 0.5
        assert entered.wait(1)
        assert client.get('/api/dashboard').status_code == 200
    finally:
        release.set()


def test_slow_explicit_mqtt_test_does_not_freeze_other_requests(gui):
    _, client, _, monkeypatch = gui
    entered = threading.Event()
    release = threading.Event()
    def blocked(settings):
        entered.set()
        release.wait(2)
        return {'status': 'ok'}
    monkeypatch.setattr(server, 'test_connection', blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, '/api/mqtt/test')
        try:
            assert entered.wait(1)
            started = time.monotonic()
            assert client.get('/api/dashboard').status_code == 200
            assert time.monotonic() - started < 0.5
        finally:
            release.set()
        assert pending.result().status_code == 200


def test_action_failure_does_not_skip_later_steps():
    queue = ActionQueue('test')
    reached = threading.Event()
    try:
        queue.submit('broken', lambda: (_ for _ in ()).throw(ConnectionError('offline')))
        queue.submit('next', reached.set)
        assert reached.wait(1)
        assert queue.idle.wait(1)
    finally:
        queue.stop()
        queue._thread.join(1)


def test_stop_discards_pending_actions_without_restarting_them():
    queue = ActionQueue('test')
    entered, release, unexpected = threading.Event(), threading.Event(), threading.Event()
    def blocked():
        entered.set()
        release.wait(2)
    queue.submit('running', blocked)
    assert entered.wait(1)
    queue.submit('pending', unexpected.set)
    queue.stop()
    release.set()
    queue._thread.join(1)
    assert not unexpected.is_set()


def test_mqtt_unconfirmed_publish_is_a_timeout(monkeypatch):
    class Info:
        rc = 0
        def wait_for_publish(self, timeout):
            assert timeout == 5
        def is_published(self):
            return False
    class Client:
        def __init__(self, **kwargs):
            pass
        def publish(self, *args, **kwargs):
            return Info()
    monkeypatch.setattr('app.mqtt.client.mqtt.Client', Client)
    client = LocalMqttClient(RuntimeMqttSettings(host='unused'))
    with pytest.raises(TimeoutError):
        client.publish('test', 1)


def test_mqtt_forward_sync_reuses_connection_for_all_values(tmp_path, monkeypatch):
    from app.core.models import MqttForwardClientConfig, VehicleRuntimeState
    from app.core.state_store import StateStore
    import app.services.worker_manager as module
    monkeypatch.setenv('MQTT_HOST', 'local.invalid')
    config = ConfigStore(str(tmp_path))
    vehicle = VehicleConfig(id='TEST', label='Test', manufacturer='bmw', license_plate='TEST', mqtt_client_ids=['remote'])
    cfg = AppConfig(vehicles=[vehicle], mqtt_clients=[MqttForwardClientConfig(id='remote', name='Remote', host='remote.invalid', base_topic='other')])
    config.save(cfg)
    states = StateStore(str(tmp_path))
    states.upsert(VehicleRuntimeState(vehicle_id='TEST', metrics={'soc': 70, 'range': 200, 'odometer': 1234}))
    manager = module.WorkerManager(str(tmp_path), config, states)
    monkeypatch.setattr(manager, '_resolve_server_name', lambda: 'local')
    connects, messages, disconnects = [], [], []
    class FakeClient:
        def __init__(self, settings):
            self.settings = settings
        def connect(self):
            connects.append(self.settings.host)
        def publish(self, topic, payload):
            messages.append((topic, payload))
        def disconnect(self):
            disconnects.append(1)
    monkeypatch.setattr(module, 'LocalMqttClient', FakeClient)
    try:
        manager.sync_vehicle_to_forward_clients('TEST')
        assert manager._forwarders['remote'].idle.wait(2)
    finally:
        manager.stop_forwarding()
        for sender in manager._forwarders.values():
            sender._thread.join(2)
    assert connects == ['remote.invalid']
    assert disconnects == [1]
    assert len(messages) == 13
    assert ('other/bmw/TEST/mapped/soc', 70) in messages


def test_failed_forward_batch_attempts_connection_once(tmp_path, monkeypatch):
    from app.core.models import MqttForwardClientConfig
    from app.core.state_store import StateStore
    import app.services.worker_manager as module
    config = ConfigStore(str(tmp_path))
    vehicle = VehicleConfig(id='TEST', label='Test', manufacturer='bmw', license_plate='TEST', mqtt_client_ids=['remote'])
    config.save(AppConfig(vehicles=[vehicle], mqtt_clients=[MqttForwardClientConfig(id='remote', name='Remote', host='offline.invalid')]))
    manager = module.WorkerManager(str(tmp_path), config, StateStore(str(tmp_path)))
    connects = []
    class FakeClient:
        def __init__(self, settings):
            pass
        def connect(self):
            connects.append(1)
            raise ConnectionError('offline')
        def disconnect(self):
            pass
    monkeypatch.setattr(module, 'LocalMqttClient', FakeClient)
    try:
        manager._forward_batch(vehicle, RuntimeMqttSettings(host='local'), [('car/bmw/TEST/mapped/soc', 1)] * 30, is_raw=False)
        deadline = time.monotonic() + 2
        while not manager._load_forward_status() and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        manager.stop_forwarding()
        for sender in manager._forwarders.values():
            sender._thread.join(2)
    assert connects == [1]
    assert manager._load_forward_status()['remote']['last_error'] == 'offline'


def test_successful_server_name_is_cached(tmp_path, monkeypatch):
    from app.core.state_store import StateStore
    import app.services.worker_manager as module
    manager = module.WorkerManager(str(tmp_path), ConfigStore(str(tmp_path)), StateStore(str(tmp_path)))
    calls = []
    class Response:
        ok = True
        def json(self):
            return {'data': {'hostname': 'home-server'}}
    def get(*args, **kwargs):
        calls.append(1)
        return Response()
    monkeypatch.setattr(module.requests, 'get', get)
    assert manager._resolve_server_name() == 'home-server'
    assert manager._resolve_server_name() == 'home-server'
    assert calls == [1]
    manager._server_name_cache = ('old', 0)
    assert manager._resolve_server_name() == 'home-server'
    assert calls == [1, 1]


def test_atomic_config_updates_allow_concurrent_readers(tmp_path):
    config = ConfigStore(str(tmp_path))
    config.save(AppConfig())
    reader = ConfigStore(str(tmp_path))
    stop = threading.Event()
    errors = []
    def read():
        while not stop.is_set():
            try:
                reader.load()
            except Exception as exc:
                errors.append(exc)
                return
    thread = threading.Thread(target=read)
    thread.start()
    try:
        for index in range(30):
            config.upsert_vehicle(VehicleConfig(id='TEST', manufacturer='bmw', license_plate='TEST', label=str(index)))
    finally:
        stop.set()
        thread.join(2)
    assert not errors
    assert reader.get_vehicle('TEST').label == '29'


def test_page_and_mqtt_crud_do_not_wait_for_unreachable_destination(gui):
    from app.core.models import MqttForwardClientConfig
    app, client, store, monkeypatch = gui
    cfg = store.load()
    cfg.mqtt_clients = [MqttForwardClientConfig(id='hogo', host='offline.invalid')]
    store.save(cfg)
    release, entered = threading.Event(), threading.Event()
    def blocked(settings):
        entered.set()
        release.wait(2)
        raise TimeoutError('offline')
    monkeypatch.setattr(server, 'test_connection', blocked)
    refresh = next(job.operation for job in app.state.background_jobs if job.name == 'MQTT Client Status')
    thread = threading.Thread(target=refresh)
    thread.start()
    try:
        assert entered.wait(1)
        for route in ('/', '/api/mqtt-clients', '/api/dashboard'):
            started = time.monotonic()
            assert client.get(route).status_code == 200
            assert time.monotonic() - started < 0.5
        started = time.monotonic()
        result = client.post('/api/mqtt-clients', json={'id': 'hogo', 'host': 'changed.invalid'})
        assert result.status_code == 200
        assert result.json()['client']['status'] == 'unknown'
        assert time.monotonic() - started < 0.5
        started = time.monotonic()
        assert client.delete('/api/mqtt-clients/hogo').status_code == 200
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        thread.join(3)


def test_failed_healthcheck_closes_client(monkeypatch):
    import app.mqtt.client as module
    closed = []
    class FakeClient:
        def __init__(self, settings):
            pass
        def connect(self):
            raise TimeoutError('offline')
        def disconnect(self):
            closed.append(True)
    monkeypatch.setattr(module, 'LocalMqttClient', FakeClient)
    with pytest.raises(TimeoutError):
        module.test_connection(RuntimeMqttSettings(host='offline'))
    assert closed == [True]
