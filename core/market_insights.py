"""
market_insights.py - Insights metier pour l'exploration, la revente et le profil.
"""

from __future__ import annotations

import datetime
import json
import os
import statistics
import unicodedata
from collections import Counter
from typing import Any

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_DIR, "data")
RESELL_HISTORY_FILE = os.path.join(_DATA_DIR, "resell_history.json")


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    clean = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text.lower())
    return " ".join(clean.split())


def _tokens(text: str) -> list[str]:
    stop = {
        "avec", "sans", "pour", "sur", "dans", "the", "and", "les", "des", "une",
        "display", "edition", "version", "piece", "pieces", "fr", "vf", "box",
        "lot", "new", "neuf", "etat",
    }
    return [token for token in _norm(text).split() if len(token) >= 2 and token not in stop]


def _title_similarity(left: str, right: str) -> float:
    lt = set(_tokens(left))
    rt = set(_tokens(right))
    if not lt or not rt:
        return 0.0
    return len(lt & rt) / max(len(lt | rt), 1)


def _price_close(left: float, right: float) -> bool:
    if left <= 0 or right <= 0:
        return False
    tolerance = max(3.0, max(left, right) * 0.12)
    return abs(left - right) <= tolerance


def detect_duplicate_groups(annonces: list) -> list[list]:
    groups: list[list] = []
    used: set[int] = set()
    for idx, annonce in enumerate(annonces):
        if idx in used:
            continue
        group = [annonce]
        seller = _norm(getattr(annonce, "vendeur_nom", ""))
        image = getattr(annonce, "image_url", "") or ""
        for jdx in range(idx + 1, len(annonces)):
            if jdx in used:
                continue
            other = annonces[jdx]
            same_image = image and image == (getattr(other, "image_url", "") or "")
            same_seller = seller and seller == _norm(getattr(other, "vendeur_nom", ""))
            sim = _title_similarity(getattr(annonce, "title", ""), getattr(other, "title", ""))
            if same_image or (sim >= 0.72 and _price_close(getattr(annonce, "price", 0), getattr(other, "price", 0))) or (same_seller and sim >= 0.66):
                group.append(other)
                used.add(jdx)
        if len(group) > 1:
            used.add(idx)
            groups.append(group)
    return groups


def enrich_annonces(annonces: list) -> list:
    for annonce in annonces:
        setattr(annonce, "duplicate_group", "")
        setattr(annonce, "duplicate_count", 1)
        setattr(annonce, "duplicate_primary", True)
        setattr(annonce, "duplicate_hint", "")

    for gid, group in enumerate(detect_duplicate_groups(annonces), start=1):
        ordered = sorted(group, key=lambda annonce: getattr(annonce, "price", 0) or 0)
        count = len(ordered)
        for index, annonce in enumerate(ordered):
            setattr(annonce, "duplicate_group", f"dup-{gid}")
            setattr(annonce, "duplicate_count", count)
            setattr(annonce, "duplicate_primary", index == 0)
            setattr(
                annonce,
                "duplicate_hint",
                f"Doublon detecte x{count}" if index == 0 else f"Variante doublon x{count}",
            )
    return annonces


def analyse_vendeur(annonces: list, vendeur_nom: str) -> dict[str, Any]:
    vendeur_norm = _norm(vendeur_nom)
    seller_items = [
        annonce for annonce in annonces
        if vendeur_norm and _norm(getattr(annonce, "vendeur_nom", "")) == vendeur_norm
    ]
    prices = [getattr(annonce, "price", 0) for annonce in seller_items if getattr(annonce, "price", 0) > 0]
    brands = Counter(getattr(annonce, "brand", "") for annonce in seller_items if getattr(annonce, "brand", ""))
    conditions = Counter(getattr(annonce, "condition", "") for annonce in seller_items if getattr(annonce, "condition", ""))
    titles = Counter(" ".join(_tokens(getattr(annonce, "title", ""))[:4]) for annonce in seller_items)
    duplicate_like = sum(1 for _, count in titles.items() if count >= 2)
    relevance = [getattr(annonce, "relevance_score", 0) for annonce in seller_items if getattr(annonce, "relevance_score", None) is not None]
    return {
        "vendeur": vendeur_nom,
        "total": len(seller_items),
        "prix_moyen": round(sum(prices) / len(prices), 2) if prices else 0.0,
        "prix_min": min(prices) if prices else 0.0,
        "prix_max": max(prices) if prices else 0.0,
        "valeur_totale": round(sum(prices), 2) if prices else 0.0,
        "top_brands": brands.most_common(5),
        "conditions": conditions.most_common(5),
        "duplicate_like": duplicate_like,
        "relevance_moyenne": round(sum(relevance) / len(relevance), 1) if relevance else 0.0,
        "annonces": seller_items,
    }


def build_dashboard_stats(annonces: list) -> dict[str, Any]:
    if not annonces:
        return {}

    prices = [getattr(annonce, "price", 0) for annonce in annonces if getattr(annonce, "price", 0) > 0]
    brands = Counter(getattr(annonce, "brand", "") for annonce in annonces if getattr(annonce, "brand", ""))
    conditions = Counter(getattr(annonce, "condition", "") for annonce in annonces if getattr(annonce, "condition", ""))
    sellers = Counter(getattr(annonce, "vendeur_nom", "") for annonce in annonces if getattr(annonce, "vendeur_nom", ""))
    affinities = [getattr(annonce, "relevance_score", 0) for annonce in annonces if getattr(annonce, "relevance_score", None) is not None]
    duplicate_groups = detect_duplicate_groups(annonces)
    prices_sorted = sorted(prices)

    bucket_counts = {
        "<20": sum(1 for price in prices if price < 20),
        "20-50": sum(1 for price in prices if 20 <= price < 50),
        "50-100": sum(1 for price in prices if 50 <= price < 100),
        "100+": sum(1 for price in prices if price >= 100),
    }

    return {
        "total": len(annonces),
        "prix_moyen": round(sum(prices) / len(prices), 2) if prices else 0.0,
        "prix_min": min(prices) if prices else 0.0,
        "prix_max": max(prices) if prices else 0.0,
        "prix_median": prices_sorted[len(prices_sorted) // 2] if prices_sorted else 0.0,
        "top_brands": brands.most_common(5),
        "etats": conditions.most_common(5),
        "top_vendeurs": sellers.most_common(5),
        "avec_image": sum(1 for annonce in annonces if getattr(annonce, "image_url", "")),
        "vendeurs_uniques": len(sellers),
        "marques_uniques": len(brands),
        "doublons": sum(len(group) for group in duplicate_groups),
        "groupes_doublons": len(duplicate_groups),
        "affinite_moyenne": round(sum(affinities) / len(affinities), 1) if affinities else 0.0,
        "haute_affinite": sum(1 for score in affinities if score >= 75),
        "buckets": list(bucket_counts.items()),
    }


def filter_alert_results(
    annonces: list,
    excluded_terms: list[str] | None = None,
    ignored_sellers: list[str] | None = None,
    max_price: float | None = None,
    min_affinity: int | None = None,
) -> tuple[list, dict[str, int]]:
    excluded_terms = [_norm(term) for term in (excluded_terms or []) if term and term.strip()]
    ignored_sellers = {_norm(seller) for seller in (ignored_sellers or []) if seller and seller.strip()}
    kept = []
    skipped = {"excluded_terms": 0, "ignored_sellers": 0, "max_price": 0, "min_affinity": 0}

    for annonce in annonces:
        title_norm = _norm(getattr(annonce, "title", ""))
        seller_norm = _norm(getattr(annonce, "vendeur_nom", ""))
        price = getattr(annonce, "price", 0) or 0
        affinity = getattr(annonce, "relevance_score", 0) or 0

        if excluded_terms and any(term and term in title_norm for term in excluded_terms):
            skipped["excluded_terms"] += 1
            continue
        if ignored_sellers and seller_norm in ignored_sellers:
            skipped["ignored_sellers"] += 1
            continue
        if max_price is not None and price > 0 and price > max_price:
            skipped["max_price"] += 1
            continue
        if min_affinity is not None and affinity < min_affinity:
            skipped["min_affinity"] += 1
            continue
        kept.append(annonce)

    return kept, skipped


def record_resell_analysis(analyse) -> None:
    history = _load(RESELL_HISTORY_FILE, [])
    history.append({
        "timestamp": _now(),
        "produit": getattr(analyse, "produit", ""),
        "etat": getattr(analyse, "etat", ""),
        "prix_achat": getattr(analyse, "prix_achat", 0),
        "prix_suggere": getattr(analyse, "prix_suggere", 0),
        "prix_vente_rapide": getattr(analyse, "prix_vente_rapide", 0),
        "prix_min_rentable": getattr(analyse, "prix_min_rentable", 0),
        "marge_estimee": getattr(analyse, "marge_estimee", 0),
        "marge_pct": getattr(analyse, "marge_pct", 0),
        "score_opportunite": getattr(analyse, "score_opportunite", 0),
        "fiabilite_marche": getattr(analyse, "fiabilite_marche", 0),
    })
    history = history[-120:]
    _save(RESELL_HISTORY_FILE, history)


def get_recent_resell_analyses(limit: int = 6) -> list[dict[str, Any]]:
    history = _load(RESELL_HISTORY_FILE, [])
    return list(reversed(history[-limit:]))


def get_portfolio_snapshot() -> dict[str, Any]:
    favoris = _load(os.path.join(_DATA_DIR, "favoris.json"), [])
    cibles = _load(os.path.join(_DATA_DIR, "cibles.json"), [])
    analyses = _load(RESELL_HISTORY_FILE, [])

    fav_value = sum(float(item.get("price", 0) or 0) for item in favoris)
    pending_targets = [item for item in cibles if item.get("statut") == "en_attente"]
    target_value = sum(float(item.get("price", 0) or 0) for item in pending_targets)
    purchase_total = sum(float(item.get("prix_achat", 0) or 0) for item in analyses)
    sale_total = sum(float(item.get("prix_suggere", 0) or 0) for item in analyses)
    margin_total = sum(float(item.get("marge_estimee", 0) or 0) for item in analyses)

    return {
        "favoris_count": len(favoris),
        "favoris_value": round(fav_value, 2),
        "cibles_count": len(pending_targets),
        "cibles_value": round(target_value, 2),
        "analyses_count": len(analyses),
        "depense_estimee": round(purchase_total, 2),
        "vente_potentielle": round(sale_total, 2),
        "marge_potentielle": round(margin_total, 2),
        "recent_analyses": get_recent_resell_analyses(),
    }
