# Car2MQTT Home Assistant Add-on

Version `0.1.3`

## Inhalt
Diese Version ist ein lauffähiges Grundgerüst für ein Home-Assistant-Add-on mit:
- gültiger Add-on-Repository-Struktur
- Web-UI mit Kachelansicht
- Fahrzeug hinzufügen per Dialog
- modularem Provider-Register
- vorbereiteten Providern für BMW und GWM/ORA
- persistenter Fahrzeugkonfiguration
- MQTT-Topic-Basis für Raw- und Mapped-Daten

## Repository-Struktur
```text
repository.yaml
car2mqtt/
  config.yaml
  Dockerfile
  build.yaml
  run.sh
  requirements.txt
  app/
```

## MQTT Topics
- Raw: `car/<hersteller>/<kennzeichen>/...`
- Mapped: `car/<hersteller>/<kennzeichen>/mapped/...`

## Hinweise
- BMW- und GWM-Anbindung sind in `v0.1.3` noch als Scaffold vorbereitet.
- Diese Version behebt primär die fehlende Home-Assistant-Repository-Struktur.
