FROM python:3.12-slim-bookworm

# Install Docker CLI + Compose v2 plugin so the MCP can drive the host Docker
# daemon (mounted via /var/run/docker.sock) to build images and run/restart
# scaffolded Dagster project containers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && chmod a+r /etc/apt/keyrings/docker.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        docker-ce-cli \
        docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py scaffold.py docker_ops.py catalog_db.py catalog_sql_guard.py catalog_schema_inspect.py .
COPY templates ./templates

ENV HOST=0.0.0.0 \
    PORT=8043 \
    MCP_HTTP_PATH=/mcp \
    DAGSTER_PROJECTS_ROOT=/projects \
    DAGSTER_PROJECT_NETWORK=datacyber_mcp \
    DAGSTER_IMAGE_PREFIX=dagster \
    DAGSTER_CONTAINER_PREFIX=dagster \
    DAGSTER_DEFAULT_HOST_PORT=3001 \
    DAGSTER_WEBSERVER_PORT=3000

EXPOSE 8043

CMD ["python", "server.py"]
