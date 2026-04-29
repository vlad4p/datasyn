FROM python:3.12-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/dagster/app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir -e .

EXPOSE 4000

# gRPC code location (Datacyber ``dagster_user_code`` service, port 4000).
CMD ["dagster", "api", "grpc", "-h", "0.0.0.0", "-p", "4000", "-m", "datasynk.definitions"]
