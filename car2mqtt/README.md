# Car2MQTT Home Assistant Add-on

Version 0.8.12

## Enthalten
- mehrstufiger Fahrzeug-Wizard
- schönere Hersteller-Auswahl
- BMW-Einrichtungs-Kachel
- Live-Status-Fahrzeugkarten
- echter MQTT-Verbindungstest zum lokalen Broker
- BMW Device-Flow Start/Polling
- Rohdaten nach `car/<hersteller>/<kennzeichen>/...`
- Mapping nach `car/<hersteller>/<kennzeichen>/mapped/...`

## Hinweise
- MQTT-Zugangsdaten werden zentral in der Add-on-Konfiguration gepflegt.
- BMW nutzt den Device Flow mit externem Login-Link.
- GWM/ORA bleibt in dieser Version ein Platzhalter für den nächsten Schritt.


## V0.8.12
- ORA/GWM Wizard erzeugt eine `ora2mqtt.yml`-Vorlage im Fahrzeugordner.
- BMW bleibt unverändert aktiv.


## V0.8.12
- ORA/GWM Local-MQTT-Monitor subscribes to GWM/<vehicleId>/status/items/... and republishes/mapps into car/gwm/<kennzeichen>/...


## V0.8.12
- Integriert ora2mqtt configure + run direkt im Add-on.
- Baut ora2mqtt, openssl.cnf und gwm_root.pem im Container automatisch ein.


## V0.8.12
- Fix: icu-libs für integrierten ora2mqtt Runner hinzugefügt.
- Dotnet Globalization explizit aktiviert.
- Ruhigeres Retry-Verhalten beim ORA configure.


## V0.8.12
- ORA/GWM: Verifikationscode-Feld im Wizard und in Bearbeiten.
- ora2mqtt configure vollständig headless für Code-Login.
- Kein Retry-Loop mehr bei Auth-/Verification-/Lockout-Fehlern.


## V0.8.12
- ORA/GWM Zweiphasen-Flow: waiting_for_code statt Fehler.
- Code senden-Button im Bearbeiten-Dialog.
- Kein automatisches Neuanfordern des Codes beim Submit.


## V0.8.12
- ORA Verifikationscode wird nicht mehr persistent gespeichert.
- Edit-Dialog mit 'Speichern' und 'Speichern und schließen'.
- Incorrect verification code stoppt Retries und wartet auf manuelle Korrektur.


## V0.8.12
- Zurück auf den stabileren UI-Stand ohne Popup/SSR-Experimente.
- ORA-Codefeld + Senden wie in 0.8.12.
- Kein Retry-Loop bei falschem Verifikationscode; Zustand bleibt manuell korrigierbar.
- Bearbeiten-Dialog mit 'Speichern' und 'Speichern & schließen'.


## V0.8.12
- Stabilitätsfix für ORA/GWM.
- Kein automatischer Restart mehr nach `you have acquired verification code too many times`.
- GWM-Fahrzeuge starten nicht mehr automatisch beim Speichern.
- Worker wird nur noch gezielt über `Code senden` fortgesetzt.
- Einmalige Verifikationscodes werden nach Verwendung aus der temporären Datei entfernt.
