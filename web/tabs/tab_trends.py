import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from data_loader import load_trend_signals, load_metric_snapshots, load_style_library

ALL_TAGS = [
    "猫眼",
    "法式",
    "3D立体",
    "渐变",
    "星月",
    "奶油",
    "镜面",
    "贴片",
    "冰透",
    "浮雕",
    "彩绘",
    "大理石纹",
    "碎钻",
    "纯色",
]
PLATFORMS = ["全部", "小红书", "抖音", "Instagram"]

# Per-style Unsplash photos (nail-specific)
STYLE_IMAGES = {
    "cat_eye": "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=300&q=80",
    "ice_blue_cat_eye": "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=300&q=80",
    "french": "https://images.unsplash.com/photo-1604655855783-7abfe0b53c87?w=300&q=80",
    "gradient": "https://images.unsplash.com/photo-1604655855782-c2e4fe62e461?w=300&q=80",
    "emboss": "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=300&q=80",
    "marble": "https://images.unsplash.com/photo-1604655855783-7abfe0b53c87?w=300&q=80",
    "celestial": "https://images.unsplash.com/photo-1604655855782-c2e4fe62e461?w=300&q=80",
    "solid": "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=300&q=80",
    "colorful": "https://images.unsplash.com/photo-1604655855782-c2e4fe62e461?w=300&q=80",
    "mirror": "https://images.unsplash.com/photo-1604655855783-7abfe0b53c87?w=300&q=80",
    "matte_cream": "https://images.unsplash.com/photo-1604654894610-df63bc536371?w=300&q=80",
    "rhinestone": "https://images.unsplash.com/photo-1604655855782-c2e4fe62e461?w=300&q=80",
}


def _composite(t: dict) -> float:
    return t["likes"] + t["collects"] * 1.5 + t["shares"] * 2 + t["comments"] * 0.5


def _match_styles(trend: dict, library: list[dict]) -> list[dict]:
    """
    Return library styles matching the trend, scored by:
      1. Tag overlap (primary)
      2. Keyword substring match in style_name or style_tags (fallback)
    """
    sig_tags = set(trend.get("style_tags", []))
    keyword = trend.get("keyword", "")
    scored: dict[str, tuple[int, dict]] = {}

    for item in library:
        item_tags = set(item.get("style_tags", []))
        score = 0

        # Tag overlap
        if sig_tags:
            score += len(sig_tags & item_tags) * 10

        # Keyword match: check if any item tag appears in trend keyword, or vice versa
        for tag in item_tags:
            if tag in keyword or keyword in item.get("style_name", ""):
                score += 5
        if item.get("style_name", "") in keyword or keyword in item.get("style_name", ""):
            score += 8

        if score > 0:
            scored[item["style_id"]] = (score, item)

    result = sorted(scored.values(), key=lambda x: x[0], reverse=True)
    return [item for _, item in result]


def render():
    st.header("📊 趋势感知")

    signals = load_trend_signals()
    snapshots = load_metric_snapshots()
    library = load_style_library()
    snap_map = {s["trend_id"]: s for s in snapshots}

    # Add composite score to all signals
    max_raw = max(_composite(t) for t in signals) if signals else 1
    for t in signals:
        t["_score"] = round(_composite(t) / max_raw * 100, 1)

    # Filters
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        platform_filter = st.selectbox("平台筛选", PLATFORMS)
    with col_f2:
        tag_filter = st.multiselect("风格标签筛选", ALL_TAGS)

    filtered = signals
    if platform_filter != "全部":
        filtered = [t for t in filtered if t["platform"] == platform_filter]
    if tag_filter:
        filtered = [
            t for t in filtered if any(tag in t.get("style_tags", []) for tag in tag_filter)
        ]

    filtered_sorted = sorted(filtered, key=lambda t: t["_score"], reverse=True)
    top10 = sorted(signals, key=lambda t: _composite(t), reverse=True)[:10]

    col_left, col_right = st.columns([1.2, 1])

    # ── Left: trend table ──────────────────────────────────────────────────────
    with col_left:
        st.subheader(f"趋势列表（{len(filtered_sorted)} 条）")
        df = pd.DataFrame(
            [
                {
                    "热度": t["_score"],
                    "平台": t["platform"],
                    "关键词": t["keyword"],
                    "点赞": t["likes"],
                    "收藏": t["collects"],
                    "分享": t["shares"],
                    "标签": "、".join(t.get("style_tags", [])[:3]),
                }
                for t in filtered_sorted
            ]
        )

        event = st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )
        selected_rows = event.selection.rows if hasattr(event, "selection") else []

    # ── Right: charts + matched styles ─────────────────────────────────────────
    with col_right:
        st.subheader("Top 10 综合热度")
        fig_bar = go.Figure(
            go.Bar(
                x=[t["_score"] for t in top10],
                y=[t["keyword"] for t in top10],
                orientation="h",
                marker_color="#FF6B9D",
                text=[f"{t['_score']:.0f}" for t in top10],
                textposition="outside",
            )
        )
        fig_bar.update_layout(
            height=320,
            margin=dict(l=0, r=20, t=10, b=0),
            xaxis_title="综合热度分",
            yaxis=dict(autorange="reversed"),
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        # Radar chart for selected or top trend
        selected_trend = None
        if selected_rows:
            selected_trend = filtered_sorted[selected_rows[0]]
        elif top10:
            selected_trend = top10[0]

        if selected_trend and selected_trend["trend_id"] in snap_map:
            snap = snap_map[selected_trend["trend_id"]]
            st.subheader(f"📡 {selected_trend['keyword']} 指标雷达")
            categories = ["外部热度", "新鲜度", "风格缺口", "上架优先级"]
            values = [
                snap["external_heat_score"],
                snap["trend_growth_score"],
                snap["style_gap_score"],
                snap["launch_priority_score"],
            ]
            fig_radar = go.Figure(
                go.Scatterpolar(
                    r=values + [values[0]],
                    theta=categories + [categories[0]],
                    fill="toself",
                    fillcolor="rgba(255, 107, 157, 0.2)",
                    line_color="#FF6B9D",
                    name=selected_trend["keyword"],
                )
            )
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(range=[0, 100])),
                showlegend=False,
                height=260,
                margin=dict(l=30, r=30, t=20, b=20),
            )
            st.plotly_chart(fig_radar, use_container_width=True)

    # ── Matched style cards (full width below) ─────────────────────────────────
    if selected_trend:
        matched = _match_styles(selected_trend, library)
        st.divider()
        st.subheader(f"💅 「{selected_trend['keyword']}」匹配的上架款式（{len(matched)} 款）")

        if not matched:
            st.info("暂无匹配款式 — 这是潜在空白机会！风格缺口评分高。")
        else:
            # Show style cards 4 per row
            cols_per_row = 4
            for i in range(0, len(matched), cols_per_row):
                row_styles = matched[i : i + cols_per_row]
                cols = st.columns(cols_per_row)
                for col, style in zip(cols, row_styles):
                    with col:
                        img_url = STYLE_IMAGES.get(style["style_id"], style.get("image_url", ""))
                        if img_url:
                            try:
                                st.image(img_url, use_container_width=True)
                            except Exception:
                                st.markdown("🎨")
                        else:
                            st.markdown("🎨")
                        st.markdown(f"**{style['style_name']}**")
                        tags = style.get("style_tags", [])
                        if tags:
                            st.caption("  ".join(f"`{t}`" for t in tags[:3]))
                        overlap_tags = set(selected_trend.get("style_tags", [])) & set(tags)
                        if overlap_tags:
                            st.caption(f"🔗 命中：{'、'.join(overlap_tags)}")
    else:
        st.divider()
        st.caption("👆 点击上方趋势行查看匹配款式")
