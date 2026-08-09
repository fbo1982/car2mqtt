from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_http_error_body_is_parsed_before_status_exception():
    source = (ROOT / "third_party/ora2mqtt/libgwmapi/GwmApiClient.cs").read_text(encoding="utf-8")
    assert 'ReadGwmResponseAsync' in source
    start = source.index('private async Task<T> ReadGwmResponseAsync')
    block = source[start:start+2200]
    assert 'ReadAsStringAsync' in block
    assert 'JsonSerializer.Deserialize<T>(content)' in block
    assert block.index('JsonSerializer.Deserialize<T>(content)') < block.index('response.EnsureSuccessStatusCode();')
    assert 'CheckResponse(result);' in block
