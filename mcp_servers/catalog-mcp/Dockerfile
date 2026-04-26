FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db.py schema_inspect.py sql_guard.py server.py .

ENV HOST=0.0.0.0 \
    PORT=8041 \
    MCP_HTTP_PATH=/mcp \
    DATABASE_URL=postgresql://datacyber:datacyber@catalog-db:5432/datacyber_catalog

EXPOSE 8041

CMD ["python", "server.py"]
