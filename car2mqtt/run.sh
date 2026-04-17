#!/usr/bin/with-contenv bashio
set -euo pipefail

export LOG_LEVEL="$(bashio::config 'log_level')"
export APP_PORT="8099"
export APP_DATA_DIR="/config/car2mqtt"

mkdir -p "$APP_DATA_DIR"
mkdir -p "$APP_DATA_DIR/providers"
mkdir -p "$APP_DATA_DIR/logs"

python -m app.main
