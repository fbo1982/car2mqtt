from __future__ import annotations

import time
import requests
from app.providers.acconia_api import AcconiaSilenceApi

BASE_URL = "https://api.connectivity.silence.eco/api/v1/me/scooters"
VARIANTS = (
    ("C", "details=true&dynamic=false&pollIfNecessary=false"),
    ("B", "details=true&dynamic=true&pollIfNecessary=false"),
    ("A", "details=true&dynamic=true&pollIfNecessary=true"),
)


def _failure(exc):
    # Never log exception text: it may contain credentials, URLs or server data.
    cause = exc.__cause__ or exc
    if isinstance(cause, requests.Timeout):
        return "Zeitüberschreitung"
    if isinstance(cause, requests.ConnectionError):
        return "Verbindungsfehler"
    return "Keine erfolgreiche Antwort"


def _probe(label, url, headers, emit, read_timeout=30):
    started = time.monotonic()
    result = {"step": label}
    response = None
    emit(f"{label}: Abruf beginnt")
    try:
        response = requests.get(url, headers=headers, timeout=(5, read_timeout), allow_redirects=False)
        result["http_status"] = response.status_code
        if response.status_code == 200:
            try:
                data = response.json()
                records = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
                records = [r for r in records if isinstance(r, dict) and any(k in r for k in ("frameNo", "imei", "batterySoc", "lastLocation", "soc"))]
                result["vehicle_count"] = len(records)
                result["has_location"] = any(isinstance(r.get("lastLocation"), dict) for r in records)
                result["has_soc"] = any("batterySoc" in r or "soc" in r for r in records)
            except ValueError:
                result["error"] = "Keine JSON-Antwort"
    except requests.RequestException as exc:
        result["error"] = _failure(exc)
    finally:
        if response is not None:
            response.close()
    result["seconds"] = round(time.monotonic() - started, 2)
    status = f"HTTP {result['http_status']}" if 'http_status' in result else result.get('error', 'Fehler')
    extra = ''
    if 'vehicle_count' in result:
        extra = f"; Fahrzeuge: {result['vehicle_count']}; Standortfeld: {'ja' if result['has_location'] else 'nein'}; Akkustandfeld: {'ja' if result['has_soc'] else 'nein'}"
    if result.get('error') and 'http_status' in result:
        extra += '; ' + result['error']
    emit(f"{label}: {status} nach {result['seconds']:.2f} s{extra}")
    return result


def run_silence_diagnostics(config, log, cancelled=lambda: False):
    def emit(message):
        log("MySilence Diagnose: " + message)

    emit("Start; gespeicherte Zugangsdaten; keine Übernahme der Testdaten in Fahrzeugstatus oder MQTT")
    headers = {"accept": "*/*", "user-agent": "Silence/220 CFNetwork/1220.1 Darwin/20.3.0"}
    steps = []
    if cancelled():
        return steps
    steps.append(_probe("Ohne Anmeldung", AcconiaSilenceApi.SCOOTERS_URL, headers, emit, read_timeout=10))
    if cancelled():
        return steps
    api = AcconiaSilenceApi(
        account=config.get("account") or config.get("username") or "",
        password=config.get("password") or "",
        api_key=config.get("api_key") or config.get("apikey") or "",
        timeout=15,
    )
    started = time.monotonic()
    emit("Anmeldung beginnt")
    try:
        token = api._login()
    except Exception as exc:
        emit(f"Anmeldung: {_failure(exc)} nach {time.monotonic() - started:.2f} s; beendet")
        return steps
    emit(f"Anmeldung erfolgreich nach {time.monotonic() - started:.2f} s")
    headers = dict(headers, authorization=token)
    for name, params in VARIANTS:
        if cancelled():
            emit("abgebrochen")
            return steps
        result = _probe(f"Variante {name} ({params})", BASE_URL + '?' + params, headers, emit)
        steps.append(result)
        if result.get('http_status') in (401, 403, 429):
            emit("API lehnt Anmeldung/Zugriff ab oder begrenzt Anfragen; weitere Varianten ausgelassen")
            break
    emit("Beendet; Testergebnisse sind keine Aussage zur Aktualität der Fahrzeugdaten")
    return steps
