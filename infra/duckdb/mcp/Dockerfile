FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import duckdb; c=duckdb.connect(); c.execute('INSTALL quack;'); c.execute('INSTALL httpfs;'); c.close()"

COPY server.py duckdb_service.py .

ENV HOST=0.0.0.0 \
    PORT=8040 \
    DUCKDB_PATH=/data/warehouse.duckdb \
    SQL_ROW_CAP=500 \
    MCP_HTTP_PATH=/mcp \
    QUACK_BIND_URI=quack:0.0.0.0:9494 \
    QUACK_ENABLE=true

EXPOSE 8040 9494

CMD ["python", "server.py"]
