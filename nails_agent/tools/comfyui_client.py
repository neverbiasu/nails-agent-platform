"""
ComfyUI Cloud Client.
Base URL: https://cloud.comfy.org
Auth: X-API-Key: comfyui-{key}

Fixed upload → submit → poll → CDN-URL flow.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests


class ComfyUIClient:
    BASE_URL = "https://cloud.comfy.org"

    def __init__(self, api_key: Optional[str] = None):
        raw = api_key or os.environ.get("COMFYUI_API_KEY", "")
        self.api_key = f"comfyui-{raw}"
        self.client_id = str(uuid.uuid4())

    @property
    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    # ── Upload ───────────────────────────────────────────────────────────────

    def upload_image(self, image_path: str) -> Optional[str]:
        """Upload local image; returns cloud filename for LoadImage nodes."""
        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{self.BASE_URL}/api/upload/image",
                headers={"X-API-Key": self.api_key},
                files={"image": (Path(image_path).name, f, "image/jpeg")},
                timeout=60,
            )
        if resp.status_code == 200:
            return resp.json().get("name")
        return None

    # ── Submit ───────────────────────────────────────────────────────────────

    def submit_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.BASE_URL}/api/prompt",
            json={"prompt": workflow, "client_id": self.client_id},
            headers=self._headers,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": resp.text[:300], "status": resp.status_code}

    # ── Poll ─────────────────────────────────────────────────────────────────

    def get_job_status(self, prompt_id: str) -> Dict[str, Any]:
        resp = requests.get(
            f"{self.BASE_URL}/api/job/{prompt_id}/status",
            headers=self._headers,
            timeout=10,
        )
        return resp.json() if resp.status_code == 200 else {"error": resp.text}

    def get_job_detail(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """Full detail including outputs — uses plural /api/jobs/ endpoint."""
        resp = requests.get(
            f"{self.BASE_URL}/api/jobs/{prompt_id}",
            headers=self._headers,
            timeout=10,
        )
        return resp.json() if resp.status_code == 200 else None

    def wait_for_job(self, prompt_id: str, timeout: int = 180) -> Dict[str, Any]:
        """Poll until job terminates; returns normalised result dict."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.get_job_status(prompt_id).get("status", "unknown")
            if status in ("success", "completed"):
                detail = self.get_job_detail(prompt_id) or {}
                return {
                    "success": True,
                    "outputs": detail.get("outputs", {}),
                    "preview_output": detail.get("preview_output"),
                }
            if status in ("failed", "cancelled"):
                return {"success": False, "error": status}
            time.sleep(3)
        return {"success": False, "error": "timeout"}

    # ── Image URL ────────────────────────────────────────────────────────────

    def view_url(self, filename: str) -> str:
        return f"{self.BASE_URL}/api/view?filename={filename}"

    def get_public_image_url(self, filename: str) -> str:
        """Follow 302 redirect → signed GCS CDN URL (valid ~6 h)."""
        resp = requests.get(
            f"{self.BASE_URL}/api/view?filename={filename}",
            headers=self._headers,
            allow_redirects=False,
            timeout=10,
        )
        if resp.status_code == 302:
            return resp.headers.get("location", "")
        return ""

    # ── High-level helper ────────────────────────────────────────────────────

    def run_tryon(
        self,
        workflow: Dict[str, Any],
        hand_image_path: str,
        style_image_path: str,
        hand_node: str = "76",
        style_node: str = "81",
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Full try-on pipeline:
        upload hand + style → patch workflow → submit → poll → CDN URL.
        """
        # Upload
        hand_name = self.upload_image(hand_image_path)
        if not hand_name:
            return {"success": False, "error": "Failed to upload hand image"}
        style_name = self.upload_image(style_image_path)
        if not style_name:
            return {"success": False, "error": "Failed to upload style image"}

        # Patch LoadImage nodes
        import copy
        wf = copy.deepcopy(workflow)
        if hand_node in wf:
            wf[hand_node]["inputs"]["image"] = hand_name
        if style_node in wf:
            wf[style_node]["inputs"]["image"] = style_name

        # Submit
        result = self.submit_workflow(wf)
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            return {"success": False, "error": f"No prompt_id: {result}"}

        # Poll
        t0 = time.time()
        job = self.wait_for_job(prompt_id, timeout=timeout)
        if not job.get("success"):
            return {"success": False, "error": job.get("error")}

        # Extract filename
        filename = None
        preview = job.get("preview_output") or {}
        filename = preview.get("filename")
        if not filename:
            for node_out in (job.get("outputs") or {}).values():
                imgs = node_out.get("images") or []
                if imgs:
                    filename = imgs[0].get("filename")
                    break
        if not filename:
            return {"success": False, "error": "No output filename in job result"}

        public_url = self.get_public_image_url(filename) or self.view_url(filename)
        return {
            "success": True,
            "image_url": public_url,
            "duration_s": round(time.time() - t0, 1),
        }
