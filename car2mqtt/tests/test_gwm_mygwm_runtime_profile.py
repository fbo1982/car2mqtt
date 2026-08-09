from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mygwm_runner_does_not_validate_fresh_token_through_legacy_h5():
    run = (ROOT / "third_party/ora2mqtt/ora2mqtt/RunCommand.cs").read_text(encoding="utf-8")
    assert 'String.Equals(options.AuthFlow, "eu_mygwm_front"' in run
    assert 'UseMyGwmEuRuntimeProfile(options.Country)' in run
    assert 'if (!force && !IsJwtExpiredOrNearExpiry(options.Account.AccessToken))' in run
    assert 'GetUserBaseInfoAsync(cancellationToken)' in run  # retained for legacy only


def test_mygwm_runtime_uses_app_gateway_identity_and_both_tokens():
    client = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    assert 'public void UseMyGwmEuRuntimeProfile(string country)' in client
    assert 'SetHeader(_appClient, "terminal", "GW_APP_GWM")' in client
    assert 'SetHeader(_appClient, "brand", "6")' in client
    assert 'SetHeader(_appClient, "regioncode", normalizedCountry)' in client
    assert 'SetHeader(_appClient, "systemtype", "2")' in client
    assert 'public void SetRefreshToken(string refreshToken)' in client


def test_mygwm_refresh_uses_same_front_service_context():
    run = (ROOT / "third_party/ora2mqtt/ora2mqtt/RunCommand.cs").read_text(encoding="utf-8")
    auth = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.UserAuth.cs").read_text(encoding="utf-8")
    assert 'RefreshTokenMyGwmEuFrontAsync' in run
    assert 'PostFrontAsync<RefreshTokenRequest, RefreshTokenResponse>("userAuth/refreshToken"' in auth


def test_configure_reuses_front_tokens_without_old_h5_validation():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    assert 'ORA_AUTH_TOKENS_REUSED ORA_AUTH_FLOW=eu_mygwm_front validation=runtime_deferred' in configure
    assert 'UseMyGwmEuRuntimeProfile(options.Country)' in configure
