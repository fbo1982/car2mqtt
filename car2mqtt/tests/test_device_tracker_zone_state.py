from types import SimpleNamespace

from app.api import server


def test_gps_device_tracker_lets_home_assistant_resolve_zone(monkeypatch):
    published = []

    class FakeMqttClient:
        def __init__(self, _settings):
            pass

        def connect(self):
            pass

        def disconnect(self):
            pass

        def publish(self, topic, payload, retain=None, qos=None):
            published.append((topic, payload, retain, qos))

    monkeypatch.setattr(server, "LocalMqttClient", FakeMqttClient)

    settings = SimpleNamespace(host="mqtt", port=1883, base_topic="car")
    card = {
        "id": "silence",
        "label": "Silence S04",
        "manufacturer": "acconia",
        "license_plate": "TEST123",
        "device_tracker_enabled": True,
        "metrics": {"latitude": 49.80463, "longitude": 8.45999},
        "remote": False,
    }

    server._publish_device_trackers([card], settings, True)

    config = next(payload for topic, payload, *_ in published if topic.endswith("/config"))
    attrs = next(payload for topic, payload, *_ in published if topic.endswith("/attributes"))
    legacy_state = next((payload, retain) for topic, payload, retain, _ in published if topic.endswith("/state"))

    assert "state_topic" not in config
    assert "payload_home" not in config
    assert "payload_not_home" not in config
    assert config["json_attributes_topic"].endswith("/attributes")
    assert attrs["latitude"] == 49.80463
    assert attrs["longitude"] == 8.45999
    assert attrs["gps_accuracy"] == 0
    assert legacy_state == ("", True)
