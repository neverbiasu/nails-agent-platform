"""
EventStore — single source of truth for the chat UI state.

Streamlit reruns the entire script on every interaction, so the ChatRunner
cannot hold Python state between calls. Everything that needs to survive
a rerun lives in st.session_state under one well-known key.

Convention: only the runner *appends* events; only the UI *reads* them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from nails_agent.agents.chat_events import ChatEvent, Phase


_STORE_KEY = "_chat_event_store"


def _default_state() -> Dict[str, Any]:
    return {
        "events": [],                # List[ChatEvent]    — replay source
        "phase": "idle",             # Phase              — current state machine position
        "pending_choice": None,      # dict | None        — UI click → runner input
        "pending_interrupt": False,  # bool               — graceful interrupt flag
        "context": {},               # dict               — runner scratch (signals, etc.)
        "start_time": None,          # float | None       — epoch for elapsed_ms
        # User toggles
        "auto_mode": False,
        "dev_mode": False,
    }


def init(session_state) -> Dict[str, Any]:
    """Initialise (or fetch) the chat store on session_state. Idempotent."""
    if _STORE_KEY not in session_state:
        session_state[_STORE_KEY] = _default_state()
    return session_state[_STORE_KEY]


def get(session_state) -> Dict[str, Any]:
    return session_state[_STORE_KEY]


def reset(session_state) -> None:
    """Wipe the chat to start a fresh session. Keep toggles."""
    auto = session_state[_STORE_KEY].get("auto_mode", False)
    dev = session_state[_STORE_KEY].get("dev_mode", False)
    session_state[_STORE_KEY] = _default_state()
    session_state[_STORE_KEY]["auto_mode"] = auto
    session_state[_STORE_KEY]["dev_mode"] = dev


def append_events(store: Dict[str, Any], events: List[ChatEvent]) -> None:
    """Append-only — events are immutable history."""
    store["events"].extend(events)
    # Track phase off the latest phase_enter event
    for e in events:
        if e.type == "phase_enter":
            store["phase"] = e.payload.phase


def replay(store: Dict[str, Any]) -> List[ChatEvent]:
    """Read the full event log for UI rendering."""
    return store["events"]


def queue_choice(store: Dict[str, Any], checkpoint_id: Phase,
                 choice_id: str, form: Optional[dict] = None) -> None:
    store["pending_choice"] = {
        "checkpoint_id": checkpoint_id,
        "choice_id": choice_id,
        "form": form or {},
    }


def take_choice(store: Dict[str, Any]) -> Optional[dict]:
    """Consume the pending choice (one-shot). UI calls this and re-renders."""
    pc = store["pending_choice"]
    store["pending_choice"] = None
    return pc


def request_interrupt(store: Dict[str, Any]) -> None:
    """Mark for graceful interrupt — runner checks between tool calls."""
    store["pending_interrupt"] = True


def consume_interrupt(store: Dict[str, Any]) -> bool:
    """Runner calls this in tight loops; returns True once if interrupt set."""
    if store["pending_interrupt"]:
        store["pending_interrupt"] = False
        return True
    return False


def latest_checkpoint(store: Dict[str, Any]) -> Optional[ChatEvent]:
    """Most-recent checkpoint event still 'open' (no subsequent phase_enter)."""
    last_cp: Optional[ChatEvent] = None
    for e in store["events"]:
        if e.type == "checkpoint":
            last_cp = e
        elif e.type == "phase_enter":
            # New phase invalidates the previous checkpoint visually,
            # but keep history. UI uses this only to decide what to highlight.
            last_cp = None if last_cp and e.payload.phase != last_cp.payload.phase else last_cp
    return last_cp
