FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY utils ./utils
COPY scrapers ./scrapers

ENV HOST=0.0.0.0 \
    PORT=8042 \
    DATA_LOCAL_ROOT=/data-local \
    MCP_HTTP_PATH=/mcp \
    HTTP_TIMEOUT_SECONDS=60 \
    HTTP_USER_AGENT="Datacyber-Scrapper/1.0 (+https://github.com/datacyber)"

EXPOSE 8042

CMD ["python", "server.py"]
