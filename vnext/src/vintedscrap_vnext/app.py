from __future__ import annotations

import customtkinter as ctk

from .config import build_paths
from .models import Listing, UserEvent
from .profile_service import rebuild_profile
from .relevance import score_listing
from .repositories import JsonEventRepository


class VintedScrapNextApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("VintedScrap Next")
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(fg_color="#121212")
        self.paths = build_paths()
        self.repo = JsonEventRepository(self.paths.events_file)
        self._build_ui()
        self._render_profile_preview()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=280, fg_color="#171717", corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(
            sidebar,
            text="VintedScrap Next",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#FFFFFF",
        ).pack(anchor="w", padx=22, pady=(28, 6))

        ctk.CTkLabel(
            sidebar,
            text="Base propre pour la future version GitHub.",
            font=ctk.CTkFont(size=13),
            text_color="#A8A8A8",
        ).pack(anchor="w", padx=22)

        self.profile_box = ctk.CTkTextbox(
            sidebar,
            height=180,
            fg_color="#101010",
            text_color="#EDEDED",
            border_width=1,
            border_color="#2B2B2B",
            corner_radius=12,
            font=ctk.CTkFont(size=12),
        )
        self.profile_box.pack(fill="x", padx=22, pady=(24, 12))
        self.profile_box.configure(state="disabled")

        refresh = ctk.CTkButton(
            sidebar,
            text="Recharger l'aperçu profil",
            fg_color="#00E5FF",
            hover_color="#00BCD4",
            text_color="#000000",
            command=self._render_profile_preview,
        )
        refresh.pack(fill="x", padx=22, pady=(0, 18))

        main = ctk.CTkFrame(self, fg_color="#121212")
        main.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        main.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            main,
            text="Version neuve en préparation",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#FFFFFF",
        ).grid(row=0, column=0, sticky="w", pady=(6, 8))

        ctk.CTkLabel(
            main,
            text="Cette base isole déjà le profil utilisateur, le scoring et la persistance. "
                 "Le scraper et les écrans métiers pourront être branchés progressivement.",
            wraplength=720,
            justify="left",
            font=ctk.CTkFont(size=14),
            text_color="#A8A8A8",
        ).grid(row=1, column=0, sticky="w")

        demo_card = ctk.CTkFrame(main, fg_color="#1B1B1B", border_width=1, border_color="#2B2B2B")
        demo_card.grid(row=2, column=0, sticky="ew", pady=(28, 0))
        demo_card.grid_columnconfigure(0, weight=1)

        listing = Listing(
            id="demo-1",
            title="Display OP12 One Piece scellé",
            price=165.0,
            brand="OnePiece",
            condition="Neuf avec étiquette",
            seller="demo_seller",
        )
        profile = rebuild_profile(self.repo.load())
        recommendation = score_listing(profile, listing)

        ctk.CTkLabel(
            demo_card,
            text=listing.title,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#FFFFFF",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))

        ctk.CTkLabel(
            demo_card,
            text=f"{listing.price:.2f} €",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#00C853",
        ).grid(row=1, column=0, sticky="w", padx=18)

        ctk.CTkLabel(
            demo_card,
            text=f"Score d'affinité: {recommendation.score}/100",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#00E5FF",
        ).grid(row=2, column=0, sticky="w", padx=18, pady=(14, 4))

        ctk.CTkLabel(
            demo_card,
            text=recommendation.explanation,
            font=ctk.CTkFont(size=13),
            text_color="#BFBFBF",
        ).grid(row=3, column=0, sticky="w", padx=18, pady=(0, 18))

    def _render_profile_preview(self) -> None:
        events = self.repo.load()
        profile = rebuild_profile(events)
        lines = [
            f"Recherches: {profile.search_count}",
            f"Ouvertures: {profile.open_count}",
            f"Favoris: {profile.favorite_count}",
            f"Ciblages: {profile.target_count}",
            "",
            f"Marques: {', '.join(list(profile.preferred_brands)[:3]) or 'Aucune'}",
            f"Conditions: {', '.join(list(profile.preferred_conditions)[:3]) or 'Aucune'}",
            f"Prix moyen: {profile.average_price if profile.average_price else 'N/A'}",
        ]
        self.profile_box.configure(state="normal")
        self.profile_box.delete("1.0", "end")
        self.profile_box.insert("1.0", "\n".join(lines))
        self.profile_box.configure(state="disabled")


def run() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    VintedScrapNextApp().mainloop()
