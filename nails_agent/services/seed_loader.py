"""
One-shot CLI that loads seed JSON files under `data/` into the SQLite
MemoryStore. Idempotent — re-running overwrites existing rows.

Usage:
    python -m nails_agent.services.seed_loader
    python -m nails_agent.services.seed_loader --data-dir /path/to/data
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from nails_agent.memory.store import MemoryStore


_DEFAULT_DATA_DIR = Path(
    os.environ.get(
        "NAILS_DATA_DIR_V2",
        str(Path(__file__).resolve().parents[2] / "data"),
    )
)


def _load_json(path: Path) -> Any:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else []


def _seed_table(
    rows: list[dict[str, Any]],
    put: Callable[[dict[str, Any]], None],
    label: str,
) -> int:
    for row in rows:
        put(row)
    return len(rows)


def seed(data_dir: Path | None = None, store: MemoryStore | None = None) -> dict[str, int]:
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    store = store or MemoryStore()

    counts: dict[str, int] = {}

    styles = _load_json(data_dir / "nail_styles_v2.json")
    counts["nail_styles_v2"] = _seed_table(styles, store.put_style, "styles")

    refs = _load_json(data_dir / "reference_hand_profiles.json")
    counts["reference_hand_profiles"] = _seed_table(
        refs, store.put_reference_hand, "reference_hand_profiles"
    )

    features = _load_json(data_dir / "nail_visual_features.json")
    counts["nail_visual_features"] = _seed_table(
        features, store.put_visual_feature, "nail_visual_features"
    )

    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=_DEFAULT_DATA_DIR)
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()

    store = MemoryStore(db_path=args.db_path) if args.db_path else MemoryStore()
    counts = seed(args.data_dir, store=store)
    print(f"Seeded SQLite store at {store.db_path}")
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
