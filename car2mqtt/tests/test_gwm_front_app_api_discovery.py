from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mobile_app_api_routes_are_probed_before_pc_api():
    api = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    app_pos = api.index('eu_global_service_global_gateway_app')
    pc_pos = api.index('eu_global_service_pc')
    assert app_pos < pc_pos
    assert '/eu-global-gateway/app-api/api/v1.0/' in api
    assert 'FrontApiLane' in api


def test_app_lane_clears_pc_specific_headers():
    api = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    assert 'FrontApiLane == "app"' in api
    assert '"brandid", "devicetype", "gwid"' in api
    assert 'SetHeader(_frontClient, "terminal", "GW_APP_GWM")' in api
    assert 'SetHeader(_frontClient, "cver", "1.3.0")' in api


def test_app_lane_probes_known_login_payloads_without_sms():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    start = configure.index('async Task<LoginAccountResponse> ProbeFrontLoginAsync')
    end = configure.index('\n            try\n            {', start)
    block = configure[start:end]
    assert 'frontPayload = "eu_legacy"' in block
    assert 'LoginAccountMyGwmEuFrontAppAsync' in block
    assert 'frontPayload = "mygwm13"' in block
    assert 'LoginAccountMyGwmEuFrontApp13Async' in block
    assert 'GetSmsCode' not in block
    assert 'sms_sent=false' in block


def test_inconclusive_app_route_does_not_trigger_sms_or_stop_discovery():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'ORA_AUTH_STEP=route_probe_inconclusive' in configure
    pos = configure.index('ORA_AUTH_STEP=route_probe_inconclusive')
    block = configure[pos:pos+900]
    assert 'sms_sent=false' in block
    assert 'continue;' in block


def test_front_code_request_and_redemption_keep_payload_lane():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'lane={client.FrontApiLane} payload={frontPayload}' in configure
    assert 'GetSmsCodeMyGwmEuFrontApp13Async' in configure
    assert 'frontApp13Request.VerifyCode = code' in configure
    assert 'request.VerifyCode = code' in configure
