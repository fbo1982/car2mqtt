ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.19

FROM mcr.microsoft.com/dotnet/sdk:8.0-alpine AS ora2mqtt-builder
WORKDIR /src
COPY third_party/ora2mqtt/libgwmapi ./libgwmapi
COPY third_party/ora2mqtt/ora2mqtt ./ora2mqtt
COPY third_party/ora2mqtt/openssl.cnf ./openssl.cnf
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "amd64" ]; then RID=linux-musl-x64;     elif [ "$TARGETARCH" = "arm64" ]; then RID=linux-musl-arm64;     elif [ "$TARGETARCH" = "arm" ]; then RID=linux-musl-arm;     else RID=linux-musl-x64; fi     && dotnet publish -c Release -o /out -r $RID --sc ./ora2mqtt/ora2mqtt.csproj     && cp ./openssl.cnf /out/openssl.cnf     && cp ./libgwmapi/Resources/gwm_root.pem /out/gwm_root.pem

FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    APP_PORT=8099 \
    APP_DATA_DIR=/config/car2mqtt \
    OPENSSL_CONF=/opt/ora2mqtt/openssl.cnf \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8

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
