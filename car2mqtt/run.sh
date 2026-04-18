#!/usr/bin/with-contenv bashio
set -euo pipefail

export LOG_LEVEL="$(bashio::config 'log_level')"
export APP_PORT="8099"
export APP_DATA_DIR="/config/car2mqtt"
export MQTT_HOST="$(bashio::config 'mqtt_host')"
export MQTT_PORT="$(bashio::config 'mqtt_port')"
export MQTT_USERNAME="$(bashio::config 'mqtt_username')"
export MQTT_PASSWORD="$(bashio::config 'mqtt_password')"
export MQTT_BASE_TOPIC="$(bashio::config 'mqtt_base_topic')"
export MQTT_QOS="$(bashio::config 'mqtt_qos')"
export MQTT_RETAIN="$(bashio::config 'mqtt_retain')"
export MQTT_TLS="$(bashio::config 'mqtt_tls')"

mkdir -p "$APP_DATA_DIR"
mkdir -p "$APP_DATA_DIR/providers"
mkdir -p "$APP_DATA_DIR/logs"

python -m app.main
