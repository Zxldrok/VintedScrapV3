from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppPaths:
    root: Path
    data_dir: Path
    events_file: Path


def build_paths(root: Path | None = None) -> AppPaths:
    base = (root or Path(__file__).resolve().parents[3]).resolve()
    data_dir = base / "runtime_data"
    return AppPaths(
        root=base,
        data_dir=data_dir,
        events_file=data_dir / "user_events.json",
    )
