from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_illegal_rs_triggers_non_sms_rs_discovery():
    api = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'MyGwmEuFrontRsCandidates' in api
    assert 'FrontRs { get; private set; }' in api
    assert 'ORA_AUTH_STEP=rs_discovery_start' in configure
    assert 'ORA_AUTH_STEP=rs_probe' in configure
    assert 'ORA_AUTH_STEP=rs_probe_rejected' in configure
    assert 'ORA_AUTH_STEP=rs_selected' in configure
    start = configure.index('ORA_AUTH_STEP=rs_discovery_start')
    end = configure.index('if (token is null)', start)
    block = configure[start:end]
    assert 'ProbeFrontLoginAsync' in block
    assert 'GetSmsCodeMyGwmEuFrontAsync' not in block
    assert 'sms_sent=false' in block


def test_rs_discovery_recognizes_observed_gwm_error_551005():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert '"551005"' in configure
    assert 'Illegal rs' in configure


def test_selected_rs_is_reused_for_code_request_and_redemption_logs():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'route={client.FrontRouteId} rs={client.FrontRs}' in configure
