import threading
import time

from app.services.forward_buffer import ForwardBuffer


def stop(sender):
    sender.stop()
    sender._thread.join(2)
    assert not sender._thread.is_alive()


def test_failed_destination_retries_after_delay_with_latest_values():
    failed, release = threading.Event(), threading.Event()
    attempts = []
    def send(batch):
        attempts.append((time.monotonic(), dict(batch)))
        if len(attempts) == 1:
            failed.set()
            release.wait(2)
            raise TimeoutError('offline')
    sender = ForwardBuffer('test', send, retry_seconds=0.15)
    try:
        sender.submit([('soc', 10), ('range', 80)])
        assert failed.wait(1)
        sender.submit([('soc', 90)])
        release.set()
        assert sender.idle.wait(2)
        assert len(attempts) == 2
        assert attempts[1][0] - attempts[0][0] >= 0.15
        assert attempts[1][1] == {'soc': 90, 'range': 80}
    finally:
        release.set()
        stop(sender)


def test_buffer_is_bounded_and_stop_discards_waiting_data():
    entered, release = threading.Event(), threading.Event()
    attempts = []
    def send(batch):
        attempts.append(dict(batch))
        entered.set()
        release.wait(2)
        raise TimeoutError('offline')
    sender = ForwardBuffer('test', send, max_topics=3)
    try:
        sender.submit([('first', 1)])
        assert entered.wait(1)
        sender.submit([(str(i), i) for i in range(100)])
        assert len(sender._pending) == 3
        assert dict(sender._pending) == {'97': 97, '98': 98, '99': 99}
        sender.stop()
        sender.submit([('ignored', 1)])
        release.set()
        sender._thread.join(2)
        assert len(attempts) == 1
        assert not sender._pending
    finally:
        release.set()
        stop(sender)


def test_slow_forward_destination_does_not_block_caller_or_other_target(tmp_path, monkeypatch):
    from app.core.config_store import ConfigStore
    from app.core.state_store import StateStore
    from app.core.models import AppConfig, VehicleConfig, MqttForwardClientConfig, RuntimeMqttSettings
    from app.services.worker_manager import WorkerManager
    config = ConfigStore(str(tmp_path))
    vehicle = VehicleConfig(id='TEST', label='Test', manufacturer='gwm', license_plate='TEST', mqtt_client_ids=['hogo', 'healthy'])
    config.save(AppConfig(vehicles=[vehicle], mqtt_clients=[
        MqttForwardClientConfig(id='hogo', host='offline.invalid'),
        MqttForwardClientConfig(id='healthy', host='healthy.invalid'),
    ]))
    manager = WorkerManager(str(tmp_path), config, StateStore(str(tmp_path)))
    entered, release, healthy = threading.Event(), threading.Event(), threading.Event()
    def publish(client, messages):
        if client.id == 'hogo':
            entered.set()
            release.wait(2)
            raise TimeoutError('offline')
        healthy.set()
    monkeypatch.setattr(manager, '_publish_batch_to_forward_client', publish)
    try:
        started = time.monotonic()
        manager._forward_batch(vehicle, RuntimeMqttSettings(host='local'), [('car/gwm/TEST/mapped/soc', 80)], is_raw=False)
        assert time.monotonic() - started < 0.5
        assert entered.wait(1)
        assert healthy.wait(1)
    finally:
        manager.stop_forwarding()
        release.set()
        for sender in manager._forwarders.values():
            sender._thread.join(2)


def test_retry_rechecks_assignment_and_raw_permission(tmp_path, monkeypatch):
    from app.core.config_store import ConfigStore
    from app.core.state_store import StateStore
    from app.core.models import AppConfig, VehicleConfig, MqttForwardClientConfig
    from app.services.worker_manager import WorkerManager
    config = ConfigStore(str(tmp_path))
    vehicle = VehicleConfig(id='TEST', label='Test', manufacturer='gwm', license_plate='TEST', mqtt_client_ids=['remote'])
    cfg = AppConfig(vehicles=[vehicle], mqtt_clients=[MqttForwardClientConfig(id='remote', host='remote.invalid', base_topic='new')])
    config.save(cfg)
    manager = WorkerManager(str(tmp_path), config, StateStore(str(tmp_path)))
    published = []
    monkeypatch.setattr(manager, '_publish_batch_to_forward_client', lambda client, messages: published.extend(messages))
    batch = {('TEST', 'car', 'car/gwm/TEST/mapped/soc', False): 80,
             ('TEST', 'car', 'car/gwm/TEST/raw/soc', True): 80,
             ('DELETED', 'car', 'car/gwm/OLD/mapped/soc', False): 10}
    manager._deliver_forward_batch('remote', batch)
    assert published == [('new/gwm/TEST/mapped/soc', 80)]
    published.clear()
    cfg.vehicles[0].mqtt_client_ids = []
    config.save(cfg)
    manager._deliver_forward_batch('remote', batch)
    assert not published
