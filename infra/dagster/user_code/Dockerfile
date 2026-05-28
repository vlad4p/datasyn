# Minimal gRPC code location (upstream deploy_docker pattern).
# No pipeline code in this repo — swap the image tag for ../datasyn-code when needed.

FROM python:3.11-slim

RUN pip install --no-cache-dir \
    dagster \
    dagster-postgres \
    dagster-docker

WORKDIR /opt/dagster/app
COPY definitions.py .

ENV DAGSTER_HOME=/opt/dagster/dagster_home/
RUN mkdir -p "$DAGSTER_HOME"

EXPOSE 4000

CMD ["dagster", "api", "grpc", "-h", "0.0.0.0", "-p", "4000", "-m", "definitions"]
