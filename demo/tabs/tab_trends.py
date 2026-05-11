import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from data_loader import load_trend_signals, load_metric_snapshots

ALL_TAGS = ["猫眼", "法式", "3D立体", "渐变", "星月", "奶油", "镜面", "贴片", "冰透",
            "浮雕", "彩绘", "大理石纹", "碎钻", "纯色"]
PLATFORMS = ["全部", "小红书", "抖音", "Instagram"]


def _composite(t: dict) -> float:
    return t["likes"] + t["collects"] * 1.5 + t["shares"] * 2 + t["comments"] * 0.5


def render():
    st.header("📊 趋势感知")

    signals = load_trend_signals()
    snapshots = load_metric_snapshots()
    snap_map = {s["trend_id"]: s for s in snapshots}

    # Filters
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        platform_filter = st.selectbox("平台筛选", PLATFORMS)
    with col_f2:
        tag_filter = st.multiselect("风格标签筛选", ALL_TAGS)

    # Add composite score to ALL signals first (so top10 below also has _score)
    max_raw = max(_composite(t) for t in signals) if signals else 1
    for t in signals:
        t["_score"] = round(_composite(t) / max_raw * 100, 1)

    filtered = signals
    if platform_filter != "全部":
        filtered = [t for t in filtered if t["platform"] == platform_filter]
    if tag_filter:
        filtered = [t for t in filtered if any(tag in t.get("style_tags", []) for tag in tag_filter)]

    filtered_sorted = sorted(filtered, key=lambda t: t["_score"], reverse=True)

    col_left, col_right = st.columns([1.2, 1])

    with col_left:
        st.subheader(f"趋势列表（{len(filtered_sorted)} 条）")
        df = pd.DataFrame([{
            "热度": t["_score"],
            "平台": t["platform"],
            "关键词": t["keyword"],
            "点赞": t["likes"],
            "收藏": t["collects"],
            "分享": t["shares"],
            "标签": "、".join(t.get("style_tags", [])[:3]),
        } for t in filtered_sorted])

        event = st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )
        selected_rows = event.selection.rows if hasattr(event, "selection") else []

    with col_right:
        top10 = sorted(signals, key=lambda t: _composite(t), reverse=True)[:10]

        st.subheader("Top 10 综合热度")
        fig_bar = go.Figure(go.Bar(
            x=[t["_score"] for t in top10],
            y=[t["keyword"] for t in top10],
            orientation="h",
            marker_color="#FF6B9D",
            text=[f"{t['_score']:.0f}" for t in top10],
            textposition="outside",
        ))
        fig_bar.update_layout(
            height=350,
            margin=dict(l=0, r=20, t=10, b=0),
            xaxis_title="综合热度分",
            yaxis=dict(autorange="reversed"),
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        # Radar chart for selected row or top 1
        selected_trend = None
        if selected_rows:
            selected_trend = filtered_sorted[selected_rows[0]]
        elif top10:
            selected_trend = top10[0]

        if selected_trend and selected_trend["trend_id"] in snap_map:
            snap = snap_map[selected_trend["trend_id"]]
            st.subheader(f"📡 {selected_trend['keyword']} 指标雷达")
            categories = ["外部热度", "增长速度", "款式缺口", "上架优先级"]
            values = [
                snap["external_heat_score"],
                snap["trend_growth_score"],
                snap["style_gap_score"],
                snap["launch_priority_score"],
            ]
            fig_radar = go.Figure(go.Scatterpolar(
                r=values + [values[0]],
                theta=categories + [categories[0]],
                fill="toself",
                fillcolor="rgba(255, 107, 157, 0.2)",
                line_color="#FF6B9D",
                name=selected_trend["keyword"],
            ))
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(range=[0, 100])),
                showlegend=False,
                height=280,
                margin=dict(l=30, r=30, t=20, b=20),
            )
            st.plotly_chart(fig_radar, use_container_width=True)
