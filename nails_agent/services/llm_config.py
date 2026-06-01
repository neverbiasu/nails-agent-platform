"""Centralised LLM environment configuration.

Provider priority (first available wins):
  1. ModelScope  — MODELSCOPE_API_KEY  (https://api-inference.modelscope.cn/v1)
  2. DashScope   — NAILS_TAG_LLM_API_KEY / OPENAI_API_KEY
  3. OpenRouter  — OPENROUTER_API_KEY

Both ModelScope and DashScope expose OpenAI-compatible `/v1/chat/completions`.
Vision tagging uses a fallback chain (see vision_tag_configs): if one VL model
returns 429 (quota) or 400 (no provider), the next candidate is tried.
ModelScope VL chain: Qwen3-VL-8B(-Thinking) → Qwen3-VL-30B → ERNIE-4.5-VL-28B → Qwen3-VL-235B → InternVL3.5-241B → QVQ-72B
DashScope vision:    qwen-vl-max
OpenRouter vision:   qwen/qwen2.5-vl-72b-instruct:free
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(Path.home() / ".hermes" / ".env", override=False)


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


@dataclass(frozen=True)
class LLMEndpointConfig:
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


# ── Per-provider helpers ───────────────────────────────────────────────────────


def modelscope_config() -> LLMEndpointConfig:
    """ModelScope API-Inference (OpenAI-compatible, bearer auth)."""
    return LLMEndpointConfig(
        model=env_value("NAILS_MODELSCOPE_MODEL", default="Qwen/Qwen3-235B-A22B-Instruct-2507"),
        api_key=env_value("MODELSCOPE_API_KEY"),
        base_url=env_value(
            "NAILS_MODELSCOPE_BASE_URL",
            "MODELSCOPE_BASE_URL",
            default="https://api-inference.modelscope.cn/v1",
        ).rstrip("/"),
    )


def dashscope_config() -> LLMEndpointConfig:
    """DashScope (Alibaba Cloud) OpenAI-compatible endpoint."""
    return LLMEndpointConfig(
        model=env_value("NAILS_TAG_LLM_MODEL", default="qwen3-max"),
        api_key=env_value("NAILS_TAG_LLM_API_KEY", "OPENAI_API_KEY"),
        base_url=env_value(
            "NAILS_TAG_LLM_BASE_URL",
            "OPENAI_BASE_URL",
            default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).rstrip("/"),
    )


def openrouter_config() -> LLMEndpointConfig:
    """OpenRouter (multi-provider proxy, OpenAI-compatible)."""
    return LLMEndpointConfig(
        model=env_value(
            "NAILS_OPENROUTER_MODEL",
            default="anthropic/claude-sonnet-4-5",
        ),
        api_key=env_value("OPENROUTER_API_KEY"),
        base_url=env_value(
            "NAILS_OPENROUTER_BASE_URL",
            "OPENROUTER_BASE_URL",
            default="https://openrouter.ai/api/v1",
        ).rstrip("/"),
    )


# ── Composite config selectors ─────────────────────────────────────────────────


def tag_llm_config(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMEndpointConfig:
    """Text-only LLM for tag extraction.

    Explicit params > NAILS_TAG_LLM_* env vars > ModelScope > DashScope > OpenRouter.
    """
    # Explicit caller override
    if model or api_key or base_url:
        return LLMEndpointConfig(
            model=model or env_value("NAILS_TAG_LLM_MODEL"),
            api_key=api_key or env_value("NAILS_TAG_LLM_API_KEY", "OPENAI_API_KEY"),
            base_url=(base_url or env_value("NAILS_TAG_LLM_BASE_URL", "OPENAI_BASE_URL")).rstrip(
                "/"
            ),
        )

    # Env-configured dedicated tag endpoint (covers both ModelScope and DashScope
    # when NAILS_TAG_LLM_* vars are set — as done in .env)
    dedicated = LLMEndpointConfig(
        model=env_value("NAILS_TAG_LLM_MODEL"),
        api_key=env_value("NAILS_TAG_LLM_API_KEY"),
        base_url=env_value("NAILS_TAG_LLM_BASE_URL").rstrip("/"),
    )
    if dedicated.available:
        return dedicated

    # Provider auto-detect: ModelScope → DashScope → OpenRouter
    for cfg in (modelscope_config(), dashscope_config(), openrouter_config()):
        if cfg.available:
            return cfg

    return LLMEndpointConfig()


def vision_tag_config() -> LLMEndpointConfig:
    """First (preferred) vision LLM endpoint for image-based tag extraction.

    Backwards-compatible single-endpoint accessor. For the full fallback chain
    use vision_tag_configs().
    """
    chain = vision_tag_configs()
    return chain[0] if chain else LLMEndpointConfig()


# ModelScope VL models verified served via /v1/models + live image probe
# (2026-06-01), ordered fast/cheap → large/accurate. Used as the fallback chain
# when one model returns 429 (quota) or 400 (no provider). ModelScope's free
# daily quota is per-model, so a cross-vendor entry (Baidu ERNIE) gives a real
# fallback once the Qwen family is exhausted — not just another Qwen quota bucket.
_MODELSCOPE_VL_CHAIN = (
    "Qwen/Qwen3-VL-8B-Instruct",
    "Qwen/Qwen3-VL-8B-Thinking",
    "Qwen/Qwen3-VL-30B-A3B-Instruct",
    "PaddlePaddle/ERNIE-4.5-VL-28B-A3B-PT",
    "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "OpenGVLab/InternVL3_5-241B-A28B",
    "Qwen/QVQ-72B-Preview",
)


def vision_tag_configs() -> list[LLMEndpointConfig]:
    """Prioritized chain of vision LLM endpoints for tag extraction.

    The caller (VisionTagEnricher) tries each in order, advancing to the next
    on quota (429) / no-provider (400) errors until one succeeds.

    Order:
      1. NAILS_VISION_TAG_* explicit override (single endpoint, if set)
      2. ModelScope VL chain (5 verified models, fast → accurate)
      3. DashScope qwen-vl-max
      4. OpenRouter qwen2.5-vl-72b free
    """
    chain: list[LLMEndpointConfig] = []
    seen: set[tuple[str, str]] = set()

    def _add(cfg: LLMEndpointConfig) -> None:
        if not cfg.available:
            return
        key = (cfg.base_url, cfg.model)
        if key in seen:
            return
        seen.add(key)
        chain.append(cfg)

    # 1. Explicit dedicated override (if a model is pinned via env)
    _add(
        LLMEndpointConfig(
            model=env_value("NAILS_VISION_TAG_MODEL"),
            api_key=env_value("NAILS_VISION_TAG_API_KEY"),
            base_url=env_value("NAILS_VISION_TAG_BASE_URL").rstrip("/"),
        )
    )

    # 2. ModelScope VL chain — reuse the explicit key/base_url if provided so the
    #    chain works even when only NAILS_VISION_TAG_API_KEY is set.
    ms = modelscope_config()
    ms_key = env_value("NAILS_VISION_TAG_API_KEY") or ms.api_key
    ms_base = (
        env_value("NAILS_VISION_TAG_BASE_URL")
        or ms.base_url
        or "https://api-inference.modelscope.cn/v1"
    ).rstrip("/")
    if ms_key:
        for model in _MODELSCOPE_VL_CHAIN:
            _add(LLMEndpointConfig(model=model, api_key=ms_key, base_url=ms_base))

    # 3. DashScope vision — only when the configured endpoint is actually
    #    DashScope (qwen-vl-max is not served by ModelScope's inference API).
    ds = dashscope_config()
    if ds.api_key and "dashscope" in ds.base_url:
        _add(
            LLMEndpointConfig(
                model="qwen-vl-max",
                api_key=ds.api_key,
                base_url=ds.base_url,
            )
        )

    # 4. OpenRouter vision (free tier)
    router_key = env_value("OPENROUTER_API_KEY")
    if router_key:
        _add(
            LLMEndpointConfig(
                model="qwen/qwen2.5-vl-72b-instruct:free",
                api_key=router_key,
                base_url=env_value(
                    "NAILS_OPENROUTER_BASE_URL",
                    "OPENROUTER_BASE_URL",
                    default="https://openrouter.ai/api/v1",
                ).rstrip("/"),
            )
        )

    return chain


# ModelScope text models for agent reasoning, ordered primary → fallback.
# Per-model daily quotas are independent, so a different model id sidesteps a
# 429 on the primary. The configured NAILS_MODELSCOPE_MODEL is always tried first.
_MODELSCOPE_TEXT_CHAIN = (
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "Qwen/Qwen3-235B-A22B-Thinking-2507",
    "deepseek-ai/DeepSeek-V3.1",
    "Qwen/Qwen2.5-72B-Instruct",
    "ZhipuAI/GLM-4.5",
)


def agent_text_models() -> list[str]:
    """Ordered list of text model identifiers for the active backend.

    Used by the agent runner to fall back to an alternate model when the
    primary returns 429 (daily quota) or is otherwise unavailable.
    """
    ms = modelscope_config()
    models: list[str] = []
    if ms.api_key:
        # Configured model first, then the rest of the ModelScope chain.
        for m in (ms.model, *_MODELSCOPE_TEXT_CHAIN):
            if m and m not in models:
                models.append(m)
        return models
    router = openrouter_config()
    if router.api_key and router.model:
        models.append(router.model)
    return models


def anthropic_model() -> str:
    return env_value("NAILS_ANTHROPIC_MODEL", "NAILS_AGENT_MODEL")


def reviewer_model() -> str:
    return env_value("NAILS_REVIEWER_LLM_MODEL", "NAILS_ANTHROPIC_MODEL", "NAILS_AGENT_MODEL")


def hermes_model() -> str:
    return env_value("NAILS_HERMES_MODEL", "NAILS_OPENROUTER_MODEL", "NAILS_AGENT_MODEL")


def openrouter_referer() -> str:
    return env_value("NAILS_OPENROUTER_REFERER")
