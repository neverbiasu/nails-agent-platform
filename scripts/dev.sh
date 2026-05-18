#!/usr/bin/env bash
#
# Local dev launcher: XHS bridge + FastAPI + Chat UI + Consumer + Caddy
# Logs → logs/<svc>.log   Ctrl-C stops everything.
#
# Via Caddy (:8080):
#   /          → Chat UI (web/chat_app.py   :8501)
#   /user/     → C端试戴  (consumer/app.py   :8503)
#   /api/      → FastAPI  (nails_agent       :8000)
#
# Direct:
#   :18060 XHS REST bridge  (scripts/xhs_rest_bridge.mjs)
#   :8000  FastAPI
#   :8501  Chat UI
#   :8503  C端试戴
#
# XHS bridge endpoints (used by xhs_mcp_fetcher.py):
#   GET  /health
#   GET  /api/v1/login/status
#   GET  /api/v1/feeds/search?keyword=<kw>[&count=<n>]
#   GET  /api/v1/feeds/list[?count=<n>]
#
#   If session is expired, re-login first:
#     uv run python scripts/xhs_login.py --name nails
#
# MVP B端 endpoints:
#   POST /api/v1/trigger          触发 pipeline
#   GET  /api/v1/events           轮询 EventLog
#   POST /api/v1/review/approve   HITL 人工确认
#   POST /api/v1/action/publish   执行发布
#
# MVP C端 endpoints:
#   POST /sessions                创建会话（上传手型图）
#   POST /api/v1/tryon/submit     提交试戴任务
#   GET  /api/v1/tryon/{job_id}   轮询试戴结果

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

# ── Load .env if present ────────────────────────────────────────────────────
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  echo "→ loaded .env"
fi

# ── Install git pre-push hook ────────────────────────────────────────────────
HOOK_SRC="$ROOT/scripts/hooks/pre-push"
HOOK_DST="$ROOT/.git/hooks/pre-push"
if [ -f "$HOOK_SRC" ] && { [ ! -f "$HOOK_DST" ] || ! diff -q "$HOOK_SRC" "$HOOK_DST" >/dev/null 2>&1; }; then
  cp "$HOOK_SRC" "$HOOK_DST" && chmod +x "$HOOK_DST"
  echo "→ git pre-push hook installed"
fi

# ── Seed SQLite style library (idempotent) ───────────────────────────────────
if ! python -c "
import sqlite3, os
db = os.path.expanduser('~/.nails_agent/memory.db')
if not os.path.exists(db):
    raise SystemExit(1)
c = sqlite3.connect(db).execute('SELECT COUNT(*) FROM nail_styles_v2')
if c.fetchone()[0] == 0:
    raise SystemExit(1)
" 2>/dev/null; then
  echo "→ seeding SQLite style library…"
  python -m nails_agent.services.seed_loader || true
fi

# ── Cleanup on exit ──────────────────────────────────────────────────────────
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

# ── XHS REST bridge ──────────────────────────────────────────────────────────
# Node.js v23 (ABI 131) matches the better-sqlite3 native binary in xhs-mcp.
# Bun requires ABI 137 and cannot load the same binary, so we must use node.
XHS_BRIDGE_NODE="${XHS_BRIDGE_NODE:-}"
if [ -z "$XHS_BRIDGE_NODE" ]; then
  # Prefer the NVM node version that matches xhs-mcp's better-sqlite3 ABI 131
  for _v in v23.1.0 v23 v22.21.1 v22.22.2; do
    _candidate="$HOME/.nvm/versions/node/$_v/bin/node"
    if [ -x "$_candidate" ]; then
      XHS_BRIDGE_NODE="$_candidate"
      break
    fi
  done
  [ -z "$XHS_BRIDGE_NODE" ] && XHS_BRIDGE_NODE="$(command -v node 2>/dev/null || true)"
fi

if [ -n "$XHS_BRIDGE_NODE" ]; then
  echo "→ starting XHS REST bridge on :18060 (logs/xhs_bridge.log)"
  "$XHS_BRIDGE_NODE" "$ROOT/scripts/xhs_rest_bridge.mjs" --port 18060 \
    >logs/xhs_bridge.log 2>&1 &
  pids+=($!)
  # Wait until bridge is ready (max 10s)
  for i in $(seq 1 10); do
    if curl -sf http://localhost:18060/health >/dev/null 2>&1; then
      echo "   XHS bridge ready (${i}s)"
      break
    fi
    sleep 1
  done
else
  echo "  (Node.js not found — XHS bridge skipped, will use mock data)"
fi

# ── FastAPI ──────────────────────────────────────────────────────────────────
echo "→ starting FastAPI on :8000 (logs/api.log)"
uvicorn nails_agent.api.main:app --host 0.0.0.0 --port 8000 --reload \
  >logs/api.log 2>&1 &
pids+=($!)

# Wait until FastAPI is ready (max 15s)
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "   API ready (${i}s)"
    break
  fi
  sleep 1
done

# ── Chat UI ──────────────────────────────────────────────────────────────────
echo "→ starting Chat UI on :8501 (logs/chat.log)"
NAILS_API_BASE="http://localhost:8000" \
streamlit run web/chat_app.py --server.port 8501 --server.headless true \
  >logs/chat.log 2>&1 &
pids+=($!)

# ── C端 消费者试戴 ────────────────────────────────────────────────────────────
echo "→ starting C端试戴 on :8503 (logs/consumer.log)"
NAILS_API_BASE="http://localhost:8000" \
streamlit run consumer/app.py --server.port 8503 --server.headless true \
  >logs/consumer.log 2>&1 &
pids+=($!)

# ── Caddy ────────────────────────────────────────────────────────────────────
if command -v caddy >/dev/null 2>&1; then
  echo "→ starting Caddy on :8080 (logs/caddy.log)"
  caddy run --config "$ROOT/Caddyfile" >logs/caddy.log 2>&1 &
  pids+=($!)
  echo
  echo "  Chat UI:           http://localhost:8080/"
  echo "  C端试戴:            http://localhost:8080/user/"
  echo "  API health:        http://localhost:8080/api/health"
  echo "  Trigger pipeline:  POST http://localhost:8080/api/v1/trigger"
  echo "  EventLog:          GET  http://localhost:8080/api/v1/events?trigger_id=..."
  echo "  XHS bridge:        http://localhost:18060/health"
else
  echo "  (Caddy not found — direct access:)"
  echo "  Chat UI:           http://localhost:8501/"
  echo "  C端试戴:            http://localhost:8503/"
  echo "  API health:        http://localhost:8000/health"
  echo "  Trigger pipeline:  POST http://localhost:8000/api/v1/trigger"
  echo "  EventLog:          GET  http://localhost:8000/api/v1/events?trigger_id=..."
  echo "  XHS bridge:        http://localhost:18060/health"
fi
echo
echo "Press Ctrl-C to stop everything."
wait
