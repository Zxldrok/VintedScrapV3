"""
scraper.py — Module de scraping pour Vinted (multi-pays)
"""

import requests, json, re, csv, time, logging, unicodedata
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── Multi-Pays ────────────────────────────────────────────────────────────────
PAYS_DISPONIBLES = {
    "🇫🇷 France":       {"url": "https://www.vinted.fr",      "currency": "EUR", "lang": "fr-FR"},
    "🇧🇪 Belgique":     {"url": "https://www.vinted.be",      "currency": "EUR", "lang": "fr-BE"},
    "🇩🇪 Allemagne":    {"url": "https://www.vinted.de",      "currency": "EUR", "lang": "de-DE"},
    "🇪🇸 Espagne":      {"url": "https://www.vinted.es",      "currency": "EUR", "lang": "es-ES"},
    "🇮🇹 Italie":       {"url": "https://www.vinted.it",      "currency": "EUR", "lang": "it-IT"},
    "🇳🇱 Pays-Bas":     {"url": "https://www.vinted.nl",      "currency": "EUR", "lang": "nl-NL"},
    "🇵🇱 Pologne":      {"url": "https://www.vinted.pl",      "currency": "PLN", "lang": "pl-PL"},
    "🇨🇿 Tchéquie":     {"url": "https://www.vinted.cz",      "currency": "CZK", "lang": "cs-CZ"},
    "🇸🇰 Slovaquie":    {"url": "https://www.vinted.sk",      "currency": "EUR", "lang": "sk-SK"},
    "🇭🇺 Hongrie":      {"url": "https://www.vinted.hu",      "currency": "HUF", "lang": "hu-HU"},
    "🇷🇴 Roumanie":     {"url": "https://www.vinted.ro",      "currency": "RON", "lang": "ro-RO"},
    "🇵🇹 Portugal":     {"url": "https://www.vinted.pt",      "currency": "EUR", "lang": "pt-PT"},
    "🇬🇧 Royaume-Uni":  {"url": "https://www.vinted.co.uk",   "currency": "GBP", "lang": "en-GB"},
    "🇺🇸 États-Unis":   {"url": "https://www.vinted.com",     "currency": "USD", "lang": "en-US"},
    "🇦🇹 Autriche":     {"url": "https://www.vinted.at",      "currency": "EUR", "lang": "de-AT"},
    "🇱🇹 Lituanie":     {"url": "https://www.vinted.lt",      "currency": "EUR", "lang": "lt-LT"},
    "🇱🇻 Lettonie":     {"url": "https://www.vinted.lv",      "currency": "EUR", "lang": "lv-LV"},
    "🇪🇪 Estonie":      {"url": "https://www.vinted.ee",      "currency": "EUR", "lang": "et-EE"},
    "🇫🇮 Finlande":     {"url": "https://www.vinted.fi",      "currency": "EUR", "lang": "fi-FI"},
    "🇸🇪 Suède":        {"url": "https://www.vinted.se",      "currency": "SEK", "lang": "sv-SE"},
    "🇩🇰 Danemark":     {"url": "https://www.vinted.dk",      "currency": "DKK", "lang": "da-DK"},
    "🇬🇷 Grèce":        {"url": "https://www.vinted.gr",      "currency": "EUR", "lang": "el-GR"},
    "🇭🇷 Croatie":      {"url": "https://www.vinted.hr",      "currency": "EUR", "lang": "hr-HR"},
}

MAX_PAGES = 5

# ─── Couleurs Vinted ──────────────────────────────────────────────────────────
COULEURS = {
    "Noir": 1, "Gris": 2, "Blanc": 3, "Crème / Beige": 4,
    "Rose": 5, "Rouge": 6, "Orange": 7, "Jaune": 8,
    "Vert olive / kaki": 9, "Vert": 10, "Turquoise": 11,
    "Bleu": 12, "Lilas / Mauve": 13, "Violet": 14,
    "Marron / Caramel": 15, "Or": 16, "Argent": 17, "Multicolore": 18,
}

# ─── Catégories Vinted ────────────────────────────────────────────────────────
CATEGORIES = {
    "Femmes - Hauts": 1904, "Femmes - Pantalons": 1906, "Femmes - Robes": 1231,
    "Femmes - Manteaux": 1232, "Femmes - Chaussures": 16, "Femmes - Sacs": 227,
    "Hommes - Hauts": 4, "Hommes - Pantalons": 6, "Hommes - Manteaux": 259,
    "Hommes - Chaussures": 17, "Enfants - Vêtements": 222, "Enfants - Chaussures": 223,
    "Sport": 76, "Maison": 31, "Livres": 79, "Électronique": 2350,
    "Jeux / Jouets": 258, "Loisirs": 84,
}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def _normaliser(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())

def _filtrer_par_titre(annonces: list, mots_cles: str) -> list:
    mots = [_normaliser(m) for m in mots_cles.split() if m.strip()]
    if not mots:
        return annonces
    return [a for a in annonces if all(m in _normaliser(a.title) for m in mots)]

# ─── Conditions ───────────────────────────────────────────────────────────────
_CONDITIONS_BY_ID = {
    6: "Neuf avec étiquette", 4: "Neuf sans étiquette",
    1: "Très bon état", 2: "Bon état", 3: "Satisfaisant",
}
_CONDITION_ID_BY_STR = {
    "neuf avec étiquette": 6, "neuf sans étiquette": 4,
    "très bon état": 1, "bon état": 2, "satisfaisant": 3,
}

# ─── Modèle Annonce ───────────────────────────────────────────────────────────
class Annonce:
    SYMBOLES = {"EUR": "€", "GBP": "£", "USD": "$", "PLN": "zł",
                "CZK": "Kč", "HUF": "Ft", "RON": "lei", "SEK": "kr", "DKK": "kr"}

    def __init__(self, data: dict, base_url: str = "https://www.vinted.fr"):
        self._base_url    = base_url
        self.id           = data.get("id", "")
        self.title        = data.get("title", "Sans titre")
        self.price        = self._parse_price(data)
        self.currency     = self._parse_currency(data)
        self.url          = self._parse_url(data)
        self.image_url    = self._parse_image(data)
        self.size         = data.get("size_title", "")
        self.brand        = data.get("brand_title", "")
        self.condition_id = self._parse_condition_id(data)
        self.condition    = _CONDITIONS_BY_ID.get(self.condition_id, "")
        self.description  = ""
        user = data.get("user", {})
        self.vendeur_id   = str(user.get("id", ""))
        self.vendeur_nom  = user.get("login", "")
        self.pays         = data.get("country_iso_code", "")

    def _parse_condition_id(self, data):
        raw = data.get("status", 0)
        if isinstance(raw, int): return raw
        if isinstance(raw, str):
            try: return int(raw)
            except ValueError: pass
            return _CONDITION_ID_BY_STR.get(raw.lower().strip(), 0)
        return 0

    def _parse_price(self, data):
        try:
            p = data.get("price", 0)
            if isinstance(p, dict): return float(p.get("amount", 0))
            if p: return float(p)
            return float(data.get("price_numeric", 0))
        except (ValueError, TypeError): return 0.0

    def _parse_currency(self, data):
        p = data.get("price", {})
        if isinstance(p, dict): return p.get("currency_code", "EUR")
        return data.get("currency", "EUR")

    def _parse_url(self, data):
        raw = data.get("url", "") or ""
        if raw.startswith("http"): return raw
        if raw.startswith("/"): return f"{self._base_url}{raw}"
        if raw: return f"{self._base_url}/items/{raw}"
        return f"{self._base_url}/items/{self.id}"

    def _parse_image(self, data):
        photos = data.get("photos", [])
        if photos:
            p = photos[0]
            return p.get("full_size_url") or p.get("url") or p.get("src", "")
        return None

    def prix_affiche(self) -> str:
        sym = self.SYMBOLES.get(self.currency, self.currency)
        return f"{self.price:.2f} {sym}"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "price": self.price,
            "currency": self.currency, "url": self.url, "image_url": self.image_url,
            "size": self.size, "brand": self.brand, "condition": self.condition,
            "description": self.description, "vendeur": self.vendeur_nom, "pays": self.pays,
        }

    def __repr__(self):
        return f"<Annonce '{self.title}' — {self.prix_affiche()}>"

# ─── Scraper Principal ────────────────────────────────────────────────────────
class VintedScraper:
    def __init__(self, pays: str = "🇫🇷 France", proxies: Optional[dict] = None,
                 delai_entre_requetes: float = 1.0):
        self.delai   = delai_entre_requetes
        self.proxies = proxies or {}
        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        self.set_pays(pays)

    def set_pays(self, pays: str):
        """Change de pays : reconfigure URL, headers, cookies et token CSRF."""
        config = PAYS_DISPONIBLES.get(pays, PAYS_DISPONIBLES[next(iter(PAYS_DISPONIBLES))])
        self.pays_actuel = pays
        self.base_url    = config["url"]
        self.api_url     = f"{self.base_url}/api/v2/catalog/items"
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36"),
            "Accept":           "application/json, text/plain, */*",
            "Accept-Language":  f"{config['lang']},en;q=0.8",
            "Referer":          self.base_url + "/",
            "Origin":           self.base_url,
        }
        self.session.headers.clear()
        self.session.headers.update(headers)
        self.session.cookies.clear()
        logger.info(f"Session → {self.base_url}")
        try:
            r = self.session.get(self.base_url, timeout=10)
            csrf = self.session.cookies.get("XSRF-TOKEN", "")
            if csrf:
                self.session.headers["X-CSRF-Token"] = csrf
                logger.info("CSRF token ok.")
            logger.info("Cookies obtenus.")
        except requests.RequestException as e:
            logger.warning(f"Init session : {e}")

    def close(self):
        self.session.close()

    def rechercher(self, mots_cles: str, prix_min: Optional[float] = None,
                   prix_max: Optional[float] = None, order: str = "newest_first",
                   brand_id: Optional[int] = None, size_id: Optional[int] = None,
                   color_id: Optional[int] = None, category_id: Optional[int] = None,
                   vendeur_id: Optional[str] = None,
                   max_pages: int = 5, par_page: int = 96) -> list:
        if not mots_cles.strip():
            raise ValueError("Mots-clés vides.")
        query = mots_cles.strip()
        tous_items = []
        for page in range(1, max_pages + 1):
            params: dict = {"search_text": query, "per_page": par_page,
                            "page": page, "order": order}
            if prix_min    is not None: params["price_from"]    = prix_min
            if prix_max    is not None: params["price_to"]      = prix_max
            if brand_id    is not None: params["brand_ids[]"]   = brand_id
            if size_id     is not None: params["size_ids[]"]    = size_id
            if color_id    is not None: params["color_ids[]"]   = color_id
            if category_id is not None: params["catalog_ids[]"] = category_id
            if vendeur_id  is not None: params["user_id"]       = vendeur_id
            try:
                r = self.session.get(self.api_url, params=params, timeout=15)
                r.raise_for_status()
            except requests.exceptions.ConnectionError:
                logger.error("Connexion impossible."); break
            except requests.exceptions.Timeout:
                logger.error("Timeout."); break
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP {e.response.status_code}"); break
            try:
                data = r.json()
            except json.JSONDecodeError:
                logger.error("Réponse non-JSON."); break
            items = data.get("items", [])
            if not items: break
            tous_items.extend(items)
            logger.info(f"Page {page} → {len(items)} annonces.")
            if len(items) < par_page: break
            time.sleep(self.delai)
        annonces = [Annonce(it, self.base_url) for it in tous_items]
        filtrees = _filtrer_par_titre(annonces, query)
        logger.info(f"Filtrage : {len(annonces)} → {len(filtrees)}.")
        return filtrees

    def rechercher_multi(self, mots_cles: str, prix_min=None, prix_max=None,
                         order="newest_first", brand_id=None, size_id=None,
                         color_id=None, category_id=None, vendeur_id=None) -> list:
        """Recherche multi-termes (virgule), dédupliqués, avec tous les filtres."""
        termes = [t.strip() for t in mots_cles.split(",") if t.strip()]
        if not termes:
            raise ValueError("Mots-clés vides.")
        resultats, vus = [], set()
        for terme in termes:
            logger.info(f"Recherche : '{terme}'")
            for a in self.rechercher(terme, prix_min, prix_max, order,
                                     brand_id, size_id, color_id, category_id,
                                     vendeur_id, max_pages=MAX_PAGES):
                if a.id not in vus:
                    vus.add(a.id)
                    resultats.append(a)
        logger.info(f"Multi terminé : {len(resultats)} uniques.")
        return resultats

    def fetch_description(self, annonce) -> str:
        """Récupère la description via JSON-LD de la page produit."""
        try:
            r = self.session.get(annonce.url, timeout=12)
            r.raise_for_status()
            match = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                              r.text, re.DOTALL | re.IGNORECASE)
            if match:
                data = json.loads(match.group(1))
                desc = data.get("description", "")
                if desc:
                    annonce.description = desc
                    return desc
            return ""
        except Exception as e:
            logger.error(f"fetch_description : {e}")
            return ""

    @staticmethod
    def exporter_csv(annonces: list, nom_fichier: str = "resultats_vinted.csv"):
        if not annonces:
            logger.warning("Aucune annonce à exporter.")
            return
        cles = ["id", "title", "price", "currency", "url", "image_url",
                "size", "brand", "condition", "description", "vendeur", "pays"]
        try:
            with open(nom_fichier, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=cles)
                writer.writeheader()
                for a in annonces:
                    writer.writerow(a.to_dict())
            logger.info(f"Export CSV : {nom_fichier} ({len(annonces)} lignes).")
        except IOError as e:
            logger.error(f"Export CSV : {e}")
