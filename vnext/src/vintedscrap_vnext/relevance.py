from __future__ import annotations

from .models import Listing, Recommendation, UserProfile
from .profile_service import tokenize


def score_listing(profile: UserProfile, listing: Listing) -> Recommendation:
    score = 50
    reasons: list[str] = []

    brand_hits = profile.preferred_brands.get(listing.brand, 0)
    if brand_hits >= 3:
        score += 18
        reasons.append("marque fréquente")
    elif brand_hits >= 1:
        score += 8
        reasons.append("marque déjà vue")

    condition_hits = profile.preferred_conditions.get(listing.condition, 0)
    if condition_hits >= 3:
        score += 12
        reasons.append("état habituel")
    elif condition_hits >= 1:
        score += 5

    seller_hits = profile.preferred_sellers.get(listing.seller, 0)
    if seller_hits >= 2:
        score += 10
        reasons.append("vendeur déjà consulté")

    average_price = profile.average_price
    if average_price and listing.price > 0:
        delta = abs(listing.price - average_price) / max(average_price, 1)
        if delta <= 0.15:
            score += 14
            reasons.append("prix dans ta zone")
        elif delta <= 0.35:
            score += 6
        elif delta >= 0.80:
            score -= 10

    matching_terms = sum(
        1 for token in tokenize(listing.title)
        if profile.preferred_terms.get(token, 0) >= 2
    )
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

    return Recommendation(score=score, label=label, reasons=reasons)
