from pathlib import Path
from types import SimpleNamespace

from app.providers.gwm_config import ensure_ora_runtime_config, merge_ora_tokens

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_config_defaults_to_mygwm13():
    provider = {"country": "DE", "device_id": "stable"}
    mqtt = SimpleNamespace(host="mqtt", username="", password="", password_set=False, tls=False, base_topic="car")
    cfg = ensure_ora_runtime_config(provider, mqtt, "TEST")
    assert cfg["AuthFlow"] == "mygwm13"


def test_mygwm13_csharp_flow_avoids_legacy_login_with_sms():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert "LoginAccountMyGwm13Async" in source  # used for initial and verified login
    assert "GetSmsCodeMyGwm13Async" in source
    assert "CheckSmsCodeAsync" in source
    assert "LoginAccountMyGwm13Async" in source
    assert "type=17" in source
    assert "ORA_AUTH_FLOW=mygwm13" in source


def test_mygwm13_client_identity_is_versioned():
    source = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    assert 'SetHeader(client, "terminal", "GW_APP_GWM")' in source
    assert 'SetHeader(client, "brand", "6")' in source
    assert 'SetHeader(client, "cver", "1.3.0")' in source


def test_legacy_flow_remains_available():
    options = (ROOT / "third_party/ora2mqtt/ora2mqtt/Ora2MqttOptions.cs").read_text(encoding="utf-8")
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'AuthFlow { get; set; } = "mygwm13"' in options
    assert '"legacy"' in configure
    assert "LoginWithSmsAsync" in configure


def test_mygwm13_handles_both_known_verification_required_codes():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'e.Code == "110641"' in source
    assert 'e.Code == "309702"' in source
    assert "falling_back=legacy" in source
    assert "UseLegacyOraProfile" in source


def test_mygwm_profile_is_scoped_to_configure_auth_not_run_command():
    base = (ROOT / "third_party/ora2mqtt/ora2mqtt/BaseCommand.cs").read_text(encoding="utf-8")
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert "UseMyGwm13Profile" not in base
    assert "client.UseMyGwm13Profile()" in configure
