"""
core/plugin_base.py — Classe de base que tout plugin doit hériter
=================================================================
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from core.plugin_api import PluginAPI


class PluginBase(ABC):
    """
    Classe abstraite de base pour toutes les extensions VintedScrap.

    Usage minimal :
        class Plugin(PluginBase):
            def on_load(self):
                self.api.register_hook("on_results", self.handle_results)

            def on_unload(self):
                pass  # nettoyage optionnel
    """

    def __init__(self, api: PluginAPI):
        self.api = api

    @abstractmethod
    def on_load(self) -> None:
        """Appelé à l'activation du plugin. Enregistrez vos hooks ici."""
        ...

    @abstractmethod
    def on_unload(self) -> None:
        """Appelé à la désactivation. Libérez vos ressources ici."""
        ...

    def get_widget(self, parent) -> object | None:
        """
        Optionnel — retourner un widget CTkFrame pour l'onglet Extensions.
        Nécessite la permission 'ui_widget'.
        """
        return None
