import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def _load(filename: str):
    return json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))


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
