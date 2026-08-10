from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from app.providers.gwm_config import clear_ora_token_bundle
from app.providers.gwm_runner import GwmIntegratedWorker


def _worker(tmp_path: Path):
    vehicle = SimpleNamespace(
        id="TEST",
        license_plate="TEST",
        provider_config={"account": "a@example.invalid", "password": "pw", "country": "DE"},
    )
    settings = SimpleNamespace(host="mqtt", username="", password="", tls=False)
    logs = []
    return GwmIntegratedWorker(
        vehicle=vehicle,
        mqtt_settings=settings,
        vehicle_dir=tmp_path,
        on_connect=lambda: None,
        on_disconnect=lambda _x: None,
        on_error=lambda _x: None,
        on_waiting=lambda _x: None,
        on_detail=lambda _x: None,
        on_message=lambda _a, _b: None,
        log_callback=logs.append,
    ), logs


def test_generic_refresh_failure_is_not_forced_reauth(tmp_path):
    worker, _ = _worker(tmp_path)
    assert not worker._is_reauth_required("ORA token refresh failed.")
    assert not worker._is_reauth_required("System busy, please try later")
    assert worker._is_reauth_required("Refresh token has expired")
    assert worker._is_reauth_required("Invalid refresh token")


def test_clear_tokens_preserves_device_identity():
    cfg = {
        "access_token": "a",
        "refresh_token": "r",
        "gw_id": "g",
        "bean_id": "b",
        "device_id": "stable-device",
        "country": "DE",
    }
    clear_ora_token_bundle(cfg)
    assert cfg == {"device_id": "stable-device", "country": "DE"}


def test_system_busy_consumes_verification_code_and_requests_fresh_one(tmp_path):
    worker, logs = _worker(tmp_path)
    code = tmp_path / "verification_code.txt"
    code.write_text("1234", encoding="utf-8")
    config = tmp_path / "ora2mqtt.yml"
    config.write_text("DeviceId: stable\n", encoding="utf-8")

    proc = SimpleNamespace(
        returncode=255,
        stdout=(
            "ORA_VERIFICATION_FAILED ORA_GWM_ERROR_CODE=123456 message=System busy, please try later\n"
            "libgwmapi.GwmApiException: System busy, please try later\n"
        ),
        stderr="",
    )
    with patch("app.providers.gwm_runner.subprocess.run", return_value=proc):
        try:
            worker._run_configure(config)
        except RuntimeError as exc:
            text = str(exc)
            assert text.startswith("ORA_WAITING_FOR_CODE::")
            assert "System busy" in text
            assert "GWM-Code 123456" in text
            assert "nicht denselben Code" in text
        else:
            raise AssertionError("expected verification-code failure")
    assert not code.exists()
    assert any("Einmalcode wird nicht wiederverwendet" in entry for entry in logs)


def test_incorrect_verification_code_is_discarded(tmp_path):
    worker, _ = _worker(tmp_path)
    code = tmp_path / "verification_code.txt"
    code.write_text("4321", encoding="utf-8")
    config = tmp_path / "ora2mqtt.yml"
    config.write_text("DeviceId: stable\n", encoding="utf-8")

    proc = SimpleNamespace(
        returncode=255,
        stdout="ORA_VERIFICATION_FAILED ORA_GWM_ERROR_CODE=110999 message=Incorrect verification code\n",
        stderr="",
    )
    with patch("app.providers.gwm_runner.subprocess.run", return_value=proc):
        try:
            worker._run_configure(config)
        except RuntimeError as exc:
            assert str(exc).startswith("ORA_WAITING_FOR_CODE::")
            assert "GWM-Code 110999" in str(exc)
        else:
            raise AssertionError("expected verification-code failure")
    assert not code.exists()


def test_success_consumes_verification_code(tmp_path):
    worker, _ = _worker(tmp_path)
    code = tmp_path / "verification_code.txt"
    code.write_text("1234", encoding="utf-8")
    config = tmp_path / "ora2mqtt.yml"
    config.write_text("DeviceId: stable\nAccount: {}\n", encoding="utf-8")

    proc = SimpleNamespace(returncode=0, stdout="Configuration successful!\n", stderr="")
    # avoid parsing/publishing a synthetic incomplete config after successful fake process
    with patch("app.providers.gwm_runner.subprocess.run", return_value=proc), \
         patch("app.providers.gwm_runner.merge_ora_tokens"), \
         patch("app.providers.gwm_runner.publish_ora_token_backup"):
        worker._run_configure(config)
    assert not code.exists()


def _runtime_yaml(access: str, refresh: str) -> str:
    return f'''DeviceId: stable-device
Country: DE
AuthFlow: eu_mygwm_front
Account:
  AccessToken: {access}
  RefreshToken: {refresh}
  GwId: gw-new
  BeanId: bean-new
Mqtt:
  Host: mqtt
  Username: ''
  Password: ''
  UseTls: false
  HomeAssistantDiscoveryTopic: null
  TopicPrefixTemplate: car/gwm/TEST/{{vin}}/status
'''


def test_prepare_runtime_files_prefers_rotated_runtime_tokens(tmp_path):
    worker, logs = _worker(tmp_path)
    worker.vehicle.provider_config.update({
        "access_token": "stale-access",
        "refresh_token": "stale-refresh",
        "device_id": "stable-device",
        "country": "DE",
    })
    config = tmp_path / "ora2mqtt.yml"
    config.write_text(_runtime_yaml("fresh-access", "fresh-refresh"), encoding="utf-8")
    persisted = []
    worker.on_tokens_updated = lambda bundle: persisted.append(dict(bundle))

    with patch("app.providers.gwm_runner.publish_ora_token_backup", return_value=True):
        worker._prepare_runtime_files()

    assert worker.vehicle.provider_config["access_token"] == "fresh-access"
    assert worker.vehicle.provider_config["refresh_token"] == "fresh-refresh"
    assert persisted and persisted[-1]["refresh_token"] == "fresh-refresh"
    rendered = config.read_text(encoding="utf-8")
    assert "RefreshToken: fresh-refresh" in rendered
    assert "RefreshToken: stale-refresh" not in rendered
    assert any("aktuelle Runtime-Tokens" in entry for entry in logs)


def test_runtime_refresh_sync_persists_rotated_tokens(tmp_path):
    worker, logs = _worker(tmp_path)
    worker.vehicle.provider_config.update({
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "device_id": "stable-device",
        "country": "DE",
    })
    (tmp_path / "ora2mqtt.yml").write_text(_runtime_yaml("rotated-access", "rotated-refresh"), encoding="utf-8")
    persisted = []
    worker.on_tokens_updated = lambda bundle: persisted.append(dict(bundle))

    with patch("app.providers.gwm_runner.publish_ora_token_backup", return_value=True):
        assert worker._sync_runtime_tokens_from_file("Test-Refresh") is True

    assert worker.vehicle.provider_config["refresh_token"] == "rotated-refresh"
    assert persisted[-1]["access_token"] == "rotated-access"
    assert persisted[-1]["refresh_token"] == "rotated-refresh"
    assert any("Test-Refresh" in entry and "neuer Token" in entry for entry in logs)
