# ComfyUI Integration Design

**Date:** 2026-06-01
**Status:** Approved (brainstorm) — pending spec review

## Goal

Integrate ComfyUI (Comfy Cloud) image generation into nails-agent-platform for three
use cases, reusing the existing in-repo Cloud client rather than building a new engine:

1. **美甲试戴出图 (nail try-on)** — apply a chosen style onto a hand image; wire into the
   `tryon_jobs` job flow.
2. **款式参考图生成 / 图像增强 (style reference / enhancement)** — generate polished cover
   images for style-card drafts inside the chat pipeline.
3. **通用 ComfyUI 客户端 (generic client)** — submit a workflow, inject params, poll, fetch outputs.

## Decisions (locked during brainstorm)

- **Architecture:** Extend the existing `nails_agent/tools/comfyui_client.py` (native Python,
  already does Cloud upload→submit→poll→CDN-URL). Do NOT shell out to the Hermes skill's
  `run_workflow.py`. Add a workflow registry to remove hard-coded node IDs from call sites.
- **Target:** Cloud-primary (`https://cloud.comfy.org`, `X-API-Key: comfyui-{key}`). Keep a
  `host`/`is_cloud` seam for future local support; do not build local now.
- **Enhancement scope:** Use `product_showcase_firered_image_edit1_1.json`; enhance the top-N
  drafts only (N=3 default, configurable). Graceful fallback keeps the original image on failure.
- **Try-on:** Full job flow (persist `TryOnJob`), no Roboflow masking in v1.

## Why reuse the in-repo client (not the skill script)

The Hermes skill's `run_workflow.py` uses the *same* Comfy Cloud REST contract
(`/api/prompt`, `/api/job/{id}/status`, `/api/view`) as the in-repo client, so they are
protocol-compatible. The skill adds schema-based param injection, local-host support, and
disk output download — but it is a CLI/subprocess tool, awkward to call from inside FastAPI /
Streamlit and a worse fit for the in-process job flow. The in-repo client returns CDN URLs
directly, which is what the app and pipeline consume. We port the *idea* of param injection
(a workflow registry / node-ID map) without adopting the script.

---

## Component 1 — Generic ComfyUI client (use case 3)

**File:** `nails_agent/tools/comfyui_client.py` (extend in place).

Existing methods stay: `upload_image`, `submit_workflow`, `wait_for_job`,
`get_public_image_url`, `run_workflow`, `run_tryon`, `run_product_showcase`, `run_social_post`.

**Add a workflow registry** so callers reference workflows by name, not file path + node IDs:

```python
WORKFLOWS = {
    "tryon":           {"path": "workflows/nail_tryon_klein_9b.json",
                         "image_nodes": {"hand": "76", "style": "81"}},
    "product_showcase":{"path": "workflows/product_showcase_firered_image_edit1_1.json",
                         "image_node": "143", "prompt_node": "208"},
    "social_media":    {"path": "workflows/social_media_firered_image_edit1_1.json",
                         "image_node": "143", "prompt_node": "192:187"},
}
```

- `load_workflow(name) -> dict` — read + cache the JSON from the registry.
- `enhance(image_path, workflow="product_showcase", prompt=None, timeout=180) -> dict`
  — convenience wrapper over `run_product_showcase`/`run_social_post` using the registry,
  returning `{success, image_url, duration_s, error}`.

Node IDs live in the registry only — no longer duplicated across `web/comfyui_tryon.py` and
the wrapper defaults. Keep `host`/`is_cloud` plumbing untouched for a future local path.

**Out of scope:** porting the skill's `extract_schema.py` full schema extraction. The three
workflows are fixed; the registry's node-ID map is sufficient.

---

## Component 2 — Image enhancement in the chat pipeline (use case 2 / 图像增强)

**Hook point:** `nails_agent/agents/workers/asset_generator.py` → `generate(analysis)`.

Today each `StyleCardDraft` is built with `image_url = signal_image_url(sig)` (the raw scraped
trend image) and no enhancement. Add enhancement after draft construction.

**Schema change:** add `enhanced_image_url: str = ""` to `StyleCardDraft`
(`nails_agent/models/schemas.py:135`). `StyleCard` inherits it. `NailStyleStoreItem` already has it.

**Flow in `generate()`:**

1. Build all drafts as today.
2. For the top-N drafts (N from a param, default 3), resolve a **local** source image:
   `signal_image_url` returns `local_image_paths[0]` when present, else a remote URL. The
   client's `upload_image` needs a local file, so:
   - If the resolved path exists on disk → enhance via `client.enhance(path, "product_showcase")`.
   - If only a remote URL exists (no local file) → skip enhancement, keep original `image_url`.
3. On success set `draft.enhanced_image_url = result["image_url"]`; on failure/skip leave it
   empty and keep `image_url`. Never raise out of enhancement — log + continue.
4. Enhancement is bounded by N to cap latency (~30–60s/image on Cloud → ~2–3 min for N=3).

**Pipeline visibility:** `chat_runner._phase_evaluating` (chat_runner.py:575, where
`asset_generator.generate` is called at ~620) emits a phase/tool event summarizing how many
covers were enhanced, so the human-in-the-loop sees progress in `chat_app.py`.

**Configuration:** N (`enhance_top_n`) and an on/off flag passed from the runner to
`asset_generator.generate(analysis, enhance_top_n=3)`. Default keeps the pipeline usable when
`COMFYUI_API_KEY` is absent (enhancement silently no-ops, drafts keep original images).

**Persistence:** `persist_asset_generation` already serializes drafts (now including
`enhanced_image_url`). When a draft is promoted into `nail_styles_store`, its
`enhanced_image_url` carries over (field already exists on `NailStyleStoreItem`).

---

## Component 3 — Try-on full job flow (use case 1)

**Files:** `web/comfyui_tryon.py`, `nails_agent/memory/store.py` (existing `put_tryon_job`).

**Bug fix:** `web/comfyui_tryon.py:17` inserts `agents/` on `sys.path` and imports
`from comfyui_client import ComfyUIClient`, but the client lives in `nails_agent/tools/`. That
import silently fails → `_CLIENT_AVAILABLE = False` → try-on is dead. Fix to import
`from nails_agent.tools.comfyui_client import ComfyUIClient`.

**Job flow in `generate_tryon(style_item, session_id, user_hand_image_id)`:**

1. Build a `TryOnJob` (status `pending`) and `store.put_tryon_job(job)`.
2. Upload hand + style images, patch nodes via the registry (`tryon`: hand=76, style=81),
   submit, poll. Capture `comfyui_prompt_id` when available.
3. On success: set `status="success"`, `result_image_url`, `duration_s`, `completed_at`;
   persist. On failure/timeout: `status="failed"`, `error_message`; persist. Return the same
   `{success, image_url, fallback_url, error, duration_s}` shape the Streamlit tab expects.

**Out of scope (v1):** Roboflow nail-region masking. The Klein workflow is image-edit and
consumes hand+style directly. Revisit only if try-on accuracy demands inpainting.

---

## Error handling & edge cases

- **Missing `COMFYUI_API_KEY`:** client returns a structured error; enhancement no-ops and
  keeps original images; try-on returns `success=False` with `fallback_url`. The pipeline
  must remain runnable end-to-end without a key.
- **Cloud timeout / job failure:** caught per-call, surfaced as `error`, never crashes the
  pipeline or the Streamlit app.
- **Remote-only source image:** enhancement is skipped (no download in v1), original kept.

## Testing

- **Client (unit):** registry loads each workflow; node-ID patching targets correct nodes;
  `enhance`/`run_tryon` return-shape; graceful failure when key missing (mock `requests`).
- **asset_generator (unit):** `enhanced_image_url` set on success, empty on
  failure/skip/remote-only; `enhance_top_n` bounds the number of client calls (mock client);
  pipeline still produces drafts with no key.
- **Try-on (unit):** a `TryOnJob` is persisted with correct status transitions on
  success and failure (mock client + in-memory store).
- Manual: run a real Cloud try-on and one pipeline enhancement to confirm CDN URLs render.

## File touch list

- `nails_agent/tools/comfyui_client.py` — registry + `load_workflow` + `enhance`.
- `nails_agent/models/schemas.py` — `StyleCardDraft.enhanced_image_url`.
- `nails_agent/agents/workers/asset_generator.py` — enhancement loop + `enhance_top_n` param.
- `nails_agent/agents/chat_runner.py` — pass `enhance_top_n`, emit enhancement event.
- `web/comfyui_tryon.py` — import fix + `TryOnJob` persistence.
- `tests/` — unit tests above.
