"""
Telegram Bot — Nails Agent Platform.

Commands:
  /start     — welcome message
  /趋势       — run step 1 (trend analysis)
  /运营       — run full 4-step pipeline
  /状态       — list recent pipeline runs
  /试戴       — link to Streamlit demo
  /help       — help text

Env vars required:
  TELEGRAM_BOT_TOKEN   — bot token from @BotFather
  TELEGRAM_ALLOWED_USERS — comma-separated chat IDs (optional whitelist)
  NAILS_DATA_DIR       — path to data directory (default: demo/data)
  NAILS_OUTPUT_DIR     — path to output directory (default: demo/output)
"""

from __future__ import annotations

import logging
import os
from typing import Set

logger = logging.getLogger(__name__)

# ── Auth helpers ──────────────────────────────────────────────────────────────


def _allowed_users() -> Set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def _is_allowed(chat_id: int) -> bool:
    allowed = _allowed_users()
    return (not allowed) or (chat_id in allowed)


# ── Bot implementation using python-telegram-bot v20+ ────────────────────────


def build_application():
    """Build and return a configured telegram Application."""
    try:
        from telegram.ext import Application, CommandHandler, MessageHandler, filters
    except ImportError:
        raise ImportError("pip install python-telegram-bot>=20.0")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(token).build()

    # Lazy import orchestrator to avoid circular dependency
    def _make_orch():
        from nails_agent.memory.store import MemoryStore
        from nails_agent.agents.orchestrator import PipelineOrchestrator

        return PipelineOrchestrator(
            memory=MemoryStore(),
            data_dir=os.environ.get("NAILS_DATA_DIR", "demo/data"),
            output_dir=os.environ.get("NAILS_OUTPUT_DIR", "demo/output"),
        )

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def start(update, context):
        chat_id = update.effective_chat.id
        if not _is_allowed(chat_id):
            return
        await update.message.reply_text(
            "💅 你好！我是美甲 AI 运营助手。\n\n"
            "发送 /趋势 开始趋势分析\n"
            "发送 /运营 运行完整流水线\n"
            "发送 /状态 查看最近流水线\n"
            "发送 /试戴 获取 AI 试戴链接\n"
        )

    async def trend(update, context):
        chat_id = update.effective_chat.id
        if not _is_allowed(chat_id):
            return
        await update.message.reply_text("⏳ 正在进行趋势分析（Step 1）…")
        messages = []
        try:
            orch = _make_orch()
            state = orch.run_step1_only(progress_cb=messages.append)
            if state.status == "done" and state.trend_analysis:
                top3 = [s.keyword for s in state.trend_analysis.top_10[:3]]
                patterns = state.trend_analysis.patterns[:2]
                anomalies = state.trend_analysis.anomalies[:2]
                reply = f"✅ 趋势分析完成！\n\n🏆 Top 3：{', '.join(top3)}\n\n"
                if patterns:
                    reply += "📊 洞察：\n" + "\n".join(f"• {p}" for p in patterns) + "\n\n"
                if anomalies:
                    reply += "🚨 异常信号：\n" + "\n".join(f"• {a}" for a in anomalies)
            else:
                reply = f"❌ 趋势分析失败：{'; '.join(state.errors)}"
        except Exception as exc:
            reply = f"❌ 系统错误：{exc}"
        await update.message.reply_text(reply)

    async def full_pipeline(update, context):
        chat_id = update.effective_chat.id
        if not _is_allowed(chat_id):
            return
        await update.message.reply_text("⏳ 正在运行完整流水线（4步）…约需 30 秒")

        progress_msgs = []

        async def _async_progress(msg: str):
            progress_msgs.append(msg)
            try:
                await update.message.reply_text(msg)
            except Exception:
                pass

        # Run synchronously (bot handlers are async, pipeline is sync)
        import asyncio

        try:
            orch = _make_orch()
            loop = asyncio.get_event_loop()
            # Run pipeline in thread pool to avoid blocking event loop
            state = await loop.run_in_executor(
                None,
                lambda: orch.run(progress_cb=lambda m: progress_msgs.append(m)),
            )
            if state.status == "done" and state.report:
                r = state.report
                reply = (
                    f"✅ 完整流水线完成！\n\n"
                    f"📈 分析趋势：{r.total_trends_analyzed} 条\n"
                    f"🎨 运营卡片：{r.total_style_cards} 张\n"
                    f"🏆 Top 3：{', '.join(r.top_3_keywords)}\n"
                    f"\n`pipeline_id: {state.pipeline_id}`"
                )
            else:
                reply = f"❌ 流水线失败：{'; '.join(state.errors)}"
        except Exception as exc:
            reply = f"❌ 系统错误：{exc}"
        await update.message.reply_text(reply, parse_mode="Markdown")

    async def status(update, context):
        chat_id = update.effective_chat.id
        if not _is_allowed(chat_id):
            return
        from nails_agent.memory.store import MemoryStore

        mem = MemoryStore()
        runs = mem.list_pipeline_runs(limit=5)
        if not runs:
            await update.message.reply_text("暂无流水线记录。")
            return
        lines = ["📋 最近流水线记录："]
        for r in runs:
            icon = "✅" if r["status"] == "done" else "❌" if r["status"] == "error" else "⏳"
            lines.append(f"{icon} `{r['pipeline_id']}` — {r['status']} @ {r['updated_at'][:16]}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def tryon_link(update, context):
        chat_id = update.effective_chat.id
        if not _is_allowed(chat_id):
            return
        await update.message.reply_text(
            "💅 AI 试戴 Demo：http://localhost:8502\n\n"
            "选择款式 → 上传手部照片 → 点击「开始试戴」即可。"
        )

    async def help_cmd(update, context):
        chat_id = update.effective_chat.id
        if not _is_allowed(chat_id):
            return
        await update.message.reply_text(
            "📖 指令列表：\n"
            "/趋势 — 趋势分析（Step 1）\n"
            "/运营 — 完整流水线（4步）\n"
            "/状态 — 最近流水线记录\n"
            "/试戴 — AI 试戴链接\n"
            "/help — 帮助"
        )

    async def message_handler(update, context):
        """Handle plain text messages (no slash prefix)."""
        chat_id = update.effective_chat.id
        if not _is_allowed(chat_id):
            return
        text = (update.message.text or "").strip()
        if "趋势" in text:
            await trend(update, context)
        elif "运营" in text or "pipeline" in text.lower():
            await full_pipeline(update, context)
        elif "试戴" in text:
            await tryon_link(update, context)
        elif "状态" in text:
            await status(update, context)
        else:
            await update.message.reply_text(
                "💅 发送「趋势分析」或「完整运营」即可触发流水线，无需 / 前缀。"
            )

    from telegram.ext import CommandHandler, MessageHandler, filters

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("趋势", trend))
    app.add_handler(CommandHandler("运营", full_pipeline))
    app.add_handler(CommandHandler("状态", status))
    app.add_handler(CommandHandler("试戴", tryon_link))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    return app


def run_polling():
    """Start the bot in polling mode (blocking)."""
    from dotenv import load_dotenv

    load_dotenv()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )

    app = build_application()
    logger.info("Starting Nails Agent Telegram bot (polling)…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_polling()
