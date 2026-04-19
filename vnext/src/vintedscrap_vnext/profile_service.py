from __future__ import annotations

import re
import unicodedata

from .models import Listing, UserEvent, UserProfile


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9\\s]", " ", text.lower()).strip()


def tokenize(text: str) -> list[str]:
    return [token for token in _normalize(text).split() if len(token) >= 2]


def _increment(counter: dict[str, int], key: str, weight: int = 1) -> None:
    if key:
        counter[key] = counter.get(key, 0) + weight


def ingest_listing(profile: UserProfile, listing: Listing, weight: int) -> None:
    _increment(profile.preferred_brands, listing.brand, weight)
    _increment(profile.preferred_conditions, listing.condition, weight)
    _increment(profile.preferred_sellers, listing.seller, weight)

    for token in tokenize(listing.title):
        _increment(profile.preferred_terms, token, weight)

    if listing.price > 0:
        profile.price_history.append(listing.price)
        if len(profile.price_history) > 120:
            del profile.price_history[:-120]


def rebuild_profile(events: list[UserEvent]) -> UserProfile:
    profile = UserProfile()
    weights = {
        "search": 2,
        "open_preview": 3,
        "open_link": 4,
        "favorite_add": 6,
        "target_add": 7,
    }

    for event in events[-400:]:
        if event.event_type == "search":
            profile.search_count += 1
            for term in event.terms:
                for token in tokenize(term):
                    _increment(profile.preferred_terms, token, 2)
            continue

        if event.listing is None:
            continue

        weight = weights.get(event.event_type, 1)
        ingest_listing(profile, event.listing, weight)

        if event.event_type in {"open_preview", "open_link"}:
            profile.open_count += 1
        elif event.event_type == "favorite_add":
            profile.favorite_count += 1
        elif event.event_type == "target_add":
            profile.target_count += 1

    return profile
