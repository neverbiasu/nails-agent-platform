"""
render_event(event, store, st) — dispatch one ChatEvent into Streamlit primitives.

Pure UI layer; no pipeline knowledge.
The store is passed in for two reasons:
  • dev_mode toggle (controls traceback visibility)
  • queue_choice / request_interrupt callbacks from button widgets
"""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from nails_agent.agents.chat_events import ChatEvent
import chat_state


# ── Dispatcher ────────────────────────────────────────────────────────────────


def render_event(event: ChatEvent, store: Dict[str, Any]) -> None:
    fn = _RENDERERS.get(event.type)
    if fn is None:
        st.warning(f"Unknown event type: {event.type}")
        return
    fn(event, store)


# ── Per-type renderers ────────────────────────────────────────────────────────


def _render_message(event: ChatEvent, store: Dict[str, Any]) -> None:
    p = event.payload
    icon = p.icon
    with st.chat_message(p.role, avatar=icon):
        st.write(p.text)


def _render_tool_call(event: ChatEvent, store: Dict[str, Any]) -> None:
    p = event.payload
    icon = {"running": "⏳", "ok": "✅", "error": "❌"}[p.status]
    dur = f" · {p.duration_ms}ms" if p.duration_ms else ""
    summary = f" · {p.result_summary}" if p.result_summary else ""
    header = f"{icon} `{p.tool}`{dur}{summary}"
    # Auto-expand running + error; collapse ok by default
    expanded_default = p.status != "ok"
    with st.expander(header, expanded=expanded_default):
        if p.args:
            st.caption("args")
            st.json(p.args, expanded=False)
        if p.result_data:
            st.caption("result")
            st.json(p.result_data, expanded=False)


def _render_phase_enter(event: ChatEvent, store: Dict[str, Any]) -> None:
    p = event.payload
    elapsed = f"({p.elapsed_ms / 1000:.1f}s)" if p.elapsed_ms else ""
    st.markdown(f"---\n#### {p.title} {elapsed}")


def _render_phase_output(event: ChatEvent, store: Dict[str, Any]) -> None:
    p = event.payload
    data = p.data
    kind = data.kind
    if kind == "table":
        _render_table(data)
    elif kind == "chart":
        _render_chart(data)
    elif kind == "markdown":
        _render_markdown(data)
    elif kind == "image_gallery":
        _render_gallery(data)
    else:
        st.warning(f"Unknown phase_output kind: {kind}")


def _render_table(data) -> None:
    import pandas as pd

    st.markdown(f"**{data.title}**")
    df = pd.DataFrame(data.rows, columns=data.columns)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_chart(data) -> None:
    import plotly.graph_objects as go

    st.markdown(f"**{data.title}**")
    if data.chart_type == "bar":
        fig = go.Figure(
            go.Bar(
                x=data.x,
                y=data.y,
                orientation="h" if isinstance(data.y[0], str) else "v",
                marker_color="#FF6B9D",
                text=[
                    f"{v:.0f}" if isinstance(v, (int, float)) else str(v)
                    for v in (data.x if isinstance(data.y[0], str) else data.y)
                ],
                textposition="outside",
            )
        )
    elif data.chart_type == "radar":
        fig = go.Figure(
            go.Scatterpolar(
                r=data.y,
                theta=data.labels or data.x,
                fill="toself",
                line_color="#FF6B9D",
            )
        )
    elif data.chart_type == "line":
        fig = go.Figure(go.Scatter(x=data.x, y=data.y, mode="lines+markers", line_color="#FF6B9D"))
    elif data.chart_type == "pie":
        fig = go.Figure(go.Pie(labels=data.labels or data.x, values=data.y))
    else:
        st.warning(f"Unsupported chart_type: {data.chart_type}")
        return
    fig.update_layout(height=320, margin=dict(l=10, r=20, t=10, b=10), plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)


def _render_markdown(data) -> None:
    st.markdown(f"**{data.title}**")
    st.markdown(data.body)


def _render_gallery(data) -> None:
    st.markdown(f"**{data.title}**")
    cols_per_row = 4
    items = data.items
    for i in range(0, len(items), cols_per_row):
        row = items[i : i + cols_per_row]
        cols = st.columns(len(row))
        for col, item in zip(cols, row):
            with col:
                if item.url:
                    try:
                        st.image(item.url, caption=item.caption, use_container_width=True)
                    except Exception:
                        st.caption(item.caption)
                else:
                    st.caption(item.caption)
                if item.badge:
                    st.markdown(f"`{item.badge}`")


def _render_checkpoint(event: ChatEvent, store: Dict[str, Any]) -> None:
    import time as _time

    p = event.payload
    is_open = _is_checkpoint_open(event, store)

    st.markdown(f"💡 **{p.prompt}**")
    if not is_open:
        st.caption("（已确认）")
        return

    # Auto-approve: if auto_mode is on AND there's a P1 auto-approve configured,
    # show a countdown and fire it automatically when the timer expires.
    auto_key = f"_auto_{event.event_id}"
    if (
        store.get("auto_mode")
        and p.auto_approve_after_s is not None
        and p.auto_approve_choice_id is not None
    ):
        # Determine which choice is auto-approved
        auto_choice = next(
            (c for c in p.choices if c.id == p.auto_approve_choice_id and c.priority == "P1"),
            None,
        )
        if auto_choice:
            start_ts = store.get(auto_key)
            if start_ts is None:
                store[auto_key] = _time.time()
                start_ts = store[auto_key]
            elapsed = _time.time() - start_ts
            remaining = max(0.0, p.auto_approve_after_s - elapsed)
            if remaining == 0:
                # Fire auto-approve
                chat_state.queue_choice(store, p.phase, auto_choice.id, {})
                st.rerun()
            else:
                st.caption(
                    f"⏱ 自动执行「{auto_choice.label}」倒计时 **{remaining:.0f}s** — 点击按钮可提前确认或取消"
                )
                st.progress(1 - remaining / p.auto_approve_after_s)

    # Render buttons
    cols = st.columns(len(p.choices))
    btn_type_map = {"primary": "primary", "secondary": "secondary", "danger": "secondary"}
    for col, choice in zip(cols, p.choices):
        with col:
            form_values: Dict[str, Any] = {}
            if choice.form:
                for field in choice.form:
                    key = f"cp_{event.event_id}_{choice.id}_{field.name}"
                    if field.type == "text":
                        form_values[field.name] = st.text_input(
                            field.label,
                            value=str(field.default or ""),
                            key=key,
                        )
                    elif field.type == "number":
                        form_values[field.name] = st.number_input(
                            field.label,
                            value=int(field.default or 0),
                            key=key,
                        )
                    elif field.type == "multiselect":
                        form_values[field.name] = st.multiselect(
                            field.label,
                            options=field.options or [],
                            default=field.default or [],
                            key=key,
                        )
            label = choice.label
            if choice.priority == "P1" and store.get("auto_mode"):
                label = f"{label}  ·  P1 自动"
            if st.button(
                label,
                type=btn_type_map[choice.style],
                key=f"cp_{event.event_id}_{choice.id}",
                use_container_width=True,
            ):
                store.pop(auto_key, None)  # cancel any running timer
                chat_state.queue_choice(store, p.phase, choice.id, form_values)
                st.rerun()


def _is_checkpoint_open(event: ChatEvent, store: Dict[str, Any]) -> bool:
    """A checkpoint is still open if no later phase_enter / phase_output exists."""
    events = store["events"]
    try:
        idx = next(i for i, e in enumerate(events) if e.event_id == event.event_id)
    except StopIteration:
        return True
    # Anything after the checkpoint that signals progress closes it
    for later in events[idx + 1 :]:
        if later.type in ("phase_enter", "checkpoint", "error"):
            return False
    return True


def _render_progress(event: ChatEvent, store: Dict[str, Any]) -> None:
    p = event.payload
    if p.fraction is not None:
        st.progress(p.fraction, text=p.text)
    else:
        st.caption(f"⏳ {p.text}")


def _render_error(event: ChatEvent, store: Dict[str, Any]) -> None:
    p = event.payload
    st.error(p.message)
    if p.traceback and store.get("dev_mode"):
        with st.expander("Traceback (dev)"):
            st.code(p.traceback, language="python")
    if p.recoverable and _is_checkpoint_open(event, store):
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "🔄 重试", key=f"retry_{event.event_id}", type="primary", use_container_width=True
            ):
                chat_state.queue_choice(store, p.phase, "retry")
                st.rerun()
        with col2:
            if st.button("✗ 中止", key=f"abort_{event.event_id}", use_container_width=True):
                chat_state.queue_choice(store, p.phase, "abort")
                st.rerun()


_RENDERERS = {
    "message": _render_message,
    "tool_call": _render_tool_call,
    "phase_enter": _render_phase_enter,
    "phase_output": _render_phase_output,
    "checkpoint": _render_checkpoint,
    "progress": _render_progress,
    "error": _render_error,
}
