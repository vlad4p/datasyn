FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV HOST=0.0.0.0 \
    PORT=8041 \
    MCP_HTTP_PATH=/mcp \
    MONGO_URI=mongodb://mongo:27017 \
    MONGO_DB=datacyber_catalog

EXPOSE 8041

CMD ["python", "server.py"]
