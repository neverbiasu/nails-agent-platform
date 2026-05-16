"""
Thin wrapper around agents/comfyui_client.py for Streamlit try-on.
Loads the FLUX.2 Klein image-edit workflow, patches the two LoadImage
nodes (76 = hand reference, 81 = nail style), submits to ComfyUI Cloud,
and returns the output image URL or a graceful fallback.
"""

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Allow importing the existing ComfyUI client from agents/
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "agents"))

# Load API key from project .env, then hermes .env as fallback
load_dotenv(_PROJECT_ROOT / ".env")
if not os.environ.get("COMFYUI_API_KEY"):
    load_dotenv(Path.home() / ".hermes" / ".env")

try:
    from comfyui_client import ComfyUIClient

    _CLIENT_AVAILABLE = True
except ImportError:
    _CLIENT_AVAILABLE = False

WORKFLOW_PATH = Path(__file__).parent.parent / "workflows" / "nail_tryon_klein_9b.json"
HAND_REF_PATH = str(Path(__file__).parent / "static" / "hand_reference.jpg")
NAIL_REF_PATH = str(Path(__file__).parent / "static" / "nail_reference.jpg")


def _load_workflow() -> dict:
    return json.loads(WORKFLOW_PATH.read_text())


def _patch_workflow(workflow: dict, hand_name: str, style_name: str) -> dict:
    """Patch node 76 (hand ref) and node 81 (nail style) with cloud-uploaded filenames."""
    patched = json.loads(json.dumps(workflow))  # deep copy
    if "76" in patched:
        patched["76"]["inputs"]["image"] = hand_name
    if "81" in patched:
        patched["81"]["inputs"]["image"] = style_name
    return patched


def _resolve_style_image(style_item: dict) -> str:
    """Resolve the local image path for a style. Falls back to nail_reference.jpg."""
    img = style_item.get("image_url", "")
    if img and Path(img).exists():
        return img
    return NAIL_REF_PATH


def generate_tryon(style_item: dict) -> dict:
    """
    Run try-on for a given StyleLibraryItem.

    Steps:
      1. Upload hand_reference.jpg + style image to ComfyUI Cloud
      2. Patch workflow nodes 76/81 with returned cloud filenames
      3. Submit workflow + wait for completion
      4. Return output URL or graceful fallback
    """
    t0 = time.time()
    fallback = NAIL_REF_PATH

    if not _CLIENT_AVAILABLE:
        return {
            "success": False,
            "image_url": None,
            "fallback_url": fallback,
            "error": "ComfyUI client not available",
            "duration_s": 0.0,
        }

    if not WORKFLOW_PATH.exists():
        return {
            "success": False,
            "image_url": None,
            "fallback_url": fallback,
            "error": f"Workflow file not found: {WORKFLOW_PATH}",
            "duration_s": 0.0,
        }

    try:
        client = ComfyUIClient()

        # 1. Upload hand reference
        hand_name = client.upload_image(HAND_REF_PATH)
        if not hand_name:
            raise RuntimeError("Failed to upload hand reference image")

        # 2. Upload style/nail reference
        style_path = _resolve_style_image(style_item)
        style_name = client.upload_image(style_path)
        if not style_name:
            raise RuntimeError(f"Failed to upload style image: {style_path}")

        # 3. Patch workflow with uploaded filenames
        workflow = _load_workflow()
        patched = _patch_workflow(workflow, hand_name, style_name)

        # 4. Submit
        result = client.submit_workflow(patched)
        if not result:
            raise RuntimeError("submit_workflow returned empty response")

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"No prompt_id in response: {result}")

        # 5. Poll until complete (FLUX.2 typically 30-60s)
        job = client.wait_for_job(prompt_id, timeout=180)
        if not job or not job.get("success"):
            raise RuntimeError(f"Job failed/timed out: {job}")

        # 6. Extract image filename from preview_output, then build view URL
        preview = job.get("preview_output") or {}
        filename = preview.get("filename")

        if not filename:
            # Fallback: scan outputs dict {node_id: {images: [...]}}
            for node_id, node_out in (job.get("outputs") or {}).items():
                imgs = node_out.get("images") or []
                if imgs:
                    filename = imgs[0].get("filename")
                    break

        if not filename:
            raise RuntimeError(f"No image filename in job result: {job}")

        # Resolve to public CDN URL (signed, valid 6h) so browser can render directly
        public_url = client.get_public_image_url(filename) or client.view_url(filename)

        return {
            "success": True,
            "image_url": public_url,
            "fallback_url": fallback,
            "error": None,
            "duration_s": round(time.time() - t0, 1),
        }

    except Exception as exc:
        return {
            "success": False,
            "image_url": None,
            "fallback_url": fallback,
            "error": str(exc),
            "duration_s": round(time.time() - t0, 1),
        }
