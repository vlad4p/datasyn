FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV HOST=0.0.0.0 \
    PORT=8040 \
    DUCKDB_PATH=/data/warehouse.duckdb \
    SQL_ROW_CAP=500 \
    MCP_HTTP_PATH=/mcp

EXPOSE 8040

CMD ["python", "server.py"]
