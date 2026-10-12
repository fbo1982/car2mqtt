import json

import pytest
import requests

from app.providers import silence_http_trace as trace


@pytest.mark.parametrize('key', ['displayName', 'DISPLAY_NAME', 'display-name',
                                 'localId', 'LOCAL_ID', 'local-id'])
def test_profile_identity_fields_are_masked_recursively(key):
    payload = {'nested': [{key: 'PRIVATE-VALUE'}], 'registered': True, 'expiresIn': '3600'}
    result = json.loads(trace._safe_body(json.dumps(payload).encode()))
    assert result['nested'][0][key] == '[REDACTED]'
    assert result['registered'] is True
    assert result['expiresIn'] == '3600'


def test_firebase_trace_masks_identity_without_changing_response(monkeypatch):
    payload = {'kind': 'identitytoolkit#VerifyPasswordResponse',
               'displayName': 'PRIVATE-NAME', 'localId': 'PRIVATE-ID',
               'email': 'PRIVATE-EMAIL', 'idToken': 'PRIVATE-TOKEN',
               'refreshToken': 'PRIVATE-REFRESH', 'registered': True, 'expiresIn': '3600'}
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode()
    response.headers['content-type'] = 'application/json'
    writes, calls = [], []
    monkeypatch.setattr(trace, '_write', lambda vehicle, message: writes.append(message))

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response

    monkeypatch.setattr(trace.requests, 'request', request)
    url = 'https://example.invalid/login?key=PRIVATE-KEY'
    body = {'email': 'PRIVATE-EMAIL', 'password': 'PRIVATE-PASSWORD'}
    received = trace.SilenceHttpTrace('TEST').request('POST', url, json=body, timeout=15)
    assert received is response and received.json() == payload
    assert calls == [('POST', url, {'json': body, 'timeout': 15})]
    report = '\n'.join(writes)
    assert 'PRIVATE-' not in report
    assert 'HTTP 200' in report and 'sha256=' in report
    assert '"registered": true' in report and '"expiresIn": "3600"' in report
