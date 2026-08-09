from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_eu_front_verification_uses_login_with_sms_on_same_front_route():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    userauth = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.UserAuth.cs").read_text(encoding="utf-8")

    assert 'LoginWithSmsMyGwmEuFrontAppAsync' in userauth
    assert 'PostFrontAsync<LoginWithSmsRequest, LoginAccountResponse>("userAuth/loginWithSMS"' in userauth
    assert 'endpoint=userAuth/loginWithSMS' in configure
    assert 'same_device=true' in configure
    assert 'Model = request.Model' in configure
    assert 'PushToken = String.Empty' in configure
    assert 'SmsCode = code' in configure


def test_eu_legacy_front_otp_is_not_redeemed_via_loginaccount_verifycode():
    configure = (ROOT / "third_party/ora2mqtt/ora2mqtt/ConfigureCommand.cs").read_text(encoding="utf-8")
    start = configure.index('if (String.Equals(frontPayload, "eu_legacy"')
    end = configure.index('else if (String.Equals(frontPayload, "mygwm13"', start)
    block = configure[start:end]
    assert 'LoginWithSmsMyGwmEuFrontAppAsync' in block
    assert 'request.VerifyCode = code' not in block
    assert 'LoginAccountMyGwmEuFrontAppAsync(request' not in block
