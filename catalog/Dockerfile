# PostgreSQL for Datacyber catalog. Init scripts run on first empty data volume only.
FROM postgres:16-alpine

COPY migrations/ /docker-entrypoint-initdb.d/
