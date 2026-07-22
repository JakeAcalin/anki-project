#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your ANTHROPIC_API_KEY to enable AI features."
fi

# Export .env into the shell too, not just for Python: ANKI_APP_HOST/PORT below
# are read at the shell level (they pick the --host/--port flags), so without
# this, setting them in .env alone would silently do nothing.
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Warning: ffmpeg not found on PATH. Video/audio processing will fail until it's installed."
  echo "  macOS:  brew install ffmpeg"
  echo "  Ubuntu: sudo apt install ffmpeg"
fi

HOST="${ANKI_APP_HOST:-127.0.0.1}"
if [ "$HOST" = "0.0.0.0" ]; then
  echo "Binding to 0.0.0.0 — reachable from other devices on your network/Tailscale, not just this machine."
  if [ -z "${APP_USERNAME:-}" ] || [ -z "${APP_PASSWORD:-}" ]; then
    echo "Warning: APP_USERNAME/APP_PASSWORD are not both set — anyone who can reach this address has full access."
  fi
fi

exec python -m uvicorn backend.main:app --host "$HOST" --port "${ANKI_APP_PORT:-8000}" --reload
