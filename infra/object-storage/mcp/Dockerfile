FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV HOST=0.0.0.0 \
    PORT=8044 \
    MCP_HTTP_PATH=/mcp \
    MINIO_ENDPOINT=http://datacyber-object-minio:9000 \
    MINIO_ACCESS_KEY=minioadmin \
    MINIO_SECRET_KEY=minioadmin123 \
    MINIO_SECURE=false \
    MINIO_DEFAULT_BUCKET=data-local

EXPOSE 8044

CMD ["python", "server.py"]
