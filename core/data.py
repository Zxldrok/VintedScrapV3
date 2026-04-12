"""
data.py — Persistance locale : favoris, recherches sauvegardées, historique des prix,
          file de ciblage (annonces à contacter).
"""

import json, os, threading, datetime
from typing import Optional

_DIR            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR       = os.path.join(_DIR, "data")
FAVORIS_FILE    = os.path.join(_DATA_DIR, "favoris.json")
RECHERCHES_FILE = os.path.join(_DATA_DIR, "recherches.json")
HISTORIQUE_FILE = os.path.join(_DATA_DIR, "historique.json")
CIBLES_FILE     = os.path.join(_DATA_DIR, "cibles.json")

_lock = threading.RLock()
_favoris_cache: Optional[list] = None


def _load(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── Favoris ──────────────────────────────────────────────────────────────────

def charger_favoris() -> list:
    global _favoris_cache
    with _lock:
        if _favoris_cache is None:
            _favoris_cache = _load(FAVORIS_FILE)
        return list(_favoris_cache)

def est_favori(id_) -> bool:
    return any(str(f["id"]) == str(id_) for f in charger_favoris())

def toggle_favori(annonce) -> bool:
    global _favoris_cache
    with _lock:
        favs = _load(FAVORIS_FILE)
        id_  = str(annonce.id)
        if any(f["id"] == id_ for f in favs):
            favs = [f for f in favs if f["id"] != id_]
            _save(FAVORIS_FILE, favs)
            _favoris_cache = favs
            return False
        favs.append({
            "id": id_, "title": annonce.title, "price": annonce.price,
            "currency": annonce.currency, "url": annonce.url,
            "image_url": annonce.image_url, "brand": annonce.brand,
            "size": annonce.size, "vendeur": getattr(annonce, "vendeur_nom", ""),
            "pays": getattr(annonce, "pays", ""),
        })
        _save(FAVORIS_FILE, favs)
        _favoris_cache = favs
        return True

def supprimer_favori(id_):
    global _favoris_cache
    with _lock:
        favs = [f for f in _load(FAVORIS_FILE) if str(f["id"]) != str(id_)]
        _save(FAVORIS_FILE, favs)
        _favoris_cache = favs

def get_favori(id_) -> dict:
    for f in charger_favoris():
        if str(f["id"]) == str(id_):
            return f
    return None

# ─── Recherches sauvegardées ───────────────────────────────────────────────────

def charger_recherches() -> list:
    with _lock:
        return _load(RECHERCHES_FILE)

def sauvegarder_recherche(nom: str, mots_cles: str, prix_min, prix_max,
                           pays: str = "🇫🇷 France", ordre: str = "newest_first"):
    with _lock:
        recs = _load(RECHERCHES_FILE)
        for r in recs:
            if r["nom"] == nom:
                r.update({"mots_cles": mots_cles, "prix_min": prix_min,
                           "prix_max": prix_max, "pays": pays, "ordre": ordre})
                _save(RECHERCHES_FILE, recs)
                return
        recs.append({"nom": nom, "mots_cles": mots_cles, "prix_min": prix_min,
                     "prix_max": prix_max, "pays": pays, "ordre": ordre})
        _save(RECHERCHES_FILE, recs)

def supprimer_recherche(nom: str):
    with _lock:
        recs = [r for r in _load(RECHERCHES_FILE) if r["nom"] != nom]
        _save(RECHERCHES_FILE, recs)

# ─── Historique des prix ───────────────────────────────────────────────────────

def enregistrer_historique(annonces: list):
    with _lock:
        histo = _load(HISTORIQUE_FILE)
        if not isinstance(histo, dict):
            histo = {}
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for a in annonces:
            id_ = str(a.id)
            pts = histo.setdefault(id_, [])
            if not pts or pts[-1]["price"] != a.price:
                pts.append({"date": now, "price": a.price, "title": a.title})
            if len(pts) > 60:
                histo[id_] = pts[-60:]
        _save(HISTORIQUE_FILE, histo)

def charger_historique(id_: str) -> list:
    with _lock:
        histo = _load(HISTORIQUE_FILE)
    if not isinstance(histo, dict):
        return []
    return histo.get(str(id_), [])

def purger_historique_ancien(jours: int = 30):
    with _lock:
        histo = _load(HISTORIQUE_FILE)
        if not isinstance(histo, dict):
            return
        limite = datetime.datetime.now() - datetime.timedelta(days=jours)
        a_supprimer = []
        for id_, pts in histo.items():
            if pts:
                try:
                    dernier = datetime.datetime.strptime(pts[-1]["date"], "%Y-%m-%d %H:%M")
                    if dernier < limite:
                        a_supprimer.append(id_)
                except (ValueError, KeyError):
                    pass
        for id_ in a_supprimer:
            del histo[id_]
        _save(HISTORIQUE_FILE, histo)
        return len(a_supprimer)

# ─── Statistiques ─────────────────────────────────────────────────────────────

def calculer_stats(annonces: list) -> dict:
    if not annonces:
        return {}
    prices   = [a.price for a in annonces if a.price > 0]
    brands   = {}
    etats    = {}
    vendeurs = {}
    for a in annonces:
        if a.brand:    brands[a.brand]         = brands.get(a.brand, 0) + 1
        if a.condition: etats[a.condition]     = etats.get(a.condition, 0) + 1
        if a.vendeur_nom: vendeurs[a.vendeur_nom] = vendeurs.get(a.vendeur_nom, 0) + 1
    return {
        "total":        len(annonces),
        "prix_moyen":   sum(prices) / len(prices) if prices else 0,
        "prix_min":     min(prices) if prices else 0,
        "prix_max":     max(prices) if prices else 0,
        "prix_median":  sorted(prices)[len(prices) // 2] if prices else 0,
        "top_brands":   sorted(brands.items(),   key=lambda x: x[1], reverse=True)[:5],
        "etats":        sorted(etats.items(),    key=lambda x: x[1], reverse=True),
        "top_vendeurs": sorted(vendeurs.items(), key=lambda x: x[1], reverse=True)[:5],
        "avec_image":   sum(1 for a in annonces if a.image_url),
    }

# ─── File de ciblage ──────────────────────────────────────────────────────────
# Statuts possibles : "en_attente" | "traite" | "ignore"

def charger_cibles() -> list:
    with _lock:
        raw = _load(CIBLES_FILE)
        return raw if isinstance(raw, list) else []

def est_cible(id_) -> bool:
    return any(str(c["id"]) == str(id_) for c in charger_cibles())

def ajouter_cible(annonce, analyse=None) -> bool:
    """
    Ajoute une annonce à la file de ciblage.
    analyse : objet AnalysePrix optionnel — enrichit l'entrée.
    Retourne True si ajouté, False si déjà présent.
    """
    with _lock:
        cibles = _load(CIBLES_FILE)
        if not isinstance(cibles, list):
            cibles = []
        id_ = str(annonce.id)
        if any(c["id"] == id_ for c in cibles):
            return False
        cibles.append({
            "id":              id_,
            "title":           annonce.title,
            "price":           annonce.price,
            "currency":        annonce.currency,
            "url":             annonce.url,
            "image_url":       getattr(annonce, "image_url", ""),
            "brand":           getattr(annonce, "brand", ""),
            "size":            getattr(annonce, "size", ""),
            "condition":       getattr(annonce, "condition", ""),
            "vendeur":         getattr(annonce, "vendeur_nom", ""),
            "ajoute_le":       datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "statut":          "en_attente",
            "prix_suggere":    round(analyse.prix_suggere, 2)      if analyse else None,
            "reduction_pct":   round(analyse.reduction_pct, 1)     if analyse else None,
            "strategie":       analyse.strategie                   if analyse else None,
            "score":           analyse.score                       if analyse else None,
            "message_suggere": analyse.message_suggere             if analyse else "",
        })
        _save(CIBLES_FILE, cibles)
        return True

def retirer_cible(id_):
    with _lock:
        cibles = [c for c in charger_cibles() if str(c["id"]) != str(id_)]
        _save(CIBLES_FILE, cibles)

def marquer_cible_traitee(id_):
    with _lock:
        cibles = charger_cibles()
        for c in cibles:
            if str(c["id"]) == str(id_):
                c["statut"]    = "traite"
                c["traite_le"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        _save(CIBLES_FILE, cibles)

def marquer_cible_ignoree(id_):
    with _lock:
        cibles = charger_cibles()
        for c in cibles:
            if str(c["id"]) == str(id_):
                c["statut"] = "ignore"
        _save(CIBLES_FILE, cibles)

def vider_cibles_traitees():
    with _lock:
        cibles = [c for c in charger_cibles() if c.get("statut") == "en_attente"]
        _save(CIBLES_FILE, cibles)
