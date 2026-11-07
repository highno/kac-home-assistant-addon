ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}

RUN apk add --no-cache \
      python3 \
      py3-jinja2 \
      py3-pillow \
      py3-requests \
      py3-yaml

COPY app /app/kac_bridge
COPY examples/kac.yaml /app/example-kac.yaml
COPY rootfs /

RUN chmod a+x /etc/s6-overlay/s6-rc.d/kac-display/run

ENV PYTHONPATH=/app

LABEL \
  org.opencontainers.image.title="Home Assistant Add-on: KAC Display Bridge" \
  org.opencontainers.image.description="Send Home Assistant entity values and image pages to KAC firmware displays" \
  org.opencontainers.image.source="https://github.com/highno/kac-home-assistant-addon" \
  org.opencontainers.image.licenses="MIT"
