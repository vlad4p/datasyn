# Legacy gRPC user-code image (``ubika_dagster`` layout). **Not used** by default
# ``docker-compose.yaml`` — the live image is built from ``dagster-code/projects/datasyn``.
# To build this template, set compose ``build.context`` to a directory that contains
# ``pyproject.toml``, ``README.md``, and ``src/`` as referenced in the COPY lines below.

FROM python:3.11-slim

WORKDIR /opt/dagster/app

COPY pyproject.toml /opt/dagster/app/pyproject.toml
COPY README.md /opt/dagster/app/README.md
COPY src /opt/dagster/app/src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 4000

# Load the code location by module so Dagster picks up the installed package
# (matches `tool.dagster.module_name` in pyproject.toml).
CMD ["dagster", "api", "grpc", "-h", "0.0.0.0", "-p", "4000", "-m", "ubika_dagster.definitions"]
