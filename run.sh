#!/usr/bin/with-contenv bashio
set -euo pipefail

export PYTHONPATH="/opt/car2mqtt/app"
export CAR2MQTT_DATA_DIR="/data/car2mqtt"
mkdir -p "$CAR2MQTT_DATA_DIR"

exec python3 -m car2mqtt.main
