#!/usr/bin/env bash
# Launch Chrome with remote debugging enabled, then open Douyin for login.
#
# Usage:
#   bash scripts/douyin_login.sh
#
# After Chrome opens:
#   1. Log into your Douyin account in the browser
#   2. Leave the Douyin tab open
#   3. The signal collector will detect and reuse the logged-in tab automatically
#
# The debug port (9222) is shared with Instagram CDP — you can use one Chrome
# instance for both fetchers simultaneously.

set -euo pipefail

PORT="${CDP_PORT:-9222}"

# Find Chrome binary
CHROME=""
for candidate in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "$(command -v google-chrome 2>/dev/null || true)" \
    "$(command -v chromium-browser 2>/dev/null || true)"; do
    if [[ -x "$candidate" ]]; then
        CHROME="$candidate"
        break
    fi
done

if [[ -z "$CHROME" ]]; then
    echo "ERROR: Could not find Chrome or Chromium. Install Google Chrome and try again."
    exit 1
fi

# Check if debug port is already open
if curl -s --max-time 1 "http://localhost:${PORT}/json/version" > /dev/null 2>&1; then
    echo "Chrome debug port ${PORT} already open."
    echo "Opening Douyin in the existing Chrome instance..."
    # Open Douyin in the running Chrome via CDP
    python3 - <<'PYEOF'
import requests, json, sys
try:
    r = requests.get("http://localhost:9222/json/new?https://www.douyin.com", timeout=5)
    print("Opened Douyin tab — log in, then leave the tab open.")
except Exception as e:
    print(f"Could not open tab automatically: {e}")
    print("Please open https://www.douyin.com manually in Chrome.")
PYEOF
    exit 0
fi

echo "Launching Chrome with --remote-debugging-port=${PORT}..."
echo "Opening https://www.douyin.com — please log in."
echo ""
echo "Once logged in, leave this Chrome window open and run the pipeline."
echo "(Press Ctrl+C here at any time — Chrome will remain running in background)"

"$CHROME" \
    --remote-debugging-port="${PORT}" \
    --no-first-run \
    --no-default-browser-check \
    "https://www.douyin.com" &

echo ""
echo "Chrome launched (PID $!). Douyin tab should open automatically."
echo "To verify: curl http://localhost:${PORT}/json/version"
