"""
comparateur_prix.py — Comparateur de prix multi-plateformes
Recherche un article sur 29 sites de seconde main / occasion depuis une annonce Vinted.
"""

import re, urllib.parse, webbrowser, logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)

@dataclass
class Plateforme:
    nom:       str
    icone:     str
    couleur:   str
    url_tpl:   str
    categorie: str = "generaliste"

PLATEFORMES: List[Plateforme] = [
    Plateforme("Vestiaire Collective", "P", "#C9A96E",
               "https://fr.vestiairecollective.com/search/?q={q}", "mode"),
    Plateforme("Reepeat",              "R", "#6C63FF",
               "https://www.reepeat.fr/search?q={q}", "mode"),
    Plateforme("Selency",              "S", "#F4A261",
               "https://selency.fr/search?q={q}", "mode"),
    Plateforme("Lucky Find",           "L", "#2ECC71",
               "https://www.luckyfind.fr/search?query={q}", "mode"),
    Plateforme("Label Emmaus",         "E", "#27AE60",
               "https://www.label-emmaus.co/fr/catalogsearch/result/?q={q}", "mode"),
    Plateforme("Leboncoin",            "B", "#E05206",
               "https://www.leboncoin.fr/recherche?text={q}", "generaliste"),
    Plateforme("eBay France",          "e", "#0064D2",
               "https://www.ebay.fr/sch/i.html?_nkw={q}&_sop=15", "generaliste"),
    Plateforme("Rakuten",              "r", "#BF0000",
               "https://fr.shopping.rakuten.com/search?keyword={q}&c=10461&p=occasion", "generaliste"),
    Plateforme("Facebook Marketplace", "f", "#1877F2",
               "https://www.facebook.com/marketplace/search/?query={q}", "generaliste"),
    Plateforme("Cdiscount Occasion",   "C", "#E0A800",
               "https://www.cdiscount.com/search/10/occasion+{q}.html", "generaliste"),
    Plateforme("Momox",                "M", "#FF6B35",
               "https://www.momox-shop.fr/catalogsearch/result/?q={q}", "generaliste"),
    Plateforme("Dealabs",              "D", "#E40046",
               "https://www.dealabs.com/search?q={q}", "generaliste"),
    Plateforme("Gens de Confiance",    "G", "#3498DB",
               "https://www.gensdeconfiance.fr/list?search={q}", "generaliste"),
    Plateforme("Back Market",          "B", "#25C37A",
               "https://www.backmarket.fr/fr-fr/search?q={q}", "hifi"),
    Plateforme("CertiDeal",            "C", "#0082C8",
               "https://www.certideal.fr/search?q={q}", "hifi"),
    Plateforme("Recommerce",           "R", "#7B2FBE",
               "https://www.recommerce.com/fr/search?q={q}", "hifi"),
    Plateforme("Fnac 2nde Vie",        "F", "#F7A600",
               "https://www.fnac.com/SearchResult/ResultSet.aspx?SCat=0&Search={q}&Tra=1", "hifi"),
    Plateforme("Darty Occasion",       "D", "#E2001A",
               "https://www.darty.com/nav/extra/search.html?text={q}&occasion=true", "hifi"),
    Plateforme("Amazon Warehouse",     "A", "#FF9900",
               "https://www.amazon.fr/s?k={q}&rh=p_n_condition-type%3A3&s=price-asc-rank", "hifi"),
    Plateforme("Beebs",                "b", "#FF6B9D",
               "https://beebs.app/en/listings?q={q}", "hifi"),
    Plateforme("Barooders",            "B", "#2980B9",
               "https://barooders.com/pages/search-results-page?q={q}", "sport"),
    Plateforme("Campsider",            "C", "#16A085",
               "https://www.campsider.com/recherche?q={q}", "sport"),
    Plateforme("Troc-Velo",            "V", "#E67E22",
               "https://www.troc-velo.com/recherche.php?q={q}", "velo"),
    Plateforme("Occaz-moteur",         "O", "#C0392B",
               "https://www.occaz-moteur.com/recherche?q={q}", "sport"),
    Plateforme("Gamecash",             "G", "#6C3483",
               "https://www.gamecash.fr/search?search_query={q}", "jeux"),
    Plateforme("Cash Converters",      "C", "#1ABC9C",
               "https://www.cashconverters.fr/search?q={q}", "jeux"),
    Plateforme("Easy Cash",            "E", "#117A65",
               "https://www.easycash.fr/recherche?q={q}", "jeux"),
    Plateforme("Izidore",              "I", "#8E44AD",
               "https://www.izidore.fr/search?q={q}", "generaliste"),
    Plateforme("YouClam",              "Y", "#1A5276",
               "https://www.youclam.com/search?q={q}", "generaliste"),
]

CATEGORIES_ORDRE = ["generaliste", "mode", "hifi", "sport", "velo", "jeux"]

LABELS_CAT = {
    "generaliste": "Generaliste",
    "mode":        "Mode",
    "hifi":        "High-Tech",
    "sport":       "Sport",
    "velo":        "Velo",
    "jeux":        "Jeux",
}


def _classer_annonce(annonce) -> str:
    titre = f"{getattr(annonce, 'title', '')} {getattr(annonce, 'brand', '')}".lower()
    if any(token in titre for token in ("iphone", "samsung", "pixel", "macbook", "ipad", "switch", "ps5", "xbox", "console", "phone")):
        return "hifi"
    if any(token in titre for token in ("velo", "bike", "bmx", "route", "gravel")):
        return "velo"
    if any(token in titre for token in ("pokemon", "one piece", "yugioh", "funko", "lego", "game", "jeu", "switch", "playstation")):
        return "jeux"
    if any(token in titre for token in ("maillot", "ski", "snow", "running", "fitness", "velo", "raquette", "golf")):
        return "sport"
    if getattr(annonce, "size", "") or any(token in titre for token in ("nike", "adidas", "zara", "lv", "gucci", "jacket", "shirt", "sac", "robe")):
        return "mode"
    return "generaliste"


def _nettoyer_query(titre: str, marque: str = "") -> str:
    stop = {"taille", "xl", "xxl", "xs", "neuf", "tres", "bon", "etat",
            "occasion", "comme", "jamais", "porte", "vendu", "lot", "avec",
            "pour", "sans", "piece", "pcs"}
    mots = re.sub(r"[^\w\s]", " ", titre.lower()).split()
    mots_filtres = [m for m in mots if m not in stop and len(m) > 1]
    query_parts = []
    if marque and marque.lower() not in [m.lower() for m in mots_filtres[:4]]:
        query_parts.append(marque)
    query_parts.extend(mots_filtres[:4])
    return " ".join(query_parts[:5])


def construire_url(plateforme: Plateforme, query: str) -> str:
    q_enc = urllib.parse.quote_plus(query)
    return plateforme.url_tpl.format(q=q_enc)


def ouvrir_comparaison(annonce, plateformes_selectionnees=None):
    query = _nettoyer_query(annonce.title, getattr(annonce, "brand", ""))
    cibles = plateformes_selectionnees or PLATEFORMES
    for p in cibles:
        url = construire_url(p, query)
        webbrowser.open(url)


def plateformes_par_categorie() -> dict:
    result = {}
    for cat in CATEGORIES_ORDRE:
        result[cat] = [p for p in PLATEFORMES if p.categorie == cat]
    return result


def get_query_annonce(annonce) -> str:
    return _nettoyer_query(annonce.title, getattr(annonce, "brand", ""))


def plateformes_recommandees(annonce) -> list[Plateforme]:
    categorie = _classer_annonce(annonce)
    query = get_query_annonce(annonce).lower()
    recommended = [p for p in PLATEFORMES if p.categorie == categorie]
    if categorie != "generaliste":
        recommended.extend(p for p in PLATEFORMES if p.categorie == "generaliste")

    if "one piece" in query or "pokemon" in query or "lego" in query:
        bonus = {"eBay France", "Rakuten", "Leboncoin", "Gamecash", "Easy Cash"}
        recommended.extend(p for p in PLATEFORMES if p.nom in bonus)

    seen = set()
    ordered = []
    for plateforme in recommended:
        if plateforme.nom not in seen:
            seen.add(plateforme.nom)
            ordered.append(plateforme)
    return ordered[:8]


def explication_recommandation(annonce) -> str:
    categorie = _classer_annonce(annonce)
    labels = {
        "mode": "mode et seconde main textile",
        "hifi": "high-tech et electronique",
        "sport": "equipement sport",
        "velo": "velo et equipement associe",
        "jeux": "jeux, cartes et collection",
        "generaliste": "plateformes generalistes",
    }
    return f"Selection optimisee pour {labels.get(categorie, 'le produit detecte')}."
