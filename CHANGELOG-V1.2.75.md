# Car2MQTT V1.2.75 – Profil und vereinfachte Fahrzeugabfragen prüfen

Stand: 12.10.2026. Basis: V1.2.74; sämtliche Korrekturen der Loganzeige bleiben enthalten.

## Anlass

Die bereitgestellten Protokolle zeigen eine erfolgreiche Firebase-Anmeldung und anschließend Lese-Timeouts bei allen drei bisherigen Fahrzeugabfragen. Diese hatten gemeinsam details=true. Laut Rückmeldung aktualisiert die MySilence-App den Standort, aber nicht den Akkustand. Getrennte Endpunkte sind dadurch noch nicht belegt; auch Datenfelder einer gemeinsamen Antwort können unterschiedlich aktuell sein.

## Änderungen

- „Verbindung prüfen“ vergleicht nach der bisherigen Kontrolle ohne Anmeldung und dem Login drei andere Anfragen:
  1. Profil: GET /api/v1/me.
  2. Fahrzeugliste ohne Parameter: GET /api/v1/me/scooters.
  3. Minimale Fahrzeugliste: GET /api/v1/me/scooters?details=false&dynamic=false&pollIfNecessary=false.
- Diese Anfragen ersetzen im manuellen Test die bisherigen Varianten C/B/A. Die reguläre Fahrzeugabfrage bleibt unverändert.
- Das Live-Protokoll nennt Antwortzeit, HTTP-Status und bei HTTP 200 die JSON-Struktur. Für Fahrzeugantworten werden erkannte Fahrzeugobjekte und das Vorhandensein bekannter Standort-/Akkustandfelder angegeben. Profilwerte und Koordinaten werden nicht ausgegeben.
- Profil-HTTP-404 oder ein Timeout verhindern die anschließenden Fahrzeugtests nicht. Bei HTTP 401/403/429 nach Anmeldung endet die Testreihe. HTTP 429 bereits ohne Anmeldung verhindert weitere Anfragen einschließlich Login.
- Das separate HTTP-Diagnoselog maskiert künftig auch displayName und localId, einschließlich üblicher Schreibweisen mit Unterstrich/Bindestrich. Bereits gespeicherte Logdateien werden dadurch nicht rückwirkend verändert.
- Hinweistext im Bearbeitungsdialog aktualisiert; Version auf 1.2.75 angehoben.

## Test auf dem betroffenen Server

1. Das vollständige Quellpaket wie die bisherigen Updates übernehmen und V1.2.75 installieren.
2. Das betroffene Fahrzeug vorübergehend deaktivieren und speichern, damit die reguläre Abfrage nicht parallel läuft. Auf die Bestätigung im Protokoll warten.
3. Den Bearbeitungsdialog öffnen und „Verbindung prüfen“ anklicken. Verwendet werden die gespeicherten Zugangsdaten; HTTP-Rohdaten-Debug muss dafür nicht eingeschaltet werden.
4. Im automatisch eingeschalteten Live-Protokoll bis „MySilence Diagnose: Beendet“ oder einer Abbruchmeldung warten. Etwa drei Minuten einplanen. Die Zeilen mit „MySilence Diagnose:“ zur Auswertung kopieren.
5. Das Fahrzeug anschließend wieder in den vorherigen Aktivierungszustand versetzen und speichern.

Die Diagnose hält einen laufenden Worker nicht selbst an. Sie läuft nur manuell, ohne automatische Wiederholung; Testdaten werden nicht in Fahrzeugstatus oder MQTT übernommen.

## Einordnung der Ergebnisse

- Profil 200, Fahrzeugabfragen Timeout: Hinweis auf ein Problem bei der Fahrzeugabfrage bzw. deren serverseitiger Verarbeitung. Das bestimmt die Ursache noch nicht.
- Eine vereinfachte Fahrzeugabfrage liefert 200 und erkannte Fahrzeugobjekte: Grundlage für den nächsten Vergleich der Datenstruktur. Erst danach lässt sich eine Änderung der regulären Abfrage begründen.
- Profil 404: Dieser Profilpfad ist im Test nicht verfügbar; daraus folgt kein Loginfehler.
- Alle angemeldeten Abfragen Timeout: Die Vereinfachung löst das beobachtete Problem nicht. Konto, Cloud-Verarbeitung und Netzwerkweg bleiben zu untersuchen.
- Null erkannte Fahrzeugobjekte kann auch eine noch unbekannte Antwortstruktur bedeuten. Vorhandene Standort- oder Akkustandfelder beweisen weder verwertbare Werte noch deren Aktualität.

## Umfang und Prüfung

173 Python-Tests, 38 Browserprüfungen und 6 Tests der Browserlogik bestanden. API-Antworten waren simuliert; kein Live-Test mit dem betroffenen Konto oder Home Assistant. Einzelheiten enthält TESTREPORT-V1.2.75.txt.

MQTT, EVCC, Mapper, onIdentify, Worker, reguläre Login-/Fahrzeuganfragen und Server-Routen sind gegenüber V1.2.74 unverändert. Dies ist eine Diagnoseversion; eine Behebung des Cloud-Timeouts oder ein separater GPS-Endpunkt ist nicht nachgewiesen.

Das ZIP enthält Quellcode, kein Home-Assistant-Backup und kein vorkompiliertes Add-on-Image. Es wurde lokal erstellt, nicht veröffentlicht oder auf dem Server installiert.
