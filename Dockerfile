# VoiceGuard unified backend — single-container production image.
# One process serves REST + WebSockets (B1..B4); see backend/cloud.py.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/voiceguard

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python backend packages (stdlib-only ML mock — no build tools needed).
COPY backend ./backend
COPY backend1 ./backend1
COPY backend2 ./backend2

# Render injects $PORT. Exactly one worker: all call/evidence/alert/audio
# state is in-memory, so extra workers would split (not share) it.
# --proxy-headers: TLS terminates at Render's proxy; this restores the real
# client scheme/host so wss:// and redirects behave correctly.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.cloud:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers"]
