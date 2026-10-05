#!/usr/bin/env bash
# One-command local start: sets up the Python venv and npm packages if needed, seeds demo
# data on first run, then runs the API (http://localhost:8000) and the web app
# (http://localhost:5173). Ctrl+C stops both.
#
#   ./start.sh            start (setup on first run)
#   ./start.sh --reseed   wipe the local database and reseed demo data

# Always run in a fresh bash process, however this file was launched
# (zsh start.sh, sh start.sh, source start.sh, npm start, double-click...).
if [ -z "${BASH_VERSION:-}" ]; then
  /bin/bash "$0" "$@"; return $? 2>/dev/null || exit $?
fi
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  /bin/bash "${BASH_SOURCE[0]}" "$@"; return $?
fi

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

say() { printf '\033[1;34m[cellloop]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[cellloop] %s\033[0m\n' "$*" >&2; exit 1; }

# --- Python -------------------------------------------------------------------------
PY=""
# Prefer the venv's own interpreter if it already exists; macOS's /usr/bin/python3 is 3.9 (too old).
for cand in "$BACKEND/.venv/bin/python" python3.14 python3.13 python3.12 python3.11 \
            /usr/local/bin/python3 /opt/homebrew/bin/python3 \
            /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$(command -v "$cand")"; break
  fi
done
[ -n "$PY" ] || die "Python 3.11+ not found (macOS's built-in python3 is 3.9). Install it from https://www.python.org/downloads/ and re-run."

if [ ! -x "$BACKEND/.venv/bin/python" ]; then
  say "Creating Python virtual environment…"
  "$PY" -m venv "$BACKEND/.venv"
fi
VENV_PY="$BACKEND/.venv/bin/python"
STAMP="$BACKEND/.venv/.requirements.sha"
REQ_SHA="$(shasum "$BACKEND/requirements.txt" | cut -d' ' -f1)"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$REQ_SHA" ]; then
  say "Installing backend dependencies (first run takes a minute)…"
  "$VENV_PY" -m pip install --quiet --upgrade pip
  "$VENV_PY" -m pip install --quiet -r "$BACKEND/requirements.txt"
  echo "$REQ_SHA" > "$STAMP"
fi

# --- Node (works even when nvm isn't loaded in this shell) --------------------------
if ! command -v npm >/dev/null 2>&1; then
  NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1091
    set +u; . "$NVM_DIR/nvm.sh"; nvm use --silent default >/dev/null 2>&1 || true; set -u
  fi
fi
if ! command -v npm >/dev/null 2>&1; then
  LATEST_NODE="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort | tail -1 || true)"
  [ -n "$LATEST_NODE" ] && export PATH="$LATEST_NODE:$PATH"
fi
for p in /opt/homebrew/bin /usr/local/bin; do
  command -v npm >/dev/null 2>&1 || { [ -x "$p/npm" ] && export PATH="$p:$PATH"; }
done
command -v npm >/dev/null 2>&1 || die "Node.js 20+ not found. Install it from https://nodejs.org/ and re-run."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 20 ] || die "Node.js 20+ required (found $(node -v))."

if [ ! -d "$FRONTEND/node_modules" ] || [ "$FRONTEND/package.json" -nt "$FRONTEND/node_modules" ]; then
  say "Installing frontend dependencies…"
  (cd "$FRONTEND" && npm install --no-audit --no-fund --loglevel=error)
  touch "$FRONTEND/node_modules"
fi

# --- Ports (skip past anything already listening, e.g. another Vite app on 5173) --------
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
free_port() {
  local p="$1"
  while port_busy "$p"; do p=$((p + 1)); done
  echo "$p"
}
REQ_API="$API_PORT"; REQ_WEB="$WEB_PORT"
API_PORT="$(free_port "$API_PORT")"
WEB_PORT="$(free_port "$WEB_PORT")"
[ "$WEB_PORT" = "$API_PORT" ] && WEB_PORT="$(free_port $((WEB_PORT + 1)))"
[ "$API_PORT" != "$REQ_API" ] && say "Port $REQ_API is busy, using $API_PORT for the API."
[ "$WEB_PORT" != "$REQ_WEB" ] && say "Port $REQ_WEB is busy (another app?), using $WEB_PORT for the web app."

# --- Environment file ---------------------------------------------------------------
if [ ! -f "$BACKEND/.env" ]; then
  say "Creating backend/.env from backend/.env.example (with a random dev secret)…"
  SECRET="$("$VENV_PY" -c 'import secrets; print(secrets.token_hex(32))')"
  sed "s/^DEV_JWT_SECRET=.*/DEV_JWT_SECRET=$SECRET/" "$BACKEND/.env.example" > "$BACKEND/.env"
fi

# --- Database -----------------------------------------------------------------------
cd "$BACKEND"
# Fail early with the readable configuration report instead of a stack trace later.
"$VENV_PY" -c 'import app.core.config as c; c.get_settings()' || die "Fix the configuration in backend/.env (see messages above) and re-run."
if [ "${1:-}" = "--reseed" ]; then
  say "Reseeding demo data…"
  "$VENV_PY" -m app.scripts.seed --reset
elif ! "$VENV_PY" -c 'import sys; from sqlalchemy import select; from app.core.database import SessionLocal, init_db; from app.models import User; init_db(); sys.exit(0 if SessionLocal().scalar(select(User).limit(1)) else 1)' 2>/dev/null; then
  say "Seeding demo data…"
  "$VENV_PY" -m app.scripts.seed --reset
fi

# --- Run ----------------------------------------------------------------------------
PIDS=()
cleanup() { trap - INT TERM EXIT; say "Stopping…"; kill "${PIDS[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup INT TERM EXIT

say "Starting API on http://localhost:$API_PORT (docs: /docs)"
FRONTEND_URL="http://localhost:$WEB_PORT" CORS_ORIGINS="[\"http://localhost:$WEB_PORT\"]" "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --reload --reload-dir app &
PIDS+=($!)

for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1 || die "API did not start; see the log above."

say "Starting web app on http://localhost:$WEB_PORT"
cd "$FRONTEND"
VITE_API_PROXY="http://127.0.0.1:$API_PORT" npx vite --port "$WEB_PORT" --strictPort &
PIDS+=($!)

for _ in $(seq 1 40); do
  curl -sf "http://localhost:$WEB_PORT/" >/dev/null 2>&1 && break
  sleep 0.5
done
say "Ready → open http://localhost:$WEB_PORT and pick a demo account. Ctrl+C to stop."
if [ -z "${CELLLOOP_NO_BROWSER:-}" ] && command -v open >/dev/null 2>&1; then
  open "http://localhost:$WEB_PORT" >/dev/null 2>&1 || true
fi
wait
