FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow \
    WEBAPP_HOST=0.0.0.0 \
    WEBAPP_PORT=8080 \
    LOG_LEVEL=INFO

# tzdata — для ZoneInfo, tini — корректная обработка SIGTERM,
# curl — для Docker HEALTHCHECK (/healthz), ca-certificates — для HTTPS к CalDAV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tini \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY satellite/ satellite/
COPY telegram_test_command.py ./

RUN useradd --system --create-home --home-dir /app --shell /usr/sbin/nologin satellite \
    && mkdir -p /app/logs \
    && chown -R satellite:satellite /app

USER satellite

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --show-error \
        "http://127.0.0.1:${WEBAPP_PORT}/healthz" >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "telegram_test_command.py"]
