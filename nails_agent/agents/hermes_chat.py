"""
HermesNailsAgent — conversational interface for the nail platform.

Now powered by openai-agents SDK with NailsOrchestrator.
Hermes-agent (NousResearch) can optionally be used as an outer wrapper
for persistent memory and web search, but the core domain logic always
runs through NailsOrchestrator with specialized handoffs.

Usage (standalone CLI):
    uv run python -m nails_agent.agents.hermes_chat

Usage (integrated):
    from nails_agent.agents.hermes_chat import HermesNailsAgent
    agent = HermesNailsAgent()
    reply = agent.chat("找最新猫眼美甲趋势")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


class HermesNailsAgent:
    """
    User-facing chat agent. Two layers:
    1. openai-agents NailsOrchestrator (always available if API key set)
    2. hermes-agent outer wrapper (optional, adds web search + memory)
    """

    def __init__(
        self,
        use_hermes_wrapper: bool = False,
        quiet_mode: bool = True,
    ):
        self._history: List = []
        self._use_hermes = use_hermes_wrapper
        self._quiet = quiet_mode

    def chat(
        self,
        message: str,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        from nails_agent.agents.agent_config import is_available

        if not is_available():
            return "❌ 未配置 API key（MODELSCOPE_API_KEY 或 OPENROUTER_API_KEY），无法启动 Agent。"

        if self._use_hermes:
            return self._chat_hermes(message, progress_cb)
        return self._chat_orchestrator(message, progress_cb)

    def _chat_orchestrator(self, message: str, progress_cb) -> str:
        """Run via openai-agents NailsOrchestrator."""
        try:
            from agents import Runner
            from nails_agent.agents.nail_agents import get_orchestrator_agent

            agent = get_orchestrator_agent()

            async def _run():
                result = await Runner.run(
                    agent,
                    message,
                    max_turns=30,
                )
                return result.final_output

            output = asyncio.get_event_loop().run_until_complete(_run())
            return str(output) if output else "（无响应）"
        except Exception as exc:
            logger.exception("Orchestrator error: %s", exc)
            return f"❌ Agent 错误：{exc}"

    def _chat_hermes(self, message: str, progress_cb) -> str:
        """Outer Hermes wrapper (optional). Falls back to orchestrator."""
        try:
            from run_agent import AIAgent  # hermes-agent

            hermes = AIAgent(
                model="anthropic/claude-sonnet-4-5",
                quiet_mode=self._quiet,
                skip_context_files=True,
                skip_memory=False,
                enabled_toolsets=["web"],
                max_iterations=10,
            )
            result = hermes.run_conversation(
                user_message=message,
                conversation_history=self._history or None,
            )
            self._history = result["messages"]
            return result["final_response"]
        except ImportError:
            return self._chat_orchestrator(message, progress_cb)
        except Exception as exc:
            logger.warning("Hermes wrapper error, falling back: %s", exc)
            return self._chat_orchestrator(message, progress_cb)

    def stream_chat(self, message: str):
        """
        Async generator yielding (event_type, content) tuples.
        event_type: 'text' | 'tool' | 'done'
        """
        from nails_agent.agents.agent_config import is_available

        if not is_available():
            yield ("text", "❌ 未配置 API key")
            yield ("done", "")
            return

        async def _astream():
            from agents import Runner
            from nails_agent.agents.nail_agents import get_orchestrator_agent

            agent = get_orchestrator_agent()
            async with Runner.run_streamed(agent, message, max_turns=30) as stream:
                async for event in stream.stream_events():
                    if hasattr(event, "type"):
                        if event.type == "run_item_stream_event":
                            item = event.item
                            if hasattr(item, "raw_item"):
                                ri = item.raw_item
                                # Tool call
                                name = getattr(ri, "name", "")
                                if name:
                                    yield ("tool", f"🔧 {name}(…)")
                        elif event.type == "raw_responses_stream_event":
                            delta = getattr(event.data, "delta", None)
                            if delta and hasattr(delta, "content"):
                                for c in delta.content:
                                    if hasattr(c, "text"):
                                        yield ("text", c.text)
            yield ("done", str(stream.final_output or ""))

        # Drive the async generator synchronously
        loop = asyncio.get_event_loop()
        agen = _astream()
        try:
            while True:
                item = loop.run_until_complete(agen.__anext__())
                yield item
        except StopAsyncIteration:
            pass

    def reset(self) -> None:
        self._history = []


def main():
    """CLI REPL for testing."""
    agent = HermesNailsAgent(quiet_mode=False)
    print("🌸 美甲 AI 助手 (openai-agents powered) — 输入 quit 退出\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            break
        reply = agent.chat(user_input, progress_cb=lambda m: print(f"  [agent] {m}"))
        print(f"\nAssistant: {reply}\n")


if __name__ == "__main__":
    main()
