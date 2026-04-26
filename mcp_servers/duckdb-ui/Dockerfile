FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends socat curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ``CALL start_ui()`` shells out to ``xdg-open`` to open a browser; slim images have no GUI.
# A no-op on PATH silences ``sh: 1: xdg-open: not found`` — use http://127.0.0.1:4213 from the host instead.
RUN printf '%s\n' '#!/bin/sh' 'exit 0' > /usr/local/bin/xdg-open && chmod +x /usr/local/bin/xdg-open

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY entrypoint.py .

ENV DUCKDB_PATH=/data/warehouse.duckdb \
    DUCKDB_UI_DUCK_PORT=4213 \
    DUCKDB_UI_PROXY_PORT=4214 \
    DUCKDB_UI_HOME=/tmp/duckdb-ui-home

# Container publishes PROXY_PORT (socat); DuckDB listens on 127.0.0.1:DUCKDB_UI_DUCK_PORT only.
EXPOSE 4214

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -sfL "http://127.0.0.1:${DUCKDB_UI_PROXY_PORT}/" >/dev/null || exit 1

CMD ["python", "entrypoint.py"]
