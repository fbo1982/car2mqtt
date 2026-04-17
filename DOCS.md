# Car2MQTT

## Beschreibung
Car2MQTT ist ein modulares Home-Assistant-Add-on für mehrere Fahrzeuge und Hersteller.

## V0.1.0 Umfang
Diese Version liefert die technische Basis:
- GUI mit Fahrzeug-Kacheln
- Herstellerabhängige Konfigurationsfelder
- Interner Vehicle Manager
- Provider-Registry
- Mapping-Grundmodell

## MQTT-Zielstruktur
### Rohdaten
`car/<hersteller>/<kennzeichen>/...`

### Gemappte Daten
`car/<hersteller>/<kennzeichen>/mapped/...`

## Hinweise
BMW und GWM sind in V0.1.0 als Provider vorbereitet, aber noch nicht vollständig an deren Upstream-Projekte angebunden.
