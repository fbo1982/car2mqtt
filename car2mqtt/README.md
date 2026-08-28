# 🚗 Car2MQTT

[![Add Car2MQTT repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Ffbo1982%2Fcar2mqtt)

**Car2MQTT** ist eine Home-Assistant-App (früher Add-on) für Fahrzeugdaten über MQTT. Sie bündelt mehrere Hersteller in einer Oberfläche, mappt Rohdaten auf ein gemeinsames Schema und stellt die Daten für **Home Assistant**, **MQTT** und **EVCC** bereit.

## Installation

### Direkt zu Home Assistant hinzufügen

Klicke auf den Button ganz oben. Home Assistant öffnet den Dialog zum Hinzufügen des Repositorys mit dieser Adresse bereits vorausgefüllt:

```text
https://github.com/fbo1982/car2mqtt
```

Danach:

1. Repository in Home Assistant hinzufügen.
2. Im **App Store** nach **Car2MQTT** suchen.
3. Car2MQTT installieren und starten.
4. Die Weboberfläche öffnen.
5. MQTT konfigurieren und anschließend die gewünschten Fahrzeuge anlegen.

### Manuelle Installation

1. Öffne in Home Assistant **Einstellungen → Apps → App Store**.
2. Öffne oben rechts das **⋮-Menü** und wähle **Repositories**.
3. Füge dieses Repository hinzu:

   ```text
   https://github.com/fbo1982/car2mqtt
   ```

4. Öffne anschließend **Car2MQTT** im App Store und installiere die App.

### Voraussetzungen

- Home Assistant OS bzw. eine Installation mit Supervisor/App-Unterstützung
- erreichbarer MQTT-Broker
- gültiger Zugang für die jeweils verwendete Fahrzeugquelle

---

## Version 1.2.66

**1.2.66 basiert funktional unverändert auf der getesteten Version 1.2.65.**

Diese Version aktualisiert die öffentliche Projektdokumentation, die Installationshinweise und die Repository-Darstellung. Die Fahrzeuglogik der funktionierenden 1.2.65 wurde für diese Veröffentlichung nicht verändert.

### Enthaltener Stand aus 1.2.65

- BMW-Antriebserkennung korrigiert: `vehicle.drivetrain.lastRemainingRange` gilt nicht mehr als Beweis für einen Kraftstofftank.
- `stateOfCharge.target` allein klassifiziert ein Fahrzeug nicht mehr als elektrifiziert.
- Reine BMW-Elektrofahrzeuge veröffentlichen keine `fuelLevel`-/`fuelRange`-Werte mehr im `mapped`-Schema.
- Veraltete retained MQTT-Werte werden bei sicher erkanntem Antriebstyp bereinigt.
- Verbrenner werden analog von veralteten EV-Metriken bereinigt.
- Regressionstests decken BMW-Verbrenner, BEV und PHEV anhand der beobachteten CarData-Strukturen ab.

---

## Unterstützte Fahrzeugquellen

| Hersteller / Quelle | Integration | Status |
|---|---|---|
| BMW CarData (EU Data Act) | native Integration | ✅ getestet |
| GWM / ORA | native Integration | ✅ getestet |
| ACCIONA / Silence (MySilence) | native Cloud-Integration | ✅ getestet |
| Remote MQTT | generische MQTT-Quelle | ✅ unterstützt |

> Car2MQTT ist ein Community-Projekt und steht in keiner offiziellen Verbindung zu BMW, GWM, ORA, ACCIONA, Silence, Home Assistant oder EVCC. Nicht öffentlich dokumentierte Hersteller-Schnittstellen können sich jederzeit ändern.

## Highlights

- eine Weboberfläche für mehrere Fahrzeuge und Hersteller
- Fahrzeugdaten lokal per MQTT veröffentlichen
- einheitliches `mapped`-Schema über Hersteller hinweg
- Home Assistant MQTT Discovery
- optionaler MQTT Device Tracker
- Fahrzeugdaten an zusätzliche / entfernte MQTT-Broker weiterleiten
- Remote-Fahrzeuge aus MQTT automatisch erkennen und im Dashboard anzeigen
- EVCC-Konfiguration pro Fahrzeug direkt aus der UI erzeugen
- standortabhängige EVCC-Fahrzeugerkennung über GPS und Home-Assistant-Zonen
- Geo-Shelly-Automationen für Ladepunkte
- Live-Logs sowie ReAuth-/Reconnect-Hilfen für unterstützte Hersteller

## Was Car2MQTT macht

Car2MQTT verarbeitet Fahrzeugdaten in mehreren Stufen:

1. **Herstellerdaten abrufen** – beispielsweise BMW CarData, GWM/ORA oder MySilence.
2. **Rohdaten nach MQTT schreiben** – unter dem jeweiligen Hersteller-/Fahrzeugpfad.
3. **Daten auf ein gemeinsames Schema mappen** – beispielsweise SoC, Reichweite, Kilometerstand, Ladezustand, Anschlussstatus und Fahrzeugtyp.
4. **Daten optional an weitere MQTT-Server weiterleiten.**
5. **Remote-Fahrzeuge aus MQTT wieder einlesen** und im Dashboard darstellen.
6. **Home-Assistant- und EVCC-Helfer erzeugen**, die direkt aus der Oberfläche kopiert werden können.

## MQTT-Struktur

Typische Topics sind:

```text
car/<manufacturer>/<plate>/_meta/...
car/<manufacturer>/<plate>/mapped/...
car/<manufacturer>/<plate>/...
```

Beispiele:

```text
car/bmw/GGCA501E/mapped/soc
car/gwm/GGCA911E/mapped/range
car/acconia/SIL123/mapped/soc
car/acconia/SIL123/mapped/latitude
car/acconia/SIL123/mapped/longitude
car/bmw/GGCA1056/_meta/last_update
```

Je nach Hersteller und verfügbarem Datenumfang werden unter anderem folgende Werte bereitgestellt:

- SoC
- Restreichweite
- Kilometerstand
- Ladezustand
- Anschlussstatus
- GPS-Position
- Tankinhalt / Kraftstoffreichweite bei passenden Fahrzeugen
- Ladelimit, sofern vom Hersteller geliefert

## Fahrzeugtypen

Car2MQTT unterscheidet die Fahrzeugdarstellung nach erkanntem Antrieb.

### Elektrofahrzeug

- SoC
- elektrische Reichweite
- lädt
- angesteckt
- Kilometerstand
- Ladelimit, sofern verfügbar

### Plug-in-Hybrid / Hybrid mit nutzbarem Traktionsakku

- SoC / E-Reichweite
- Tankinhalt / Kraftstoffreichweite
- lädt
- angesteckt
- Kilometerstand
- Ladelimit, sofern verfügbar

### Verbrenner

- Tankinhalt
- Kraftstoffreichweite
- Kilometerstand
- Antrieb

## Home Assistant MQTT Discovery

Car2MQTT kann Fahrzeug-Entitäten über **MQTT Discovery** automatisch in Home Assistant bereitstellen.

Die Funktion wird unter **Einstellungen → Home Assistant → MQTT Discovery** aktiviert. Discovery-Nachrichten werden anschließend beim Start sowie beim Anlegen oder Ändern eines Fahrzeugs veröffentlicht.

Bei einer Migration von manuell angelegten MQTT-Sensoren sollte die bestehende Konfiguration zunächst geprüft bzw. bereinigt werden, damit keine doppelten Entitäten entstehen.

Je nach Fahrzeugquelle können unter anderem SoC, Reichweite, Kilometerstand, Ladezustand, Anschlussstatus, Ladelimit, Akkukapazität und weitere Zustände angelegt werden. Nicht verfügbare Herstellerwerte bleiben in Home Assistant unbekannt.

Der optionale Device Tracker ist davon unabhängig konfigurierbar.

## BMW CarData

Die BMW-Integration verwendet BMW CarData / EU-Data-Act-Daten und mappt die verfügbaren Fahrzeugwerte in das gemeinsame Car2MQTT-Schema.

Ab 1.2.65 wurde die Antriebsklassifizierung insbesondere für folgende Fälle robuster gemacht:

- reine Verbrenner / Mild-Hybride
- reine Elektrofahrzeuge
- Plug-in-Hybride

Dadurch sollen bei BEVs keine alten Tankwerte und bei Verbrennern keine alten EV-Werte im retained MQTT-Zustand verbleiben.

## GWM / ORA

Die GWM-/ORA-Integration ist in Car2MQTT integriert und unterstützt die für den Betrieb benötigten Authentifizierungs-, ReAuth- und Fahrzeugdatenpfade.

Der GWM-/ORA-Teil verwendet bzw. enthält technische Arbeit, die auf dem ursprünglichen Projekt **ora2mqtt von zivillian** basiert:

```text
https://github.com/zivillian/ora2mqtt
```

Car2MQTT hat diese Funktionalität für den eigenen Multi-Fahrzeug-, Home-Assistant-, MQTT- und EVCC-Workflow umfangreich erweitert und integriert. Die Herkunft des ursprünglichen ORA-Ansatzes soll ausdrücklich transparent bleiben.

## ACCIONA / Silence (MySilence)

Die MySilence-Anbindung fragt die Fahrzeugdaten read-only über die von der MySilence-App verwendete Cloud-Schnittstelle ab.

Unterstützt werden – sofern vom Backend geliefert – unter anderem:

- SoC
- Restreichweite
- GPS-Position (`latitude`, `longitude`, optional `altitude`)
- Ladezustand
- Anschlussstatus
- feste Fahrzeugauswahl über FrameNo, IMEI oder Name
- konfigurierbares Polling

Die MySilence-Schnittstelle ist nicht offiziell dokumentiert. Änderungen an App oder Backend können daher Anpassungen in Car2MQTT erforderlich machen.

Beim Mapping hat ein expliziter Anschlusswert (`plugged`, `connected`, `chargerConnected` oder `chargingConnected`) Vorrang vor dem Ladeflag. Nur wenn kein separater Anschlusswert vorhanden ist, wird `charging` als Fallback für `plugged` verwendet.

## Remote MQTT / verteilte Installationen

Car2MQTT kann Fahrzeugdaten zusätzlich an weitere MQTT-Broker verteilen.

Damit sind zum Beispiel folgende Setups möglich:

- ein zentraler Car2MQTT-Standort ruft Herstellerdaten ab
- weitere Home-Assistant-Installationen erhalten diese Daten per MQTT
- Remote-Fahrzeuge erscheinen dort automatisch im Dashboard
- lokale und Remote-Fahrzeuge können gleichzeitig verwendet werden

Die Remote-Darstellung ist bewusst reduziert. Status- und Fahrdaten sowie Copy-Konfigurationen bleiben verfügbar, die Fahrzeugquelle selbst wird jedoch am Ursprungssystem verwaltet.

## EVCC

Für jedes Fahrzeug kann Car2MQTT eine passende EVCC-Konfiguration erzeugen.

Der Copy Helper stellt unter anderem Vorlagen bereit für:

- EVCC-Fahrzeugabschnitt
- `configuration.yaml`
- `automations.yaml`
- fahrzeugspezifische Variablenblöcke

### EVCC Geo Detection

Car2MQTT kann auf jedem Standort lokal einen EVCC-Zustand aus Fahrzeugverbindung, GPS und einer Home-Assistant-Zone ableiten:

```text
car/<manufacturer>/<plate>/mapped/evccStatus
car/<manufacturer>/<plate>/mapped/evccAtSite
car/<manufacturer>/<plate>/mapped/evccDistance
car/<manufacturer>/<plate>/mapped/evccGeoReason
```

`evccStatus` verwendet die EVCC-Zustände:

- `A` – nicht verbunden / nicht am Standort
- `B` – verbunden
- `C` – lädt

Ist der Geo-Filter aktiviert, werden `B` und `C` nur ausgegeben, wenn sich das Fahrzeug innerhalb des konfigurierten Radius um die ausgewählte Home-Assistant-Zone befindet.

Die ursprünglichen Herstellerwerte `mapped/plugged` und `mapped/charging` werden dabei nicht verändert.

Das ist insbesondere für verteilte Installationen wichtig: Dasselbe Fahrzeug kann an Standort A lokal `A` und an Standort B gleichzeitig `B` oder `C` liefern.

### Home-Zone Resolver

Die Geo-Erkennung liest die ausgewählte Home-Assistant-Zone über die Home-Assistant-API. Für `zone.home` existiert zusätzlich ein Fallback auf die Home-Assistant-Systemkoordinaten. Fehler beim Zonenabruf werden im Log und im Geo-Status sichtbar gemacht.

## Geo-Shelly Automation

Für schaltbare Lade-Steckdosen kann Car2MQTT einen Shelly bei Geo-Ankunft einschalten und bei tatsächlicher Abfahrt wieder ausschalten.

Je lokalem oder Remote-Fahrzeug kann festgelegt werden, ob es die Geo-Shelly-Automation an diesem Standort auslösen darf. Mehrere Fahrzeuge können gleichzeitig ausgewählt werden. Ausgeschaltet wird erst, wenn keines der ausgewählten Fahrzeuge mehr vor Ort ist.

Unter **Einstellungen → Geo Automation** werden die standortbezogenen Shelly-Daten gepflegt:

- Host / IP
- Shelly `Switch ID`
- maximale Leistung für sicheres Ausschalten

Beim Shelly Pro 1PM ist die `Switch ID` üblicherweise `0` und bezeichnet den RPC-Kanal `Switch:0`.

## EVCC-Ladelimit

Das gemappte `limitSoc` ist ein langlebiger Fahrzeug-Einstellwert und kann unverändert bleiben, obwohl die Fahrzeugverbindung in Ordnung ist.

Die erzeugte EVCC-Konfiguration setzt für `limitsoc` deshalb keinen MQTT-Timeout. Live-Werte wie SoC, Reichweite und `evccStatus` behalten dagegen ihren konfigurierten Timeout, damit ein Ausfall der Datenquelle weiterhin sichtbar bleibt.

## Wichtige Bereiche der Weboberfläche

### Fahrzeuge

- lokale Fahrzeuge anlegen und bearbeiten
- Hersteller auswählen
- Zugangsdaten bzw. fahrzeugspezifische Parameter pflegen
- MQTT-Clients je Fahrzeug zuweisen
- Device Tracker je Fahrzeug konfigurieren
- Geo-Shelly-Trigger je Standort auswählen

### Einstellungen

- MQTT
- Home-Assistant-Zone
- MQTT Discovery
- Device Tracker
- EVCC Geo Detection
- Geo Automation

### MQTT Clients

- zusätzliche MQTT-Zielserver definieren
- Clients aktivieren / deaktivieren
- `mapped` und optional `raw` weitergeben
- Verbindungsstatus prüfen

### Copy Helper

- EVCC-Konfiguration kopieren
- Home-Assistant-Konfiguration kopieren
- Automations- und Variablenblöcke kopieren

## Sicherheit und Datenschutz

Bitte veröffentliche in Logs oder Issue-Berichten keine Zugangsdaten oder personenbezogenen Fahrzeugdaten.

Insbesondere sollten folgende Informationen entfernt bzw. anonymisiert werden:

- Kennzeichen
- Namen / Benutzernamen
- E-Mail-Adressen
- Hostnamen und interne Domains
- Passwörter
- Tokens / Refresh-Tokens
- VIN / Fahrgestellnummern, sofern sie für die Fehlersuche nicht zwingend erforderlich sind

## Projektstatus

Car2MQTT ist ein praxisorientiertes Community-Projekt mit Fokus auf Home Assistant, MQTT und EVCC. Die Herstellerintegrationen hängen teilweise von externen bzw. nicht öffentlich dokumentierten Schnittstellen ab. Änderungen seitens der Hersteller können deshalb jederzeit Anpassungen erforderlich machen.

Fehlerberichte und technische Rückmeldungen können über GitHub eingereicht werden:

```text
https://github.com/fbo1982/car2mqtt/issues
```

## Hinweis zu Marken und Drittprojekten

Alle genannten Marken und Produktnamen gehören den jeweiligen Rechteinhabern. Car2MQTT ist nicht offiziell mit den genannten Fahrzeugherstellern, Home Assistant oder EVCC verbunden.

Der GWM-/ORA-Bereich enthält bzw. basiert teilweise auf Arbeit aus **zivillian/ora2mqtt**. Die entsprechenden Herkunftshinweise bleiben im Projekt erhalten.
