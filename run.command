#!/bin/sh
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"

PI_HOST="${PI_HOST:-pi5}"
PI_USER="${PI_USER:-pi}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"

# If something is already on the port, stop it to avoid "Address already in use".
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti tcp:$PORT || true)"
  if [ -n "$PIDS" ]; then
    echo "Stopping existing process on port $PORT: $PIDS"
    kill $PIDS 2>/dev/null || true
    sleep 0.5
  fi
fi

python3 "$DIR/server.py" --host "$HOST" --port "$PORT" --pi-host "$PI_HOST" --pi-user "$PI_USER" &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

sleep 2

if command -v open >/dev/null 2>&1; then
  open "http://$HOST:$PORT"
else
  echo "Server running on http://$HOST:$PORT"
fi

wait "$SERVER_PID"
