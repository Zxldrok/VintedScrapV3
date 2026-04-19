from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Listing:
    id: str
    title: str
    price: float
    currency: str = "EUR"
    brand: str = ""
    condition: str = ""
    seller: str = ""
    url: str = ""


@dataclass(slots=True)
class UserEvent:
    event_type: str
    listing: Listing | None = None
    terms: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserProfile:
    search_count: int = 0
    open_count: int = 0
    favorite_count: int = 0
    target_count: int = 0
    preferred_brands: dict[str, int] = field(default_factory=dict)
    preferred_conditions: dict[str, int] = field(default_factory=dict)
    preferred_sellers: dict[str, int] = field(default_factory=dict)
    preferred_terms: dict[str, int] = field(default_factory=dict)
    price_history: list[float] = field(default_factory=list)

    @property
    def average_price(self) -> float | None:
        valid_prices = [price for price in self.price_history if price > 0]
        if not valid_prices:
            return None
        return round(sum(valid_prices) / len(valid_prices), 2)


@dataclass(slots=True)
class Recommendation:
    score: int
    label: str
    reasons: list[str]

    @property
    def explanation(self) -> str:
        if not self.reasons:
            return self.label
        return f"{self.label} · {', '.join(self.reasons[:2])}"
