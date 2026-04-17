# Car2MQTT – HAOS Add-on Scaffold

Version: **0.1.0**

Dieses Repository ist das erste Grundgerüst für ein Home-Assistant-Add-on, das mehrere Fahrzeuge und Hersteller über eine modulare GUI verwalten soll.

## Ziele von V0.1.0
- HAOS-Add-on-Grundstruktur
- Web-UI mit Kachelansicht
- Fahrzeug hinzufügen / bearbeiten / löschen
- Hersteller-Auswahl (BMW, GWM/ORA)
- Provider-Plugin-System als Basis für weitere Hersteller
- Persistente Konfiguration in `/data`
- MQTT-Topic-Strategie vorbereitet
- Mapping-Layer für kanonische Daten vorbereitet
- Start/Stop-Simulation pro Fahrzeug über internen Manager

## Noch nicht vollständig in V0.1.0
- Keine echte BMW-Authentifizierung
- Keine echte Anbindung an `bmw-python-streaming-mqtt-bridge`
- Keine echte Anbindung an `ora2mqtt`
- Noch kein echtes MQTT-Publishing der Live-Daten
- Noch keine Home-Assistant-Discovery

## Geplante nächste Versionen
- **0.2.0**: BMW-Provider mit echtem Auth-Flow and Token-Speicherung
- **0.3.0**: MQTT-Publisher + Mapping-Ausgabe
- **0.4.0**: GWM/ORA-Provider-Integration

## Start lokal
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=app
python -m car2mqtt.main
```

Dann im Browser öffnen:

```text
http://127.0.0.1:8099
```

## Repository-Struktur
```text
car2mqtt-v0.1.0/
├── app/
│   └── car2mqtt/
│       ├── mapping/
│       ├── providers/
│       ├── static/
│       ├── templates/
│       ├── config.py
│       ├── main.py
│       ├── manager.py
│       ├── models.py
│       ├── mqtt.py
│       └── store.py
├── translations/
├── CHANGELOG.md
├── config.yaml
├── DOCS.md
├── Dockerfile
├── README.md
├── requirements.txt
├── run.sh
└── VERSION
```
