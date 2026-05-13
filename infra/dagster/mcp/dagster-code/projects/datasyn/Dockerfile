FROM python:3.12-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/opt/dagster/dagster_home

WORKDIR /opt/dagster/app

COPY pyproject.toml ./
COPY workspace.yaml ./
COPY src ./src

RUN pip install --no-cache-dir -e .

RUN mkdir -p $DAGSTER_HOME

EXPOSE 4000

# Align with ``infra/dagster`` ``dagster_user_code`` (gRPC code location).
CMD ["dagster", "api", "grpc", "-h", "0.0.0.0", "-p", "4000", "-m", "datasyn.definitions"]
