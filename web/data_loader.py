import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"

# Pipeline persistence wraps lists as {wrapper_key: [...], timestamp: ...}.
# Mock seeds are flat lists. We unwrap on load so the UI sees one schema.
_UNWRAP_KEYS = {
    "metric_snapshots.json": "snapshots",
    "style_cards.json": "style_cards",
}


def _load(filename: str):
    """Prefer pipeline output (real data) over seed data (mock).

    Falls back to mock/seed data if the output file is empty (0 items) —
    this keeps the UI populated when the pipeline ran but produced no signals
    (e.g. XHS session expired during collection).
    """
    out = OUTPUT_DIR / filename
    seed = DATA_DIR / filename

    def _parse(path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        # Auto-unwrap pipeline outputs to match mock schema
        if isinstance(data, dict):
            wrapper = _UNWRAP_KEYS.get(filename)
            if wrapper and wrapper in data:
                data = data[wrapper]
        return data

    if out.exists():
        data = _parse(out)
        # If output is empty, fall back to seed/mock so the UI isn't blank
        empty = (isinstance(data, list) and len(data) == 0) or (isinstance(data, dict) and not data)
        if not empty:
            return data
        if seed.exists():
            return _parse(seed)
        return data  # empty but seed also missing

    if seed.exists():
        return _parse(seed)
    return []


def load_trend_signals():
    return _load("trend_signals.json")


def load_style_library():
    return _load("style_library.json")


def load_metric_snapshots():
    return _load("metric_snapshots.json")


def load_module_outputs():
    return _load("module_outputs.json")


def load_action_executions():
    return _load("action_executions.json")


def load_style_cards():
    return _load("style_cards.json")


def load_user_profile():
    return _load("user_profile.json")


def load_event_log():
    return _load("event_log.json")
