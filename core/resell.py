"""
core/resell.py - Module d'aide a l'achat-revente Vinted
======================================================
Fournit :
  - Analyse du marche pour un produit donne
  - Estimation d'un prix de vente rapide et d'un prix cible
  - Generation d'un titre et d'une description reutilisables
  - Score d'opportunite et niveau de confiance
"""

from __future__ import annotations

import logging
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass, field

log = logging.getLogger("resell")


CONDITIONS = [
    "Tous états",
    "Neuf avec étiquette",
    "Neuf sans étiquette",
    "Très bon état",
    "Bon état",
    "Satisfaisant",
]

CONDITIONS_ID = {
    "Neuf avec étiquette": 6,
    "Neuf sans étiquette": 4,
    "Très bon état": 1,
    "Bon état": 2,
    "Satisfaisant": 3,
}

MARGE_MIN = 0.15
FRAIS_PLATEFORME = 0.05
FRAIS_EXPEDITION = 2.50


@dataclass
class AnalyseRevente:
    produit: str
    prix_achat: float
    etat: str
    prix_marche_moyen: float
    prix_marche_min: float
    prix_marche_max: float
    prix_marche_mediane: float
    nb_annonces: int
    prix_suggere: float
    prix_vente_rapide: float
    prix_min_rentable: float
    frais_plateforme: float
    frais_expedition: float
    marge_estimee: float
    marge_pct: float
    marge_nette: float
    marge_nette_pct: float
    titre: str
    description: str
    conseil: str
    score_opportunite: int
    fiabilite_marche: int
    annonces_ref: list = field(default_factory=list)

    def fmt(self, value: float) -> str:
        return f"{value:.2f} €"


def _normaliser(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def _tokens(text: str) -> set[str]:
    return {token for token in _normaliser(text).split() if len(token) >= 2}


def _similarite_titre(reference: str, title: str) -> float:
    ref_tokens = _tokens(reference)
    cand_tokens = _tokens(title)
    if not ref_tokens or not cand_tokens:
        return 0.0
    return len(ref_tokens & cand_tokens) / len(ref_tokens)


def _filtrer_outliers(prices: list[float]) -> list[float]:
    if len(prices) < 4:
        return prices

    mediane = statistics.median(prices)
    deviations = [abs(price - mediane) for price in prices]
    mad = statistics.median(deviations)
    if mad == 0:
        return prices

    filtered = [price for price in prices if abs(price - mediane) / mad <= 3.5]
    minimum_expected = max(3, len(prices) // 2)
    return filtered if len(filtered) >= minimum_expected else prices


def _prix_attractif(value: float) -> float:
    if value <= 0:
        return 0.0
    if value < 1:
        return round(value, 2)

    lower = max(0.99, math.floor(value) - 0.01)
    upper = math.floor(value) + 0.99
    choice = min((round(lower, 2), round(upper, 2)), key=lambda candidate: abs(candidate - value))
    return round(choice, 2)


def _fiabilite_marche(prices: list[float]) -> int:
    if not prices:
        return 10

    count = len(prices)
    if count >= 20:
        score = 90
    elif count >= 10:
        score = 78
    elif count >= 5:
        score = 64
    elif count >= 3:
        score = 48
    else:
        score = 30

    if count >= 2:
        mediane = statistics.median(prices)
        spread = statistics.pstdev(prices) / max(mediane, 1)
        if spread < 0.12:
            score += 10
        elif spread < 0.22:
            score += 4
        elif spread > 0.40:
            score -= 15
        elif spread > 0.28:
            score -= 6

    return max(5, min(100, score))


def analyser_marche(
    produit: str,
    etat: str,
    scraper_instance,
) -> tuple[list, float, float, float, float, int]:
    """
    Recherche les annonces similaires sur Vinted.
    Retourne (annonces_ref, moyenne, min, max, mediane, fiabilite).
    """
    try:
        annonces = scraper_instance.rechercher(
            produit, max_pages=3, par_page=48, order="newest_first"
        )
    except Exception as exc:
        log.error(f"Erreur scraping marche : {exc}")
        return [], 0.0, 0.0, 0.0, 0.0, 10

    if not annonces:
        return [], 0.0, 0.0, 0.0, 0.0, 10

    similaires = [
        annonce for annonce in annonces
        if _similarite_titre(produit, annonce.title) >= 0.45
    ]
    if len(similaires) >= 3:
        annonces = similaires

    condition_id = CONDITIONS_ID.get(etat)
    if condition_id:
        filtrees = [annonce for annonce in annonces if annonce.condition_id == condition_id]
        if len(filtrees) >= 3:
            annonces = filtrees

    prices = [annonce.price for annonce in annonces if annonce.price > 0]
    if not prices:
        return annonces, 0.0, 0.0, 0.0, 0.0, 10

    filtered_prices = _filtrer_outliers(prices)
    moyenne = statistics.mean(filtered_prices)
    mediane = statistics.median(filtered_prices)
    fiabilite = _fiabilite_marche(filtered_prices)

    ref_min = min(filtered_prices)
    ref_max = max(filtered_prices)
    annonces_ref = [annonce for annonce in annonces if ref_min <= annonce.price <= ref_max]
    if len(annonces_ref) < 3:
        annonces_ref = sorted(
            annonces,
            key=lambda annonce: abs(annonce.price - mediane) if annonce.price > 0 else 10**9,
        )

    return annonces_ref, moyenne, ref_min, ref_max, mediane, fiabilite


def calculer_prix_suggere(
    prix_achat: float,
    prix_marche_moyen: float,
    prix_marche_mediane: float,
    etat: str,
) -> tuple[float, float, float, float, float]:
    """
    Calcule les prix de vente utiles.
    Retourne (prix_suggere, prix_vente_rapide, prix_min_rentable, marge, marge_pct).
    """
    if prix_achat <= 0:
        raise ValueError("Le prix d'achat doit être supérieur à 0.")

    prix_min_rentable = round(prix_achat * (1 + MARGE_MIN), 2)
    ancre_marche = min(
        [value for value in (prix_marche_mediane, prix_marche_moyen) if value > 0],
        default=0.0,
    )

    if ancre_marche > 0:
        prix_vente_rapide_brut = max(prix_min_rentable, ancre_marche * 0.93)
        prix_suggere_brut = max(prix_min_rentable, ancre_marche * 0.98)
    else:
        buffer = {
            "Neuf avec étiquette": 1.26,
            "Neuf sans étiquette": 1.23,
            "Très bon état": 1.20,
            "Bon état": 1.18,
            "Satisfaisant": 1.16,
        }.get(etat, 1.20)
        prix_vente_rapide_brut = prix_achat * max(1 + MARGE_MIN, buffer)
        prix_suggere_brut = prix_vente_rapide_brut * 1.06

    prix_vente_rapide = max(prix_min_rentable, _prix_attractif(prix_vente_rapide_brut))
    prix_suggere = max(prix_vente_rapide, prix_min_rentable, _prix_attractif(prix_suggere_brut))

    marge = round(prix_suggere - prix_achat, 2)
    marge_pct = (marge / prix_achat * 100) if prix_achat > 0 else 0.0

    return round(prix_suggere, 2), round(prix_vente_rapide, 2), prix_min_rentable, marge, marge_pct


def score_opportunite(
    prix_achat: float,
    prix_marche_moyen: float,
    prix_marche_mediane: float,
    nb_annonces: int,
    marge_pct: float,
    fiabilite_marche: int,
) -> int:
    """Score 0-100 indiquant le potentiel de l'opération."""
    score = 42

    if marge_pct >= 50:
        score += 28
    elif marge_pct >= 30:
        score += 18
    elif marge_pct >= 15:
        score += 10
    elif marge_pct < 0:
        score -= 25
    elif marge_pct < 10:
        score -= 8

    if nb_annonces == 0:
        score -= 6
    elif nb_annonces < 5:
        score += 8
    elif nb_annonces < 20:
        score += 4
    elif nb_annonces > 60:
        score -= 8

    ancre_marche = prix_marche_mediane or prix_marche_moyen
    if ancre_marche > 0 and prix_achat > 0:
        ratio = prix_achat / ancre_marche
        if ratio <= 0.45:
            score += 18
        elif ratio <= 0.65:
            score += 9
        elif ratio >= 0.95:
            score -= 14

    score += int((fiabilite_marche - 50) / 5)
    return max(0, min(100, score))


def generer_titre(produit: str, etat: str) -> str:
    """Genere un titre propre pour une future annonce."""
    produit_clean = produit.strip().title()
    etat_court = {
        "Neuf avec étiquette": "Neuf avec étiquette",
        "Neuf sans étiquette": "Neuf sans étiquette",
        "Très bon état": "Très bon état",
        "Bon état": "Bon état",
        "Satisfaisant": "Petit prix",
    }.get(etat, "")

    titre = f"{produit_clean} - {etat_court}" if etat_court else produit_clean
    return titre if len(titre) <= 60 else titre[:57] + "..."


def generer_description(
    produit: str,
    etat: str,
    prix_suggere: float,
    annonces_ref: list,
) -> str:
    """Genere une description reutilisable pour Vinted."""
    prix_ref_str = ""
    if annonces_ref:
        prices = [annonce.price for annonce in annonces_ref if annonce.price > 0]
        if prices:
            avg = statistics.mean(prices)
            prix_ref_str = f"Positionnement marché observé autour de {avg:.0f} €.\n"

    etat_desc = {
        "Neuf avec étiquette": "Article neuf, jamais utilisé, avec étiquette.",
        "Neuf sans étiquette": "Article neuf ou quasi neuf, jamais utilisé.",
        "Très bon état": "Article en très bon état, propre et prêt à être porté ou utilisé.",
        "Bon état": "Article en bon état général avec une usure normale.",
        "Satisfaisant": "Article fonctionnel avec quelques traces visibles, prix ajusté.",
    }.get(etat, "Article en bon état.")

    desc = f"""{produit.strip()} à vendre.

{etat_desc}

{prix_ref_str}✅ Envoi soigné.
📦 Expédition rapide après paiement.
💬 Je réponds volontiers aux questions et offres raisonnables.

Prix affiché conseillé : {prix_suggere:.2f} €."""
    return desc.strip()


def generer_conseil(
    marge_pct: float,
    nb_annonces: int,
    fiabilite_marche: int,
    prix_vente_rapide: float,
    prix_suggere: float,
    prix_min_rentable: float,
) -> str:
    """Genere un conseil synthétique et actionnable."""
    conseils = [
        f"Vente rapide autour de {prix_vente_rapide:.2f} € ; prix cible plus patient autour de {prix_suggere:.2f} €.",
        f"Évitez de descendre sous {prix_min_rentable:.2f} € pour garder votre marge minimale.",
    ]

    if marge_pct < 0:
        conseils.append("Le coût d'achat est trop proche du marché : opération risquée en l'état.")
    elif marge_pct < 15:
        conseils.append("Marge serrée : misez sur des photos propres et une annonce très claire.")
    elif marge_pct >= 40:
        conseils.append("Très bon potentiel : publiez vite pendant que la fenêtre de prix est favorable.")

    if nb_annonces == 0:
        conseils.append("Peu de références visibles : bonne piste, mais vérifiez aussi d'autres plateformes.")
    elif nb_annonces > 30:
        conseils.append("Marché chargé : il faudra être compétitif et réactif sur les messages.")

    if fiabilite_marche < 40:
        conseils.append("La confiance marché est faible : utilisez cette estimation comme ordre de grandeur, pas comme vérité absolue.")
    elif fiabilite_marche >= 75:
        conseils.append("Les références observées sont assez cohérentes pour fixer un prix avec confiance.")

    return " ".join(conseils)


def analyser_revente(
    produit: str,
    prix_achat: float,
    etat: str,
    scraper_instance,
) -> AnalyseRevente:
    """Fonction principale - retourne une AnalyseRevente complète."""
    produit = (produit or "").strip()
    if len(produit) < 3:
        raise ValueError("Le produit doit contenir au moins 3 caractères.")
    if prix_achat <= 0:
        raise ValueError("Le prix d'achat doit être supérieur à 0.")

    annonces, avg, pmin, pmax, mediane, fiabilite = analyser_marche(produit, etat, scraper_instance)
    prix_suggere, prix_vente_rapide, prix_min_rentable, marge, marge_pct = calculer_prix_suggere(
        prix_achat, avg, mediane, etat
    )
    frais_plateforme = round(prix_suggere * FRAIS_PLATEFORME, 2)
    frais_expedition = FRAIS_EXPEDITION
    marge_nette = round(prix_suggere - frais_plateforme - frais_expedition - prix_achat, 2)
    marge_nette_pct = round((marge_nette / prix_achat * 100), 1) if prix_achat > 0 else 0.0
    score = score_opportunite(prix_achat, avg, mediane, len(annonces), marge_pct, fiabilite)
    titre = generer_titre(produit, etat)
    description = generer_description(produit, etat, prix_suggere, annonces)
    conseil = generer_conseil(
        marge_pct, len(annonces), fiabilite, prix_vente_rapide, prix_suggere, prix_min_rentable
    )

    return AnalyseRevente(
        produit=produit,
        prix_achat=prix_achat,
        etat=etat,
        prix_marche_moyen=avg,
        prix_marche_min=pmin,
        prix_marche_max=pmax,
        prix_marche_mediane=mediane,
        nb_annonces=len(annonces),
        prix_suggere=prix_suggere,
        prix_vente_rapide=prix_vente_rapide,
        prix_min_rentable=prix_min_rentable,
        frais_plateforme=frais_plateforme,
        frais_expedition=frais_expedition,
        marge_estimee=marge,
        marge_pct=marge_pct,
        marge_nette=marge_nette,
        marge_nette_pct=marge_nette_pct,
        titre=titre,
        description=description,
        conseil=conseil,
        score_opportunite=score,
        fiabilite_marche=fiabilite,
        annonces_ref=annonces[:6],
    )
