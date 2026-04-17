# Car2MQTT Home Assistant Add-on

Version `0.2.1`

## Inhalt
Diese Version bringt das Scaffold auf den gewünschten Stil und verankert MQTT zentral in der Add-on-Konfiguration.

### Neu in v0.2.1
- evcc-inspirierte Kacheloberfläche
- Dialog „Fahrzeug hinzufügen" im gleichen Stil
- MQTT-Zugangsdaten zentral in der Add-on-Konfiguration
- MQTT-Konfiguration im Dialog nur noch als Read-only-Übersicht
- vorbereitete Herstellerdialoge für BMW CarData und GWM/ORA
- Fahrzeugdaten speichern weiterhin persistent im Add-on-Storage

## MQTT-Konfiguration
Die Zugangsdaten werden jetzt in Home Assistant unter **Add-on → Konfiguration** gepflegt:
- `mqtt_host`
- `mqtt_port`
- `mqtt_username`
- `mqtt_password`
- `mqtt_base_topic`
- `mqtt_qos`
- `mqtt_retain`
- `mqtt_tls`

Diese Werte gelten global für alle Fahrzeuge.

## Topic-Struktur
- Raw: `car/<hersteller>/<kennzeichen>/...`
- Mapped: `car/<hersteller>/<kennzeichen>/mapped/...`

## Hinweise
- Live-MQTT-Connect-Test und echte BMW-Auth folgen im nächsten Schritt.
- v0.2.1 fokussiert UI-Stil, zentrale MQTT-Konfiguration und saubere Fahrzeuganlage.
