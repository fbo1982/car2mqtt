from pathlib import Path


def test_front_route_switch_does_not_mutate_httpclient_baseaddress_after_request():
    source = Path("third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text()
    method = source.split("public void UseMyGwmEuFrontProfile", 1)[1].split("private static string CountryToFrontLanguage", 1)[0]
    assert "_frontClient.BaseAddress" not in method
    assert "GetFrontUri(url)" in source
    assert "new Uri(new Uri(baseUrl), url)" in source


def test_release_is_1251():
    assert Path("VERSION").read_text().strip() == "1.2.55"
    assert 'version: "1.2.55"' in Path("config.yaml").read_text()
