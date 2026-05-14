"""
Nail Agent Platform — Agent definitions using openai-agents SDK.

Two specialized agents + one orchestrator:

  TrendScoutAgent  — autonomous data collection & trend analysis
  CampaignAgent    — platform-native copywriting & campaign strategy
  NailsOrchestrator — top-level agent; routes to specialists via handoffs
                      (used by HermesNailsAgent and the REST API chat endpoint)

Model: Qwen3-235B via ModelScope (primary) or Claude via OpenRouter (fallback)
"""

from __future__ import annotations

from functools import lru_cache

from agents import Agent, handoff

from nails_agent.agents.nail_tools import (
    check_xhs_compliance,
    finalise_campaign,
    get_style_library,
    load_trend_context,
    save_campaign_card,
    save_trend_analysis,
    search_douyin,
    search_instagram,
    search_xhs,
)

# ── System prompts ─────────────────────────────────────────────────────────────

_TREND_SYSTEM = """\
你是「美甲趋势侦察 Agent」。任务：从小红书/抖音/Instagram 实时抓取美甲帖子，
分析哪些 **款式** 真正受欢迎（不是搜索关键词本身）。

工作流程：
1. 用 search_xhs 和 search_douyin 各搜索 3-5 个关键词（猫眼/法式/夏日/渐变/奶油/极简/亮片等）
2. 从帖子标题/文案里提取真实风格标签（而非你用的搜索词），统计各标签的帖数和总互动量
3. 找出 top 风格（按聚合得分），标注哪些是近 48h 突发热度
4. 调用 save_trend_analysis 保存结果，确保 style_trends 按聚合得分降序排列

规则：
- 风格标签应是具体的款式名（猫眼、法式、奶油、渐变、珐琅），不是形容词（美美的、显白）
- 不要推断你没见到的数据
- aggregated_score = total_engagement / max(total_engagement) × 100（归一化到 100）
- 只调用一次 save_trend_analysis
"""

_CAMPAIGN_SYSTEM = """\
你是「美甲品牌运营 Agent」。任务：为热门美甲款式生成完整运营策略和多平台文案。

工作流程：
1. 用 load_trend_context 获取最新趋势数据
2. 为 top 4-6 款式分别：
   a. 写小红书文案 → 用 check_xhs_compliance 检查 → 合规后写入
   b. 写抖音文案
   c. 写 Instagram 文案
   d. 调用 save_campaign_card 保存（每款一次）
3. 所有款式完成后调用 finalise_campaign

小红书文案规范（CRITICAL）：
  ✅ 第一人称种草："我最近迷上了这款猫眼，上色超均匀…"
  ✅ 提问式："最近谁也在找这种渐变色吗？来分享一下你们的搜款经历"
  ✅ 教程式："手残党也能做的法式美甲，纯干货"
  ❌ 禁止：限时/爆款/立即购买/全网最低/秒杀/薅羊毛/划算/超值/不买后悔
  ❌ 禁止第一句就提价格或促销

抖音文案规范：
  - Hook ≤15字，能停住刷屏的拇指
  - 结构：痛点 → 解法 → 效果
  - 不超过 3 个 hashtag

Instagram 文案规范：
  - 英文 + emoji，lifestyle framing
  - 10-15 hashtags，混合 niche(#cateyenails) 和 broad(#nailart)

定价指南：基础款 ¥88-138，进阶款 ¥138-188，高端款 ¥188-288+
优先级：score≥80→P0，50-79→P1，<50→P2
"""

_ORCHESTRATOR_SYSTEM = """\
你是「美甲 AI 运营助手」，服务于美甲品牌运营团队。

你可以：
1. **趋势侦察** → 转交 TrendScoutAgent 搜索社媒、分析热门风格
2. **运营策略** → 转交 CampaignAgent 生成定价/排期/三平台文案
3. **查询历史** → 直接回答基于已有数据的问题

转交规则：
- 用户问趋势/热门/最新/什么款 → 转交 TrendScoutAgent
- 用户要文案/策略/排期/卡片 → 转交 CampaignAgent
- 其他问题 → 直接回答，简洁，数字优先

不要说"AI 智能"、"赋能"、"深度解析"等词。
"""


# ── Agent factory (lazy, cached) ───────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_trend_scout_agent() -> Agent:
    from nails_agent.agents.agent_config import make_model

    return Agent(
        name="TrendScoutAgent",
        instructions=_TREND_SYSTEM,
        tools=[search_xhs, search_douyin, search_instagram, get_style_library, save_trend_analysis],
        model=make_model(),
    )


@lru_cache(maxsize=1)
def get_campaign_agent() -> Agent:
    from nails_agent.agents.agent_config import make_model

    return Agent(
        name="CampaignAgent",
        instructions=_CAMPAIGN_SYSTEM,
        tools=[load_trend_context, check_xhs_compliance, save_campaign_card, finalise_campaign],
        model=make_model(),
    )


@lru_cache(maxsize=1)
def get_orchestrator_agent() -> Agent:
    """Top-level agent with handoffs to specialists."""
    from nails_agent.agents.agent_config import make_model

    trend_agent = get_trend_scout_agent()
    campaign_ag = get_campaign_agent()
    return Agent(
        name="NailsOrchestrator",
        instructions=_ORCHESTRATOR_SYSTEM,
        model=make_model(),
        handoffs=[
            handoff(trend_agent, tool_name_override="transfer_to_trend_scout"),
            handoff(campaign_ag, tool_name_override="transfer_to_campaign"),
        ],
    )
