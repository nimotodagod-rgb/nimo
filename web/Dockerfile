FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=10000

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libreoffice-impress-nogui \
    python3 \
    python3-flask \
    python3-pil \
    python3-psycopg2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY office_worker.py /app/office_worker.py
COPY assets /app/assets
COPY web /app/web

WORKDIR /app/web
EXPOSE 10000
CMD ["python3", "server.py"]
