"""
Agent Chat — Streamlit entry point.

Run:
    uv run streamlit run web/chat_app.py
"""

from __future__ import annotations

import streamlit as st

# Make sibling files importable
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import chat_state
import chat_render
from nails_agent.agents.chat_events import UserAction
from nails_agent.agents.chat_runner import ChatPipelineRunner


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="💅 美甲趋势 · Agent Chat",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("💅 美甲趋势 · Agent Chat")
st.caption("一个 human-in-the-loop pipeline — 在每个关键节点暂停，等你确认或调整。")


# ── Bootstrap ─────────────────────────────────────────────────────────────────

store = chat_state.init(st.session_state)


@st.cache_resource
def _get_runner() -> ChatPipelineRunner:
    """Runner is cheap, but caching avoids re-initing MemoryStore each rerun."""
    return ChatPipelineRunner()


runner = _get_runner()


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("会话")

    if st.button("🔄 重置 / 新会话", use_container_width=True):
        chat_state.reset(st.session_state)
        st.rerun()

    if store["phase"] not in ("idle", "done", "interrupted"):
        if st.button("✗ 中止当前操作", use_container_width=True):
            chat_state.request_interrupt(store)
            st.rerun()

    st.divider()
    st.header("设置")
    store["auto_mode"] = st.toggle(
        "自动执行 (P1 自动通过)",
        value=store["auto_mode"],
        help="开启后 P1 优先级的 checkpoint 会在倒计时后自动选默认项。P0 始终阻塞等你。",
    )
    store["dev_mode"] = st.toggle(
        "🐛 Dev mode",
        value=store["dev_mode"],
        help="错误事件展示完整 traceback。",
    )

    st.divider()
    st.header("状态")
    st.caption(f"当前阶段: `{store['phase']}`")
    st.caption(f"事件数: {len(store['events'])}")


# ── Replay event history FIRST so the user bubble shows immediately ──────────
# (Drains happen after this — that way the user always sees their own message
# the instant they hit enter, even if the runner is about to spend 5–10s
# probing slow sources.)

for event in chat_state.replay(store):
    chat_render.render_event(event, store)


# ── Drain pending work ────────────────────────────────────────────────────────
# Order matters: pending_start > pending_choice > pending_interrupt.

# 1) A queued "start" — user already saw their bubble, now do the heavy work.
if pending_text := store.get("pending_start"):
    store["pending_start"] = None
    with st.spinner("正在准备…（首次启动会检查数据源，可能 5–10s）"):
        action = UserAction(type="start", payload={"text": pending_text, "skip_user_bubble": True})
        new_events = runner.advance(action, store)
    chat_state.append_events(store, new_events)
    st.rerun()

# 2) A clicked checkpoint choice.
pending = chat_state.take_choice(store)
if pending is not None:
    with st.spinner("处理中…"):
        action = UserAction(type="choose", payload=pending)
        new_events = runner.advance(action, store)
    chat_state.append_events(store, new_events)
    st.rerun()

# 3) Graceful interrupt — only honour at quiet states; active phases poll the flag.
if store["pending_interrupt"] and store["phase"] in (
    "idle",
    "plan_review",
    "trends_review",
    "strategy_review",
    "done",
):
    new_events = runner.advance(UserAction(type="interrupt"), store)
    store["pending_interrupt"] = False
    chat_state.append_events(store, new_events)
    st.rerun()


# ── Chat input (start a new turn) ─────────────────────────────────────────────

allow_input = store["phase"] in ("idle", "done", "interrupted")
prompt = st.chat_input(
    "输入指令开始（任意文字都行）…" if allow_input else "进行中，先完成或中止再开新会话…",
    disabled=not allow_input,
)
if prompt:
    if store["phase"] in ("done", "interrupted"):
        chat_state.reset(st.session_state)
        store = chat_state.init(st.session_state)
    # Two-phase commit: show user bubble first, then process on next rerun.
    from nails_agent.agents.chat_events import make_message

    chat_state.append_events(store, [make_message("user", prompt)])
    store["pending_start"] = prompt
    st.rerun()
