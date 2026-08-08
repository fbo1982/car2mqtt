from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_551008_triggers_non_sms_identity_discovery():
    api = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'MyGwmEuFrontIdentityCandidates' in api
    assert 'UseMyGwmEuFrontIdentity' in api
    assert '"551008"' in configure
    assert 'ORA_AUTH_STEP=identity_discovery_start' in configure
    assert 'ORA_AUTH_STEP=identity_probe' in configure
    assert 'ORA_AUTH_STEP=identity_probe_rejected' in configure
    assert 'ORA_AUTH_STEP=identity_selected' in configure
    start = configure.index('ORA_AUTH_STEP=identity_discovery_start')
    end = configure.index('// Any other structured GWM response means the rs value', start)
    block = configure[start:end]
    assert 'LoginAccountMyGwmEuFrontAsync' in block
    assert 'GetSmsCodeMyGwmEuFrontAsync' not in block
    assert 'sms_sent=false' in block


def test_identity_candidates_are_grounded_in_known_gwm_profiles():
    api = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    assert '("mygwm_app", "GW_APP_GWM", "6", "CC01")' in api
    assert '("legacy_ora", "GW_APP_ORA", "3", "CC01")' in api
    assert '("haval_app", "GW_APP_Haval", "1", "CC01")' in api


def test_selected_identity_is_logged_on_sms_request_and_redemption():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'profile={client.FrontIdentityLabel}' in configure
    assert 'terminal={client.FrontTerminal}' in configure
    assert 'brand={client.FrontBrand}' in configure
    assert 'enterpriseId={client.FrontEnterpriseId}' in configure
