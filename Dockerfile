FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

ENV ANKI_APP_DATA_DIR=/app/data

# No VOLUME instruction here: Railway's builder rejects it. Persistence is
# configured on the host side instead — see README's "Deploying it" section
# (Railway Volumes tab, mount path /app/data).
EXPOSE 8000

CMD uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
