#!/usr/bin/env bash
#
# run_pipeline.sh — one command to run the full 4-step nails pipeline while
# watching BOTH log streams live in the same terminal:
#
#   [xhs-mcp]  → the xiaohongshu-mcp REST bridge (Playwright scraper / browser /
#                bot-challenge details)         ……  logs/xhs_bridge.log
#   [agent]    → the Python pipeline itself (TrendScout → value → campaign →
#                report, incl. fetcher + LLM logs)  ……  logs/pipeline.log
#
# Usage:
#   scripts/run_pipeline.sh [options]
#
# Options:
#   --headful           Run the XHS scraper in a VISIBLE browser (default).
#                       Far less likely to be bot-challenged than headless.
#   --headless          Run the XHS scraper headless (CI / no display).
#   --login             Force an XHS QR re-login before running (scan with the
#                       secondary XHS app). Auto-triggered if not logged in.
#   --keep-bridge       Leave the XHS bridge running after the pipeline exits
#                       (default: stop it only if THIS script started it).
#   --output-dir DIR    Pipeline output dir (default: web/output).
#   --data-dir   DIR    Pipeline data dir   (default: web/data).
#   -h, --help          Show this help.
#
# Examples:
#   scripts/run_pipeline.sh                 # headful, auto-login if needed
#   scripts/run_pipeline.sh --login         # refresh cookies first, then run
#   scripts/run_pipeline.sh --headless --keep-bridge
#
# Env (optional, also read from .env):
#   XHS_MCP_HEADLESS            true|false  — overridden by --headful/--headless
#   NAILS_XHS_SEARCH_DELAY_MIN  per-keyword search throttle floor (sec, default 3)
#   NAILS_XHS_SEARCH_DELAY_MAX  per-keyword search throttle ceiling (sec, default 7)
#   XHS_BRIDGE_NODE             explicit path to a Node.js binary for the bridge
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

# ── Defaults / arg parsing ───────────────────────────────────────────────────
HEADLESS="${XHS_MCP_HEADLESS:-false}"   # default headful (more stealthy)
FORCE_LOGIN=0
KEEP_BRIDGE=0
OUTPUT_DIR="web/output"
DATA_DIR="web/data"

while [ $# -gt 0 ]; do
  case "$1" in
    --headful)     HEADLESS="false" ;;
    --headless)    HEADLESS="true" ;;
    --login)       FORCE_LOGIN=1 ;;
    --keep-bridge) KEEP_BRIDGE=1 ;;
    --output-dir)  OUTPUT_DIR="${2:?--output-dir needs a value}"; shift ;;
    --data-dir)    DATA_DIR="${2:?--data-dir needs a value}"; shift ;;
    -h|--help)     sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

PORT=18060
BRIDGE_LOG="logs/xhs_bridge.log"
PIPELINE_LOG="logs/pipeline.log"

# ── Colors (only when attached to a TTY) ─────────────────────────────────────
if [ -t 1 ]; then
  C_XHS=$'\033[36m'; C_AGENT=$'\033[32m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_XHS=""; C_AGENT=""; C_DIM=""; C_RST=""
fi
say() { echo "${C_DIM}→ $*${C_RST}"; }

# ── Load .env ────────────────────────────────────────────────────────────────
if [ -f "$ROOT/.env" ]; then
  set -a; # shellcheck disable=SC1091
  source "$ROOT/.env"; set +a
  say "loaded .env"
fi

# ── Resolve a Node.js that matches xhs-mcp's better-sqlite3 ABI (131 = node 23)
resolve_node() {
  if [ -n "${XHS_BRIDGE_NODE:-}" ]; then echo "$XHS_BRIDGE_NODE"; return; fi
  for _v in v23.1.0 v23 v22.21.1 v22.22.2; do
    _c="$HOME/.nvm/versions/node/$_v/bin/node"
    [ -x "$_c" ] && { echo "$_c"; return; }
  done
  command -v node 2>/dev/null || true
}

bridge_up() { curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; }
logged_in() {
  curl -sf "http://localhost:$PORT/api/v1/login/status" 2>/dev/null \
    | grep -q '"is_logged_in":[[:space:]]*true'
}

# ── State for cleanup ────────────────────────────────────────────────────────
STARTED_BRIDGE=0
BRIDGE_PID=""
TAIL_PID=""

cleanup() {
  local code=$?
  [ -n "$TAIL_PID" ] && kill "$TAIL_PID" 2>/dev/null || true
  if [ "$STARTED_BRIDGE" = "1" ] && [ "$KEEP_BRIDGE" = "0" ] && [ -n "$BRIDGE_PID" ]; then
    say "stopping XHS bridge (pid $BRIDGE_PID)"
    kill "$BRIDGE_PID" 2>/dev/null || true
  elif [ "$STARTED_BRIDGE" = "1" ]; then
    say "leaving XHS bridge running on :$PORT (pid $BRIDGE_PID)"
  fi
  exit $code
}
trap cleanup INT TERM EXIT

# ── 1. XHS bridge: reuse if up, else start ───────────────────────────────────
if bridge_up; then
  say "XHS bridge already running on :$PORT — reusing it"
else
  NODE_BIN="$(resolve_node)"
  [ -z "$NODE_BIN" ] && { echo "Node.js not found — cannot start XHS bridge" >&2; exit 1; }
  say "starting XHS bridge on :$PORT (headless=$HEADLESS) → $BRIDGE_LOG"
  XHS_MCP_HEADLESS="$HEADLESS" "$NODE_BIN" "$ROOT/scripts/xhs_rest_bridge.mjs" --port "$PORT" \
    >"$BRIDGE_LOG" 2>&1 &
  BRIDGE_PID=$!
  STARTED_BRIDGE=1
  for i in $(seq 1 15); do
    bridge_up && { say "XHS bridge ready (${i}s)"; break; }
    sleep 1
    [ "$i" = "15" ] && { echo "XHS bridge did not become healthy — see $BRIDGE_LOG" >&2; exit 1; }
  done
fi

# ── 2. Login: refresh cookies if asked or not logged in ──────────────────────
if [ "$FORCE_LOGIN" = "1" ] || ! logged_in; then
  if [ "$FORCE_LOGIN" = "1" ]; then
    say "forcing XHS re-login (scan the QR with your secondary XHS app)…"
  else
    say "XHS not logged in — launching QR login (scan with your secondary XHS app)…"
  fi
  XHS_MCP_HEADLESS=false uv run python scripts/xhs_login.py --name nails
  logged_in || { echo "Still not logged in after login flow — aborting." >&2; exit 1; }
  say "XHS login OK — cookies hot-reloaded into the bridge"
fi

# Quick sanity probe so we fail fast if the scraper is being bot-challenged.
PROBE="$(curl -sf "http://localhost:$PORT/api/v1/feeds/search?keyword=%E7%8C%AB%E7%9C%BC%E7%BE%8E%E7%94%B2&count=1" 2>/dev/null || true)"
if echo "$PROBE" | grep -q '"total":[[:space:]]*0'; then
  echo "${C_DIM}⚠ probe search returned 0 results — XHS may be bot-challenging the"
  echo "  scraper. The run will continue, but if you see empty signals, reset the"
  echo "  bridge and re-login:  scripts/run_pipeline.sh --login${C_RST}" >&2
else
  say "probe search returned data — scraper is live"
fi

# ── 3. Stream the bridge log live (prefixed) alongside the pipeline ──────────
say "tailing $BRIDGE_LOG as ${C_XHS}[xhs-mcp]${C_RST}"
# -n0: only show NEW lines from here on; -F: follow across rotation.
tail -n0 -F "$BRIDGE_LOG" 2>/dev/null \
  | sed -u "s/^/${C_XHS}[xhs-mcp]${C_RST} /" &
TAIL_PID=$!

echo
say "running pipeline → output=$OUTPUT_DIR  data=$DATA_DIR  (log: $PIPELINE_LOG)"
echo "${C_DIM}──────────────────────────────────────────────────────────────${C_RST}"

# Run the pipeline in the foreground, prefix every line as [agent], and also
# persist the full stream to logs/pipeline.log. PIPESTATUS preserves the real
# python exit code through the sed/tee pipe.
set +e
uv run python -u -m nails_agent run --output-dir "$OUTPUT_DIR" --data-dir "$DATA_DIR" 2>&1 \
  | sed -u "s/^/${C_AGENT}[agent]${C_RST}   /" \
  | tee "$PIPELINE_LOG"
RUN_CODE=${PIPESTATUS[0]}
set -e

echo "${C_DIM}──────────────────────────────────────────────────────────────${C_RST}"
if [ "$RUN_CODE" = "0" ]; then
  say "pipeline finished OK. Report: $OUTPUT_DIR/report.json"
else
  echo "pipeline exited with code $RUN_CODE — see $PIPELINE_LOG" >&2
fi
exit "$RUN_CODE"
