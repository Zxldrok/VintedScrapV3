"""
analyzer.py — Analyse de prix et suggestion d'offres intelligentes

Pour chaque annonce ciblée :
  1. Analyse l'historique des prix de l'annonce
  2. Compare au marché (annonces similaires en cours)
  3. Prend en compte l'état de l'article
  4. Calcule un score de négociabilité (0–100)
  5. Choisit une stratégie et suggère un prix d'offre
  6. Génère un message prêt à copier-coller
"""

import statistics, logging, random
from dataclasses import dataclass, field
from typing import Optional

from . import data

logger = logging.getLogger(__name__)

# ─── Stratégies ───────────────────────────────────────────────────────────────

STRATEGIES = {
    "agressive":  0.75,   # -25%
    "moderee":    0.85,   # -15%
    "douce":      0.92,   # -8%
    "symbolique": 0.97,   # -3%
}

SEUIL_AGRESSIVE = 70
SEUIL_MODEREE   = 45
SEUIL_DOUCE     = 20

MESSAGES_FR = [
    "Bonjour ! Seriez-vous prêt(e) à accepter {prix} € pour \"{titre}\" ? Merci beaucoup !",
    "Bonjour, votre article m'intéresse vraiment. Accepteriez-vous {prix} € ? Bonne journée !",
    "Salut ! Est-ce que {prix} € vous conviendrait pour cet article ? Merci !",
    "Bonjour ! Je suis très intéressé(e). Serait-il possible de l'avoir pour {prix} € ?",
]


# ─── Résultat d'analyse ───────────────────────────────────────────────────────

@dataclass
class AnalysePrix:
    annonce_id:           str
    titre:                str
    prix_actuel:          float
    devise:               str   = "EUR"

    # Historique
    prix_histo_min:       float = 0.0
    prix_histo_max:       float = 0.0
    prix_histo_moy:       float = 0.0
    nb_points_histo:      int   = 0
    tendance:             str   = "stable"   # hausse | baisse | stable

    # Score & stratégie
    score:                int   = 50         # 0 (pas négociable) → 100 (très négociable)
    strategie:            str   = "moderee"
    prix_suggere:         float = 0.0
    reduction_pct:        float = 0.0
    message_suggere:      str   = ""

    # Raisons (tag, texte) : tag ∈ {"bon", "mauvais", "neutre", "info"}
    raisons:              list  = field(default_factory=list)

    @property
    def economie(self) -> float:
        return max(0.0, self.prix_actuel - self.prix_suggere)

    @property
    def sym(self) -> str:
        return {"EUR": "€", "GBP": "£", "USD": "$", "PLN": "zł",
                "CZK": "Kč", "HUF": "Ft", "RON": "lei",
                "SEK": "kr", "DKK": "kr"}.get(self.devise, self.devise)

    def fmt(self, p: float) -> str:
        return f"{p:.2f} {self.sym}"


# ─── Analyseur ────────────────────────────────────────────────────────────────

class AnalyseurPrix:

    def analyser(self, annonce, annonces_marche: Optional[list] = None) -> AnalysePrix:
        a = AnalysePrix(
            annonce_id  = str(annonce.id),
            titre       = annonce.title,
            prix_actuel = annonce.price,
            devise      = annonce.currency,
        )
        self._historique(a)
        if annonces_marche:
            self._marche(a, annonces_marche, annonce)
        self._etat(a, annonce)
        self._score(a)
        self._offre(a)
        self._message(a)
        logger.info(
            f"Analyse '{a.titre[:30]}' → {a.score}/100 | "
            f"{a.strategie} | suggère {a.fmt(a.prix_suggere)}"
        )
        return a

    # ── 1. Historique ─────────────────────────────────────────────────────────

    def _historique(self, a: AnalysePrix):
        pts = data.charger_historique(a.annonce_id)
        prices = [p["price"] for p in pts if p.get("price", 0) > 0]
        if len(prices) < 2:
            a.raisons.append(("info", "Historique insuffisant (première fois vue)."))
            return

        a.prix_histo_min  = min(prices)
        a.prix_histo_max  = max(prices)
        a.prix_histo_moy  = statistics.mean(prices)
        a.nb_points_histo = len(prices)

        # Tendance
        mi = len(prices) // 2
        moy_debut = statistics.mean(prices[:mi])
        moy_fin   = statistics.mean(prices[mi:])
        delta = (moy_fin - moy_debut) / moy_debut * 100 if moy_debut else 0
        if delta > 5:
            a.tendance = "hausse"
            a.raisons.append(("bon", f"Prix en hausse (+{delta:.0f}%) → vendeur peut baisser."))
        elif delta < -5:
            a.tendance = "baisse"
            a.raisons.append(("mauvais", f"Prix en baisse ({delta:.0f}%) → peu de marge restante."))
        else:
            a.tendance = "stable"
            a.raisons.append(("neutre", "Prix stable dans le temps."))

        # Prix actuel vs moyenne historique
        if a.prix_actuel > a.prix_histo_moy * 1.05:
            ecart = (a.prix_actuel - a.prix_histo_moy) / a.prix_histo_moy * 100
            a.raisons.append(("bon", f"Prix actuel {ecart:.0f}% au-dessus de sa moyenne historique."))
        elif a.prix_actuel <= a.prix_histo_min * 1.02:
            a.raisons.append(("mauvais", "Prix proche de son minimum historique."))

    # ── 2. Marché ─────────────────────────────────────────────────────────────

    def _marche(self, a: AnalysePrix, marche: list, ref):
        comparables = [
            x for x in marche
            if x.currency == ref.currency
            and x.price > 0
            and str(x.id) != str(ref.id)
        ]
        if not comparables:
            return

        prix_marche = sorted(x.price for x in comparables)
        med         = statistics.median(prix_marche)
        pct         = sum(1 for p in prix_marche if p < a.prix_actuel) / len(prix_marche) * 100

        if pct > 75:
            a.raisons.append(("bon", f"Plus cher que {pct:.0f}% du marché ({len(comparables)} annonces similaires)."))
        elif pct > 50:
            a.raisons.append(("neutre", f"Dans la moyenne haute du marché."))
        elif pct > 25:
            a.raisons.append(("neutre", "Dans la moyenne du marché."))
        else:
            a.raisons.append(("mauvais", f"Déjà parmi les moins chers du marché."))

        ecart_med = (a.prix_actuel - med) / med * 100 if med else 0
        if ecart_med > 20:
            a.raisons.append(("bon", f"Prix {ecart_med:.0f}% au-dessus de la médiane marché ({a.fmt(med)})."))

    # ── 3. État ───────────────────────────────────────────────────────────────

    def _etat(self, a: AnalysePrix, annonce):
        cond = getattr(annonce, "condition_id", 0)
        if cond in (2, 3):
            a.raisons.append(("bon", f"État '{annonce.condition}' → marge plus large habituelle."))
        elif cond in (4, 6):
            a.raisons.append(("mauvais", "Article neuf → peu de marge en général."))

    # ── 4. Score ──────────────────────────────────────────────────────────────

    def _score(self, a: AnalysePrix):
        score = 50
        for tag, _ in a.raisons:
            if tag == "bon":     score += 15
            elif tag == "mauvais": score -= 20
        if a.nb_points_histo >= 5: score += 5
        if a.prix_actuel > 50:     score += 8
        elif a.prix_actuel > 20:   score += 4
        a.score = max(0, min(100, score))

    # ── 5. Offre ──────────────────────────────────────────────────────────────

    def _offre(self, a: AnalysePrix):
        if a.score >= SEUIL_AGRESSIVE:
            a.strategie = "agressive"
        elif a.score >= SEUIL_MODEREE:
            a.strategie = "moderee"
        elif a.score >= SEUIL_DOUCE:
            a.strategie = "douce"
        else:
            a.strategie = "symbolique"

        brut = a.prix_actuel * STRATEGIES[a.strategie]
        # Arrondi au 0.50 le plus proche
        a.prix_suggere = max(0.5, round(brut * 2) / 2)
        a.reduction_pct = (1 - a.prix_suggere / a.prix_actuel) * 100

    # ── 6. Message ────────────────────────────────────────────────────────────

    def _message(self, a: AnalysePrix):
        tpl = random.choice(MESSAGES_FR)
        a.message_suggere = tpl.format(
            prix  = f"{a.prix_suggere:.2f}",
            titre = a.titre[:50],
        )


# ─── Helpers UI ───────────────────────────────────────────────────────────────

def label_strategie(s: str) -> str:
    return {
        "agressive":  "🔥 Agressive  (−25%)",
        "moderee":    "⚡ Modérée    (−15%)",
        "douce":      "🌿 Douce       (−8%)",
        "symbolique": "💬 Symbolique  (−3%)",
    }.get(s, s)

def couleur_score(score: int) -> str:
    if score >= 70: return "#34d399"
    if score >= 45: return "#f0c040"
    if score >= 20: return "#f6ad55"
    return "#f87171"


# ─── Singleton ────────────────────────────────────────────────────────────────

_analyseur = AnalyseurPrix()

def analyser_annonce(annonce, annonces_marche=None) -> AnalysePrix:
    return _analyseur.analyser(annonce, annonces_marche)
