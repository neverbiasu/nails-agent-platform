"""
ComfyUI Cloud Client.
Base URL: https://cloud.comfy.org
Auth: X-API-Key: comfyui-{key}

Fixed upload → submit → poll → CDN-URL flow.
"""

from __future__ import annotations

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

    # ── Generic workflow runner ──────────────────────────────────────────────

    def run_workflow(
        self,
        workflow: Dict[str, Any],
        image_inputs: Dict[str, str],
        text_overrides: Optional[Dict[str, str]] = None,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        General-purpose: upload N images → patch their LoadImage nodes →
        optionally override text prompts → submit → poll → return CDN URL.

        Args:
            image_inputs: {node_id: local_image_path} for every LoadImage
                          node in the workflow. Single- or multi-image flows
                          are both supported.
            text_overrides: {node_id: prompt_text} to swap into TextEncode
                          nodes (anything with an `inputs.text` or
                          `inputs.prompt` field).
        """
        import copy

        wf = copy.deepcopy(workflow)

        # Upload + patch images
        for node_id, path in image_inputs.items():
            if node_id not in wf:
                return {"success": False, "error": f"Image node '{node_id}' missing in workflow"}
            name = self.upload_image(path)
            if not name:
                return {
                    "success": False,
                    "error": f"Failed to upload image for node {node_id}: {path}",
                }
            wf[node_id].setdefault("inputs", {})["image"] = name

        # Optional text overrides
        if text_overrides:
            for node_id, text in text_overrides.items():
                if node_id not in wf:
                    continue
                inp = wf[node_id].setdefault("inputs", {})
                if "prompt" in inp:
                    inp["prompt"] = text
                elif "text" in inp:
                    inp["text"] = text

        # Submit + poll + extract CDN URL
        submit = self.submit_workflow(wf)
        prompt_id = submit.get("prompt_id")
        if not prompt_id:
            return {"success": False, "error": f"No prompt_id: {submit}"}

        t0 = time.time()
        job = self.wait_for_job(prompt_id, timeout=timeout)
        if not job.get("success"):
            return {"success": False, "error": job.get("error")}

        filename = (job.get("preview_output") or {}).get("filename")
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

    # ── Workflow-specific convenience wrappers ───────────────────────────────

    def run_tryon(
        self,
        workflow: Dict[str, Any],
        hand_image_path: str,
        style_image_path: str,
        hand_node: str = "76",
        style_node: str = "81",
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """Try-on workflow: 2 LoadImage nodes (hand + style)."""
        return self.run_workflow(
            workflow=workflow,
            image_inputs={hand_node: hand_image_path, style_node: style_image_path},
            timeout=timeout,
        )

    def run_product_showcase(
        self,
        workflow: Dict[str, Any],
        nail_image_path: str,
        prompt: Optional[str] = None,
        image_node: str = "143",
        prompt_node: str = "208",
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """Product display image: single input image, optional prompt override."""
        return self.run_workflow(
            workflow=workflow,
            image_inputs={image_node: nail_image_path},
            text_overrides={prompt_node: prompt} if prompt else None,
            timeout=timeout,
        )

    def run_social_post(
        self,
        workflow: Dict[str, Any],
        nail_image_path: str,
        prompt: Optional[str] = None,
        image_node: str = "143",
        prompt_node: str = "192:187",
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """Social-media hero image: single input image, optional prompt override."""
        return self.run_workflow(
            workflow=workflow,
            image_inputs={image_node: nail_image_path},
            text_overrides={prompt_node: prompt} if prompt else None,
            timeout=timeout,
        )
