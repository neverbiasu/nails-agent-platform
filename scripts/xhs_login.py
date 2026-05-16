"""
Interactive XHS QR login → saves session to xhs-mcp DB.

This version does NO programmatic click — the user clicks 登录 themselves
in the visible browser window (XHS detects programmatic clicks and won't
open the login modal).

Flow:
  1. Script opens a Chromium window with playwright-stealth-like tweaks
  2. User clicks 登录 button in the browser
  3. User scans QR with phone (XHS app)
  4. Script polls — when #login-btn disappears from DOM, login succeeded
  5. Save storageState to ~/.xhs-mcp/data.db

Usage:
    uv run python scripts/xhs_login.py --name nails
"""

from __future__ import annotations
import argparse
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

DB_PATH = "/Users/nev4rb14su/.xhs-mcp/data.db"

# Hide common automation fingerprints
STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
window.chrome = { runtime: {} };
"""


def login_and_save(name: str, max_wait_s: int = 300) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        ctx.add_init_script(STEALTH_INIT)
        page = ctx.new_page()

        print("→ Opening XHS explore page…")
        page.goto(
            "https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=20000
        )
        time.sleep(2)

        # Remove cookie banner if any
        page.evaluate("""() => {
            document.querySelectorAll('.cookie-banner-overlay,[class*=cookie-banner]').forEach(e => e.remove());
        }""")

        print("\n╔══════════════════════════════════════════════════════════╗")
        print("║  请在浏览器窗口里手动操作：                                ║")
        print("║   1. 点击左侧 「登录」 按钮                                ║")
        print("║   2. 用小号 XHS app 扫码                                  ║")
        print("║   3. 在 app 上点击确认登录                                ║")
        print("║                                                          ║")
        print("║  脚本会等到 #login-btn 从页面消失（= 真登录成功）          ║")
        print(f"║  最长等待 {max_wait_s}s                                          ║")
        print("╚══════════════════════════════════════════════════════════╝\n")

        logged_in = False
        for i in range(max_wait_s // 5):
            time.sleep(5)
            try:
                login_btn_visible = page.evaluate("""() => {
                    const btn = document.querySelector('#login-btn');
                    if (!btn) return false;
                    const rect = btn.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }""")
            except Exception:
                login_btn_visible = True

            cookies = ctx.cookies()
            n_cookies = len(cookies)
            print(
                f"  [{(i + 1) * 5:3d}s] login-btn visible: {login_btn_visible}  cookies: {n_cookies}"
            )

            if not login_btn_visible:
                logged_in = True
                print("  ✓ #login-btn gone → real login detected!")
                # Wait extra time for XHS to fully establish session cookies
                print("  → Waiting 15s for XHS to write all auth cookies…")
                # Navigate to a logged-in page to force cookie refresh
                try:
                    page.goto(
                        "https://www.xiaohongshu.com/explore",
                        wait_until="domcontentloaded",
                        timeout=10000,
                    )
                    time.sleep(5)
                    # Click on a user-only area to trigger more auth cookies
                    page.evaluate("""() => window.scrollTo(0, 500)""")
                    time.sleep(5)
                    page.evaluate("""() => window.scrollTo(0, 1000)""")
                    time.sleep(5)
                except Exception as e:
                    print(f"  (navigation warning: {e})")
                break

        if not logged_in:
            print(f"\n⚠️  Timed out after {max_wait_s}s. Aborting.")
            browser.close()
            return

        # Capture session
        state = ctx.storage_state()
        state["cookies"] = [
            c
            for c in state["cookies"]
            if any(d in c.get("domain", "") for d in ["xiaohongshu.com", "xhscdn.com"])
        ]
        state["origins"] = [
            o for o in state.get("origins", []) if "xiaohongshu" in o.get("origin", "")
        ]
        print(f"\n→ Captured {len(state['cookies'])} XHS cookies")
        print(f"   names: {[c['name'] for c in state['cookies']]}")
        browser.close()

        # Save to xhs-mcp DB
        conn = sqlite3.connect(DB_PATH)
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute("SELECT id FROM accounts WHERE name=?", (name,)).fetchone()
        if row:
            conn.execute(
                "UPDATE accounts SET state=?,status='active',last_login_at=?,updated_at=? WHERE name=?",
                (json.dumps(state), now, now, name),
            )
            print(f"✅ Updated '{name}' in xhs-mcp DB")
        else:
            conn.execute(
                "INSERT INTO accounts (id,name,state,status,last_login_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), name, json.dumps(state), "active", now, now, now),
            )
            print(f"✅ Created '{name}' in xhs-mcp DB")
        conn.commit()
        conn.close()
        print("\nDone. Try `xhs_check_auth_status` next.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="nails")
    parser.add_argument("--wait", type=int, default=300)
    args = parser.parse_args()
    login_and_save(args.name, args.wait)
