"""
plugins/discord_notify/plugin.py
=================================
Exemple de plugin VintedScrap : notifie un webhook Discord à chaque
nouvelle annonce détectée par l'alerte automatique.

Pour tester :
  1. Créez un webhook sur votre serveur Discord (Paramètres > Intégrations)
  2. Collez l'URL dans la config du plugin via l'onglet Extensions
  3. Activez l'alerte automatique dans la sidebar
"""

import json
from pathlib import Path
from core.plugin_base import PluginBase
from core.plugin_api import PluginAPI

CONFIG_FILE = "config.json"


class Plugin(PluginBase):

    def __init__(self, api: PluginAPI):
        super().__init__(api)
        self._config: dict = {}

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def on_load(self):
        self._config = self._lire_config()
        self.api.register_hook("on_new_annonce", self._handle_new_annonce)
        self.api.register_hook("on_app_start",   self._handle_start)

    def on_unload(self):
        pass  # pas de ressources persistantes à libérer

    # ── Widget de configuration (affiché dans l'onglet Extensions) ────────────

    def get_widget(self, parent):
        import customtkinter as ctk
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="Webhook URL",
                     font=ctk.CTkFont(size=11), text_color="#B0B0B0"
        ).grid(row=0, column=0, sticky="w", pady=(6, 2))

        self._entry_url = ctk.CTkEntry(
            frame, placeholder_text="https://discord.com/api/webhooks/...",
            height=32, font=ctk.CTkFont(size=11))
        self._entry_url.insert(0, self._config.get("webhook_url", ""))
        self._entry_url.grid(row=1, column=0, sticky="ew")

        ctk.CTkLabel(frame, text="Prix max (€)",
                     font=ctk.CTkFont(size=11), text_color="#B0B0B0"
        ).grid(row=2, column=0, sticky="w", pady=(8, 2))

        self._entry_prix = ctk.CTkEntry(frame, placeholder_text="999",
                                        height=32, font=ctk.CTkFont(size=11))
        self._entry_prix.insert(0, str(self._config.get("prix_max", 999)))
        self._entry_prix.grid(row=3, column=0, sticky="ew")

        ctk.CTkButton(frame, text="💾  Enregistrer", height=32,
                      command=self._sauver_config_widget
        ).grid(row=4, column=0, pady=(10, 0), sticky="ew")

        return frame

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _handle_start(self):
        if not self._config.get("webhook_url"):
            self.api.notify("Discord Notifier",
                            "⚠️ Configurez votre webhook URL dans l'onglet Extensions.")

    def _handle_new_annonce(self, annonce: dict = None, **_):
        if not annonce:
            return
        webhook = self._config.get("webhook_url", "").strip()
        prix_max = float(self._config.get("prix_max", 999))

        if not webhook:
            return
        if annonce.get("price", 0) > prix_max:
            return

        payload = {
            "embeds": [{
                "title":       f"🛍️ {annonce['title']}",
                "url":         annonce["url"],
                "color":       0x00E5FF,
                "description": f"**{annonce['price']:.2f} €**  •  {annonce.get('condition', '')}",
                "thumbnail":   {"url": annonce.get("image_url", "")},
                "footer":      {"text": f"VintedScrap — {annonce.get('brand', '')} {annonce.get('size', '')}"}
            }]
        }
        try:
            result = self.api.http_post(webhook, json=payload, timeout=8)
            if result["status"] not in (200, 204):
                self.api.notify("Erreur Discord", f"HTTP {result['status']}")
        except Exception as e:
            self.api.notify("Erreur Discord", str(e))

    # ── Config persistante ────────────────────────────────────────────────────

    def _lire_config(self) -> dict:
        try:
            cfg = Path(self.api.get_data_path()) / CONFIG_FILE
            if cfg.exists():
                return json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _sauver_config_widget(self):
        self._config["webhook_url"] = self._entry_url.get().strip()
        try:
            self._config["prix_max"] = float(self._entry_prix.get())
        except ValueError:
            pass
        cfg = Path(self.api.get_data_path()) / CONFIG_FILE
        cfg.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
        self.api.notify("Config sauvegardée", "Paramètres Discord mis à jour ✓")
