"""
TriggerGateway — validates and standardises pipeline trigger events.

Responsibilities:
- Accept input from POST /api/v1/trigger (manual, scheduled, or signal-driven)
- Normalise to TriggerEvent with a stable trigger_id
- Write TriggerEvent to EventLog (first record in every pipeline chain)
- Return TriggerEvent for the Orchestrator to consume

Does NOT perform trend analysis or data collection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from nails_agent.memory.event_log import EventLog
from nails_agent.models.schemas import TriggerEvent

AGENT_ID = "TriggerGateway"


class TriggerGateway:
    def __init__(
        self,
        event_log: Optional[EventLog] = None,
        db_path: Optional[Path] = None,
    ):
        self._event_log = event_log or EventLog(db_path=db_path)

    def fire(
        self,
        source: str,
        keywords: Optional[List[str]] = None,
        goal: Optional[str] = None,
        shop_data: Optional[Dict[str, Any]] = None,
    ) -> TriggerEvent:
        event = TriggerEvent(
            source=source,
            keywords=keywords or [],
            goal=goal,
            shop_data=shop_data or {},
        )
        self._event_log.write(
            event_type="TriggerEvent",
            payload=event.model_dump(),
            trigger_id=event.trigger_id,
            agent_id=AGENT_ID,
        )
        return event
