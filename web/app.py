"""
美甲 AI 运营平台 — V0 Streamlit Demo
运行：streamlit run web/app.py --server.port 8502
"""

import sys
from pathlib import Path

# Ensure demo/ is importable as a package
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
from tabs import tab_overview, tab_trends, tab_tryon, tab_operations, tab_datachain

st.set_page_config(
    page_title="美甲 AI 运营平台",
    page_icon="💅",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Header
st.markdown(
    "<h1 style='text-align:center; color:#FF6B9D;'>💅 美甲 AI 运营平台</h1>"
    "<p style='text-align:center; color:#888;'>AI Hackathon 2026 · 美团赛道 · V0 Demo</p>",
    unsafe_allow_html=True,
)
st.divider()

# Main tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "🏠 概览",
        "📊 趋势感知",
        "💅 AI 试戴",
        "🎯 智能运营",
        "📋 数据链路",
    ]
)

with tab1:
    tab_overview.render()

with tab2:
    tab_trends.render()

with tab3:
    tab_tryon.render()

with tab4:
    tab_operations.render()

with tab5:
    tab_datachain.render()
