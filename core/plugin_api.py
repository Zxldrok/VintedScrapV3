"""
core/plugin_api.py — API publique exposée aux extensions VintedScrap
======================================================================
Chaque plugin reçoit une instance de PluginAPI au moment de son activation.
C'est la SEULE interface autorisée entre un plugin et l'application.
Les plugins n'ont JAMAIS accès direct à AppVinted, scraper, ou data.
"""

from __future__ import annotations
import threading
from typing import Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.plugin_manager import PluginManager

# ── Types de hooks disponibles ────────────────────────────────────────────────
HOOKS = {
    "on_results":        "Déclenché après chaque recherche (liste d'annonces)",
    "on_new_annonce":    "Déclenché pour chaque nouvelle annonce (alerte active)",
    "on_favori_added":   "Déclenché quand un favori est ajouté",
    "on_app_start":      "Déclenché au démarrage de l'application",
    "on_app_close":      "Déclenché à la fermeture de l'application",
    "on_sidebar_widget": "Permet d'ajouter un widget dans l'onglet Extensions",
}

# ── Permissions déclarables dans le manifest ──────────────────────────────────
PERMISSIONS = {
    "read_results":   "Lire les annonces des recherches",
    "read_favorites": "Lire les favoris de l'utilisateur",
    "write_data":     "Écrire des fichiers dans data/plugins/<nom>/",
    "network":        "Effectuer des requêtes HTTP sortantes",
    "notifications":  "Afficher des notifications toast",
    "ui_widget":      "Injecter un widget dans la sidebar",
}

class PluginAPI:
    """
    Interface sécurisée fournie à chaque plugin.
    Seules les méthodes publiques ci-dessous sont accessibles.
    """

    def __init__(self, plugin_name: str, permissions: list[str],
                 manager: "PluginManager", app_ref, toast_fn=None):
        self._name        = plugin_name
        self._permissions = set(permissions)
        self._manager     = manager
        self._app         = app_ref          # référence faible — usage interne uniquement
        self._hooks: dict[str, list[Callable]] = {h: [] for h in HOOKS}
        self._data_dir    = None             # initialisé par le manager si write_data accordé
        self._toast_fn    = toast_fn           # injecté par PluginManager depuis main

    # ── Enregistrement de hooks ───────────────────────────────────────────────

    def register_hook(self, hook_name: str, callback: Callable) -> None:
        """Enregistre une fonction callback sur un hook applicatif."""
        if hook_name not in HOOKS:
            raise ValueError(f"Hook inconnu : '{hook_name}'. Disponibles : {list(HOOKS)}")
        self._hooks[hook_name].append(callback)

    # ── Notifications ─────────────────────────────────────────────────────────

    def notify(self, titre: str, message: str) -> None:
        """Affiche une notification toast (permission 'notifications' requise)."""
        self._check_perm("notifications")
        if self._toast_fn:
            try:
                self._toast_fn(f"[{self._name}] {titre}", message)
            except Exception:
                pass

    # ── Accès données (lecture seule) ─────────────────────────────────────────

    def get_last_results(self) -> list[dict]:
        """Retourne les annonces du dernier résultat (permission 'read_results')."""
        self._check_perm("read_results")
        raw = getattr(self._app, "_annonces", [])
        return [self._annonce_to_dict(a) for a in raw]

    def get_favorites(self) -> list[dict]:
        """Retourne la liste des favoris (permission 'read_favorites')."""
        self._check_perm("read_favorites")
        from core import data
        return data.charger_favoris()

    # ── Stockage plugin (isolé) ───────────────────────────────────────────────

    def get_data_path(self) -> str:
        """Retourne le chemin du dossier de données isolé du plugin."""
        self._check_perm("write_data")
        return str(self._data_dir)

    # ── Requêtes réseau ───────────────────────────────────────────────────────

    def http_get(self, url: str, timeout: int = 10) -> dict:
        """Effectue un GET HTTP (permission 'network' requise). Retourne {status, text}."""
        self._check_perm("network")
        import requests
        r = requests.get(url, timeout=timeout)
        return {"status": r.status_code, "text": r.text}

    def http_post(self, url: str, json: dict = None, timeout: int = 10) -> dict:
        """Effectue un POST HTTP (permission 'network' requise)."""
        self._check_perm("network")
        import requests
        r = requests.post(url, json=json, timeout=timeout)
        return {"status": r.status_code, "text": r.text}

    # ── Utilitaires ───────────────────────────────────────────────────────────

    @property
    def plugin_name(self) -> str:
        return self._name

    # ── Privé ─────────────────────────────────────────────────────────────────

    def _check_perm(self, perm: str):
        if perm not in self._permissions:
            raise PermissionError(
                f"Plugin '{self._name}' : permission '{perm}' non déclarée dans le manifest.")

    @staticmethod
    def _annonce_to_dict(a) -> dict:
        return {
            "id":        str(a.id),
            "title":     a.title,
            "price":     a.price,
            "currency":  getattr(a, "currency", "EUR"),
            "brand":     a.brand,
            "size":      a.size,
            "condition": a.condition,
            "url":       a.url,
            "image_url": a.image_url,
        }
