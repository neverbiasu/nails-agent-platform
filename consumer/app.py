"""
Demo V1 — Consumer Try-On Streamlit (thin HTTP client).

This is the interim consumer UI. All business logic lives in the FastAPI
backend at NAILS_API_BASE (default: http://localhost:8000). It will be
replaced by the Next.js / Vue rewrite; for now this proves the API surface
and gives QA something to click.
"""

from __future__ import annotations

import base64
import os
from html import escape
from pathlib import Path
from typing import Any

import requests
import streamlit as st


API_BASE = os.environ.get("NAILS_API_BASE", "http://localhost:8000")
ROOT_DIR = Path(__file__).resolve().parent

st.set_page_config(page_title="美甲试戴推荐 Demo V1", page_icon=None, layout="wide")
st.markdown(
    """
    <style>
      :root {
        --ink: #f7f9fc; --muted: #98a2b3; --line: #293241; --panel: #111722;
        --soft: #171e2b; --accent: #ff5c7a; --accent-soft: rgba(255, 92, 122, 0.14);
        --good: #63d8a6;
      }
      .stApp { background: #0d111a; }
      .block-container { padding-top: 1.35rem; padding-bottom: 3rem; }
      .kicker { color: var(--accent); font-size: 0.82rem; font-weight: 760; margin-bottom: 0.1rem; }
      .subtitle { color: var(--muted); margin-top: -0.35rem; margin-bottom: 1.1rem; }
      .result-card { border: 1px solid var(--line); border-radius: 8px; padding: 0.95rem;
                     min-height: 116px;
                     background: linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.025)); }
      .result-label { color: var(--muted); font-size: 0.82rem; margin-bottom: 0.25rem; }
      .result-value { color: var(--ink); font-size: 1.45rem; font-weight: 780; margin-bottom: 0.32rem; }
      .result-reason { color: #c8d0dc; font-size: 0.84rem; line-height: 1.45; }
      .style-title { color: var(--ink); font-weight: 750; font-size: 1rem; margin-top: 0.55rem; }
      .style-meta { color: var(--muted); font-size: 0.78rem; margin-bottom: 0.38rem; }
      .score { color: var(--good); font-weight: 780; }
      .pill { display: inline-block; border: 1px solid var(--line); border-radius: 999px;
              padding: 0.16rem 0.52rem; color: #d8dee9; background: rgba(255,255,255,0.05);
              font-size: 0.76rem; margin-right: 0.25rem; margin-bottom: 0.25rem; }
      .pill-hot { border-color: rgba(255,92,122,0.5); color: #ffd6df; background: var(--accent-soft); }
      .small-muted { color: var(--muted); font-size: 0.82rem; }
      div[data-testid="stMetric"] {
        background: linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.025));
        border: 1px solid var(--line); padding: 0.75rem 0.85rem; border-radius: 8px;
      }
      div[data-testid="stMetric"] label, div[data-testid="stMetric"] label p { color: var(--muted) !important; }
      div[data-testid="stMetricValue"], div[data-testid="stMetricValue"] div { color: var(--ink) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Static label maps (mirrors backend; cheap to duplicate) ───────────────────

HAND_SHAPE_LABELS = {
    "slender_long": "纤长型",
    "short_wide": "短宽型",
    "square_palm": "方掌型",
    "narrow_palm": "窄掌型",
    "unknown": "未识别",
}
SKIN_TONE_LABELS = {
    "cool_fair": "冷白",
    "warm_fair": "暖白",
    "natural": "自然肤色",
    "warm_yellow": "暖黄",
    "wheat": "小麦色",
    "deep": "深肤色",
    "unknown": "未识别",
}
UNDERTONE_LABELS = {
    "warm": "暖调",
    "cool": "冷调",
    "neutral": "中性",
    "unknown": "未识别",
}
COLOR_FAMILY_LABELS = {
    "red": "红色系",
    "pink": "粉色系",
    "nude": "裸色系",
    "white": "白色系",
    "black": "黑色系",
    "green": "绿色系",
    "blue": "蓝色系",
    "purple": "紫色系",
    "gold_silver": "金银色系",
    "multi": "多色系",
    "unknown": "未知色系",
}
COLOR_TEMP_LABELS = {
    "warm": "暖色",
    "cool": "冷色",
    "neutral": "中性色",
    "mixed": "混合色",
    "unknown": "未知",
}
LEVEL_LABELS = {
    "light": "浅明度",
    "medium": "中等",
    "dark": "深明度",
    "low": "低",
    "high": "高",
    "mixed": "混合",
    "unknown": "未知",
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def api_get(path: str, **kwargs) -> Any:
    r = requests.get(f"{API_BASE}{path}", timeout=30, **kwargs)
    r.raise_for_status()
    return r.json()


def api_post(path: str, json_body: dict | None = None, files: dict | None = None) -> Any:
    r = requests.post(f"{API_BASE}{path}", json=json_body, files=files, timeout=180)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=60)
def fetch_styles_map() -> dict[str, dict[str, Any]]:
    try:
        return {s["style_id"]: s for s in api_get("/styles")}
    except Exception:
        return {}


def pill_html(values: list[str], hot: bool = False) -> str:
    cls = "pill pill-hot" if hot else "pill"
    return " ".join(f'<span class="{cls}">{escape(str(v))}</span>' for v in values)


def result_card(label: str, value: str, confidence: float | None, reason: str) -> None:
    suffix = "" if confidence is None else f" · {confidence:.2f}"
    st.markdown(
        f'<div class="result-card"><div class="result-label">{escape(label)}{escape(suffix)}</div>'
        f'<div class="result-value">{escape(value)}</div>'
        f'<div class="result-reason">{escape(reason)}</div></div>',
        unsafe_allow_html=True,
    )


def b64_to_image_bytes(b64: str) -> bytes:
    return base64.b64decode(b64) if b64 else b""


def resolve_image(path_or_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    p = Path(path_or_url)
    if p.is_absolute():
        return str(p)
    # legacy relative paths stored in style.image_url (e.g. "images/...")
    for cand in (ROOT_DIR / path_or_url, ROOT_DIR.parent / path_or_url):
        if cand.exists():
            return str(cand)
    return str(p)


# ── Card rendering ────────────────────────────────────────────────────────────


def style_card(
    item: dict[str, Any],
    snapshot_id: str,
    session_id: str,
    button_prefix: str,
    styles_map: dict[str, dict[str, Any]],
) -> None:
    style = styles_map.get(item["style_id"], {})
    image = resolve_image(style.get("image_url", ""))
    primary_color = item.get("primary_color_name") or item.get("main_color_name") or "未知"
    family_label = COLOR_FAMILY_LABELS.get(item.get("primary_color_family", "unknown"), "未知色系")
    temp_label = COLOR_TEMP_LABELS.get(item.get("color_temperature", "unknown"), "未知")
    brightness_label = LEVEL_LABELS.get(item.get("brightness_level", "unknown"), "未知")
    saturation_label = LEVEL_LABELS.get(item.get("saturation_level", "unknown"), "未知")
    visual_score = item.get("visual_similarity_score") or 0
    visual_line = ""
    if visual_score:
        visual_line = (
            f'<div class="small-muted">视觉相似：<span class="score">{visual_score}</span> · '
            f"调色板 {item.get('palette_similarity_score', 0)}</div>"
        )

    with st.container(border=True):
        if image:
            st.image(image, width="stretch")
        st.markdown(
            f'<div class="style-title">#{item["rank"]} {escape(style.get("title", item["style_id"]))}</div>'
            f'<div class="style-meta">{escape(style.get("style_id", ""))} · '
            f'<span class="score">{item["total_score"]}</span> 分</div>'
            f"{pill_html(item.get('reason_tags', []), hot=True)}"
            f'<div class="small-muted">主色：{escape(primary_color)} · {escape(family_label)} · {escape(temp_label)}</div>'
            f'<div class="small-muted">明暗/饱和：{escape(brightness_label)} · {escape(saturation_label)}</div>'
            f"{visual_line}"
            f'<div class="small-muted" style="margin-top:0.35rem;">{escape(item.get("reason_text", ""))}</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        if c1.button(
            "点击", key=f"{button_prefix}_click_{snapshot_id}_{item['style_id']}", width="stretch"
        ):
            api_post(
                f"/sessions/{session_id}/events",
                json_body={
                    "style_id": item["style_id"],
                    "event_type": "click",
                    "source_snapshot_id": snapshot_id,
                },
            )
            st.toast(f"已记录点击：{style.get('title', '')}")
            st.rerun()
        if c2.button(
            "试戴", key=f"{button_prefix}_try_{snapshot_id}_{item['style_id']}", width="stretch"
        ):
            with st.spinner("ComfyUI 试戴中（约 30–60 秒）..."):
                try:
                    job = api_post(
                        f"/sessions/{session_id}/tryon",
                        json_body={
                            "style_id": item["style_id"],
                            "source_snapshot_id": snapshot_id,
                        },
                    )
                except Exception as exc:
                    st.error(f"试戴失败：{exc}")
                    return
            if job.get("status") == "success":
                st.toast(f"试戴完成：{style.get('title', '')}")
            else:
                st.warning(f"试戴未成功：{job.get('error_message', '')}")
            st.rerun()


def render_recommendation_grid(
    snapshot: dict[str, Any] | None,
    session_id: str,
    prefix: str,
    styles_map: dict[str, dict[str, Any]],
) -> None:
    if not snapshot:
        st.info("暂无推荐结果")
        return
    cols = st.columns(5)
    for index, item in enumerate(snapshot.get("items", [])[:10]):
        with cols[index % 5]:
            style_card(item, snapshot["snapshot_id"], session_id, prefix, styles_map)


def render_profile(profile: dict[str, Any], user_image: dict[str, Any]) -> None:
    cols = st.columns(3)
    with cols[0]:
        result_card(
            "手型",
            HAND_SHAPE_LABELS.get(profile.get("hand_shape", "unknown"), "未知"),
            profile.get("hand_shape_confidence"),
            "由 MediaPipe 关键点比例归类",
        )
    with cols[1]:
        result_card(
            "肤色",
            SKIN_TONE_LABELS.get(profile.get("skin_tone", "unknown"), "未知"),
            profile.get("skin_confidence"),
            f"RGB: {profile.get('skin_rgb', [])}",
        )
    with cols[2]:
        result_card(
            "冷暖调",
            UNDERTONE_LABELS.get(profile.get("undertone", "unknown"), "未知"),
            profile.get("undertone_confidence"),
            "由 Lab / HSV / YCrCb 特征判断",
        )

    left, right = st.columns([1, 1])
    img_path = user_image.get("image_url", "")
    annot_path = user_image.get("annotated_image_url", "")
    with left:
        if img_path and Path(img_path).exists():
            st.image(img_path, caption="上传手图", width="stretch")
        else:
            st.info("用户原图不可访问（API 服务可能与 Streamlit 不在同一文件系统）")
    with right:
        if annot_path and Path(annot_path).exists():
            st.image(annot_path, caption="关键点与肤色采样区域", width="stretch")


# ── Page ──────────────────────────────────────────────────────────────────────


st.markdown(
    '<div class="kicker">User-side Try-on Recommendation · V1 (API-backed)</div>',
    unsafe_allow_html=True,
)
st.title("美甲试戴推荐 Demo V1")
st.markdown(
    '<div class="subtitle">上传手图生成本次会话画像，第一轮按参考手匹配，第二轮从点击与真实 ComfyUI 试戴中学习颜色偏好并推荐相似款。</div>',
    unsafe_allow_html=True,
)
st.caption(f"API: `{API_BASE}` · 改前端时只需写 JS，业务逻辑跟着这套 API 走")

with st.sidebar:
    st.subheader("V1 控制台")
    try:
        api_get("/health")
    except Exception as exc:
        st.error(f"API 未就绪：{exc}")
        st.stop()

    uploaded = st.file_uploader("上传手部图片", type=["png", "jpg", "jpeg", "webp"])
    sample_files = sorted((ROOT_DIR / "images").glob("image*.png"))
    use_sample = st.checkbox("使用本地样例", value=False)
    sample_path: Path | None = None
    if use_sample and sample_files:
        sample_name = st.selectbox("选择样例", [p.name for p in sample_files])
        sample_path = ROOT_DIR / "images" / sample_name

    upload_payload = None
    upload_name = ""
    if uploaded is not None:
        upload_payload = uploaded.getvalue()
        upload_name = uploaded.name
    elif use_sample and sample_path is not None:
        upload_payload = sample_path.read_bytes()
        upload_name = sample_path.name

    if st.button("创建会话并分析", width="stretch", disabled=upload_payload is None):
        with st.spinner("正在识别手型、肤色与冷暖调..."):
            try:
                created = api_post(
                    "/sessions",
                    files={"image": (upload_name, upload_payload, "image/png")},
                )
            except requests.HTTPError as exc:
                msg = exc.response.text if exc.response is not None else str(exc)
                st.error(f"创建失败：{msg}")
                created = None
        if created:
            st.session_state["active_session_id"] = created["session"]["session_id"]
            st.success("已创建 V1 会话并生成第一轮推荐")
            st.rerun()

    st.divider()

session_id = st.session_state.get("active_session_id")
if not session_id:
    st.info("请先在左侧上传手部图片，或选择本地样例并创建会话。")
    st.stop()

try:
    bundle = api_get(f"/sessions/{session_id}")
except requests.HTTPError as exc:
    st.warning(f"会话不存在：{exc}")
    st.session_state.pop("active_session_id", None)
    st.stop()

session = bundle["session"]
profile = bundle["hand_profile"]
user_image = bundle["user_image"]

if not profile or not user_image:
    st.warning("当前会话缺少手部画像或上传图片，请重新创建会话。")
    st.stop()

styles_map = fetch_styles_map()

try:
    round1 = api_get(f"/sessions/{session_id}/recommendations/latest", params={"round_no": 1})
except Exception:
    round1 = None
try:
    round2 = api_get(f"/sessions/{session_id}/recommendations/latest", params={"round_no": 2})
except Exception:
    round2 = None
try:
    events = api_get(f"/sessions/{session_id}/events")
except Exception:
    events = []
try:
    try_on_job = api_get(f"/sessions/{session_id}/tryon/latest")
except Exception:
    try_on_job = None

metric_cols = st.columns(5)
metric_cols[0].metric("当前会话", session_id)
metric_cols[1].metric("手型", HAND_SHAPE_LABELS.get(profile["hand_shape"], "未知"))
metric_cols[2].metric("肤色", SKIN_TONE_LABELS.get(profile["skin_tone"], "未知"))
metric_cols[3].metric("行为", len(events))
metric_cols[4].metric("二轮推荐", "已生成" if round2 else "未生成")

tab_profile, tab_round1, tab_tryon, tab_round2 = st.tabs(
    ["手部画像", "第一轮推荐", "ComfyUI 试戴 & 行为", "第二轮推荐"]
)

with tab_profile:
    render_profile(profile, user_image)

with tab_round1:
    st.subheader("第一轮推荐：参考手画像匹配")
    st.caption("只使用用户手型/肤色与美甲库参考手手型/肤色匹配，不使用行为偏好。")
    render_recommendation_grid(round1, session_id, "round1", styles_map)

with tab_tryon:
    st.subheader("ComfyUI 试戴与本次行为")
    st.caption("点击或试戴卡片下方按钮即可触发；试戴会真实调用 ComfyUI Cloud，约 30–60 秒返回。")
    if try_on_job:
        style = styles_map.get(try_on_job["style_id"], {})
        c1, c2 = st.columns([1, 1])
        with c1:
            img_path = user_image.get("image_url", "")
            if img_path and Path(img_path).exists():
                st.image(img_path, caption="用户手图", width="stretch")
        with c2:
            result_url = try_on_job.get("result_image_url")
            if result_url:
                st.image(result_url, caption=f"试戴结果：{style.get('title', '')}", width="stretch")
            else:
                st.warning(
                    f"试戴未完成：{try_on_job.get('status')} · {try_on_job.get('error_message') or ''}"
                )
    else:
        st.info("还没有试戴结果，请在推荐卡片中点击「试戴」。")

    st.markdown("#### 本次 Session 行为")
    if events:
        st.dataframe(events, width="stretch", hide_index=True)
    else:
        st.info("暂无行为记录")

with tab_round2:
    st.subheader("第二轮推荐：视觉偏好相似款")
    st.caption(
        "点击/试戴不会直接让原款置顶，而是学习色系、调色板、冷暖、明暗和饱和度后推荐相似款。"
    )
    c1, _ = st.columns([1, 4])
    if c1.button("刷新推荐", width="stretch"):
        try:
            api_post(f"/sessions/{session_id}/recommendations/round2")
            st.success("已根据本次行为生成第二轮推荐")
        except requests.HTTPError as exc:
            msg = (
                exc.response.json().get("detail", str(exc))
                if exc.response is not None
                else str(exc)
            )
            st.warning(msg)
        st.rerun()
    if not round2:
        st.info("点击或试戴后，点击「刷新推荐」生成第二轮推荐。")
    else:
        render_recommendation_grid(round2, session_id, "round2", styles_map)
