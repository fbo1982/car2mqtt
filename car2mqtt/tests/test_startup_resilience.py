import threading
import time
from collections import Counter

from fastapi.testclient import TestClient

import app.api.server as server
from app.core.config_store import ConfigStore
from app.core.models import AppConfig, VehicleConfig
from app.services.background import BackgroundJob


def configure(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MQTT_HOST", "offline.example.invalid")
    monkeypatch.setattr(server.WorkerManager, "_resolve_server_name", lambda self: "local")
    monkeypatch.setattr(server, "_read_detected_homezone", lambda: {"entity_id": "zone.home"})
    vehicle = VehicleConfig(id="TEST", label="Test", manufacturer="bmw", license_plate="TEST")
    vehicle.provider_state.auth_state = "authorized"
    cfg = AppConfig(vehicles=[vehicle])
    cfg.ui_settings.ha_discovery_enabled = True
    cfg.ui_settings.device_tracker_enabled = True
    ConfigStore(str(tmp_path)).save(cfg)
    return cfg


def test_startup_and_ui_respond_while_all_integrations_are_blocked(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    release = threading.Event()
    entered = {name: threading.Event() for name in ("workers", "geo", "discovery", "remote", "zones", "trackers")}

    def blocked(name, result=None):
        def operation(*args, **kwargs):
            entered[name].set()
            release.wait(3)
            return result
        return operation

    monkeypatch.setattr(server.WorkerManager, "start_or_restart_vehicle", blocked("workers"))
    monkeypatch.setattr(server.EvccGeoFilterService, "start", blocked("geo"))
    monkeypatch.setattr(server.EvccGeoFilterService, "stop", lambda self: None)
    monkeypatch.setattr(server, "publish_all_discovery", blocked("discovery", 1))
    monkeypatch.setattr(server, "_discover_remote_vehicle_snapshots", blocked("remote", []))
    monkeypatch.setattr(server, "_load_homeassistant_zones", blocked("zones", []))
    monkeypatch.setattr(server, "_publish_device_trackers", blocked("trackers"))
    app = server.create_app()
    try:
        started = time.monotonic()
        with TestClient(app) as client:
            assert time.monotonic() - started < 1.0
            for name, event in entered.items():
                assert event.wait(1.0), name
            for route in ("/", "/api/dashboard", "/api/settings"):
                before = time.monotonic()
                response = client.get(route)
                assert response.status_code == 200, response.text
                assert time.monotonic() - before < 1.0
            assert client.get("/api/dashboard").json()["vehicles"][0]["id"] == "TEST"
    finally:
        release.set()
        for job in getattr(app.state, "background_jobs", []):
            job.stop()
            job._thread.join(2)


def test_shutdown_during_blocked_start_cleans_up_after_start_returns():
    entered = threading.Event()
    release = threading.Event()
    cleaned = threading.Event()

    def start():
        entered.set()
        release.wait(3)

    job = BackgroundJob("test", start, cleanup=cleaned.set)
    job.start()
    try:
        assert entered.wait(1)
        before = time.monotonic()
        job.stop()
        assert time.monotonic() - before < 0.2
        assert not cleaned.is_set()
    finally:
        release.set()
        job._thread.join(2)
    assert cleaned.is_set()
    assert not job._thread.is_alive()


def test_background_job_retries_transient_failure_and_stops_without_another_attempt():
    recovered = threading.Event()
    calls = []

    def operation():
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("broker starting")
        recovered.set()

    job = BackgroundJob("retry", operation, retry_interval=0.01)
    job.start()
    try:
        assert recovered.wait(1)
    finally:
        job.stop()
        job._thread.join(1)
    assert len(calls) == 2


def test_failed_worker_does_not_prevent_other_workers_and_only_failed_one_retries(tmp_path, monkeypatch):
    cfg = configure(tmp_path, monkeypatch)
    other = cfg.vehicles[0].model_copy(deep=True)
    other.id = "OTHER"
    other.license_plate = "OTHER"
    cfg.vehicles.append(other)
    cfg.ui_settings.ha_discovery_enabled = False
    cfg.ui_settings.device_tracker_enabled = False
    ConfigStore(str(tmp_path)).save(cfg)
    calls = Counter()
    recovered = threading.Event()

    def start_worker(self, vehicle_id, settings):
        calls[vehicle_id] += 1
        if vehicle_id == "TEST" and calls[vehicle_id] == 1:
            raise ConnectionError("broker starting")
        if vehicle_id == "TEST":
            recovered.set()

    class QuickRetryJob(BackgroundJob):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, retry_interval=0.01, **kwargs)

    monkeypatch.setattr(server, "BackgroundJob", QuickRetryJob)
    monkeypatch.setattr(server.WorkerManager, "start_or_restart_vehicle", start_worker)
    monkeypatch.setattr(server.EvccGeoFilterService, "start", lambda self: None)
    monkeypatch.setattr(server.EvccGeoFilterService, "stop", lambda self: None)
    monkeypatch.setattr(server, "_discover_remote_vehicle_snapshots", lambda *args: [])
    monkeypatch.setattr(server, "_load_homeassistant_zones", lambda: [])
    monkeypatch.setattr(server, "_publish_device_trackers", lambda *args: None)
    app = server.create_app()
    with TestClient(app):
        assert recovered.wait(1)
    for job in app.state.background_jobs:
        job._thread.join(1)
    assert calls == {"TEST": 2, "OTHER": 1}


def test_periodic_job_updates_cached_remote_vehicles_without_querying_on_http(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(server.WorkerManager, "start_or_restart_vehicle", lambda *args: None)
    monkeypatch.setattr(server.EvccGeoFilterService, "start", lambda *args: None)
    monkeypatch.setattr(server.EvccGeoFilterService, "stop", lambda *args: None)
    monkeypatch.setattr(server, "publish_all_discovery", lambda *args: 0)
    monkeypatch.setattr(server, "_publish_device_trackers", lambda *args: None)
    monkeypatch.setattr(server, "_load_homeassistant_zones", lambda: [{"entity_id": "zone.home", "name": "Home"}])
    remote = {"id": "remote::bmw::REMOTE::other", "label": "Remote", "manufacturer": "BMW", "license_plate": "REMOTE", "remote": True}
    calls = []
    def discover(*args):
        calls.append(1)
        return [remote]
    monkeypatch.setattr(server, "_discover_remote_vehicle_snapshots", discover)
    app = server.create_app()
    with TestClient(app) as client:
        deadline = time.monotonic() + 1
        while not app.state.remote_cards and time.monotonic() < deadline:
            time.sleep(0.01)
        for _ in range(3):
            payload = client.get("/api/dashboard").json()
            assert {card["id"] for card in payload["vehicles"]} == {"TEST", remote["id"]}
        assert len(calls) == 1
        assert "device_tracker_enabled" not in remote
    for job in app.state.background_jobs:
        job._thread.join(1)
