"""
recommandations.py — Système intelligent de recommandation VintedScrap
Analyse l'historique des recherches pour proposer des annonces personnalisées.
"""

import json, os, logging, re, unicodedata
from collections import Counter
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_DIR, "data")
RECHERCHES_FILE = os.path.join(_DATA_DIR, "recherches.json")
HISTORIQUE_RECO_FILE = os.path.join(_DATA_DIR, "historique_recherches.json")


# ─── Persistance de l'historique des termes tapés ────────────────────────────

def _charger_histo_reco() -> dict:
    try:
        with open(HISTORIQUE_RECO_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"termes": {}, "sequences": []}


def _sauvegarder_histo_reco(data: dict):
    with open(HISTORIQUE_RECO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def enregistrer_terme(terme: str):
    """Enregistre un terme recherché pour alimenter les recommandations."""
    if not terme or not terme.strip():
        return
    terme = terme.strip().lower()
    histo = _charger_histo_reco()
    termes = histo.get("termes", {})
    termes[terme] = termes.get(terme, 0) + 1
    histo["termes"] = termes
    # Séquences (les N derniers termes pour suggestions contextuelles)
    seqs = histo.get("sequences", [])
    seqs.append(terme)
    if len(seqs) > 200:
        seqs = seqs[-200:]
    histo["sequences"] = seqs
    _sauvegarder_histo_reco(histo)

def _normaliser(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", "", s.lower()).strip()


# ─── Suggestions de saisie intelligente ──────────────────────────────────────

def obtenir_suggestions(prefixe: str, max_resultats: int = 6) -> List[str]:
    """
    Retourne les suggestions pour la saisie intelligente.
    Combine :
     - L'historique personnel (termes fréquents)
     - Les recherches sauvegardées (mots-clés)
    """
    if not prefixe or not prefixe.strip():
        return obtenir_suggestions_populaires(max_resultats)

    prefixe_norm = _normaliser(prefixe)
    histo = _charger_histo_reco()
    termes = histo.get("termes", {})

    # Recherches sauvegardées
    try:
        with open(RECHERCHES_FILE, encoding="utf-8") as f:
            sauvegardes = json.load(f)
        for r in sauvegardes:
            for t in r.get("mots_cles", "").split(","):
                t = t.strip().lower()
                if t:
                    termes[t] = termes.get(t, 0) + 1
    except Exception:
        pass

    suggestions = []
    for terme, freq in sorted(termes.items(), key=lambda x: x[1], reverse=True):
        if _normaliser(terme).startswith(prefixe_norm) and terme not in suggestions:
            suggestions.append(terme)
        if len(suggestions) >= max_resultats:
            break

    # Compléter avec des correspondances partielles si pas assez
    if len(suggestions) < max_resultats:
        for terme, freq in sorted(termes.items(), key=lambda x: x[1], reverse=True):
            if prefixe_norm in _normaliser(terme) and terme not in suggestions:
                suggestions.append(terme)
            if len(suggestions) >= max_resultats:
                break

    return suggestions[:max_resultats]


def obtenir_suggestions_populaires(max_resultats: int = 6) -> List[str]:
    """Retourne les termes les plus fréquemment recherchés."""
    histo = _charger_histo_reco()
    termes = histo.get("termes", {})
    # Ajouter les recherches sauvegardées
    try:
        with open(RECHERCHES_FILE, encoding="utf-8") as f:
            sauvegardes = json.load(f)
        for r in sauvegardes:
            for t in r.get("mots_cles", "").split(","):
                t = t.strip().lower()
                if t:
                    termes[t] = termes.get(t, 0) + 1
    except Exception:
        pass
    sorted_termes = sorted(termes.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in sorted_termes[:max_resultats]]


# ─── Recommandations d'annonces ───────────────────────────────────────────────

def generer_requetes_recommandation(max_termes: int = 5) -> List[str]:
    """
    Génère une liste de termes de recherche à lancer pour les recommandations.
    Basé sur les recherches les plus fréquentes de l'utilisateur.
    """
    suggestions = obtenir_suggestions_populaires(max_termes)
    if not suggestions:
        return []
    return suggestions


def a_suffisamment_d_historique() -> bool:
    """Indique si l'utilisateur a assez d'historique pour des recommandations."""
    histo = _charger_histo_reco()
    termes = histo.get("termes", {})
    # Ajouter les recherches sauvegardées dans le compte
    try:
        with open(RECHERCHES_FILE, encoding="utf-8") as f:
            sauvegardes = json.load(f)
        nb_sauv = len(sauvegardes)
    except Exception:
        nb_sauv = 0
    return len(termes) >= 1 or nb_sauv >= 1
