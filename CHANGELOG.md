# Changelog

## 1.2.65

- Corrected BMW powertrain classification for BEV, hybrid and combustion vehicles.
- BMW generic remaining-range data is no longer interpreted as fuel range on pure EVs.
- 48-V / battery-management data alone no longer classifies combustion BMWs as hybrids.
- Obsolete retained MQTT metrics are actively cleared when the normalized powertrain changes.
- Added regression coverage for BMW powertrain mapping and retained-topic cleanup.

## 1.2.64

- Fixed `500 Internal Server Error` when saving existing vehicles.
- Restored the `normalize_plate` import in the vehicle update path.
- Added regression coverage for vehicle saving.

## 1.2.60

- Improved Home Assistant zone resolution for EVCC Geo Detection.
- Added fallbacks for `zone.home` and custom zones.
- Zone lookup errors are surfaced in logs and status output.

## 1.2.59

- Geo-Shelly trigger selection moved from global settings to each local or remote vehicle.

## 1.2.58

- Added Geo-Shelly automation for site-local arrival/departure switching.

## 1.2.56

- EVCC `limitsoc` no longer uses an artificial MQTT timeout.

## 1.2.55

- Improved ACCIONA / Silence EVCC defaults and charging-port mapping.

## 1.2.54

- Added local EVCC Geo Detection with `evccStatus`, `evccAtSite`, `evccDistance` and `evccGeoReason` topics.
