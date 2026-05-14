import streamlit as st
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from data_loader import load_metric_snapshots, load_event_log, load_style_cards


def render():
    st.header("🏠 平台概览")

    metrics = load_metric_snapshots()
    cards = load_style_cards()
    logs = load_event_log()

    # KPI cards
    top = max(metrics, key=lambda m: m["launch_priority_score"])
    p0_count = sum(1 for c in cards if c["schedule"]["priority"] == "P0")
    generated = sum(1 for c in cards if c["generation_status"] == "success")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔥 本周 Top 趋势", top.get("style_name", top.get("keyword", "—")))
    col2.metric("📊 上架优先评分", f"{top['launch_priority_score']:.1f} / 100")
    col3.metric("🎯 P0 款式", f"{p0_count} 款")
    col4.metric("🎨 已生成素材", f"{generated} / {len(cards)} 款")

    st.divider()

    # Pipeline stage progress
    st.subheader("⚙️ 流水线状态")
    stages = [
        ("趋势分析", "trend-analyst", "✅"),
        ("价值评估", "value-evaluator", "✅"),
        ("素材生成", "asset-generator", "✅"),
        ("运营策略", "campaign-strategist", "✅"),
        ("汇总报告", "nails-summarizer", "✅"),
    ]
    cols = st.columns(len(stages))
    for col, (name, agent, icon) in zip(cols, stages):
        col.markdown(f"**{icon} {name}**")
        col.progress(1.0)
        col.caption(agent)

    st.divider()

    # Recent event log
    st.subheader("📋 最近事件")
    recent = logs[-6:][::-1]
    df = pd.DataFrame([{
        "时间": e["timestamp"][11:19],
        "Agent": e["source_agent"],
        "事件": e["event_type"],
        "摘要": e["payload"].get("summary", ""),
    } for e in recent])
    st.dataframe(df, use_container_width=True, hide_index=True)
