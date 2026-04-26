FROM python:3.12-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/opt/dagster/dagster_home

WORKDIR /opt/dagster/app

COPY pyproject.toml ./
COPY workspace.yaml ./
COPY {name} ./{name}

RUN pip install --no-cache-dir -e .

RUN mkdir -p $DAGSTER_HOME

EXPOSE {port}

# `dagster dev` runs both the webserver and a local daemon (schedules/sensors).
CMD ["dagster", "dev", "-h", "0.0.0.0", "-p", "{port}", "-w", "workspace.yaml"]
