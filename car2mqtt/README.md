# Car2MQTT Home Assistant Add-on

Version 0.4.8

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


## V0.4.8
- ORA/GWM Wizard erzeugt eine `ora2mqtt.yml`-Vorlage im Fahrzeugordner.
- BMW bleibt unverändert aktiv.


## V0.4.8
- ORA/GWM Local-MQTT-Monitor subscribes to GWM/<vehicleId>/status/items/... and republishes/mapps into car/gwm/<kennzeichen>/...


## V0.4.8
- Integriert ora2mqtt configure + run direkt im Add-on.
- Baut ora2mqtt, openssl.cnf und gwm_root.pem im Container automatisch ein.


## V0.4.8
- Fix: icu-libs für integrierten ora2mqtt Runner hinzugefügt.
- Dotnet Globalization explizit aktiviert.
- Ruhigeres Retry-Verhalten beim ORA configure.
