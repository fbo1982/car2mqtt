"""Focused probes for separating account access from vehicle-data failures."""
import copy
import json

import pytest
import requests

from app.providers import acconia_diagnostics as diag


class Response:
    def __init__(self, status, data=None):
        self.status_code = status
        self.data = data
        self.closed = False

    def json(self):
        return self.data

    def close(self):
        self.closed = True


def install_responses(monkeypatch, responses):
    calls = []
    monkeypatch.setattr(diag.AcconiaSilenceApi, '_login', lambda self: 'test-token')

    def get(url, **kwargs):
        calls.append((url, kwargs))
        response = responses[len(calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(diag.requests, 'get', get)
    return calls


def test_unsupported_profile_does_not_skip_vehicle_probes(monkeypatch):
    responses = [Response(401), Response(404), Response(200, []), Response(200, [])]
    calls = install_responses(monkeypatch, responses)
    logs = []
    steps = diag.run_silence_diagnostics({}, logs.append)
    assert len(calls) == 4
    assert steps[1]['http_status'] == 404
    assert steps[2]['http_status'] == steps[3]['http_status'] == 200
    assert all(response.closed for response in responses)
    assert logs[-1].startswith('MySilence Diagnose: Beendet;')


@pytest.mark.parametrize('payload,kind', [
    ({'displayName': 'PRIVATE-PROFILE', 'lastLocation': {'latitude': 42}}, 'Objekt'),
    ([{'localId': 'PRIVATE-PROFILE'}], 'Liste'),
    ('PRIVATE-PROFILE', 'Skalar'),
    (None, 'Null'),
])
def test_profile_only_reports_json_shape(monkeypatch, payload, kind):
    response = Response(200, payload)
    monkeypatch.setattr(diag.requests, 'get', lambda *args, **kwargs: response)
    logs = []
    step = diag._probe('Profil', diag.PROFILE_URL, {}, logs.append, vehicle_payload=False)
    assert step['json_type'] == kind
    assert 'vehicle_count' not in step
    assert 'has_location' not in step
    assert 'PRIVATE-PROFILE' not in json.dumps(step) + '\n'.join(logs)
    assert response.closed


def test_location_only_response_is_distinguished_from_soc(monkeypatch):
    responses = [Response(401), Response(200, {}),
                 Response(200, {'vehicles': [{'batterySoc': 55}]}),
                 Response(200, [{'frameNo': 'PRIVATE-VIN',
                                 'lastLocation': {'latitude': 48.123456}}])]
    install_responses(monkeypatch, responses)
    logs = []
    steps = diag.run_silence_diagnostics({}, logs.append)
    # Unknown envelope: zero recognized objects does not imply zero registered vehicles.
    assert steps[2]['json_type'] == 'Objekt'
    assert steps[2]['vehicle_count'] == 0
    assert steps[3]['vehicle_count'] == 1
    assert steps[3]['has_location'] is True
    assert steps[3]['has_soc'] is False
    report = '\n'.join(logs)
    assert 'erkannte Fahrzeugobjekte: 0' in report
    assert 'Standortfeld: ja; Akkustandfeld: nein' in report
    assert '48.123456' not in report and 'PRIVATE-VIN' not in report


def test_all_authenticated_timeouts_finish_without_retry_or_config_mutation(monkeypatch):
    responses = [Response(401)] + [requests.ReadTimeout('PRIVATE-TOKEN') for _ in range(3)]
    calls = install_responses(monkeypatch, responses)
    config = {'account': 'PRIVATE-ACCOUNT', 'password': 'PRIVATE-PASSWORD',
              'extra': {'enabled': True}}
    before = copy.deepcopy(config)
    logs = []
    steps = diag.run_silence_diagnostics(config, logs.append)
    assert config == before
    assert len(calls) == len(steps) == 4
    assert all(step['error'] == 'Zeitüberschreitung' for step in steps[1:])
    assert calls[0][1]['timeout'] == (5, 10)
    assert all(call[1]['timeout'] == (5, 30) for call in calls[1:])
    assert 'PRIVATE-' not in json.dumps(steps) + '\n'.join(logs)
    assert logs[-1].startswith('MySilence Diagnose: Beendet;')


@pytest.mark.parametrize('status', [401, 403, 429])
@pytest.mark.parametrize('rejected_call', [3, 4])
def test_later_vehicle_rejection_stops_remaining_calls(monkeypatch, status, rejected_call):
    responses = [Response(401), Response(200, {}), Response(200, []), Response(200, [])]
    responses[rejected_call - 1] = Response(status)
    calls = install_responses(monkeypatch, responses)
    steps = diag.run_silence_diagnostics({}, lambda message: None)
    assert len(calls) == rejected_call
    assert steps[-1]['http_status'] == status
    assert all(response.closed for response in responses[:rejected_call])


def test_unauthenticated_rate_limit_skips_login(monkeypatch):
    response = Response(429)
    calls = install_responses(monkeypatch, [response])
    monkeypatch.setattr(diag.AcconiaSilenceApi, '_login',
                        lambda self: pytest.fail('Login despite rate limiting'))
    logs = []
    steps = diag.run_silence_diagnostics({}, logs.append)
    assert len(calls) == len(steps) == 1
    assert 'HTTP 429 ohne Anmeldung' in logs[-1]
    assert response.closed


def test_cancellation_after_profile_skips_vehicle_calls(monkeypatch):
    calls = install_responses(monkeypatch, [Response(401), Response(200, {})])
    logs = []
    steps = diag.run_silence_diagnostics({}, logs.append, cancelled=lambda: len(calls) >= 2)
    assert len(calls) == len(steps) == 2
    assert logs[-1] == 'MySilence Diagnose: abgebrochen'
