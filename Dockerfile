FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY satellite/ satellite/
COPY telegram_test_command.py .

RUN useradd --system --create-home --home-dir /app --shell /usr/sbin/nologin satellite \
    && mkdir -p /app/logs \
    && chown -R satellite:satellite /app

USER satellite

ENV PYTHONUNBUFFERED=1

CMD ["python", "telegram_test_command.py"]
