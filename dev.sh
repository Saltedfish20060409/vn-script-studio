#!/usr/bin/env bash
# VN Script Studio one-click dev launcher (macOS / Linux).
# Windows users: use dev.ps1 instead.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PY="$BACKEND/.venv/bin/python"

info()  { printf '\033[36m== %s ==\033[0m\n' "$*"; }
warn()  { printf '\033[33m%s\033[0m\n' "$*"; }
die()   { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

SKIP_DOCKER=0
NO_BROWSER=0
for arg in "$@"; do
  case "$arg" in
    -SkipDocker|--skip-docker) SKIP_DOCKER=1 ;;
    -NoBrowser|--no-browser)   NO_BROWSER=1 ;;
  esac
done

info "VN Script Studio one-click dev"

[ -x "$PY" ] || die "Missing backend/.venv — run once:
  cd backend
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  cp .env.example .env"

[ -f "$BACKEND/.env" ] || die "Missing backend/.env — copy .env.example to .env first"

if [ "$SKIP_DOCKER" = "0" ]; then
  info "postgres/redis (docker compose)"
  ( cd "$ROOT" && docker compose up -d ) || die "docker compose up failed"
fi

if [ ! -d "$FRONTEND/node_modules" ]; then
  warn "frontend/node_modules missing — running npm install ..."
  ( cd "$FRONTEND" && npm install ) || die "npm install failed"
fi

# Run backend (reload) and frontend (vite) in background, then open browser.
info "backend on :8000"
( cd "$BACKEND" && PYTHONPATH=. "$PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 ) &
BACK_PID=$!

info "frontend on :5173"
( cd "$FRONTEND" && npm run dev ) &
FRONT_PID=$!

trap 'warn "stopping…"; kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT INT TERM

# wait for backend then open browser
for _ in $(seq 1 40); do
  if curl -s -o /dev/null --max-time 1 http://127.0.0.1:8000/health 2>/dev/null; then
    break
  fi
  sleep 0.5
done

if [ "$NO_BROWSER" = "0" ]; then
  ( command -v xdg-open >/dev/null && xdg-open http://localhost:5173 ) \
    || ( command -v open >/dev/null && open http://localhost:5173 ) \
    || true
fi

info "Ready: http://localhost:5173  (Ctrl+C to stop both)"
wait
