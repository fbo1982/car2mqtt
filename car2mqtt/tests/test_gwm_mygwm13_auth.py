from pathlib import Path
from types import SimpleNamespace

from app.providers.gwm_config import ensure_ora_runtime_config, _normalize_auth_flow

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_config_defaults_to_eu_mygwm_front():
    provider = {"country": "DE", "device_id": "stable"}
    mqtt = SimpleNamespace(host="mqtt", username="", password="", password_set=False, tls=False, base_topic="car")
    cfg = ensure_ora_runtime_config(provider, mqtt, "TEST")
    assert cfg["AuthFlow"] == "eu_mygwm_front"


def test_previous_experimental_flows_are_migrated_to_front_service():
    assert _normalize_auth_flow("mygwm13") == "eu_mygwm_front"
    assert _normalize_auth_flow("eu_verifycode") == "eu_mygwm_front"
    assert _normalize_auth_flow("") == "eu_mygwm_front"
    assert _normalize_auth_flow("legacy") == "legacy"


def test_front_service_profile_uses_pc_mygwm_identity():
    source = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    assert "eu-front-service.gwmcloud.com" in source
    assert "eu-official-commerce/eu-official-gateway/pc-api/api/v1.0/" in source
    assert 'SetHeader(_frontClient, "appid", "6")' in source
    assert 'SetHeader(_frontClient, "brand", "6")' in source
    assert 'SetHeader(_frontClient, "enterpriseid", "CC01")' in source
    assert 'SetHeader(_frontClient, "rs", "5")' in source
    assert 'SetHeader(_frontClient, "terminal", "GW_PC_GWM")' in source


def test_front_service_login_body_matches_public_mygwm_shape():
    dto = (ROOT / "third_party/ora2mqtt/libgwmapi/DTO/UserAuth/MyGwmEuFrontLoginRequest.cs").read_text(encoding="utf-8")
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert '[JsonPropertyName("account")]' in dto
    assert '[JsonPropertyName("password")]' in dto
    assert '[JsonPropertyName("deviceid")]' in dto
    assert '[JsonPropertyName("verifyCode")]' in dto
    assert 'JsonIgnoreCondition.WhenWritingNull' in dto
    assert 'Password = Md5Lower(password)' in configure
    assert 'DeviceId = options.DeviceId' in configure


def test_front_transport_uses_gwm_client_certificate():
    base = (ROOT / "third_party/ora2mqtt/ora2mqtt/BaseCommand.cs").read_text(encoding="utf-8")
    assert "frontHttpHandler" in base
    assert "frontHttpHandler.ClientCertificates.Add(pkcs12)" in base
    assert "new GwmApiClient(h5Client, appClient, frontClient" in base


def test_front_flow_requests_and_redeems_code_on_same_transport():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=initial_login transport=eu-front-service' in source
    assert 'ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=request_code transport=eu-front-service' in source
    assert 'GetSmsCodeMyGwmEuFrontAsync' in source
    assert 'ORA_AUTH_FLOW=eu_mygwm_front ORA_AUTH_STEP=verified_login transport=eu-front-service' in source
    assert 'frontRequest.VerifyCode = code;' in source
    assert source.count('LoginAccountMyGwmEuFrontAsync(frontRequest') >= 2


def test_front_flow_does_not_send_otp_to_legacy_verification_endpoints():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    start = source.index('if (useEuMyGwmFront)\n                    {', source.index('LoginAccountResponse token;', source.index('code = VerificationCode')))
    end = source.index('else if (useMyGwm13)', start)
    front_verify_block = source[start:end]
    assert 'CheckSmsCode' not in front_verify_block
    assert 'LoginWithSmsAsync' not in front_verify_block
    assert 'LoginAccountMyGwmEuFrontAsync' in front_verify_block


def test_front_api_methods_use_front_transport_not_h5():
    auth = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.UserAuth.cs").read_text(encoding="utf-8")
    assert 'LoginAccountMyGwmEuFrontAsync' in auth
    assert 'PostFrontAsync<MyGwmEuFrontLoginRequest, LoginAccountResponse>' in auth
    assert 'GetSmsCodeMyGwmEuFrontAsync' in auth
    assert 'return PostFrontAsync("userAuth/getSMSCode"' in auth


def test_options_and_runner_default_to_front_service():
    options = (ROOT / "third_party/ora2mqtt/ora2mqtt/Ora2MqttOptions.cs").read_text(encoding="utf-8")
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    runner = (ROOT / "app/providers/gwm_runner.py").read_text(encoding="utf-8")
    assert 'AuthFlow { get; set; } = "eu_mygwm_front"' in options
    assert 'options.AuthFlow ?? "eu_mygwm_front"' in configure
    assert 'provider_config.get("auth_flow", "eu_mygwm_front")' in runner
    assert '{"mygwm13", "eu_verifycode"}' in runner


def test_front_http_and_gwm_failures_have_machine_readable_markers():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'ORA_AUTH_FRONT_HTTP_FAILED' in source
    assert 'ORA_AUTH_FRONT_REQUEST_FAILED' in source
    assert 'ORA_GWM_ERROR_CODE={frontCodeRequestException.Code}' in source
    assert 'route=inferred_eu_pc_api_v1' in source


def test_legacy_flows_remain_available_for_rollback():
    source = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'String.Equals(authFlow, "mygwm13"' in source
    assert 'String.Equals(authFlow, "eu_verifycode"' in source
    assert 'client.LoginWithSmsAsync' in source
