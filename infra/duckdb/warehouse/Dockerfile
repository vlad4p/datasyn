FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir "duckdb>=1.5.3,<2"

WORKDIR /data

COPY init_db.py /init_db.py

CMD ["sh", "-c", "python /init_db.py && exec tail -f /dev/null"]
