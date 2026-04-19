"""
user_profile.py — Profil utilisateur local et scoring de pertinence.

Objectifs :
  - mémoriser les actions utilisateur
  - construire un profil simple et explicable
  - scorer les annonces selon ce profil
"""

from __future__ import annotations

import datetime
import json
import os
import re
import threading
import unicodedata
from collections import Counter
from typing import Any

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_DIR, "data")
PROFILE_FILE = os.path.join(_DATA_DIR, "user_profile.json")
EVENTS_FILE = os.path.join(_DATA_DIR, "user_events.json")

_LOCK = threading.RLock()


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in _norm(text).split() if len(t) >= 2]


def _empty_profile() -> dict[str, Any]:
    return {
        "updated_at": "",
        "search_count": 0,
        "open_count": 0,
        "favorite_count": 0,
        "target_count": 0,
        "preferred_brands": {},
        "preferred_conditions": {},
        "preferred_sellers": {},
        "preferred_terms": {},
        "price_history": [],
        "price_min_pref": None,
        "price_max_pref": None,
        "price_avg_pref": None,
        "last_searches": [],
        "summary": "",
    }


def load_profile() -> dict[str, Any]:
    return _load(PROFILE_FILE, _empty_profile())


def _load_events() -> list[dict[str, Any]]:
    return _load(EVENTS_FILE, [])


def _increment(counter_map: dict[str, int], key: str, weight: int = 1) -> None:
    if not key:
        return
    counter_map[key] = counter_map.get(key, 0) + weight


def _ingest_annonce(profile: dict[str, Any], annonce: dict[str, Any], weight: int) -> None:
    _increment(profile["preferred_brands"], annonce.get("brand", ""), weight)
    _increment(profile["preferred_conditions"], annonce.get("condition", ""), weight)
    _increment(profile["preferred_sellers"], annonce.get("vendeur", ""), weight)

    title = annonce.get("title", "")
    for token in _tokens(title):
        _increment(profile["preferred_terms"], token, weight)

    price = annonce.get("price")
    if isinstance(price, (int, float)) and price > 0:
        history = profile["price_history"]
        history.append(float(price))
        if len(history) > 120:
            del history[:-120]


def _refresh_price_preferences(profile: dict[str, Any]) -> None:
    prices = [p for p in profile.get("price_history", []) if isinstance(p, (int, float)) and p > 0]
    if not prices:
        profile["price_min_pref"] = None
        profile["price_max_pref"] = None
        profile["price_avg_pref"] = None
        return
    profile["price_min_pref"] = min(prices)
    profile["price_max_pref"] = max(prices)
    profile["price_avg_pref"] = round(sum(prices) / len(prices), 2)


def _top_keys(counter_map: dict[str, int], limit: int = 3) -> list[str]:
    return [k for k, _ in sorted(counter_map.items(), key=lambda kv: kv[1], reverse=True)[:limit] if k]


def _build_summary(profile: dict[str, Any]) -> str:
    brands = ", ".join(_top_keys(profile["preferred_brands"], 2))
    conditions = ", ".join(_top_keys(profile["preferred_conditions"], 2))
    avg_price = profile.get("price_avg_pref")

    parts = []
    if brands:
        parts.append(f"attire par {brands}")
    if avg_price:
        parts.append(f"vise souvent autour de {avg_price:.0f} €")
    if conditions:
        parts.append(f"préfère {conditions}")
    if not parts:
        return "Profil en cours d'apprentissage."
    return "Utilisateur " + " · ".join(parts) + "."


def _rebuild_profile(events: list[dict[str, Any]]) -> dict[str, Any]:
    profile = _empty_profile()
    weights = {
        "search": 2,
        "open_preview": 3,
        "open_link": 4,
        "favorite_add": 6,
        "target_add": 7,
        "compare_open": 4,
    }

    for event in events[-400:]:
        etype = event.get("type", "")
        if etype == "search":
            profile["search_count"] += 1
            terms = event.get("terms", [])
            for term in terms:
                for token in _tokens(term):
                    _increment(profile["preferred_terms"], token, 2)
            payload = event.get("filters", {})
            if isinstance(payload, dict):
                if payload.get("price_min") not in (None, ""):
                    profile["price_history"].append(float(payload["price_min"]))
                if payload.get("price_max") not in (None, ""):
                    profile["price_history"].append(float(payload["price_max"]))
            if terms:
                profile["last_searches"].append(", ".join(terms[:3]))
                profile["last_searches"] = profile["last_searches"][-12:]
            continue

        annonce = event.get("annonce")
        if not isinstance(annonce, dict):
            continue
        weight = weights.get(etype, 1)
        _ingest_annonce(profile, annonce, weight)
        if etype in ("open_preview", "open_link", "compare_open"):
            profile["open_count"] += 1
        elif etype == "favorite_add":
            profile["favorite_count"] += 1
        elif etype == "target_add":
            profile["target_count"] += 1

    _refresh_price_preferences(profile)
    profile["updated_at"] = _now()
    profile["summary"] = _build_summary(profile)
    return profile


def record_search(terms: list[str], filters: dict[str, Any] | None = None) -> None:
    if not terms:
        return
    with _LOCK:
        events = _load_events()
        events.append({
            "type": "search",
            "timestamp": _now(),
            "terms": [t.strip() for t in terms if t and t.strip()],
            "filters": filters or {},
        })
        events = events[-400:]
        _save(EVENTS_FILE, events)
        _save(PROFILE_FILE, _rebuild_profile(events))


def record_annonce_event(event_type: str, annonce) -> None:
    if annonce is None:
        return
    payload = {
        "id": str(getattr(annonce, "id", "")),
        "title": getattr(annonce, "title", ""),
        "price": getattr(annonce, "price", 0),
        "brand": getattr(annonce, "brand", ""),
        "size": getattr(annonce, "size", ""),
        "condition": getattr(annonce, "condition", ""),
        "vendeur": getattr(annonce, "vendeur_nom", ""),
        "url": getattr(annonce, "url", ""),
    }
    with _LOCK:
        events = _load_events()
        events.append({
            "type": event_type,
            "timestamp": _now(),
            "annonce": payload,
        })
        events = events[-400:]
        _save(EVENTS_FILE, events)
        _save(PROFILE_FILE, _rebuild_profile(events))


def get_profile_summary() -> str:
    return load_profile().get("summary") or "Profil en cours d'apprentissage."


def get_profile_snapshot() -> dict[str, Any]:
    profile = load_profile()
    return {
        "updated_at": profile.get("updated_at", ""),
        "summary": profile.get("summary") or "Profil en cours d'apprentissage.",
        "search_count": profile.get("search_count", 0),
        "open_count": profile.get("open_count", 0),
        "favorite_count": profile.get("favorite_count", 0),
        "target_count": profile.get("target_count", 0),
        "preferred_brands": _top_keys(profile.get("preferred_brands", {}), 5),
        "preferred_conditions": _top_keys(profile.get("preferred_conditions", {}), 5),
        "preferred_sellers": _top_keys(profile.get("preferred_sellers", {}), 5),
        "preferred_terms": _top_keys(profile.get("preferred_terms", {}), 8),
        "price_min_pref": profile.get("price_min_pref"),
        "price_max_pref": profile.get("price_max_pref"),
        "price_avg_pref": profile.get("price_avg_pref"),
        "last_searches": list(profile.get("last_searches", [])[-6:]),
    }


def get_recent_events(limit: int = 10) -> list[dict[str, Any]]:
    events = _load_events()
    return list(reversed(events[-max(1, limit):]))


def get_preferred_search_terms(limit: int = 5) -> list[str]:
    profile = load_profile()
    terms = sorted(profile.get("preferred_terms", {}).items(), key=lambda kv: kv[1], reverse=True)
    return [term for term, _ in terms[:limit]]


def score_annonce(annonce) -> tuple[int, str]:
    profile = load_profile()
    score = 50
    reasons: list[str] = []

    brand = getattr(annonce, "brand", "")
    if brand:
        brand_hits = profile["preferred_brands"].get(brand, 0)
        if brand_hits >= 3:
            score += 18
            reasons.append("marque fréquente")
        elif brand_hits >= 1:
            score += 8
            reasons.append("marque déjà vue")

    condition = getattr(annonce, "condition", "")
    if condition:
        cond_hits = profile["preferred_conditions"].get(condition, 0)
        if cond_hits >= 3:
            score += 12
            reasons.append("état habituel")
        elif cond_hits >= 1:
            score += 5

    seller = getattr(annonce, "vendeur_nom", "")
    if seller and profile["preferred_sellers"].get(seller, 0) >= 2:
        score += 10
        reasons.append("vendeur déjà consulté")

    avg_price = profile.get("price_avg_pref")
    price = getattr(annonce, "price", 0) or 0
    if avg_price and price > 0:
        delta = abs(price - avg_price) / max(avg_price, 1)
        if delta <= 0.15:
            score += 14
            reasons.append("prix dans ta zone")
        elif delta <= 0.35:
            score += 6
        elif delta >= 0.8:
            score -= 10

    tokens = _tokens(getattr(annonce, "title", ""))
    pref_terms = profile.get("preferred_terms", {})
    matching_terms = sum(1 for token in tokens if pref_terms.get(token, 0) >= 2)
    if matching_terms >= 2:
        score += 16
        reasons.append("titre proche de tes recherches")
    elif matching_terms == 1:
        score += 7

    score = max(0, min(100, score))
    if score >= 80:
        label = "Très pertinent"
    elif score >= 65:
        label = "Pertinent"
    elif score >= 50:
        label = "À surveiller"
    else:
        label = "Hors cible"

    reason_text = ", ".join(reasons[:2]) if reasons else "profil en apprentissage"
    return score, f"{label} · {reason_text}"


def enrich_annonces(annonces: list) -> list:
    for annonce in annonces:
        score, explanation = score_annonce(annonce)
        setattr(annonce, "relevance_score", score)
        setattr(annonce, "relevance_explanation", explanation)
    return annonces
