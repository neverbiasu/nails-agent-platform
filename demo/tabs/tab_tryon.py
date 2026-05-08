import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from data_loader import load_style_library
from comfyui_tryon import generate_tryon

STATIC_DIR = Path(__file__).parent.parent / "static"


def render():
    st.header("💅 AI 试戴")
    st.caption("选择喜欢的美甲款式，AI 为你生成试戴效果图")

    styles = load_style_library()
    style_names = [s["style_name"] for s in styles]
    style_map = {s["style_name"]: s for s in styles}

    col_sel, col_hand, col_result = st.columns([1, 1, 1])

    with col_sel:
        st.subheader("1️⃣ 选择款式")
        chosen_name = st.selectbox("美甲款式", style_names, label_visibility="collapsed")
        chosen = style_map[chosen_name]
        st.markdown(f"**{chosen['style_name']}**")
        tags = chosen.get("style_tags", [])
        st.markdown(" ".join(f"`{t}`" for t in tags))
        st.markdown(f"适合场景：{' | '.join(chosen.get('scene_tags', []))}")
        st.markdown(f"适合甲型：{' | '.join(chosen.get('nail_shape_tags', []))}")

        generate_btn = st.button("✨ 生成试戴图", type="primary", use_container_width=True)

    with col_hand:
        st.subheader("2️⃣ 手部参考")
        hand_img = STATIC_DIR / "hand_reference.jpg"
        if hand_img.exists():
            st.image(str(hand_img), caption="参考手部图", use_container_width=True)
        else:
            st.info("手部参考图未找到")

        nail_img = STATIC_DIR / "nail_reference.jpg"
        st.markdown("**美甲参考**")
        if nail_img.exists():
            st.image(str(nail_img), caption=chosen_name, use_container_width=True)

    with col_result:
        st.subheader("3️⃣ 试戴效果")

        if "tryon_result" not in st.session_state:
            st.session_state.tryon_result = None
        if "tryon_style" not in st.session_state:
            st.session_state.tryon_style = None

        if generate_btn:
            st.session_state.tryon_result = None
            st.session_state.tryon_style = chosen_name
            with st.spinner("🎨 正在生成试戴效果图（约 30-60 秒）…"):
                result = generate_tryon(chosen)
            st.session_state.tryon_result = result

        result = st.session_state.tryon_result

        if result is None:
            st.info("点击「生成试戴图」开始")
        elif result["success"]:
            st.success(f"✅ 生成成功（{result['duration_s']}s）")
            img_url = result["image_url"]
            if img_url and (img_url.startswith("http") or Path(img_url).exists()):
                st.image(img_url, caption=f"AI 试戴 — {st.session_state.tryon_style}",
                         use_container_width=True)
            else:
                st.image(str(nail_img), caption="预览效果", use_container_width=True)
        else:
            st.warning("⚠️ 生成未完成，显示预览模式")
            st.caption(f"原因：{result.get('error', '未知')}")
            fallback = result.get("fallback_url", "")
            if fallback and Path(fallback).exists():
                st.image(fallback, caption=f"预览 — {chosen_name}", use_container_width=True)
            elif nail_img.exists():
                st.image(str(nail_img), caption=f"预览 — {chosen_name}", use_container_width=True)

    st.divider()
    st.caption("🔧 试戴引擎：FLUX.2 Klein via ComfyUI Cloud | 生成图分辨率 1024×1024")
