"""
ReviewerGuardrail — two-layer review of CandidatePackage.

Layer 1 (rules, fast):
  - Keyword blacklist check
  - review_score threshold (< 0.3 → immediate reject)

Layer 2 (LLM, slow, optional):
  - Content consistency and risk assessment via Claude/OpenRouter
  - Falls back to rule-only verdict if API key absent

Outputs ReviewDecision(status, reason, suggestions, risk_flags).
Does NOT execute any action — HITL confirmation required before ActionExecutor fires.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from nails_agent.memory.event_log import EventLog
from nails_agent.models.schemas import CandidatePackage, ReviewDecision

logger = logging.getLogger(__name__)

AGENT_ID = "ReviewerGuardrail"

# Keywords that trigger automatic reject regardless of score
_BLACKLIST = frozenset(
    [
        "违规",
        "假货",
        "非法",
        "违法",
        "欺诈",
        "仿品",
        "刷单",
        "博彩",
        "色情",
        "赌博",
    ]
)

_SCORE_REJECT_THRESHOLD = 0.3
_SCORE_REVISE_THRESHOLD = 0.55


class ReviewerGuardrail:
    def __init__(self, event_log: Optional[EventLog] = None, db_path: Optional[Path] = None):
        self.event_log = event_log or EventLog(db_path=db_path)
        # Only use the LLM layer when an Anthropic key is present — the layer
        # calls anthropic.Anthropic() directly. OpenRouter is NOT routed here;
        # if only OPENROUTER_API_KEY is set the LLM layer is skipped and the
        # rule-based decision is returned as-is.
        self._has_llm = bool(os.environ.get("ANTHROPIC_API_KEY"))

    def review(self, pkg: CandidatePackage) -> ReviewDecision:
        """Run two-layer review and write ReviewEvent to EventLog."""
        decision = self._rule_review(pkg)

        # Only call LLM layer if rules passed (status != "reject") and key available
        if decision.status != "reject" and self._has_llm:
            try:
                decision = self._llm_review(pkg, preliminary=decision)
            except Exception as exc:
                logger.warning("LLM review failed, keeping rule-based decision: %s", exc)

        # Persist review decision
        review_status = "pending_human" if decision.status == "pass" else "rejected"
        self.event_log.update_candidate_review(pkg.trigger_id, decision, status=review_status)
        self.event_log.write(
            event_type="ReviewEvent",
            payload={
                "candidate_id": pkg.id,
                "decision": decision.model_dump(),
                "review_status": review_status,
            },
            trigger_id=pkg.trigger_id,
            agent_id=AGENT_ID,
        )
        logger.info(
            "ReviewerGuardrail: trigger=%s status=%s review_status=%s",
            pkg.trigger_id,
            decision.status,
            review_status,
        )
        return decision

    # ── Layer 1: Rule-based (always runs) ─────────────────────────────────────

    def _rule_review(self, pkg: CandidatePackage) -> ReviewDecision:
        risk_flags: list[str] = []
        suggestions: list[str] = []

        # Blacklist scan
        full_text = f"{pkg.trend_summary} {pkg.strategy}".lower()
        hits = [kw for kw in _BLACKLIST if kw in full_text]
        if hits:
            risk_flags.append(f"敏感词：{', '.join(hits)}")

        # Score gate
        if pkg.review_score < _SCORE_REJECT_THRESHOLD:
            risk_flags.append(
                f"review_score {pkg.review_score:.2f} 低于拒绝阈值 {_SCORE_REJECT_THRESHOLD}"
            )

        if risk_flags:
            return ReviewDecision(
                status="reject",
                reason=f"规则层拒绝：{'; '.join(risk_flags)}",
                suggestions=["重新采集数据后再触发"]
                if pkg.review_score < _SCORE_REJECT_THRESHOLD
                else ["移除违规内容后重试"],
                risk_flags=risk_flags,
            )

        # Soft check: revise if score is borderline
        if pkg.review_score < _SCORE_REVISE_THRESHOLD:
            suggestions.append(
                f"review_score {pkg.review_score:.2f} 偏低，建议补充更多趋势信号后重试"
            )
            return ReviewDecision(
                status="revise",
                reason=f"内容质量待提升（score={pkg.review_score:.2f}，未达 pass 阈值 {_SCORE_REVISE_THRESHOLD}）",
                suggestions=suggestions,
                risk_flags=[],
            )

        # Pass
        if len(pkg.trend_summary) < 10:
            suggestions.append("趋势摘要较短，可扩充关键词后重新分析")
        if not pkg.assets:
            suggestions.append("素材资产为空，建议配图后发布")

        return ReviewDecision(
            status="pass",
            reason=f"规则层通过（score={pkg.review_score:.2f}），等待人工确认",
            suggestions=suggestions,
            risk_flags=[],
        )

    # ── Layer 2: LLM-based (optional) ─────────────────────────────────────────

    def _llm_review(self, pkg: CandidatePackage, preliminary: ReviewDecision) -> ReviewDecision:
        """
        Ask the LLM to check internal consistency and brand safety.
        Falls back to preliminary decision if LLM call fails.
        """
        import anthropic

        client = anthropic.Anthropic()
        prompt = (
            f"你是美甲品牌运营审查员。请审查以下运营方案，判断是否通过、需修改或拒绝发布。\n\n"
            f"## 趋势摘要\n{pkg.trend_summary}\n\n"
            f"## 运营策略\n{pkg.strategy}\n\n"
            f"## 素材数量\n{len(pkg.assets)} 张\n\n"
            f"## 预审结论\n{preliminary.status} — {preliminary.reason}\n\n"
            f"请返回 JSON，格式：\n"
            '{"status": "pass|revise|reject", "reason": "...", '
            '"suggestions": ["..."], "risk_flags": ["..."]}'
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        import json

        raw = msg.content[0].text.strip()
        # Strip markdown fences (```json ... ``` or ``` ... ```)
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]  # content between first pair of fences
            if raw.startswith("json"):
                raw = raw[4:]  # remove literal "json" prefix
            raw = raw.strip()
        data = json.loads(raw)
        return ReviewDecision(
            status=data.get("status", preliminary.status),
            reason=data.get("reason", preliminary.reason),
            suggestions=data.get("suggestions", preliminary.suggestions),
            risk_flags=data.get("risk_flags", preliminary.risk_flags),
        )
