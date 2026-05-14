"""
Shared model client configuration for openai-agents SDK.

Priority: ANTHROPIC_API_KEY → MODELSCOPE_API_KEY → OPENROUTER_API_KEY

The openai-agents SDK is built on the OpenAI client, so Anthropic is reached
via OpenRouter's Claude proxy or a Responses-API-compatible proxy.
ModelScope and OpenRouter both expose OpenAI-compatible endpoints.
"""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv

# Load env files once at import
load_dotenv(Path(__file__).parent.parent.parent / ".env")
load_dotenv(Path.home() / ".hermes" / ".env", override=False)

# ── ModelScope constants ──────────────────────────────────────────────────────

MODELSCOPE_BASE_URL = os.environ.get(
    "MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1"
)
MODELSCOPE_MODEL = os.environ.get("NAILS_MODELSCOPE_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507")

# ── OpenRouter constants ──────────────────────────────────────────────────────

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.environ.get("NAILS_OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5")


def get_model_string() -> str:
    """Return the model identifier for the active backend."""
    if os.environ.get("MODELSCOPE_API_KEY"):
        return MODELSCOPE_MODEL
    if os.environ.get("OPENROUTER_API_KEY"):
        return OPENROUTER_MODEL
    return MODELSCOPE_MODEL  # default; will fail gracefully if no key


@lru_cache(maxsize=1)
def get_openai_client():
    """
    Return a cached AsyncOpenAI client pointed at the available backend.
    Cached so all agents share one HTTP connection pool.
    """
    from agents import AsyncOpenAI

    ms_key = os.environ.get("MODELSCOPE_API_KEY")
    or_key = os.environ.get("OPENROUTER_API_KEY")

    if ms_key:
        return AsyncOpenAI(api_key=ms_key, base_url=MODELSCOPE_BASE_URL)
    if or_key:
        return AsyncOpenAI(
            api_key=or_key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={"HTTP-Referer": "https://github.com/neverbiasu/nails-agent-platform"},
        )
    # No key — return a dummy client (agents will error gracefully)
    return AsyncOpenAI(api_key="no-key", base_url=MODELSCOPE_BASE_URL)


def make_model():
    """Return an OpenAIChatCompletionsModel for the active backend."""
    from agents import OpenAIChatCompletionsModel

    return OpenAIChatCompletionsModel(
        model=get_model_string(),
        openai_client=get_openai_client(),
    )


def is_available() -> bool:
    return bool(os.environ.get("MODELSCOPE_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
