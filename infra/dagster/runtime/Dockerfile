# Image for dagster-webserver and dagster-daemon. No pipeline code here;
# user code is loaded remotely via the gRPC server (see ``../user_code/Dockerfile``).

FROM python:3.11-slim

RUN pip install --no-cache-dir \
    dagster \
    dagster-graphql \
    dagster-webserver \
    dagster-postgres \
    dagster-docker

ENV DAGSTER_HOME=/opt/dagster/dagster_home/

RUN mkdir -p $DAGSTER_HOME

COPY docker-entrypoint.sh dagster.yaml workspace.yaml $DAGSTER_HOME/
RUN chmod +x "$DAGSTER_HOME/docker-entrypoint.sh" \
    && mv "$DAGSTER_HOME/dagster.yaml" "$DAGSTER_HOME/dagster.yaml.template"

WORKDIR $DAGSTER_HOME
ENTRYPOINT ["/opt/dagster/dagster_home/docker-entrypoint.sh"]
