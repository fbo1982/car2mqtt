# Car2MQTT V1.2.74

Stand: 12.10.2026. Basis: hochgeladenes `car2mqtt-main.zip`, intern V1.2.73.

## Korrekturen

- Doppelte HTML-IDs `editAcconiaHttpRawDebug` und `silenceRawLogBtn` entfernt. Anlege- und Bearbeitungsdialog verwenden getrennte Diagnoseschalter.
- Der Schalter im Bearbeitungsdialog lädt und speichert die Einstellung des ausgewählten Fahrzeugs. Auch beim Anlegen wird die eigene Einstellung gespeichert und bei einem neuen Dialog wieder auf „aus“ gesetzt.
- Zusätzlich behoben: Die ACCIONA-Konfigurationsvalidierung hatte `http_raw_debug` beim Speichern verworfen. Sie übernimmt jetzt ausdrücklich den booleschen Wert `true`; ohne ausdrückliche Aktivierung bleibt die Diagnose aus.
- „HTTP-Diagnoselog anzeigen / aktualisieren“ zeigt den Inhalt direkt als Text im Bearbeitungsdialog. HTML-artiger Loginhalt wird nicht ausgeführt.
- Separater Download als UTF-8-Textdatei `mysilence-http-diagnose.log`. Anzeige und Download funktionieren auch unter dem Home-Assistant-Ingress-Pfad.
- Fehlende Datei: verständlicher Hinweis mit nächstem Schritt, HTTP 404 und Status `missing`; kein Download einer Hinweismeldung als vermeintliches Log.
- Leere Datei: eigener Hinweis und Status `empty`. Vorhandenes Log: Status `available`. Lesefehler: HTTP 500, Status `error` und verständliche Meldung.
- Logantworten werden mit `Cache-Control: no-store` und `X-Content-Type-Options: nosniff` ausgeliefert. Der Endpunkt unterstützt `?download=true` mit einem Attachment-Header.
- Beim Schließen oder Fahrzeugwechsel werden Anzeige und Downloadzustand zurückgesetzt. Verspätete Antworten überschreiben nicht das Log eines anderen Fahrzeugs.

## Unveränderte Bereiche

MQTT, EVCC, Mapper und `onIdentify` bleiben unverändert. Ebenso unverändert bleiben reguläre MySilence-HTTP-Anfragen, Polling, Worker, Logaufzeichnung, Maskierung und Rotation. Im HTTP-Trace-Modul wurde ausschließlich das Lesen der Logdatei angepasst.

Der Vergleich mit dem V1.2.73-Original prüft unveränderte Dateien bytegenau; innerhalb der gemeinsam genutzten Dateien werden die begrenzten Änderungen zusätzlich geprüft. Bereits im Ausgangsarchiv enthaltene Python-/Pytest-Cachedateien werden nicht mit ausgeliefert.

## Verwendung

1. Das Quellpaket wie die bisherigen Updates in das verwendete Add-on-Repository übernehmen und V1.2.74 installieren.
2. Beim ACCIONA/Silence-Fahrzeug „Bearbeiten“ öffnen, „HTTP-Rohdaten-Diagnose einschalten“ aktivieren und speichern.
3. Bei aktivem Fahrzeug den nächsten Poll abwarten und „HTTP-Diagnoselog anzeigen / aktualisieren“ anklicken.
4. Bei Bedarf mit „HTTP-Diagnoselog herunterladen“ als Textdatei speichern.

## Prüfung

- 151 Python-Tests erfolgreich, einschließlich 19 neuer Prüfungen für IDs, Konfigurationsspeicherung, Opt-in und Log-Endpunkt.
- 38 neue Browserprüfungen erfolgreich: direkter Zugriff und Home-Assistant-Ingress, Schalter, Textanzeige, tatsächlicher Dateidownload, fehlende/leere Dateien, Lese-/Netzwerkfehler und verspätete Antworten.
- Vorhandene Tests der Browserlogik ebenfalls ausgeführt; Ergebnis im beiliegenden Testbericht.
- Tests mit simulierten Antworten, ohne Zugriff auf ein echtes MySilence-Konto oder einen produktiven MQTT-Broker. Kein Live-Test auf der Home-Assistant-Installation.

Die neuen Tests liegen unter `car2mqtt/tests/test_silence_http_trace_ui.py` und `car2mqtt/tests/test_silence_http_trace_ui.cjs`. Für den Browsertest zuerst mit `tests/render_http_trace_fixture.py <Ausgabedatei.html>` die Vorlage rendern, danach `node tests/test_silence_http_trace_ui.cjs <Ausgabedatei.html>` ausführen. Dafür werden Playwright und Chromium benötigt; `CHROMIUM_PATH` kann auf einen installierten Browser zeigen.

SHA-256 des Ausgangsarchivs: `08817de9b1a06159d0eef536d9b7c424853fa4ff89ec1ae27738d76d2e19c547`.
