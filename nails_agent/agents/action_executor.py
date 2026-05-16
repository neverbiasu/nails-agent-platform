"""
ActionExecutor — executes approved CandidatePackage after HITL confirmation.

MVP implementations:
  1. XHS draft creation via Go service (localhost:18060)
  2. OpenClaw webhook stub (HTTP POST, mock payload)

MUST NOT self-trigger — caller is responsible for HITL gate.
Writes ActionEvent to EventLog on completion.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from nails_agent.memory.event_log import EventLog
from nails_agent.models.schemas import ActionEvent, CandidatePackage

logger = logging.getLogger(__name__)

AGENT_ID = "ActionExecutor"

_XHS_GO_BASE = os.environ.get("XHS_GO_BASE_URL", "http://localhost:18060")
_OPENCLAW_WEBHOOK = os.environ.get("OPENCLAW_WEBHOOK_URL", "")
_HTTP_TIMEOUT = 10.0


class ActionExecutor:
    def __init__(self, event_log: Optional[EventLog] = None, db_path: Optional[Path] = None):
        self.event_log = event_log or EventLog(db_path=db_path)

    def publish(self, pkg: CandidatePackage, platform: str) -> ActionEvent:
        """
        Execute publication for the given platform.
        platform: "xhs" | "openclaw"
        """
        if platform == "xhs":
            return self._publish_xhs(pkg)
        elif platform == "openclaw":
            return self._publish_openclaw(pkg)
        else:
            raise ValueError(f"Unsupported platform: {platform}")

    # ── XHS: create draft via Go service ──────────────────────────────────────

    def _publish_xhs(self, pkg: CandidatePackage) -> ActionEvent:
        title = pkg.trend_summary[:50]
        content = f"{pkg.trend_summary}\n\n{pkg.strategy}"

        payload = {
            "title": title,
            "content": content,
            "images": pkg.assets[:9],  # XHS max 9 images
        }

        try:
            resp = httpx.post(
                f"{_XHS_GO_BASE}/api/v1/drafts/create",
                json=payload,
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            result_url = data.get("draft_url") or data.get("url") or ""
            status = "success"
        except httpx.ConnectError:
            logger.warning("XHS Go service unavailable, recording as pending")
            result_url = ""
            status = "pending"
        except Exception as exc:
            logger.error("XHS publish error: %s", exc)
            result_url = ""
            status = "failed"

        return self._record(pkg, platform="xhs", status=status, result_url=result_url)

    # ── OpenClaw: webhook stub ─────────────────────────────────────────────────

    def _publish_openclaw(self, pkg: CandidatePackage) -> ActionEvent:
        webhook_url = _OPENCLAW_WEBHOOK
        if not webhook_url:
            # No URL configured — record as stub/pending
            logger.info("OpenClaw webhook not configured, recording as stub")
            return self._record(pkg, platform="openclaw", status="pending", result_url="")

        payload = {
            "trigger_id": pkg.trigger_id,
            "message": f"【美甲趋势播报】{pkg.trend_summary[:100]}",
            "strategy": pkg.strategy[:200],
            "source": "nails-agent-platform",
        }
        try:
            resp = httpx.post(webhook_url, json=payload, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            status = "success"
            result_url = webhook_url
        except Exception as exc:
            logger.error("OpenClaw webhook error: %s", exc)
            status = "failed"
            result_url = ""

        return self._record(pkg, platform="openclaw", status=status, result_url=result_url)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _record(
        self,
        pkg: CandidatePackage,
        platform: str,
        status: str,
        result_url: str,
    ) -> ActionEvent:
        event = ActionEvent(
            trigger_id=pkg.trigger_id,
            platform=platform,
            status=status,
            result_url=result_url or None,
        )
        self.event_log.write(
            event_type="ActionEvent",
            payload=event.model_dump(),
            trigger_id=pkg.trigger_id,
            agent_id=AGENT_ID,
        )
        return event
