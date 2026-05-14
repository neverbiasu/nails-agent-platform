import streamlit as st
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from data_loader import load_module_outputs, load_action_executions, load_style_cards

STATIC_DIR = Path(__file__).parent.parent / "static"

PRIORITY_COLOR = {"P0": "🔴", "P1": "🟡", "P2": "🟢"}
STATUS_BADGE = {"success": "✅", "pending": "⏳", "failed": "❌"}


def render():
    st.header("🎯 智能运营")

    sub = st.tabs(["模块输出", "动作执行", "款式卡片", "运营策略"])

    with sub[0]:
        _tab_modules()
    with sub[1]:
        _tab_actions()
    with sub[2]:
        _tab_cards()
    with sub[3]:
        _tab_campaign()


def _tab_modules():
    st.subheader("Agent 模块输出")
    modules = load_module_outputs()
    for m in modules:
        icon = "🔴" if m["priority"] == "high" else ("🟡" if m["priority"] == "medium" else "🟢")
        with st.expander(f"{icon} {m['module_name']} — {m['decision']}"):
            st.markdown(f"**决策原因**：{m['reason']}")
            st.markdown(f"**机会类型**：`{m.get('opportunity_type', '-')}`")
            st.markdown(f"**优先级**：`{m['priority']}`")
            if m.get("recommended_actions"):
                st.markdown("**推荐动作**：")
                for a in m["recommended_actions"]:
                    st.markdown(f"  - `{a}`")
            st.caption(f"生成时间：{m['created_at']}")


def _tab_actions():
    st.subheader("动作执行记录")
    actions = load_action_executions()
    df = pd.DataFrame([{
        "ID": a["action_id"],
        "动作": a["action_name"],
        "款式": a.get("style_id", "-"),
        "状态": STATUS_BADGE.get(a["status"], "?") + " " + a["status"],
        "耗时": _duration(a.get("created_at"), a.get("finished_at")),
    } for a in actions])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    selected_id = st.selectbox("查看详情", [a["action_id"] for a in actions])
    sel = next(a for a in actions if a["action_id"] == selected_id)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**输入**")
        st.json(sel["inputs"])
    with col2:
        st.markdown("**输出**")
        st.json(sel["outputs"])


def _tab_cards():
    st.subheader(f"款式卡片 · Top {10}")
    cards = load_style_cards()
    if not cards:
        st.info("暂无款式卡片数据。")
        return

    # Show all cards in a 4-column grid
    cols_per_row = 4
    for i in range(0, len(cards), cols_per_row):
        row_cards = cards[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, card in zip(cols, row_cards):
            with col:
                priority = card["schedule"]["priority"]
                st.markdown(f"**{PRIORITY_COLOR.get(priority, '')} {card['style_name']}**")
                st.caption(f"优先级：{priority} | 评分：{card['launch_priority_score']:.1f}")
                nail_img = STATIC_DIR / "nail_reference.jpg"
                if nail_img.exists():
                    st.image(str(nail_img), use_container_width=True)
                pv = card.get("platform_variants", {})
                if pv.get("xiaohongshu"):
                    with st.expander("小红书文案"):
                        st.write(pv["xiaohongshu"]["caption"])
                        st.caption(" ".join(pv["xiaohongshu"].get("hashtags", [])))
                pricing = card.get("pricing", {})
                if pricing:
                    st.markdown(
                        f"💰 基础价 **¥{pricing.get('base_price')}** "
                        f"| 溢价 ¥{pricing.get('premium_price')} "
                        f"| 促销 ¥{pricing.get('promo_price')}"
                    )


def _tab_campaign():
    st.subheader("运营策略总览")
    cards = load_style_cards()

    schedule_data = []
    for card in cards:
        sch = card.get("schedule", {})
        priority = sch.get("priority", "P2")
        schedule_data.append({
            "款式": card["style_name"],
            "优先级": PRIORITY_COLOR.get(priority, "") + " " + priority,
            "评分": f"{card['launch_priority_score']:.1f}",
            "小红书发布": sch.get("xiaohongshu_publish_at", "-")[:10],
            "抖音发布": sch.get("douyin_publish_at", "-")[:10],
            "Instagram": sch.get("instagram_publish_at", "-")[:10],
            "基础价": card.get("pricing", {}).get("base_price", "-"),
        })

    df = pd.DataFrame(schedule_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    p0 = [c for c in cards if c["schedule"]["priority"] == "P0"]
    p1 = [c for c in cards if c["schedule"]["priority"] == "P1"]
    p2 = [c for c in cards if c["schedule"]["priority"] == "P2"]

    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔴 P0 立即上架", len(p0))
    col2.metric("🟡 P1 下周上架", len(p1))
    col3.metric("🟢 P2 待定", len(p2))
    col4.metric("📊 本轮评估", len(cards))

    st.info("💡 建议：本周重点推广猫眼系列（猫眼美甲 + 冰透蓝猫眼），小红书+抖音联动发布，预计触达用户 15 万+")


def _duration(start: str, end: str) -> str:
    if not start or not end:
        return "-"
    try:
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S+08:00"
        s = datetime.strptime(start, fmt)
        e = datetime.strptime(end, fmt)
        secs = int((e - s).total_seconds())
        return f"{secs}s" if secs < 60 else f"{secs // 60}m {secs % 60}s"
    except Exception:
        return "-"
