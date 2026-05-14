from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.hand_analysis import analyze_hand_image  # noqa: E402


st.set_page_config(
    page_title="V1 手部画像识别验证",
    page_icon=None,
    layout="wide",
)

st.markdown(
    """
    <style>
      :root {
        --ink: #f7f9fc;
        --muted: #98a2b3;
        --line: #293241;
        --panel: #121823;
        --accent: #ff5c7a;
      }
      .stApp {
        background: #0d111a;
      }
      .block-container {
        padding-top: 1.4rem;
        padding-bottom: 3rem;
      }
      h1, h2, h3, p, label {
        letter-spacing: 0;
      }
      .subtitle {
        color: var(--muted);
        margin-top: -0.4rem;
        margin-bottom: 1rem;
      }
      .result-card {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 1rem;
        background: linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.025));
        min-height: 118px;
      }
      .result-label {
        color: var(--muted);
        font-size: 0.84rem;
        margin-bottom: 0.32rem;
      }
      .result-value {
        color: var(--ink);
        font-size: 1.55rem;
        font-weight: 780;
        margin-bottom: 0.35rem;
      }
      .result-reason {
        color: #c8d0dc;
        font-size: 0.86rem;
        line-height: 1.45;
      }
      .rgb-chip {
        display: inline-block;
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 0.2rem 0.62rem;
        color: #d5dbe5;
        background: rgba(255,255,255,0.045);
        font-size: 0.8rem;
        margin-top: 0.2rem;
      }
      div[data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 8px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def result_card(label: str, value: str, confidence: float | None, reason: str) -> None:
    suffix = "" if confidence is None else f" · {confidence:.2f}"
    st.markdown(
        f"""
        <div class="result-card">
          <div class="result-label">{label}{suffix}</div>
          <div class="result-value">{value}</div>
          <div class="result-reason">{reason}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.title("V1 手部画像识别验证")
st.markdown(
    '<div class="subtitle">上传一张完整手背图，系统会识别五类手型、肤色类别和肤色冷暖倾向。</div>',
    unsafe_allow_html=True,
)

uploaded = st.file_uploader("上传手部图片", type=["png", "jpg", "jpeg", "webp"])

sample_files = sorted((ROOT_DIR / "images").glob("image*.png"))
with st.sidebar:
    st.subheader("本地样例")
    use_sample = st.checkbox("使用 demo_v1/images 样例", value=False)
    sample_path = None
    if use_sample and sample_files:
        sample_name = st.selectbox("选择样例图片", [p.name for p in sample_files])
        sample_path = ROOT_DIR / "images" / sample_name
    st.divider()
    st.caption("当前阈值是 V1 初版规则，后续需要用真实上传图调参。")

source = None
if uploaded is not None:
    source = uploaded.getvalue()
elif use_sample and sample_path is not None:
    source = sample_path

if source is None:
    st.info("请上传图片，或在侧边栏选择一张本地样例图。")
    st.stop()

with st.spinner("正在识别手部关键点与肤色..."):
    result = analyze_hand_image(source)

if not result["ok"]:
    st.error(result["error"])
    st.image(result["original_image"], caption="原图", width="stretch")
    st.stop()

cols = st.columns(3)
with cols[0]:
    result_card(
        "手型",
        result["hand_shape_label"],
        result["hand_shape_confidence"],
        result["hand_shape_reason"],
    )
with cols[1]:
    result_card(
        "肤色",
        result["skin_tone_label"],
        result["skin_confidence"],
        result["skin_reason"],
    )
with cols[2]:
    result_card(
        "冷暖调",
        result["undertone_label"],
        result["undertone_confidence"],
        result["undertone_reason"],
    )

left, right = st.columns([1, 1])
with left:
    st.subheader("原图")
    st.image(result["original_image"], width="stretch")
with right:
    st.subheader("关键点与肤色采样区域")
    st.image(result["annotated_image"], width="stretch")

rgb = result["median_rgb"]
st.markdown(
    f'<span class="rgb-chip">median_rgb: [{rgb[0]}, {rgb[1]}, {rgb[2]}]</span>'
    f'<span class="rgb-chip">detected hand: {result["handedness"]}</span>',
    unsafe_allow_html=True,
)

st.subheader("手型计算指标")
st.dataframe(
    [{"metric": key, "value": value} for key, value in result["metrics"].items()],
    width="stretch",
    hide_index=True,
)

st.subheader("肤色计算指标")
st.dataframe(
    [{"metric": key, "value": value} for key, value in result["color_metrics"].items()],
    width="stretch",
    hide_index=True,
)
