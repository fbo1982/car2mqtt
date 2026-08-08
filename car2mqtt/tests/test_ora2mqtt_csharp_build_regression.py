from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CONFIGURE = ROOT / "third_party" / "ora2mqtt" / "ora2mqtt" / "ConfigureCommand.cs"


def test_verification_exception_does_not_shadow_outer_gwm_exception():
    source = CONFIGURE.read_text(encoding="utf-8")
    assert "catch (GwmApiException verificationException)" in source
    assert "ORA_GWM_ERROR_CODE={verificationException.Code}" in source
    # Regression for the Home Assistant build failure in 1.2.35/1.2.36: a nested
    # catch must not redeclare the enclosing catch variable `e`.
    verification_scope = source.split("catch (GwmApiException e) when", 1)[1]
    assert "catch (GwmApiException e)" not in verification_scope


def test_catch_parameter_names_are_not_redeclared_in_nested_scope():
    source = CONFIGURE.read_text(encoding="utf-8")
    names = re.findall(r"catch \([^)]*\s+(\w+)\)", source)
    assert "verificationException" in names
    assert "frontCodeRequestException" in names
    assert "initialLoginException" in names
