"""
core/resell.py — Module d'aide à l'achat-revente Vinted
=========================================================
Fournit :
  - Analyse du marché pour un produit donné
  - Estimation du prix de revente optimal
  - Génération de titre attractif
  - Génération de description optimisée
Utilise l'API Vinted via scraper + Claude via l'API Anthropic.
"""

from __future__ import annotations
import logging, statistics, re, unicodedata
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("resell")

# ─── Conditions disponibles ────────────────────────────────────────────────────
CONDITIONS = [
    "Neuf avec étiquette",
    "Neuf sans étiquette",
    "Très bon état",
    "Bon état",
    "Satisfaisant",
]

CONDITIONS_ID = {
    "Neuf avec étiquette":  6,
    "Neuf sans étiquette":  4,
    "Très bon état":        1,
    "Bon état":             2,
    "Satisfaisant":         3,
}

# Coefficient de décote selon l'état (par rapport au prix neuf)
DECOTE_ETAT = {
    "Neuf avec étiquette":  0.90,
    "Neuf sans étiquette":  0.80,
    "Très bon état":        0.65,
    "Bon état":             0.50,
    "Satisfaisant":         0.35,
}

# Marge bénéficiaire cible minimale
MARGE_MIN = 0.15


@dataclass
class AnalyseRevente:
    produit:           str
    prix_achat:        float
    etat:              str
    prix_marche_moyen: float
    prix_marche_min:   float
    prix_marche_max:   float
    nb_annonces:       int
    prix_suggere:      float
    marge_estimee:     float
    marge_pct:         float
    titre:             str
    description:       str
    conseil:           str
    score_opportunite: int        # 0-100
    annonces_ref:      list = field(default_factory=list)

    def fmt(self, v: float) -> str:
        return f"{v:.2f} €"


def _normaliser(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", s.lower()).strip()


def analyser_marche(produit: str, etat: str, scraper_instance) -> tuple[list, float, float, float]:
    """
    Recherche les annonces similaires sur Vinted.
    Retourne (annonces, moyenne, min, max).
    """
    try:
        annonces = scraper_instance.rechercher(
            produit, max_pages=3, par_page=48, order="newest_first"
        )
    except Exception as e:
        log.error(f"Erreur scraping marché : {e}")
        return [], 0.0, 0.0, 0.0

    # Filtrer par état si précisé
    cid = CONDITIONS_ID.get(etat)
    if cid:
        filtrees = [a for a in annonces if a.condition_id == cid]
        if len(filtrees) >= 3:
            annonces = filtrees

    # Garder seulement les annonces avec prix > 0
    prices = [a.price for a in annonces if a.price > 0]
    if not prices:
        return annonces, 0.0, 0.0, 0.0

    # Supprimer les outliers (prix < P10 ou > P90)
    prices_sorted = sorted(prices)
    p10 = prices_sorted[max(0, len(prices_sorted) // 10)]
    p90 = prices_sorted[min(len(prices_sorted) - 1, int(len(prices_sorted) * 0.9))]
    filtered = [p for p in prices if p10 <= p <= p90]
    if not filtered:
        filtered = prices

    avg = statistics.mean(filtered)
    return annonces, avg, min(filtered), max(filtered)


def calculer_prix_suggere(
    prix_achat: float,
    prix_marche_moyen: float,
    etat: str,
) -> tuple[float, float, float]:
    """
    Calcule le prix de revente optimal.
    Retourne (prix_suggere, marge_absolue, marge_pct).
    """
    decote = DECOTE_ETAT.get(etat, 0.65)

    # Prix plafond basé sur le marché (compétitif : légèrement sous la moyenne)
    prix_marche_cible = prix_marche_moyen * 0.92 if prix_marche_moyen > 0 else 0

    # Prix plancher basé sur l'achat (marge min)
    prix_min_marge = prix_achat * (1 + MARGE_MIN)

    # Prix suggéré : meilleur entre marché et marge mini
    if prix_marche_cible > prix_min_marge:
        prix = prix_marche_cible
    elif prix_min_marge > 0:
        prix = prix_min_marge
    else:
        # Pas de référence marché → appliquer la décote sur le prix d'achat supposé neuf
        prix = prix_achat * decote * 1.2

    # Arrondir au .99 attractif
    prix = round(prix - 0.01, 0) + 0.99 if prix > 1 else prix
    prix = round(prix, 2)

    marge = prix - prix_achat
    marge_pct = (marge / prix_achat * 100) if prix_achat > 0 else 0

    return prix, marge, marge_pct


def score_opportunite(
    prix_achat: float,
    prix_marche_moyen: float,
    nb_annonces: int,
    marge_pct: float,
) -> int:
    """Score 0-100 indiquant le potentiel de l'opération."""
    score = 50

    # Marge : +30 si > 50%, +15 si > 25%, -20 si < 0
    if marge_pct >= 50:
        score += 30
    elif marge_pct >= 25:
        score += 15
    elif marge_pct >= 10:
        score += 5
    elif marge_pct < 0:
        score -= 20

    # Concurrence : moins d'annonces = mieux
    if nb_annonces == 0:
        score += 10   # niche, peu de concurrence
    elif nb_annonces < 5:
        score += 15
    elif nb_annonces < 20:
        score += 5
    elif nb_annonces > 50:
        score -= 10

    # Rapport prix achat / marché
    if prix_marche_moyen > 0 and prix_achat > 0:
        ratio = prix_achat / prix_marche_moyen
        if ratio < 0.4:
            score += 20   # acheté très bon marché
        elif ratio < 0.6:
            score += 10
        elif ratio > 0.9:
            score -= 15

    return max(0, min(100, score))


def generer_titre(produit: str, etat: str) -> str:
    """
    Génère un titre attractif pour l'annonce Vinted (60 caractères max).
    Règles Vinted : pas de majuscules excessives, description concise.
    """
    produit_clean = produit.strip().title()
    etat_court = {
        "Neuf avec étiquette":  "Neuf avec étiquette",
        "Neuf sans étiquette":  "Neuf sans étiquette ✨",
        "Très bon état":        "Très bon état",
        "Bon état":             "Bon état",
        "Satisfaisant":         "Bon prix",
    }.get(etat, "")

    titre = f"{produit_clean} — {etat_court}" if etat_court else produit_clean

    # Tronquer à 60 caractères
    if len(titre) > 60:
        titre = titre[:57] + "…"
    return titre


def generer_description(
    produit: str,
    etat: str,
    prix_achat: float,
    prix_suggere: float,
    annonces_ref: list,
) -> str:
    """
    Génère une description complète et optimisée pour Vinted.
    """
    # Prix du marché pour la référence
    prix_ref_str = ""
    if annonces_ref:
        prices = [a.price for a in annonces_ref if a.price > 0]
        if prices:
            avg = statistics.mean(prices)
            prix_ref_str = f"Prix moyen du marché : {avg:.0f} €\n"

    etat_desc = {
        "Neuf avec étiquette":  "Article neuf, jamais porté/utilisé, étiquette d'origine présente.",
        "Neuf sans étiquette":  "Article neuf ou comme neuf, étiquette retirée mais jamais utilisé.",
        "Très bon état":        "Article en très bon état, peu utilisé, aucun défaut visible.",
        "Bon état":             "Article en bon état général, légères traces d'utilisation normales.",
        "Satisfaisant":         "Article fonctionnel avec quelques marques d'usure, prix ajusté en conséquence.",
    }.get(etat, "Article en bon état.")

    desc = f"""{produit.strip()} à vendre !

{etat_desc}

✅ Vendu rapidement, expédition soignée.
📦 Envoi sous 48h après paiement.
💬 N'hésitez pas à me faire une offre ou à poser vos questions !

{prix_ref_str}🔒 Paiement sécurisé via Vinted — acheteur protégé."""

    return desc.strip()


def generer_conseil(
    marge_pct: float,
    nb_annonces: int,
    prix_marche_moyen: float,
    prix_achat: float,
) -> str:
    """Génère un conseil personnalisé selon la situation du marché."""
    conseils = []

    if marge_pct < 0:
        conseils.append("⚠️ Attention : le prix du marché est inférieur à votre prix d'achat. "
                        "Revenez sur votre décision d'achat ou recherchez un canal de vente alternatif.")
    elif marge_pct < 15:
        conseils.append("💡 Marge faible. Pour améliorer votre résultat, "
                        "soignez les photos et la description pour justifier un prix plus élevé.")
    elif marge_pct >= 40:
        conseils.append("🚀 Excellente opportunité ! Le marché valorise bien ce produit. "
                        "Publiez rapidement avant que la concurrence augmente.")

    if nb_annonces == 0:
        conseils.append("🔍 Aucune annonce similaire trouvée — produit rare ou niche. "
                        "Testez un prix légèrement plus élevé.")
    elif nb_annonces > 30:
        conseils.append("📊 Marché saturé. Différenciez-vous avec de belles photos "
                        "et répondez rapidement aux messages.")

    if not conseils:
        conseils.append("✨ Bon potentiel. Publiez avec de bonnes photos pour maximiser vos chances.")

    return " ".join(conseils)


def analyser_revente(
    produit: str,
    prix_achat: float,
    etat: str,
    scraper_instance,
) -> AnalyseRevente:
    """
    Fonction principale — retourne une AnalyseRevente complète.
    """
    # 1. Analyse du marché
    annonces, avg, pmin, pmax = analyser_marche(produit, etat, scraper_instance)

    # 2. Prix suggéré
    prix_suggere, marge, marge_pct = calculer_prix_suggere(prix_achat, avg, etat)

    # 3. Score opportunité
    score = score_opportunite(prix_achat, avg, len(annonces), marge_pct)

    # 4. Titre + description
    titre = generer_titre(produit, etat)
    description = generer_description(produit, etat, prix_achat, prix_suggere, annonces)
    conseil = generer_conseil(marge_pct, len(annonces), avg, prix_achat)

    return AnalyseRevente(
        produit=produit,
        prix_achat=prix_achat,
        etat=etat,
        prix_marche_moyen=avg,
        prix_marche_min=pmin,
        prix_marche_max=pmax,
        nb_annonces=len(annonces),
        prix_suggere=prix_suggere,
        marge_estimee=marge,
        marge_pct=marge_pct,
        titre=titre,
        description=description,
        conseil=conseil,
        score_opportunite=score,
        annonces_ref=annonces[:6],
    )
