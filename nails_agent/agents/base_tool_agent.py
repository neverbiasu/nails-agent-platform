"""
Lightweight tool-use agent loop supporting two backends:
  • Anthropic SDK  (when ANTHROPIC_API_KEY is set)
  • OpenAI SDK → OpenRouter  (when OPENROUTER_API_KEY is set, no Anthropic key)

Both backends follow the same tool_use loop:
  user → assistant → [tool_use → tool_result] → … → end_turn

Usage:
    agent = ToolAgent(
        system_prompt="...",
        tools=[my_tool_def, ...],       # Anthropic tool schema format
        tool_functions={"my_tool": fn},
    )
    result = agent.run("user message", progress_cb=print)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

# Auto-load API keys: project .env first, then hermes .env as fallback
load_dotenv(Path(__file__).parent.parent.parent / ".env")
load_dotenv(Path.home() / ".hermes" / ".env", override=False)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get("NAILS_AGENT_MODEL", "claude-sonnet-4-5")
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_OPENROUTER_MODEL = os.environ.get("NAILS_OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5")


# ── Result ─────────────────────────────────────────────────────────────────────

class AgentResult:
    def __init__(
        self,
        text: str,
        tool_calls: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
        duration_s: float,
        error: Optional[str] = None,
    ):
        self.text = text
        self.tool_calls = tool_calls
        self.messages = messages
        self.duration_s = duration_s
        self.error = error

    @property
    def success(self) -> bool:
        return self.error is None


# ── Schema conversion ──────────────────────────────────────────────────────────

def _anthropic_to_openai_tools(tools: List[Dict]) -> List[Dict]:
    """Convert Anthropic tool schemas to OpenAI function-calling format."""
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return result


# ── Main agent class ───────────────────────────────────────────────────────────

class ToolAgent:
    """
    Backend-agnostic tool-use agent.
    Automatically selects Anthropic or OpenAI/OpenRouter based on available keys.
    Tool schemas use Anthropic format (input_schema); converted internally for OpenAI.
    """

    def __init__(
        self,
        system_prompt: str,
        tools: List[Dict[str, Any]],
        tool_functions: Dict[str, Callable],
        model: str = _DEFAULT_MODEL,
        max_iterations: int = 20,
        max_tokens: int = 4096,
        api_key: Optional[str] = None,
    ):
        self.system_prompt = system_prompt
        self.tools = tools
        self.tool_functions = tool_functions
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens

        anthropic_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")

        if anthropic_key:
            import anthropic as _ant
            self._backend = "anthropic"
            self.model = model
            self._client = _ant.Anthropic(api_key=anthropic_key)
        elif openrouter_key:
            import openai as _oai
            self._backend = "openai"
            self.model = _OPENROUTER_MODEL
            self._client = _oai.OpenAI(
                api_key=openrouter_key,
                base_url=_OPENROUTER_BASE,
            )
        else:
            # No key available — run will fail gracefully
            self._backend = "none"
            self.model = model
            self._client = None

    def run(
        self,
        user_message: str,
        progress_cb: Optional[Callable[[str], None]] = None,
        extra_context: Optional[str] = None,
    ) -> AgentResult:
        if self._client is None:
            return AgentResult(
                text="",
                tool_calls=[],
                messages=[],
                duration_s=0.0,
                error="No API key configured (ANTHROPIC_API_KEY or OPENROUTER_API_KEY)",
            )

        if extra_context:
            user_message = f"{extra_context}\n\n{user_message}"

        if self._backend == "anthropic":
            return self._run_anthropic(user_message, progress_cb)
        else:
            return self._run_openai(user_message, progress_cb)

    # ── Anthropic backend ──────────────────────────────────────────────────────

    def _run_anthropic(
        self,
        user_message: str,
        progress_cb: Optional[Callable],
    ) -> AgentResult:
        import anthropic as _ant
        t0 = time.time()
        messages: List[Dict] = [{"role": "user", "content": user_message}]
        all_tool_calls: List[Dict] = []
        final_text = ""

        for _ in range(self.max_iterations):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=self.system_prompt,
                    tools=self.tools,
                    messages=messages,
                )
            except _ant.APIError as e:
                return AgentResult("", all_tool_calls, messages,
                                   round(time.time() - t0, 1), str(e))

            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            if text_parts:
                final_text = "\n".join(text_parts)

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for tu in tool_uses:
                    result_content = self._call_tool(tu.name, tu.input, progress_cb)
                    all_tool_calls.append({"tool": tu.name, "input": tu.input})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": result_content,
                    })
                messages.append({"role": "user", "content": tool_results})
            else:
                break

        return AgentResult(final_text, all_tool_calls, messages,
                           round(time.time() - t0, 1))

    # ── OpenAI / OpenRouter backend ────────────────────────────────────────────

    def _run_openai(
        self,
        user_message: str,
        progress_cb: Optional[Callable],
    ) -> AgentResult:
        t0 = time.time()
        openai_tools = _anthropic_to_openai_tools(self.tools)
        messages: List[Dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]
        all_tool_calls: List[Dict] = []
        final_text = ""

        for _ in range(self.max_iterations):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    tools=openai_tools,
                    messages=messages,
                    tool_choice="auto",
                )
            except Exception as e:
                return AgentResult("", all_tool_calls, messages,
                                   round(time.time() - t0, 1), str(e))

            choice = response.choices[0]
            msg = choice.message

            if msg.content:
                final_text = msg.content

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                # Append assistant message with tool_calls
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                })

                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    result_content = self._call_tool(tc.function.name, args, progress_cb)
                    all_tool_calls.append({"tool": tc.function.name, "input": args})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
                    })
            else:
                break  # end_turn / stop

        return AgentResult(final_text, all_tool_calls, messages,
                           round(time.time() - t0, 1))

    # ── Shared tool dispatch ───────────────────────────────────────────────────

    def _call_tool(
        self,
        name: str,
        args: Dict[str, Any],
        progress_cb: Optional[Callable],
    ) -> str:
        fn = self.tool_functions.get(name)
        if fn is None:
            return json.dumps({"error": f"Tool '{name}' not found"})
        if progress_cb:
            progress_cb(f"🔧 {name}({_summarise_args(args)})")
        try:
            raw = fn(**args)
            return json.dumps(raw, ensure_ascii=False, default=str)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": str(exc)})


def _summarise_args(args: Dict[str, Any]) -> str:
    parts = []
    for k, v in list(args.items())[:3]:
        if isinstance(v, list):
            parts.append(f"{k}=[{len(v)} items]")
        elif isinstance(v, str) and len(v) > 40:
            parts.append(f"{k}={v[:37]}…")
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)
