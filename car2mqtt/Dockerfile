ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.19
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    APP_PORT=8099 \
    APP_DATA_DIR=/config/car2mqtt

WORKDIR ${APP_HOME}

RUN apk add --no-cache bash curl
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY run.sh /run.sh
RUN chmod a+x /run.sh
COPY app ./app

EXPOSE 8099
CMD [ "/run.sh" ]
