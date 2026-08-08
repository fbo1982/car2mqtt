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


def test_system_busy_keeps_verification_code(tmp_path):
    worker, _ = _worker(tmp_path)
    code = tmp_path / "verification_code.txt"
    code.write_text("1234", encoding="utf-8")
    config = tmp_path / "ora2mqtt.yml"
    config.write_text("DeviceId: stable\n", encoding="utf-8")

    proc = SimpleNamespace(returncode=255, stdout="libgwmapi.GwmApiException: System busy, please try later\n", stderr="")
    with patch("app.providers.gwm_runner.subprocess.run", return_value=proc):
        try:
            worker._run_configure(config)
        except RuntimeError as exc:
            assert str(exc).startswith("ORA_AUTH_TRANSIENT::")
        else:
            raise AssertionError("expected transient auth error")
    assert code.read_text(encoding="utf-8") == "1234"


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
