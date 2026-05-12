"""
Hermes-Agent powered conversational interface.

Uses the NousResearch hermes-agent SDK as the outer shell for user conversations.
Hermes provides: web search, persistent memory, trajectory saving, multi-model support.

Our domain tools (trend scout, campaign, try-on) are registered as Hermes "skills"
or called directly from within the conversation via Python tool calls.

Usage (standalone CLI):
    python -m nails_agent.agents.hermes_chat

Usage (integrated into chat_runner):
    from nails_agent.agents.hermes_chat import HermesNailsAgent
    agent = HermesNailsAgent()
    reply = agent.chat("找最新猫眼美甲趋势")
"""
from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_HERMES_SYSTEM = """\
你是「美甲 AI 助手」，服务于美甲品牌运营团队。你的能力：

1. **趋势侦察** — 实时搜索小红书/抖音/Instagram，发现热门美甲风格
2. **运营策略** — 为热门款式生成完整运营策略（定价/排期/多平台文案）
3. **AI 试戴** — 帮助用户预览美甲上手效果（上传手部图片）
4. **数据查询** — 查看历史分析报告、款式库存

操作方式：
- 需要实时趋势数据时，调用 trend_scout 分析工具
- 需要生成运营内容时，调用 campaign_agent
- 回答要简洁，数字和事实优先，不用"AI智能"、"赋能"等词

当前平台背景：小红书+抖音+Instagram 三平台同步运营，核心用户群体 18-35岁女性。
"""


class HermesNailsAgent:
    """
    Wraps hermes-agent AIAgent for the nails platform.
    Falls back to direct Anthropic if hermes-agent is not installed.
    """

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4-5",
        quiet_mode: bool = True,
        save_trajectories: bool = False,
    ):
        self._model = model
        self._quiet = quiet_mode
        self._save_traj = save_trajectories
        self._agent = None
        self._history = []
        self._init_agent()

    def _init_agent(self) -> None:
        try:
            from run_agent import AIAgent  # hermes-agent package
            self._agent = AIAgent(
                model=self._model,
                quiet_mode=self._quiet,
                save_trajectories=self._save_traj,
                ephemeral_system_prompt=_HERMES_SYSTEM,
                skip_context_files=True,
                max_iterations=30,
                enabled_toolsets=["web", "browser"],
            )
            logger.info("Hermes AIAgent initialised (model=%s)", self._model)
        except ImportError:
            logger.info("hermes-agent not installed — using Anthropic direct mode")
            self._agent = None

    def chat(
        self,
        message: str,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Send a message and return the response text.
        Automatically routes domain requests to our specialized agents.
        """
        # Check if this is a domain request we should handle directly
        routed = self._try_route_domain(message, progress_cb)
        if routed is not None:
            return routed

        if self._agent is not None:
            # Use Hermes for general conversation
            result = self._agent.run_conversation(
                user_message=message,
                system_message=_HERMES_SYSTEM,
                conversation_history=self._history or None,
            )
            self._history = result["messages"]
            return result["final_response"]
        else:
            # Pure fallback: direct Anthropic
            return self._anthropic_fallback(message)

    def _try_route_domain(
        self,
        message: str,
        progress_cb: Optional[Callable],
    ) -> Optional[str]:
        """
        Route recognised domain intents to specialized agents.
        Returns response string, or None if not a domain request.
        """
        msg_lower = message.lower()

        # Trend analysis intent
        trend_keywords = ["趋势", "热门", "流行", "搜索美甲", "分析趋势", "trend", "scout"]
        if any(k in msg_lower for k in trend_keywords):
            return self._handle_trend_request(message, progress_cb)

        # Campaign / strategy intent
        campaign_keywords = ["运营策略", "文案", "排期", "定价", "生成卡片", "campaign", "strategy"]
        if any(k in msg_lower for k in campaign_keywords):
            return self._handle_campaign_request(message, progress_cb)

        # Try-on intent
        tryon_keywords = ["试戴", "效果", "上手", "试色", "tryon", "try-on"]
        if any(k in msg_lower for k in tryon_keywords):
            return "💅 请上传您的手部照片，选择想试的款式，AI 将为您生成上手效果图。（在 Demo 页面的「AI 试戴」标签中操作）"

        return None  # Not a domain request — let Hermes handle it

    def _handle_trend_request(
        self,
        message: str,
        progress_cb: Optional[Callable],
    ) -> str:
        if progress_cb:
            progress_cb("🔍 TrendScoutAgent 启动，搜索社媒趋势…")
        try:
            from nails_agent.agents.trend_agent import run_trend_scout
            result = run_trend_scout(progress_cb=progress_cb)
            lines = ["📊 **趋势分析结果**\n"]
            if result.style_trends:
                lines.append("| 风格 | 帖数 | 互动量 | 热度 |")
                lines.append("|------|-----:|---------:|-----:|")
                for st in result.style_trends[:6]:
                    lines.append(
                        f"| {st.tag} | {st.post_count} | {st.total_engagement:,} | {st.aggregated_score:.0f} |"
                    )
            if result.patterns:
                lines.append("\n**观察到的规律**")
                for p in result.patterns[:3]:
                    lines.append(f"- {p}")
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ 趋势分析失败：{exc}"

    def _handle_campaign_request(
        self,
        message: str,
        progress_cb: Optional[Callable],
    ) -> str:
        if progress_cb:
            progress_cb("🤖 CampaignAgent 启动，生成运营内容…")
        try:
            from nails_agent.agents.trend_agent import run_trend_scout
            from nails_agent.agents.campaign_agent import run_campaign_agent
            trend = run_trend_scout(progress_cb=progress_cb)
            campaign = run_campaign_agent(trend, max_cards=4, progress_cb=progress_cb)
            lines = [f"🎯 **运营策略** — 共 {len(campaign.style_cards)} 款\n"]
            if campaign.executive_summary:
                lines.append(f"> {campaign.executive_summary}\n")
            for card in campaign.style_cards[:3]:
                xhs = card.platform_variants.get("xiaohongshu")
                lines.append(f"### {card.style_name}")
                lines.append(f"定价 {card.pricing.base_price if card.pricing else '待定'} · 优先级 {card.schedule.priority if card.schedule else 'P1'}")
                if xhs:
                    lines.append(f"**小红书文案**：{xhs.caption[:120]}…")
                lines.append("")
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ 运营策略生成失败：{exc}"

    def _anthropic_fallback(self, message: str) -> str:
        """Minimal Anthropic SDK fallback when hermes-agent is not installed."""
        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=os.environ.get("NAILS_AGENT_MODEL", "claude-sonnet-4-5"),
                max_tokens=1024,
                system=_HERMES_SYSTEM,
                messages=[{"role": "user", "content": message}],
            )
            return response.content[0].text
        except Exception as exc:
            return f"❌ 对话失败：{exc}"

    def reset(self) -> None:
        """Clear conversation history."""
        self._history = []


def main():
    """CLI entry point for testing the Hermes chat agent."""
    import readline  # noqa: F401 — enables arrow-key history in REPL
    agent = HermesNailsAgent(quiet_mode=False, save_trajectories=True)
    print("🌸 美甲 AI 助手 (Hermes-powered) — 输入 quit 退出\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break
        reply = agent.chat(user_input, progress_cb=lambda m: print(f"  [agent] {m}"))
        print(f"\nAssistant: {reply}\n")


if __name__ == "__main__":
    main()
