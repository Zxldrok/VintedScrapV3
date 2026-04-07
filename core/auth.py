"""
auth.py — Authentification compte Vinted (lecture seule)
Gère la connexion, la session authentifiée et le stockage chiffré des credentials.
"""

import json, os, base64, threading, logging
import requests

logger = logging.getLogger(__name__)

_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR   = os.path.join(_DIR, "data")
_CREDS_FILE = os.path.join(_DATA_DIR, "compte.json")


# ─── Chiffrement léger (XOR + base64, sans dépendance externe) ───────────────

def _cle() -> bytes:
    import socket
    raw = socket.gethostname() + "VintedScrap_2025"
    return (raw * 8).encode()[:32]

def _chiffrer(texte: str) -> str:
    cle  = _cle()
    data = texte.encode("utf-8")
    xored = bytes(b ^ cle[i % len(cle)] for i, b in enumerate(data))
    return base64.b64encode(xored).decode()

def _dechiffrer(texte: str) -> str:
    cle  = _cle()
    data = base64.b64decode(texte.encode())
    xored = bytes(b ^ cle[i % len(cle)] for i, b in enumerate(data))
    return xored.decode("utf-8")


# ─── Stockage credentials ─────────────────────────────────────────────────────

def sauvegarder_credentials(email: str, password: str):
    payload = {"email": _chiffrer(email), "password": _chiffrer(password)}
    with open(_CREDS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f)

def charger_credentials():
    try:
        with open(_CREDS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return _dechiffrer(d["email"]), _dechiffrer(d["password"])
    except Exception:
        return None, None

def supprimer_credentials():
    try:
        os.remove(_CREDS_FILE)
    except FileNotFoundError:
        pass

def credentials_existent() -> bool:
    return os.path.exists(_CREDS_FILE)


# ─── Session Vinted authentifiée ──────────────────────────────────────────────

class VintedAuth:
    """
    Gère la session Vinted authentifiée.
    Toutes les actions sont en LECTURE SEULE.
    L'utilisateur ouvre lui-même les annonces pour envoyer des offres.
    """

    # Endpoints tentés dans l'ordre (Vinted change régulièrement son API)
    LOGIN_URLS = [
        "https://www.vinted.fr/api/v2/users/login",
        "https://www.vinted.fr/api/v2/sessions",
        "https://www.vinted.fr/oauth/token",
    ]
    ME_URL   = "https://www.vinted.fr/api/v2/users/me"
    BASE_URL = "https://www.vinted.fr"

    def __init__(self):
        self.session  = requests.Session()
        self.connecte = False
        self.profil   = {}
        self._lock    = threading.Lock()
        self._configurer_headers()

    def _configurer_headers(self):
        self.session.headers.update({
            "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"),
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer":         self.BASE_URL,
            "Origin":          self.BASE_URL,
        })

    def _obtenir_csrf(self):
        try:
            self.session.get(self.BASE_URL, timeout=10)
            csrf = self.session.cookies.get("XSRF-TOKEN", "")
            if csrf:
                self.session.headers["X-CSRF-Token"] = csrf
        except requests.RequestException as e:
            logger.warning(f"CSRF : {e}")

    def connecter(self, email: str, password: str) -> dict:
        with self._lock:
            self._obtenir_csrf()
            # Corps de la requête selon l'endpoint
            payloads = [
                {"login": email, "password": password, "remember": True},   # /users/login
                {"login": email, "password": password, "remember": True},   # /sessions
                {"grant_type": "password", "username": email, "password": password},  # /oauth/token
            ]
            last_status = None
            for url, payload in zip(self.LOGIN_URLS, payloads):
                try:
                    r = self.session.post(url, json=payload, timeout=15)
                except requests.RequestException as e:
                    return {"ok": False, "erreur": f"Erreur réseau : {e}"}

                last_status = r.status_code
                if r.status_code == 404:
                    logger.info(f"Endpoint {url} → 404, essai suivant…")
                    continue  # Essayer l'endpoint suivant
                if r.status_code == 401:
                    return {"ok": False, "erreur": "Email ou mot de passe incorrect."}
                if r.status_code == 429:
                    return {"ok": False, "erreur": "Trop de tentatives. Réessayez plus tard."}
                if r.status_code == 200:
                    try:
                        body = r.json()
                        user = body.get("user") or body.get("data", {}).get("user", {})
                        if not user and "login" in body:
                            user = body  # certains endpoints renvoient l'user directement
                        self.profil   = self._extraire_profil(user)
                        self.connecte = True
                        logger.info(f"Connecté via {url} : {self.profil.get('login')}")
                        return {"ok": True, "profil": self.profil}
                    except Exception as e:
                        return {"ok": False, "erreur": f"Réponse inattendue : {e}"}
                # Autre code HTTP
                logger.info(f"Endpoint {url} → {r.status_code}")

            # Tous les endpoints ont échoué
            if last_status == 404:
                return {
                    "ok": False,
                    "erreur": (
                        "L'API de connexion Vinted est inaccessible (404).\n"
                        "L'application fonctionne sans compte — la connexion\n"
                        "est optionnelle (profil / solde uniquement)."
                    )
                }
            return {"ok": False, "erreur": f"Erreur Vinted ({last_status})."}

    def deconnecter(self):
        with self._lock:
            self.session.cookies.clear()
            self.connecte = False
            self.profil   = {}
            self._configurer_headers()

    def rafraichir_profil(self) -> dict:
        if not self.connecte:
            return {}
        try:
            r = self.session.get(self.ME_URL, timeout=10)
            if r.status_code == 200:
                self.profil = self._extraire_profil(r.json().get("user", {}))
                return self.profil
        except Exception as e:
            logger.error(f"rafraichir_profil : {e}")
        return self.profil

    def _extraire_profil(self, user: dict) -> dict:
        photo = user.get("photo", {}) or {}
        bal   = user.get("balance", {})
        return {
            "id":          user.get("id", ""),
            "login":       user.get("login", ""),
            "email":       user.get("email", ""),
            "prenom":      user.get("real_name", ""),
            "photo_url":   photo.get("full_size_url") or photo.get("url", ""),
            "nb_avis":     user.get("feedback_count", 0),
            "note":        round(float(user.get("feedback_reputation", 0)) * 5, 1),
            "nb_articles": user.get("item_count", 0),
            "solde":       float(bal.get("amount", 0)) if isinstance(bal, dict) else float(bal or 0),
            "devise":      "EUR",
        }

    def est_connecte(self) -> bool:
        return self.connecte

    def close(self):
        self.session.close()


# ─── Singleton ────────────────────────────────────────────────────────────────

_instance: VintedAuth | None = None

def get_auth() -> VintedAuth:
    global _instance
    if _instance is None:
        _instance = VintedAuth()
    return _instance
