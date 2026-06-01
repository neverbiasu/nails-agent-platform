"""
Shared model client configuration for openai-agents SDK.

Priority: ANTHROPIC_API_KEY → MODELSCOPE_API_KEY → OPENROUTER_API_KEY

The openai-agents SDK is built on the OpenAI client, so Anthropic is reached
via OpenRouter's Claude proxy or a Responses-API-compatible proxy.
ModelScope and OpenRouter both expose OpenAI-compatible endpoints.
"""

from __future__ import annotations

from functools import lru_cache

from nails_agent.services.llm_config import (
    modelscope_config,
    openrouter_config,
    openrouter_referer,
)

_DUMMY_BASE_URL = "http://localhost/v1"


def get_model_string() -> str:
    """Return the model identifier for the active backend."""
    ms = modelscope_config()
    if ms.api_key:
        return ms.model
    router = openrouter_config()
    if router.api_key:
        return router.model
    return ms.model or router.model


@lru_cache(maxsize=1)
def get_openai_client():
    """
    Return a cached AsyncOpenAI client pointed at the available backend.
    Cached so all agents share one HTTP connection pool.
    """
    from agents import AsyncOpenAI

    ms = modelscope_config()
    router = openrouter_config()

    if ms.api_key:
        return AsyncOpenAI(api_key=ms.api_key, base_url=ms.base_url or None)
    if router.api_key:
        headers = {}
        if referer := openrouter_referer():
            headers["HTTP-Referer"] = referer
        return AsyncOpenAI(
            api_key=router.api_key,
            base_url=router.base_url or None,
            default_headers=headers or None,
        )
    # No key — return a dummy client (agents will error gracefully)
    return AsyncOpenAI(api_key="no-key", base_url=_DUMMY_BASE_URL)


def make_model(model_string: str | None = None):
    """Return an OpenAIChatCompletionsModel for the active backend.

    *model_string* overrides the default model id (used by the fallback runner).
    """
    from agents import OpenAIChatCompletionsModel

    return OpenAIChatCompletionsModel(
        model=model_string or get_model_string(),
        openai_client=get_openai_client(),
    )


def is_available() -> bool:
    return bool(modelscope_config().api_key or openrouter_config().api_key)


def _is_quota_error(exc: Exception) -> bool:
    """True when *exc* looks like a quota / rate-limit / model-unavailable error."""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("429", "quota", "rate limit", "rate_limit", "no provider", "exceeded")
    )


async def run_streamed_with_fallback(agent, user_msg: str, progress_cb, max_turns: int):
    """Run an agent via Runner.run_streamed, falling back across text models.

    On a quota/rate-limit/no-provider error the agent's model is swapped to the
    next candidate from agent_text_models() and the run is retried. Returns the
    final_output of the first successful run, or re-raises the last error.
    """
    from agents import Runner

    from nails_agent.services.llm_config import agent_text_models

    models = agent_text_models() or [get_model_string()]
    last_exc: Exception | None = None

    for i, model_string in enumerate(models):
        if i > 0:
            if progress_cb:
                progress_cb(f"♻️ 配额受限，切换模型 → {model_string}")
            agent.model = make_model(model_string)
        try:
            stream = Runner.run_streamed(agent, user_msg, max_turns=max_turns)
            async for event in stream.stream_events():
                if hasattr(event, "type") and event.type == "run_item_stream_event":
                    item = event.item
                    if hasattr(item, "raw_item"):
                        ri = item.raw_item
                        name = getattr(ri, "name", "") if hasattr(ri, "name") else ""
                        if name and progress_cb:
                            progress_cb(f"🔧 {name}(…)")
            return stream.final_output
        except Exception as exc:  # noqa: BLE001 — inspect & decide retry
            last_exc = exc
            if _is_quota_error(exc) and i < len(models) - 1:
                continue
            raise

    if last_exc:
        raise last_exc
    return None
