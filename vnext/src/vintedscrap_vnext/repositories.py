from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import Listing, UserEvent


class JsonEventRepository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[UserEvent]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

        events: list[UserEvent] = []
        for item in raw:
            listing_data = item.get("listing")
            listing = Listing(**listing_data) if isinstance(listing_data, dict) else None
            events.append(
                UserEvent(
                    event_type=item.get("event_type", ""),
                    listing=listing,
                    terms=item.get("terms", []),
                    filters=item.get("filters", {}),
                )
            )
        return events

    def save(self, events: list[UserEvent]) -> None:
        payload = []
        for event in events:
            item = asdict(event)
            payload.append(item)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
