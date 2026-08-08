from pathlib import Path
from types import SimpleNamespace

from app.providers.gwm_config import ensure_ora_runtime_config, _normalize_auth_flow

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_config_defaults_to_eu_verifycode():
    provider = {"country": "DE", "device_id": "stable"}
    mqtt = SimpleNamespace(host="mqtt", username="", password="", password_set=False, tls=False, base_topic="car")
    cfg = ensure_ora_runtime_config(provider, mqtt, "TEST")
    assert cfg["AuthFlow"] == "eu_verifycode"


def test_v1238_experimental_flow_is_migrated():
    assert _normalize_auth_flow("mygwm13") == "eu_verifycode"
    assert _normalize_auth_flow("") == "eu_verifycode"
    assert _normalize_auth_flow("legacy") == "legacy"


def test_eu_verifycode_keeps_known_good_eu_identity_and_code_request():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=initial_login endpoint=loginAccount profile=EU_ORA' in source
    assert 'ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=request_code endpoint=getSMSCode type=3 profile=EU_ORA' in source
    assert 'client.UseLegacyOraProfile()' in source


def test_eu_verifycode_avoids_login_with_sms_for_otp_completion():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'else if (useEuVerifyCode)' in source
    assert 'CheckSmsCodeEuAsync' in source
    assert 'request.VerifyCode = code;' in source
    assert 'ORA_AUTH_FLOW=eu_verifycode ORA_AUTH_STEP=verified_login endpoint=loginAccount verifyCode=present profile=EU_ORA' in source
    # legacy rollback still exists, but eu_verifycode finalizes with LoginAccountAsync(request).
    eu_block = source.split('else if (useEuVerifyCode)', 1)[1].split('else\n                    {', 1)[0]
    assert 'LoginWithSmsAsync' not in eu_block
    assert 'LoginAccountAsync(request' in eu_block


def test_eu_login_request_omits_verify_code_until_second_call():
    dto = (ROOT / "third_party/ora2mqtt/libgwmapi/DTO/UserAuth/LoginAccountRequest.cs").read_text(encoding="utf-8")
    assert '[JsonPropertyName("verifyCode")]' in dto
    assert 'JsonIgnoreCondition.WhenWritingNull' in dto


def test_eu_check_sms_code_matches_type3_request():
    dto = (ROOT / "third_party/ora2mqtt/libgwmapi/DTO/UserAuth/EuCheckSmsCode.cs").read_text(encoding="utf-8")
    auth = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.UserAuth.cs").read_text(encoding="utf-8")
    assert 'public int Type { get; set; } = 3;' in dto
    assert 'CheckSmsCodeEuAsync' in auth


def test_experimental_mygwm_profile_remains_non_default_for_debugging():
    options = (ROOT / "third_party/ora2mqtt/ora2mqtt/Ora2MqttOptions.cs").read_text(encoding="utf-8")
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'AuthFlow { get; set; } = "eu_verifycode"' in options
    assert 'options.AuthFlow ?? "eu_verifycode"' in configure
    assert 'String.Equals(authFlow, "mygwm13"' in configure
    assert 'UseMyGwm13Profile' in configure
    assert 'String.Equals(authFlow, "legacy"' not in configure or 'legacy' in configure


def test_initial_login_non_verification_error_gets_machine_readable_code():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'ORA_AUTH_INITIAL_FAILED' in source
    assert 'ORA_GWM_ERROR_CODE={initialLoginException.Code}' in source


def test_eu_rate_limited_code_request_allows_external_mygwm_code():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'ORA_AUTH_STEP=request_code_limited' in source
    assert 'external_code=allowed' in source
    assert 'official My GWM app' in source
    assert 'codeRequestException.Message.Contains("too many"' in source


def test_runner_preserves_external_code_instruction():
    source = (ROOT / "app/providers/gwm_runner.py").read_text(encoding="utf-8")
    assert 'legacy EU code-request endpoint is rate-limited' in source
    assert 'offiziellen MyGWM-App genau einen neuen Verify-Code anfordern' in source
