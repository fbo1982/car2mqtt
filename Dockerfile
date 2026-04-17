ARG BUILD_FROM=ghcr.io/home-assistant/base:3.22
FROM $BUILD_FROM

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/car2mqtt

RUN apk add --no-cache \
    python3 \
    py3-pip \
    bash

COPY requirements.txt /opt/car2mqtt/requirements.txt
RUN pip3 install --no-cache-dir -r /opt/car2mqtt/requirements.txt

COPY app /opt/car2mqtt/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
