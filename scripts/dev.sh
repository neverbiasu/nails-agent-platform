#!/usr/bin/env bash
#
# Local dev launcher: starts FastAPI + merchant Streamlit + consumer Streamlit
# + Caddy reverse proxy. Logs go to logs/<svc>.log. Ctrl-C stops everything.
#
# Routes after start-up:
#   http://localhost:8080/        → merchant Streamlit (demo/app.py)
#   http://localhost:8080/user/   → consumer Streamlit (demo_v1/app.py)
#   http://localhost:8080/api/    → FastAPI
#   http://localhost:8000         → FastAPI direct (no rewrite)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

pids=()
cleanup() {
  echo
  echo "→ shutting down…"
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "→ starting FastAPI on :8000 (logs/api.log)"
uvicorn nails_agent.api.main:app --host 0.0.0.0 --port 8000 --reload \
  >logs/api.log 2>&1 &
pids+=($!)

echo "→ starting merchant Streamlit on :8501 (logs/merchant.log)"
streamlit run demo/app.py --server.port 8501 --server.headless true \
  >logs/merchant.log 2>&1 &
pids+=($!)

echo "→ starting consumer V1 Streamlit on :8503 with /user prefix (logs/consumer.log)"
NAILS_API_BASE="http://localhost:8000" \
streamlit run demo_v1/app.py --server.port 8503 --server.headless true \
  --server.baseUrlPath=/user \
  >logs/consumer.log 2>&1 &
pids+=($!)

if command -v caddy >/dev/null 2>&1; then
  echo "→ starting Caddy on :8080 (logs/caddy.log)"
  caddy run --config "$ROOT/Caddyfile" >logs/caddy.log 2>&1 &
  pids+=($!)
  echo
  echo "  Merchant:  http://localhost:8080/"
  echo "  Consumer:  http://localhost:8080/user/"
  echo "  API:       http://localhost:8080/api/health"
else
  echo "  (Caddy not installed — skipping reverse proxy. Access services directly:)"
  echo "  Merchant:  http://localhost:8501/"
  echo "  Consumer:  http://localhost:8503/"
  echo "  API:       http://localhost:8000/health"
fi
echo
echo "Press Ctrl-C to stop everything."
wait
