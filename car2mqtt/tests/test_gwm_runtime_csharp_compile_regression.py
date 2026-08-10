from pathlib import Path


def test_jwt_padding_switch_parenthesized():
    src = Path("third_party/ora2mqtt/ora2mqtt/RunCommand.cs").read_text()
    assert "payload += (payload.Length % 4) switch" in src
    assert "payload += payload.Length % 4 switch" not in src


def test_release_version_1251():
    assert Path("VERSION").read_text().strip() == "1.2.62"
    assert 'version: "1.2.62"' in Path("config.yaml").read_text()
