from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIGURE = ROOT / "third_party" / "ora2mqtt" / "ora2mqtt" / "ConfigureCommand.cs"


def test_verification_exception_does_not_shadow_outer_gwm_exception():
    source = CONFIGURE.read_text(encoding="utf-8")
    assert "catch (GwmApiException verificationException)" in source
    assert "ORA_GWM_ERROR_CODE={verificationException.Code}" in source
    assert source.count("catch (GwmApiException e)") == 3
