# Home Assistant Supervisor >= 2026.04 supplies BUILD_ARCH and BUILD_VERSION.
# Keep sane defaults for local development builds.
ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=dev

FROM mcr.microsoft.com/dotnet/sdk:8.0-alpine AS ora2mqtt-builder
ARG BUILD_ARCH
WORKDIR /src
COPY third_party/ora2mqtt/libgwmapi ./libgwmapi
COPY third_party/ora2mqtt/ora2mqtt ./ora2mqtt
COPY third_party/ora2mqtt/openssl.cnf ./openssl.cnf
RUN if [ "$BUILD_ARCH" = "amd64" ]; then RID=linux-musl-x64; \
    elif [ "$BUILD_ARCH" = "aarch64" ]; then RID=linux-musl-arm64; \
    else echo "Unsupported Home Assistant architecture: $BUILD_ARCH" >&2; exit 1; fi \
    && dotnet publish -c Release -o /out -r "$RID" --sc ./ora2mqtt/ora2mqtt.csproj \
    && cp ./openssl.cnf /out/openssl.cnf \
    && cp ./libgwmapi/Resources/gwm_root.pem /out/gwm_root.pem

# Since Supervisor 2026.04 build.yaml is no longer used. Select the official
# Home Assistant Python base image directly from BUILD_ARCH.
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.12-alpine3.19
ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Car2MQTT" \
    org.opencontainers.image.description="Multi-vehicle MQTT bridge with BMW wizard/auth flow for Home Assistant" \
    org.opencontainers.image.source="https://github.com/tbo1982/car2mqtt"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    APP_PORT=8099 \
    APP_DATA_DIR=/config/car2mqtt \
    OPENSSL_CONF=/opt/ora2mqtt/openssl.cnf \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    CAR2MQTT_VERSION=${BUILD_VERSION}

WORKDIR ${APP_HOME}

RUN apk add --no-cache bash curl ca-certificates icu-libs
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY --from=ora2mqtt-builder /out /opt/ora2mqtt
RUN chmod +x /opt/ora2mqtt/ora2mqtt && cp /opt/ora2mqtt/gwm_root.pem /etc/ssl/certs/gwm_root.pem || true

COPY run.sh /run.sh
RUN chmod a+x /run.sh
COPY app ./app
COPY third_party ./third_party

EXPOSE 8099
CMD [ "/run.sh" ]
