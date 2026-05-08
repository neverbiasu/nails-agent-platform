import streamlit as st
import pandas as pd
import altair as alt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from data_loader import load_event_log

AGENT_ORDER = [
    "nails-orchestrator",
    "trend-analyst",
    "value-evaluator",
    "asset-generator",
    "campaign-strategist",
    "nails-summarizer",
]

EVENT_COLOR = {
    "PipelineStart": "#4CAF50",
    "AgentStart": "#2196F3",
    "DataProduced": "#FF9800",
    "AgentComplete": "#9C27B0",
    "PipelineComplete": "#F44336",
}


def _parse_ts(ts: str) -> pd.Timestamp:
    try:
        return pd.Timestamp(ts)
    except Exception:
        return pd.Timestamp("2026-05-04 18:00:00")


def render():
    st.header("📋 数据链路")
    st.caption("全链路事件日志 — 流水线各节点的实时记录")

    logs = load_event_log()

    # Gantt-style chart via Altair
    df_gantt = pd.DataFrame([{
        "Agent": e["source_agent"],
        "事件类型": e["event_type"],
        "时间": _parse_ts(e["timestamp"]),
        "摘要": e["payload"].get("summary", ""),
    } for e in logs])

    # Map agents to y-axis position
    agent_rank = {a: i for i, a in enumerate(AGENT_ORDER)}
    df_gantt["排序"] = df_gantt["Agent"].map(lambda a: agent_rank.get(a, 99))
    df_gantt["颜色"] = df_gantt["事件类型"].map(lambda e: EVENT_COLOR.get(e, "#607D8B"))

    chart = (
        alt.Chart(df_gantt)
        .mark_circle(size=120)
        .encode(
            x=alt.X("时间:T", title="时间", axis=alt.Axis(format="%H:%M:%S")),
            y=alt.Y("Agent:N", sort=AGENT_ORDER, title="Agent"),
            color=alt.Color("事件类型:N",
                            scale=alt.Scale(
                                domain=list(EVENT_COLOR.keys()),
                                range=list(EVENT_COLOR.values()),
                            )),
            tooltip=["Agent", "事件类型", "时间:T", "摘要"],
        )
        .properties(height=280, title="流水线事件时间线")
    )
    st.altair_chart(chart, use_container_width=True)

    # Legend
    legend_cols = st.columns(len(EVENT_COLOR))
    for col, (evt, color) in zip(legend_cols, EVENT_COLOR.items()):
        col.markdown(f"<span style='color:{color}'>●</span> {evt}", unsafe_allow_html=True)

    st.divider()

    # Full event log table
    st.subheader("事件明细")
    df_table = pd.DataFrame([{
        "ID": e["event_id"],
        "时间": e["timestamp"][11:19],
        "Agent": e["source_agent"],
        "事件": e["event_type"],
        "摘要": e["payload"].get("summary", ""),
    } for e in logs])

    event = st.dataframe(
        df_table,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    selected_rows = event.selection.rows if hasattr(event, "selection") else []
    if selected_rows:
        sel_log = logs[selected_rows[0]]
        st.subheader(f"🔍 {sel_log['event_id']} — Payload 详情")
        st.json(sel_log["payload"])

    # Pipeline summary KPI
    st.divider()
    st.subheader("📈 本次流水线 KPI")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Top 趋势", "猫眼美甲")
    col2.metric("上架优先评分", "88.7")
    col3.metric("已生成素材", "5 款")
    col4.metric("运营方案就绪", "3 款")
