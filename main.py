"""
main.py — Interface graphique VintedScrap
v3.0 : compte Vinted, ciblage d'annonces, analyse de prix intelligente.
"""

import threading, webbrowser, itertools, os, sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from tkinter import messagebox, simpledialog, Menu, filedialog
import tkinter as tk

import customtkinter as ctk
import requests
from PIL import Image

# ── Imports Windows optionnels ────────────────────────────────────────────────
try:
    import win32clipboard
    _WIN32 = True
except ImportError:
    _WIN32 = False

try:
    from windows_toasts import Toast, WindowsToaster
    _TOAST = True
except ImportError:
    _TOAST = False

try:
    import winsound
    _WINSOUND = True
except ImportError:
    _WINSOUND = False

from core import scraper, data, analyzer, recommandations, comparateur_prix, auth, user_profile, resell

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

FONT = "Inter"  # Requiert Inter installé — sinon fallback automatique sur Segoe UI

C = {
    "bg":           "#121212",   # fond charbon doux
    "sidebar":      "#161616",   # sidebar légèrement plus claire
    "card":         "#1E1E1E",   # surfaces cartes
    "card_hover":   "#252525",   # hover card
    "border":       "#2A2A2A",   # bordures subtiles chaudes
    "accent":       "#00E5FF",   # cyan électrique — CTA primaire
    "accent_hover": "#00BCD4",   # cyan hover
    "prix":         "#00C853",   # vert émeraude — prix / succès
    "fav":          "#FF4081",   # rose vif favoris
    "nouveau":      "#00E676",   # vert flash nouvelles annonces
    "t1":           "#FFFFFF",   # blanc pur — titres
    "t2":           "#B0B0B0",   # gris clair — texte secondaire
    "t3":           "#666666",   # gris moyen — labels / tertiaire
    "tag_bg":       "#252525",   # fond badges
    "tag_fg":       "#00E5FF",   # texte badges cyan
    "alerte_on":    "#FF9800",   # orange alerte
    "liste_bg":     "#1A1A1A",   # fond lignes liste
    "liste_hover":  "#222222",   # hover lignes liste
    "cible":        "#7C4DFF",   # violet ciblage
    "input_bg":     "#0D0D0D",   # fond des champs de saisie
    "glass":        "#1E1E1E",   # surface glassmorphism
}


# ─── Notification Windows native ─────────────────────────────────────────────

def envoyer_toast(titre: str, message: str):
    if _TOAST:
        try:
            toaster = WindowsToaster("VintedScrap")
            t = Toast()
            t.text_fields = [titre, message]
            toaster.show_toast(t)
            return
        except Exception:
            pass
    if _WINSOUND:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass


# ─── Bannière de notification ─────────────────────────────────────────────────

class BannerNotif(ctk.CTkToplevel):
    def __init__(self, master, titre: str, message: str):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=C["card"])
        ctk.CTkLabel(self, text=f"● {titre}",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["alerte_on"]).pack(padx=16, pady=(12, 2), anchor="w")
        ctk.CTkLabel(self, text=message, font=ctk.CTkFont(size=11),
                     text_color=C["t1"], wraplength=280).pack(padx=16, pady=(0, 12), anchor="w")
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = 310, self.winfo_reqheight()
        self.geometry(f"{w}x{h}+{sw - w - 20}+{sh - h - 60}")
        self.after(6000, self.destroy)


# ─── Aperçu rapide ────────────────────────────────────────────────────────────

class FenetreApercu(ctk.CTkToplevel):
    IMG_W, IMG_H = 360, 360

    def __init__(self, master, annonce: scraper.Annonce):
        super().__init__(master)
        self.title("Aperçu")
        self.resizable(False, False)
        self.configure(fg_color=C["card"])
        self.attributes("-topmost", True)
        self._photo = None
        self._construire(annonce)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h   = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        if annonce.image_url:
            threading.Thread(target=self._dl_image,
                             args=(annonce.image_url,), daemon=True).start()
        threading.Thread(target=self._dl_description,
                         args=(annonce,), daemon=True).start()

    def _construire(self, a: scraper.Annonce):
        self.grid_columnconfigure(0, weight=1)
        self.lbl_img = ctk.CTkLabel(self, text="…", width=self.IMG_W, height=self.IMG_H,
                                    fg_color="#1a2333", corner_radius=12,
                                    text_color=C["t3"], font=ctk.CTkFont(size=28))
        self.lbl_img.grid(row=0, column=0, padx=20, pady=(20, 12), sticky="ew")
        ctk.CTkLabel(self, text=a.title, font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["t1"], wraplength=360, justify="center"
        ).grid(row=1, column=0, padx=20, pady=(0, 6))
        ctk.CTkLabel(self, text=a.prix_affiche(),
                     font=ctk.CTkFont(size=22, weight="bold"), text_color=C["prix"]
        ).grid(row=2, column=0, pady=(0, 8))
        infos = [("État", a.condition), ("Marque", a.brand),
                 ("Taille", a.size), ("Vendeur", getattr(a, "vendeur_nom", ""))]
        info_frame = ctk.CTkFrame(self, fg_color="#1a2333", corner_radius=10)
        info_frame.grid(row=3, column=0, padx=20, pady=(0, 12), sticky="ew")
        info_frame.grid_columnconfigure(1, weight=1)
        r = 0
        for label, val in infos:
            if not val: continue
            ctk.CTkLabel(info_frame, text=label, font=ctk.CTkFont(size=11),
                         text_color=C["t3"]).grid(row=r, column=0, padx=12, pady=3, sticky="w")
            ctk.CTkLabel(info_frame, text=val, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["t1"]).grid(row=r, column=1, padx=12, pady=3, sticky="w")
            r += 1
        ctk.CTkFrame(self, fg_color=C["border"], height=1).grid(
            row=4, column=0, sticky="ew", padx=20, pady=4)
        ctk.CTkLabel(self, text="DESCRIPTION", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["t3"]).grid(row=5, column=0, padx=20, pady=(4, 2), sticky="w")
        self.lbl_desc = ctk.CTkLabel(self, text="⏳ Chargement…",
                     font=ctk.CTkFont(size=11), text_color=C["t2"],
                     wraplength=360, justify="left")
        self.lbl_desc.grid(row=6, column=0, padx=20, pady=(0, 8), sticky="w")
        ctk.CTkFrame(self, fg_color=C["border"], height=1).grid(
            row=7, column=0, sticky="ew", padx=20, pady=4)
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=8, column=0, padx=20, pady=(4, 20), sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(btn_row, text="Voir l'annonce →", height=38, corner_radius=10,
                      fg_color=C["accent"], hover_color=C["accent_hover"], text_color="#ffffff",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=lambda: webbrowser.open(a.url)
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        ctk.CTkButton(btn_row, text="✕ Fermer", height=38, corner_radius=10,
                      fg_color=C["border"], hover_color="#2d3a50", text_color=C["t2"],
                      font=ctk.CTkFont(size=13), command=self.destroy
        ).grid(row=0, column=1)

    def _dl_description(self, annonce):
        try:
            app = self.winfo_toplevel()
            if hasattr(app, 'scraper'):
                app.scraper.fetch_description(annonce)
            desc = annonce.description or "Aucune description fournie par le vendeur."
            if len(desc) > 500:
                desc = desc[:497] + "…"
        except Exception:
            desc = "Impossible de charger la description."
        self.after(0, lambda: self.lbl_desc.configure(text=desc))

    def _dl_image(self, url):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).resize(
                (self.IMG_W, self.IMG_H), Image.LANCZOS)
            ci = ctk.CTkImage(light_image=img, dark_image=img,
                              size=(self.IMG_W, self.IMG_H))
            self._photo = ci
            self.after(0, lambda: self.lbl_img.configure(image=ci, text=""))
        except Exception:
            self.after(0, lambda: self.lbl_img.configure(text="✕"))


# ─── Historique des prix ──────────────────────────────────────────────────────

class FenetreHistorique(ctk.CTkToplevel):
    W, H   = 560, 340
    PAD_L, PAD_B, PAD_T, PAD_R = 64, 48, 24, 24

    def __init__(self, master, annonce_id: str, titre: str):
        super().__init__(master)
        self.title(f"Historique — {titre[:40]}")
        self.resizable(True, True)
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.geometry(f"{self.W}x{self.H+80}")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="📊  Évolution du prix",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["t1"]).grid(row=0, column=0, pady=(16, 4))
        self.canvas = tk.Canvas(self, bg="#0d1117", bd=0, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        ctk.CTkButton(self, text="Fermer", height=32, corner_radius=8,
                      fg_color=C["border"], hover_color="#2d3a50", text_color=C["t2"],
                      command=self.destroy).grid(row=2, column=0, pady=(0, 12))
        pts = data.charger_historique(annonce_id)
        self.after(100, lambda: self._dessiner(pts))

    def _dessiner(self, pts: list):
        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width()  or self.W
        ch = self.canvas.winfo_height() or self.H
        self.canvas.delete("all")
        if len(pts) < 2:
            self.canvas.create_text(cw//2, ch//2,
                text="Pas assez de données\n(au moins 2 relevés nécessaires)",
                fill=C["t3"], font=("Segoe UI", 12), justify="center")
            return
        prices = [p["price"] for p in pts]
        dates  = [p["date"]  for p in pts]
        pmin, pmax = min(prices), max(prices)
        if pmin == pmax: pmin -= 1; pmax += 1
        gx0, gx1 = self.PAD_L, cw - self.PAD_R
        gy0, gy1 = self.PAD_T, ch - self.PAD_B
        gw, gh   = gx1 - gx0, gy1 - gy0
        def px(i): return gx0 + i * gw / (len(pts) - 1)
        def py(p): return gy1 - (p - pmin) / (pmax - pmin) * gh
        for i in range(5):
            y = gy0 + i * gh / 4
            p = pmax - i * (pmax - pmin) / 4
            self.canvas.create_line(gx0, y, gx1, y, fill="#1f2d40", dash=(4, 4))
            self.canvas.create_text(gx0 - 6, y, text=f"{p:.0f}€",
                                    fill=C["t3"], font=("Segoe UI", 9), anchor="e")
        self.canvas.create_line(gx0, gy0, gx0, gy1, fill=C["border"], width=1)
        self.canvas.create_line(gx0, gy1, gx1, gy1, fill=C["border"], width=1)
        for i, d in [(0, dates[0]), (len(pts)-1, dates[-1])]:
            label  = d[5:16] if len(d) >= 16 else d
            anchor = "w" if i == 0 else "e"
            self.canvas.create_text(px(i), gy1 + 14, text=label,
                                    fill=C["t3"], font=("Segoe UI", 9), anchor=anchor)
        poly = [gx0, gy1]
        for i, p in enumerate(prices): poly += [px(i), py(p)]
        poly += [gx1, gy1]
        self.canvas.create_polygon(poly, fill="#0e3028", outline="")
        coords = []
        for i, p in enumerate(prices): coords += [px(i), py(p)]
        self.canvas.create_line(coords, fill=C["accent"], width=2, smooth=True)
        for i, p in enumerate(prices):
            x, y = px(i), py(p)
            self.canvas.create_oval(x-4, y-4, x+4, y+4,
                                    fill=C["accent"], outline=C["bg"], width=2)
            if i == 0 or i == len(prices)-1 or p in (pmin, pmax):
                anchor = "sw" if i < len(prices)//2 else "se"
                self.canvas.create_text(x, y - 10, text=f"{p:.2f}€",
                                        fill=C["prix"], font=("Segoe UI", 9, "bold"),
                                        anchor=anchor)


# ─── Comparateur ──────────────────────────────────────────────────────────────

class FenetreComparateur(ctk.CTkToplevel):
    def __init__(self, master, annonces: list):
        super().__init__(master)
        self.title("Comparateur d'annonces")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        nb = len(annonces)
        self.geometry(f"{min(nb * 340, 1020)}x620")
        self.grid_columnconfigure(list(range(nb)), weight=1)
        self.grid_rowconfigure(0, weight=1)
        for col, a in enumerate(annonces[:3]):
            self._colonne(a, col)

    def _colonne(self, a: scraper.Annonce, col: int):
        frame = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=14,
                             border_width=1, border_color=C["border"])
        frame.grid(row=0, column=col, padx=10, pady=16, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        lbl_img = ctk.CTkLabel(frame, text="…", width=280, height=220,
                               fg_color="#1a2333", corner_radius=10,
                               text_color=C["t3"], font=ctk.CTkFont(size=22))
        lbl_img.grid(row=0, column=0, padx=12, pady=(14, 8), sticky="ew")
        if a.image_url:
            threading.Thread(target=self._dl_img,
                             args=(a.image_url, lbl_img), daemon=True).start()
        ctk.CTkLabel(frame, text=a.title, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t1"], wraplength=260, justify="center"
        ).grid(row=1, column=0, padx=12, pady=(0, 6))
        ctk.CTkLabel(frame, text=a.prix_affiche(),
                     font=ctk.CTkFont(size=20, weight="bold"), text_color=C["prix"]
        ).grid(row=2, column=0, pady=(0, 8))
        info_frame = ctk.CTkFrame(frame, fg_color="#1a2333", corner_radius=10)
        info_frame.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="ew")
        info_frame.grid_columnconfigure(1, weight=1)
        for r, (lbl, val) in enumerate([("État", a.condition), ("Marque", a.brand),
                 ("Taille", a.size), ("Vendeur", getattr(a, "vendeur_nom", ""))]):
            if not val: continue
            ctk.CTkLabel(info_frame, text=lbl, font=ctk.CTkFont(size=10),
                         text_color=C["t3"]).grid(row=r, column=0, padx=10, pady=2, sticky="w")
            ctk.CTkLabel(info_frame, text=val, font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=C["t1"]).grid(row=r, column=1, padx=10, pady=2, sticky="w")
        ctk.CTkButton(frame, text="Voir l'annonce →", height=36, corner_radius=8,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#ffffff", font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: webbrowser.open(a.url)
        ).grid(row=4, column=0, padx=12, pady=(4, 14), sticky="ew")

    def _dl_img(self, url, lbl):
        try:
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).resize((280, 220), Image.LANCZOS)
            ci  = ctk.CTkImage(light_image=img, dark_image=img, size=(280, 220))
            self.after(0, lambda: lbl.configure(image=ci, text=""))
            self._keep = getattr(self, "_keep", [])
            self._keep.append(ci)
        except Exception:
            self.after(0, lambda: lbl.configure(text="✕"))


# ─── Dashboard Stats ──────────────────────────────────────────────────────────

class FenetreDashboard(ctk.CTkToplevel):
    W, H = 680, 520

    def __init__(self, master, stats: dict, titre_recherche: str = ""):
        super().__init__(master)
        self.title("📊 Dashboard")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.geometry(f"{self.W}x{self.H}")
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=f"📊  Dashboard — {titre_recherche or 'Résultats'}",
                     font=ctk.CTkFont(size=15, weight="bold"), text_color=C["t1"]
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 12), sticky="w")
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                        scrollbar_button_color=C["border"])
        scroll.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 8))
        scroll.grid_columnconfigure((0, 1), weight=1)
        if not stats:
            ctk.CTkLabel(scroll, text="Aucune donnée disponible.",
                         text_color=C["t3"]).pack(pady=40)
            return
        def metrique(parent, row, col, label, valeur, couleur=C["t1"]):
            f = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                             border_width=1, border_color=C["border"])
            f.grid(row=row, column=col, padx=6, pady=6, sticky="ew")
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=10),
                         text_color=C["t3"]).pack(padx=14, pady=(10, 2), anchor="w")
            ctk.CTkLabel(f, text=valeur, font=ctk.CTkFont(size=18, weight="bold"),
                         text_color=couleur).pack(padx=14, pady=(0, 10), anchor="w")
        scroll.grid_columnconfigure((0, 1, 2, 3), weight=1)
        metrique(scroll, 0, 0, "Annonces",    str(stats.get("total", 0)),            C["accent"])
        metrique(scroll, 0, 1, "Prix moyen",  f"{stats.get('prix_moyen', 0):.2f} €", C["prix"])
        metrique(scroll, 0, 2, "Prix min",    f"{stats.get('prix_min', 0):.2f} €",   C["nouveau"])
        metrique(scroll, 0, 3, "Prix médian", f"{stats.get('prix_median', 0):.2f} €",C["t1"])
        self._section(scroll, 1, "🏷️  Top Marques",   stats.get("top_brands", []),   C["accent"])
        self._section(scroll, 2, "📦  États",          stats.get("etats", []),         C["prix"])
        self._section(scroll, 3, "👤  Top Vendeurs",   stats.get("top_vendeurs", []), C["tag_fg"])
        self._graphique_barres(scroll, 4, stats)
        ctk.CTkButton(self, text="Fermer", height=34, corner_radius=8,
                      fg_color=C["border"], hover_color="#2d3a50", text_color=C["t2"],
                      command=self.destroy).grid(row=2, column=0, columnspan=2, pady=(0, 12))

    def _section(self, parent, row, titre, items, couleur):
        f = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                         border_width=1, border_color=C["border"])
        f.grid(row=row, column=0, columnspan=4, padx=6, pady=6, sticky="ew")
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text=titre, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t1"]).grid(row=0, column=0, columnspan=3,
                                               padx=14, pady=(10, 6), sticky="w")
        total = sum(v for _, v in items) if items else 1
        for i, (label, val) in enumerate(items):
            pct = val / total * 100 if total else 0
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=11),
                         text_color=C["t2"]).grid(row=i+1, column=0, padx=14, pady=2, sticky="w")
            bar = ctk.CTkProgressBar(f, height=10, corner_radius=5,
                                     progress_color=couleur, fg_color=C["border"])
            bar.set(pct / 100)
            bar.grid(row=i+1, column=1, padx=6, pady=2, sticky="ew")
            ctk.CTkLabel(f, text=f"{val}  ({pct:.0f}%)", font=ctk.CTkFont(size=10),
                         text_color=C["t3"]).grid(row=i+1, column=2, padx=14, pady=2, sticky="e")

    def _graphique_barres(self, parent, row, stats):
        f = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                         border_width=1, border_color=C["border"])
        f.grid(row=row, column=0, columnspan=4, padx=6, pady=6, sticky="ew")
        ctk.CTkLabel(f, text="💰  Répartition des prix",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=C["t1"]
        ).pack(padx=14, pady=(10, 4), anchor="w")
        canvas = tk.Canvas(f, bg=C["card"], bd=0, highlightthickness=0, height=100)
        canvas.pack(fill="x", padx=14, pady=(0, 12))
        canvas.update_idletasks()
        cw = canvas.winfo_width() or 600
        vals = [("Min", stats.get("prix_min", 0), C["nouveau"]),
                ("Médian", stats.get("prix_median", 0), C["accent"]),
                ("Moyen", stats.get("prix_moyen", 0), C["prix"]),
                ("Max", stats.get("prix_max", 0), C["fav"])]
        pmax = max(v for _, v, _ in vals) or 1
        bw = cw // len(vals) - 20
        for i, (lbl, val, col) in enumerate(vals):
            x = i * (cw // len(vals)) + 10
            h = int((val / pmax) * 70)
            canvas.create_rectangle(x, 80 - h, x + bw, 80, fill=col, outline="")
            canvas.create_text(x + bw//2, 80 - h - 6, text=f"{val:.0f}€",
                               fill=col, font=("Segoe UI", 8, "bold"))
            canvas.create_text(x + bw//2, 92, text=lbl,
                               fill=C["t3"], font=("Segoe UI", 9))


# ─── Fenêtre Analyse Annonce ──────────────────────────────────────────────────

class FenetreAnalyse(ctk.CTkToplevel):
    """Popup d'analyse de prix complète pour une annonce."""

    def __init__(self, master, annonce: scraper.Annonce, annonces_marche: list):
        super().__init__(master)
        self.title(f"Analyse — {annonce.title[:40]}")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.geometry("480x640")
        self._annonce = annonce
        self._analyse = None
        self._construire_chargement()
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h   = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"480x640+{(sw-480)//2}+{(sh-640)//2}")
        threading.Thread(
            target=self._analyser,
            args=(annonce, annonces_marche),
            daemon=True
        ).start()

    def _construire_chargement(self):
        self.lbl_load = ctk.CTkLabel(self, text="🔍  Analyse en cours…",
                                     font=ctk.CTkFont(size=15), text_color=C["t2"])
        self.lbl_load.place(relx=0.5, rely=0.5, anchor="center")

    def _analyser(self, annonce, marche):
        a = analyzer.analyser_annonce(annonce, marche)
        self._analyse = a
        self.after(0, self._afficher, a)

    def _afficher(self, a: analyzer.AnalysePrix):
        self.lbl_load.place_forget()
        self.grid_columnconfigure(0, weight=1)

        row = 0

        # ── En-tête titre + prix ───────────────────────────────────────────
        ctk.CTkLabel(self, text=CarteAnnonce._trunc(a.titre, 45),
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["t1"], wraplength=440, justify="center"
        ).grid(row=row, column=0, padx=20, pady=(18, 4), sticky="ew"); row += 1

        ctk.CTkLabel(self, text=a.fmt(a.prix_actuel),
                     font=ctk.CTkFont(size=20, weight="bold"), text_color=C["prix"]
        ).grid(row=row, column=0, pady=(0, 12)); row += 1

        # ── Score de négociabilité ─────────────────────────────────────────
        score_color = analyzer.couleur_score(a.score)
        score_frame = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=14,
                                   border_width=1, border_color=C["border"])
        score_frame.grid(row=row, column=0, padx=20, pady=(0, 12), sticky="ew"); row += 1
        score_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(score_frame, text="SCORE DE NÉGOCIABILITÉ",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["t3"]).grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        bar_score = ctk.CTkProgressBar(score_frame, height=14, corner_radius=7,
                                       progress_color=score_color, fg_color=C["border"])
        bar_score.set(a.score / 100)
        bar_score.grid(row=1, column=0, padx=16, pady=(0, 4), sticky="ew")

        ctk.CTkLabel(score_frame, text=f"{a.score} / 100",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=score_color).grid(row=2, column=0, padx=16, pady=(0, 4))

        ctk.CTkLabel(score_frame, text=analyzer.label_strategie(a.strategie),
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t2"]).grid(row=3, column=0, padx=16, pady=(0, 12))

        # ── Raisons ────────────────────────────────────────────────────────
        raisons_frame = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=14,
                                     border_width=1, border_color=C["border"])
        raisons_frame.grid(row=row, column=0, padx=20, pady=(0, 12), sticky="ew"); row += 1
        raisons_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(raisons_frame, text="ANALYSE DÉTAILLÉE",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["t3"]).grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")

        icons = {"bon": "✅", "mauvais": "❌", "neutre": "➡️", "info": "ℹ️"}
        colors = {"bon": C["nouveau"], "mauvais": C["fav"],
                  "neutre": C["t2"], "info": C["t3"]}
        for i, (tag, texte) in enumerate(a.raisons):
            rf = ctk.CTkFrame(raisons_frame, fg_color="transparent")
            rf.grid(row=i+1, column=0, padx=12, pady=2, sticky="ew")
            rf.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(rf, text=icons.get(tag, "•"),
                         font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0, 6))
            ctk.CTkLabel(rf, text=texte, font=ctk.CTkFont(size=11),
                         text_color=colors.get(tag, C["t2"]),
                         wraplength=360, justify="left"
            ).grid(row=0, column=1, sticky="w")
        ctk.CTkFrame(raisons_frame, fg_color="transparent", height=8).grid(
            row=len(a.raisons)+1, column=0)

        # ── Offre suggérée ────────────────────────────────────────────────
        offre_frame = ctk.CTkFrame(self, fg_color="#0e1f15", corner_radius=14,
                                   border_width=2, border_color=C["nouveau"])
        offre_frame.grid(row=row, column=0, padx=20, pady=(0, 12), sticky="ew"); row += 1
        offre_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(offre_frame, text="💡  OFFRE SUGGÉRÉE",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["nouveau"]).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")

        ctk.CTkLabel(offre_frame, text=a.fmt(a.prix_suggere),
                     font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=C["nouveau"]).grid(row=1, column=0, pady=(0, 2))

        ctk.CTkLabel(offre_frame, text=f"Économie estimée : {a.fmt(a.economie)}  •  −{a.reduction_pct:.0f}%",
                     font=ctk.CTkFont(size=11), text_color=C["t2"]
        ).grid(row=2, column=0, pady=(0, 12))

        # ── Message suggéré ───────────────────────────────────────────────
        msg_frame = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=14,
                                 border_width=1, border_color=C["border"])
        msg_frame.grid(row=row, column=0, padx=20, pady=(0, 12), sticky="ew"); row += 1
        msg_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(msg_frame, text="MESSAGE À ENVOYER",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["t3"]).grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        ctk.CTkLabel(msg_frame, text=a.message_suggere,
                     font=ctk.CTkFont(size=11, slant="italic"), text_color=C["t1"],
                     wraplength=400, justify="left"
        ).grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        # ── Boutons ───────────────────────────────────────────────────────
        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.grid(row=row, column=0, padx=20, pady=(0, 20), sticky="ew"); row += 1
        btn_f.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(btn_f, text="📋 Copier message", height=36, corner_radius=10,
                      fg_color=C["border"], hover_color="#2d3a50", text_color=C["t1"],
                      font=ctk.CTkFont(size=12),
                      command=lambda: self._copier(a.message_suggere)
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

        ctk.CTkButton(btn_f, text="🎯 Cibler", height=36, corner_radius=10,
                      fg_color=C["cible"], hover_color="#6d28d9", text_color="#fff",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: self._cibler(a)
        ).grid(row=0, column=1, padx=4, sticky="ew")

        ctk.CTkButton(btn_f, text="Ouvrir →", height=36, corner_radius=10,
                      fg_color=C["accent"], hover_color=C["accent_hover"], text_color="#ffffff",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: webbrowser.open(self._annonce.url)
        ).grid(row=0, column=2, padx=(4, 0), sticky="ew")

    def _copier(self, texte: str):
        self.clipboard_clear()
        self.clipboard_append(texte)
        envoyer_toast("Copié !", "Message copié dans le presse-papier.")

    def _cibler(self, a: analyzer.AnalysePrix):
        try:
            ajout = data.ajouter_cible(self._annonce, a)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de cibler l'annonce :\n{e}")
            return
        if ajout:
            try:
                app = self.winfo_toplevel()
                if hasattr(app, "rafraichir_cibles"):
                    app.rafraichir_cibles()
            except Exception:
                pass
            envoyer_toast("Ciblé !", f"'{CarteAnnonce._trunc(a.titre, 30)}' ajouté à la file.")
        else:
            messagebox.showinfo("Déjà ciblé", "Cette annonce est déjà dans votre file de ciblage.")
        try:
            self.destroy()
        except Exception:
            pass


# ─── Fenêtre Comparateur de Prix Multi-Sites ─────────────────────────────────

class FenetreComparateurPrix(ctk.CTkToplevel):
    """Popup de comparaison de prix multi-plateformes pour une annonce."""

    def __init__(self, master, annonce: scraper.Annonce):
        super().__init__(master)
        self.title(f"Comparer — {annonce.title[:40]}")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self._annonce = annonce
        self._query   = comparateur_prix.get_query_annonce(annonce)
        self._sel      = {}   # plateforme.nom -> BooleanVar

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(720, sw - 80), min(700, sh - 80)
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._construire()

    def _construire(self):
        # ── En-tête ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="🔍  Comparer les prix en ligne",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C["t1"]).grid(row=0, column=0, padx=20, pady=(14, 2), sticky="w")
        ctk.CTkLabel(header,
                     text=f"Recherche : « {self._query} »",
                     font=ctk.CTkFont(size=11, slant="italic"),
                     text_color=C["t3"]).grid(row=1, column=0, padx=20, pady=(0, 4), sticky="w")

        # Champ de recherche modifiable
        champ_f = ctk.CTkFrame(header, fg_color="transparent")
        champ_f.grid(row=2, column=0, padx=20, pady=(4, 14), sticky="ew")
        champ_f.grid_columnconfigure(0, weight=1)
        self._champ_query = ctk.CTkEntry(
            champ_f, placeholder_text="Modifier la recherche…",
            height=34, corner_radius=8, fg_color=C["input_bg"],
            border_color=C["accent"], border_width=1, text_color=C["t1"],
            font=ctk.CTkFont(size=12))
        self._champ_query.insert(0, self._query)
        self._champ_query.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._champ_query.bind("<Return>", lambda _: self._maj_query())
        ctk.CTkButton(champ_f, text="↺", width=34, height=34, corner_radius=8,
                      fg_color=C["border"], hover_color=C["accent"],
                      text_color=C["t1"], font=ctk.CTkFont(size=14),
                      command=self._maj_query).grid(row=0, column=1)

        # ── Corps scrollable — plateformes par catégorie ────────────────────────
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                              scrollbar_button_color=C["border"])
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.scroll.grid_columnconfigure(0, weight=1)
        self._remplir_plateformes()

        # ── Barre de bas ───────────────────────────────────────────────────────
        bar = ctk.CTkFrame(self, fg_color=C["sidebar"], corner_radius=0)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(bar, text="Tout sélectionner", height=34, corner_radius=8,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=lambda: self._tout(True)
        ).grid(row=0, column=0, padx=(12, 4), pady=10)

        ctk.CTkButton(bar, text="Tout désélectionner", height=34, corner_radius=8,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=lambda: self._tout(False)
        ).grid(row=0, column=1, padx=4, pady=10, sticky="w")

        ctk.CTkButton(bar, text="🌐  Ouvrir la sélection", height=40, corner_radius=10,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#000000", font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._ouvrir_selection
        ).grid(row=0, column=2, padx=(4, 12), pady=8, sticky="e")

    def _remplir_plateformes(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        self._sel.clear()
        cats = comparateur_prix.plateformes_par_categorie()
        row = 0
        for cat, plateformes in cats.items():
            if not plateformes:
                continue
            label_cat = comparateur_prix.LABELS_CAT.get(cat, cat)
            ctk.CTkLabel(self.scroll, text=label_cat,
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=C["t3"]
            ).grid(row=row, column=0, padx=16, pady=(14, 4), sticky="w")
            row += 1

            # Grille de boutons 3 colonnes
            grid_f = ctk.CTkFrame(self.scroll, fg_color="transparent")
            grid_f.grid(row=row, column=0, padx=12, pady=(0, 4), sticky="ew")
            grid_f.grid_columnconfigure((0, 1, 2), weight=1)
            row += 1

            for i, p in enumerate(plateformes):
                var = tk.BooleanVar(value=True)
                self._sel[p.nom] = (var, p)
                col_idx = i % 3
                row_idx = i // 3

                btn_f = ctk.CTkFrame(grid_f, fg_color=C["card"], corner_radius=10,
                                     border_width=1, border_color=C["border"])
                btn_f.grid(row=row_idx, column=col_idx, padx=4, pady=4, sticky="ew")
                btn_f.grid_columnconfigure(1, weight=1)

                chk = ctk.CTkCheckBox(btn_f, text="", variable=var, width=20,
                                      fg_color=p.couleur, hover_color=p.couleur,
                                      border_color=C["border"],
                                      command=lambda: None)
                chk.grid(row=0, column=0, padx=(8, 4), pady=8)

                ctk.CTkLabel(btn_f, text=p.nom,
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=C["t1"], anchor="w"
                ).grid(row=0, column=1, padx=(0, 4), pady=8, sticky="ew")

                ctk.CTkButton(btn_f, text="→", width=28, height=28, corner_radius=6,
                              fg_color="transparent", hover_color=C["border"],
                              text_color=C["t3"], font=ctk.CTkFont(size=12),
                              command=lambda pl=p: webbrowser.open(
                                  comparateur_prix.construire_url(pl, self._champ_query.get().strip() or self._query))
                ).grid(row=0, column=2, padx=(0, 6), pady=6)

    def _maj_query(self):
        """Met à jour la requête depuis le champ éditable."""
        nouvelle = self._champ_query.get().strip()
        if nouvelle:
            self._query = nouvelle

    def _tout(self, valeur: bool):
        for nom, (var, _) in self._sel.items():
            var.set(valeur)

    def _ouvrir_selection(self):
        query = self._champ_query.get().strip() or self._query
        sel = [p for nom, (var, p) in self._sel.items() if var.get()]
        if not sel:
            messagebox.showwarning("Sélection vide", "Sélectionnez au moins une plateforme.")
            return
        for p in sel:
            url = comparateur_prix.construire_url(p, query)
            webbrowser.open(url)
        envoyer_toast(f"Comparaison lancée", f"{len(sel)} site(s) ouverts pour « {query} »")


# ─── Carte Annonce (mode grille) ──────────────────────────────────────────────

# ─── Fenetre Resultats Revente ────────────────────────────────────────────────

class FenetreRevente(ctk.CTkToplevel):
    """Popup presentant l'analyse complete pour la revente d'un produit."""

    def __init__(self, master, analyse):
        super().__init__(master)
        self.title(f"Analyse Revente — {analyse.produit[:40]}")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.geometry("560x780")
        self._analyse = analyse
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                        scrollbar_button_color=C["border"],
                                        scrollbar_button_hover_color=C["accent"])
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        self._construire(scroll, analyse)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"560x780+{(sw-560)//2}+{(sh-780)//2}")

    def _construire(self, parent, a):
        row = 0

        # Score opportunite
        score_color = (C["prix"] if a.score_opportunite >= 70
                       else C["alerte_on"] if a.score_opportunite >= 40
                       else C["fav"])
        score_label = ("Excellente opportunité 🚀" if a.score_opportunite >= 70
                       else "Opportunité correcte ✅" if a.score_opportunite >= 50
                       else "Opportunité limitée ⚠️" if a.score_opportunite >= 30
                       else "Peu rentable ❌")

        hero = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=16,
                            border_width=2, border_color=score_color)
        hero.grid(row=row, column=0, padx=16, pady=(16, 8), sticky="ew"); row += 1
        hero.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hero, text="SCORE D'OPPORTUNITÉ",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color=C["t3"]
        ).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")

        score_row = ctk.CTkFrame(hero, fg_color="transparent")
        score_row.grid(row=1, column=0, padx=16, pady=(0, 4), sticky="ew")
        score_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(score_row, text=f"{a.score_opportunite}/100",
                     font=ctk.CTkFont(family=FONT, size=36, weight="bold"),
                     text_color=score_color
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(score_row, text=score_label,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=score_color, wraplength=300, justify="left"
        ).grid(row=0, column=1, padx=(12, 0), sticky="w")

        bar_bg = ctk.CTkFrame(hero, fg_color=C["border"], corner_radius=4, height=6)
        bar_bg.grid(row=2, column=0, padx=16, pady=(4, 14), sticky="ew")
        bar_pct = max(0.02, a.score_opportunite / 100)
        bar_fg = ctk.CTkFrame(bar_bg, fg_color=score_color, corner_radius=4, height=6)
        bar_fg.place(relx=0, rely=0, relwidth=bar_pct, relheight=1)

        # Prix & marge
        pf = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                          border_width=1, border_color=C["border"])
        pf.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
        pf.grid_columnconfigure((0, 1, 2), weight=1)

        def metric(par, col, label, value, color=C["t1"]):
            f = ctk.CTkFrame(par, fg_color="transparent")
            f.grid(row=0, column=col, padx=8, pady=12, sticky="ew")
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C["t3"]).pack()
            ctk.CTkLabel(f, text=value,
                         font=ctk.CTkFont(family=FONT, size=16, weight="bold"),
                         text_color=color).pack()

        metric(pf, 0, "PRIX D'ACHAT",
               f"{a.prix_achat:.2f} €", C["t2"])
        metric(pf, 1, "PRIX SUGGÉRÉ",
               f"{a.prix_suggere:.2f} €", C["accent"])
        mc = C["prix"] if a.marge_pct >= 0 else C["fav"]
        metric(pf, 2, "MARGE ESTIMÉE",
               f"+{a.marge_estimee:.2f} €\n({a.marge_pct:+.0f}%)", mc)

        # Marche
        if a.nb_annonces > 0:
            mf = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                              border_width=1, border_color=C["border"])
            mf.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
            mf.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(mf, text="📊  Marché actuel",
                         font=ctk.CTkFont(size=11, weight="bold"), text_color=C["t1"]
            ).grid(row=0, column=0, padx=14, pady=(10, 6), sticky="w")
            mr = ctk.CTkFrame(mf, fg_color="transparent")
            mr.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="ew")
            mr.grid_columnconfigure((0, 1, 2), weight=1)
            for col, (lbl, val) in enumerate([
                ("Annonces", str(a.nb_annonces)),
                ("Prix moyen", f"{a.prix_marche_moyen:.2f} €"),
                ("Fourchette",
                 f"{a.prix_marche_min:.0f}–{a.prix_marche_max:.0f} €"),
            ]):
                f2 = ctk.CTkFrame(mr, fg_color="transparent")
                f2.grid(row=0, column=col, sticky="ew")
                ctk.CTkLabel(f2, text=lbl, font=ctk.CTkFont(size=9),
                             text_color=C["t3"]).pack()
                ctk.CTkLabel(f2, text=val,
                             font=ctk.CTkFont(size=12, weight="bold"),
                             text_color=C["t1"]).pack()

        # Conseil
        cf = ctk.CTkFrame(parent, fg_color="#1a2a1a", corner_radius=12,
                          border_width=1, border_color=C["prix"])
        cf.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
        ctk.CTkLabel(cf, text=a.conseil,
                     font=ctk.CTkFont(size=11), text_color=C["t1"],
                     wraplength=490, justify="left"
        ).grid(row=0, column=0, padx=14, pady=10, sticky="w")

        # Titre
        tf = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                          border_width=1, border_color=C["border"])
        tf.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
        tf.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tf, text="✏️  Titre de l'annonce",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color=C["t1"]
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")
        self._titre_var = ctk.StringVar(value=a.titre)
        ctk.CTkEntry(tf, textvariable=self._titre_var, height=36, corner_radius=8,
                     font=ctk.CTkFont(size=12),
                     fg_color=C["input_bg"], border_color=C["accent"],
                     text_color=C["t1"]
        ).grid(row=1, column=0, padx=14, pady=(0, 4), sticky="ew")
        ctk.CTkLabel(tf, text=f"{len(a.titre)}/60 caractères",
                     font=ctk.CTkFont(size=9), text_color=C["t3"]
        ).grid(row=2, column=0, padx=14, pady=(0, 8), sticky="w")

        # Description
        df = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                          border_width=1, border_color=C["border"])
        df.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
        df.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(df, text="📝  Description de l'annonce",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color=C["t1"]
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")
        self._desc_box = ctk.CTkTextbox(df, height=180, corner_radius=8,
                                        font=ctk.CTkFont(size=11),
                                        fg_color=C["input_bg"], text_color=C["t1"],
                                        border_color=C["border"], border_width=1)
        self._desc_box.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")
        self._desc_box.insert("1.0", a.description)

        # Annonces de reference
        if a.annonces_ref:
            rf = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                              border_width=1, border_color=C["border"])
            rf.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
            rf.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(rf, text="🔗  Annonces similaires",
                         font=ctk.CTkFont(size=11, weight="bold"), text_color=C["t1"]
            ).grid(row=0, column=0, padx=14, pady=(10, 6), sticky="w")
            for i, ann in enumerate(a.annonces_ref[:4], 1):
                ar = ctk.CTkFrame(rf, fg_color=C["tag_bg"], corner_radius=8)
                ar.grid(row=i, column=0, padx=14, pady=2, sticky="ew")
                ar.grid_columnconfigure(0, weight=1)
                t = (ann.title[:45] + "…") if len(ann.title) > 45 else ann.title
                ctk.CTkLabel(ar, text=t, font=ctk.CTkFont(size=10),
                             text_color=C["t2"], anchor="w"
                ).grid(row=0, column=0, padx=8, pady=4, sticky="w")
                ctk.CTkLabel(ar, text=ann.prix_affiche(),
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=C["prix"]
                ).grid(row=0, column=1, padx=8, pady=4)
                ctk.CTkButton(ar, text="→", width=28, height=24, corner_radius=6,
                              fg_color="transparent", hover_color=C["border"],
                              text_color=C["t3"], font=ctk.CTkFont(size=12),
                              command=lambda u=ann.url: webbrowser.open(u)
                ).grid(row=0, column=2, padx=(0, 6), pady=2)
            ctk.CTkFrame(rf, fg_color="transparent", height=8
            ).grid(row=len(a.annonces_ref[:4])+1, column=0)

        # Boutons action
        bf = ctk.CTkFrame(parent, fg_color="transparent")
        bf.grid(row=row, column=0, padx=16, pady=(8, 20), sticky="ew"); row += 1
        bf.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(bf, text="📋  Copier le titre", height=38,
                      corner_radius=10, fg_color=C["border"],
                      hover_color=C["card_hover"], text_color=C["t1"],
                      font=ctk.CTkFont(size=12),
                      command=self._copier_titre
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(bf, text="📄  Copier la description", height=38,
                      corner_radius=10, fg_color=C["border"],
                      hover_color=C["card_hover"], text_color=C["t1"],
                      font=ctk.CTkFont(size=12),
                      command=self._copier_description
        ).grid(row=0, column=1, padx=(4, 0), sticky="ew")
        produit_enc = self._analyse.produit.replace(" ", "+")
        ctk.CTkButton(bf, text="🔍  Rechercher sur Vinted", height=38,
                      corner_radius=10, fg_color=C["accent"],
                      hover_color=C["accent_hover"], text_color="#000000",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda p=produit_enc: webbrowser.open(
                          f"https://www.vinted.fr/catalog?search_text={p}")
        ).grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky="ew")

    def _copier_titre(self):
        self.clipboard_clear()
        self.clipboard_append(self._titre_var.get())
        envoyer_toast("Copié !", "Titre copié dans le presse-papier.")

    def _copier_description(self):
        self.clipboard_clear()
        self.clipboard_append(self._desc_box.get("1.0", "end").strip())
        envoyer_toast("Copié !", "Description copiée dans le presse-papier.")


class CarteAnnonce(ctk.CTkFrame):
    """
    Carte annonce mode grille.
    État normal  : image + titre + prix + tags — boutons cachés.
    État étendu  : après un clic sur la carte, tous les boutons d'action apparaissent.
    """
    IMAGE_W = 220
    IMAGE_H = 200

    def __init__(self, parent, annonce: scraper.Annonce, app, nouveau=False,
                 selection_var=None, **kwargs):
        self._border_base = C["nouveau"] if nouveau else C["border"]
        super().__init__(parent, corner_radius=16, fg_color=C["card"],
                         border_width=1, border_color=self._border_base,
                         width=260, **kwargs)
        self.annonce      = annonce
        self.app          = app
        self._photo       = None
        self._pil_img     = None
        self._sel_var     = selection_var
        self._etendu      = False
        self._construire(nouveau)
        self._charger_image()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    # ── Construction ──────────────────────────────────────────────────────────

    def _construire(self, nouveau):
        self.grid_columnconfigure(0, weight=1)
        row = 0

        # Badge NEW + checkbox comparateur
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=row, column=0, padx=10, pady=(8, 0), sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        if nouveau:
            ctk.CTkLabel(top, text="● NEW", font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C["nouveau"]).grid(row=0, column=0, sticky="w")
        if self._sel_var is not None:
            ctk.CTkCheckBox(top, text="", variable=self._sel_var, width=20,
                            fg_color=C["accent"], hover_color=C["accent_hover"],
                            border_color=C["border"],
                            command=self.app._maj_bouton_comparateur
            ).grid(row=0, column=1, sticky="e")
        row += 1

        # Image cliquable
        self.lbl_image = ctk.CTkLabel(self, text="", width=self.IMAGE_W,
                                      height=self.IMAGE_H, fg_color="#2C2C2C",
                                      corner_radius=12, text_color=C["t3"],
                                      font=ctk.CTkFont(family=FONT, size=22))
        self.lbl_image.grid(row=row, column=0, padx=12, pady=(4, 6), sticky="ew")
        self.lbl_image.bind("<Button-1>", self._toggle_etendu)
        self.lbl_image.bind("<Button-3>", self._menu_image)
        self.lbl_image.configure(cursor="hand2")
        row += 1

        # Titre
        self.lbl_titre = ctk.CTkLabel(self, text=self._trunc(self.annonce.title, 32),
                     font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
                     text_color=C["t1"], wraplength=220, justify="left")
        self.lbl_titre.grid(row=row, column=0, padx=12, pady=(0, 4), sticky="w")
        self.lbl_titre.bind("<Button-1>", self._toggle_etendu)
        self.lbl_titre.configure(cursor="hand2")
        row += 1

        # Prix + tags
        row_info = ctk.CTkFrame(self, fg_color="transparent")
        row_info.grid(row=row, column=0, padx=12, pady=(0, 6), sticky="ew")
        row_info.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row_info, text=self.annonce.prix_affiche(),
                     font=ctk.CTkFont(family=FONT, size=17, weight="bold"),
                     text_color=C["prix"]).grid(row=0, column=0, sticky="w")
        tags = [t for t in [self.annonce.brand, self.annonce.size] if t]
        if tags:
            tf = ctk.CTkFrame(row_info, fg_color="transparent")
            tf.grid(row=0, column=1, sticky="e")
            for tag in tags[:2]:
                ctk.CTkLabel(tf, text=tag, font=ctk.CTkFont(size=10),
                             text_color=C["tag_fg"], fg_color=C["tag_bg"],
                             corner_radius=6, padx=6, pady=2
                ).pack(side="left", padx=2)
        row += 1

        # Condition
        if self.annonce.condition:
            ctk.CTkLabel(self, text=f"✓  {self.annonce.condition}",
                         font=ctk.CTkFont(family=FONT, size=10), text_color=C["t2"],
                         fg_color=C["tag_bg"], corner_radius=6, padx=8, pady=3
            ).grid(row=row, column=0, padx=12, pady=(0, 4), sticky="w")
            row += 1

        # Hint expand
        self.lbl_hint = ctk.CTkLabel(self, text="↓  Cliquer pour les actions",
                     font=ctk.CTkFont(family=FONT, size=9), text_color=C["t3"])
        self.lbl_hint.grid(row=row, column=0, padx=12, pady=(0, 8))
        self.lbl_hint.bind("<Button-1>", self._toggle_etendu)
        self.lbl_hint.configure(cursor="hand2")
        row += 1

        # ── Zone d'actions (cachée par défaut) ──────────────────────────────────
        self._row_actions_start = row
        self._frame_actions = ctk.CTkFrame(self, fg_color="transparent")
        # griddée uniquement quand étendu
        self._frame_actions.grid_columnconfigure(0, weight=1)
        self._construire_actions()

    def _construire_actions(self):
        f = self._frame_actions
        f.grid_columnconfigure(0, weight=1)

        sep = ctk.CTkFrame(f, fg_color=C["accent"], height=1)
        sep.grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 8))

        # Rangée 1 : Voir · Historique · Favori
        r1 = ctk.CTkFrame(f, fg_color="transparent")
        r1.grid(row=1, column=0, padx=8, pady=(0, 4), sticky="ew")
        r1.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(r1, text="Voir sur Vinted →", height=34, corner_radius=8,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#000000", font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
                      command=lambda: webbrowser.open(self.annonce.url)
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

        ctk.CTkButton(r1, text="📈", width=34, height=34, corner_radius=8,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=14),
                      command=lambda: FenetreHistorique(
                          self.winfo_toplevel(), str(self.annonce.id), self.annonce.title)
        ).grid(row=0, column=1, padx=(0, 4))

        est_fav = data.est_favori(self.annonce.id)
        self.btn_fav = ctk.CTkButton(r1, text="♥", width=34, height=34, corner_radius=8,
                                     fg_color=C["fav"] if est_fav else "transparent",
                                     border_width=1,
                                     border_color=C["fav"] if est_fav else C["border"],
                                     hover_color=C["fav"], text_color=C["fav"],
                                     font=ctk.CTkFont(size=14),
                                     command=self._toggle_fav)
        self.btn_fav.grid(row=0, column=2)

        # Rangée 2 : Analyser & Cibler
        ctk.CTkButton(f, text="🎯  Analyser & Cibler", height=32, corner_radius=8,
                      fg_color="transparent", hover_color=C["cible"],
                      border_width=1, border_color=C["cible"],
                      text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=11, weight="bold"),
                      command=self._ouvrir_analyse
        ).grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")

        # Rangée 3 : Comparateur multi-sites
        ctk.CTkButton(f, text="🌐  Comparer les prix", height=32, corner_radius=8,
                      fg_color="transparent", hover_color="#1a3a2a",
                      border_width=1, border_color=C["prix"],
                      text_color=C["prix"], font=ctk.CTkFont(family=FONT, size=11, weight="bold"),
                      command=self._ouvrir_comparateur_prix
        ).grid(row=3, column=0, padx=8, pady=(0, 4), sticky="ew")

        # Rangée 4 : Aperçu · Copier lien
        r4 = ctk.CTkFrame(f, fg_color="transparent")
        r4.grid(row=4, column=0, padx=8, pady=(0, 10), sticky="ew")
        r4.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(r4, text="🔍 Aperçu", height=28, corner_radius=7,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=lambda: FenetreApercu(self.winfo_toplevel(), self.annonce)
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(r4, text="🔗 Lien", width=64, height=28, corner_radius=7,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=self._copier_lien
        ).grid(row=0, column=1)

    # ── Toggle étendu ─────────────────────────────────────────────────────────

    def _toggle_etendu(self, event=None):
        self._etendu = not self._etendu
        if self._etendu:
            self._frame_actions.grid(row=self._row_actions_start, column=0,
                                     sticky="ew", padx=0, pady=0)
            self.lbl_hint.configure(text="↑  Réduire", text_color=C["accent"])
            self.configure(border_color=C["accent"])
        else:
            self._frame_actions.grid_remove()
            self.lbl_hint.configure(text="↓  Cliquer pour les actions", text_color=C["t3"])
            self.configure(border_color=self._border_base)

    def _on_enter(self, _=None):
        if not self._etendu:
            self.configure(fg_color=C["card_hover"], border_color=C["accent"])
            if hasattr(self, "lbl_hint"):
                self.lbl_hint.configure(text_color=C["t2"])

    def _on_leave(self, _=None):
        if not self._etendu:
            self.configure(fg_color=C["card"], border_color=self._border_base)
            if hasattr(self, "lbl_hint"):
                self.lbl_hint.configure(text_color=C["t3"])

    # ── Actions ───────────────────────────────────────────────────────────────

    def _ouvrir_analyse(self):
        app = self.winfo_toplevel()
        FenetreAnalyse(app, self.annonce, getattr(app, "_annonces", []))

    def _ouvrir_comparateur_prix(self):
        FenetreComparateurPrix(self.winfo_toplevel(), self.annonce)

    def _toggle_fav(self):
        ajout = data.toggle_favori(self.annonce)
        self.btn_fav.configure(
            fg_color=C["fav"] if ajout else "transparent",
            border_color=C["fav"] if ajout else C["border"])
        self.app.rafraichir_favoris()

    def _copier_lien(self):
        self.clipboard_clear()
        self.clipboard_append(self.annonce.url)

    def _menu_image(self, event):
        menu = Menu(self, tearoff=0, bg="#1a2333", fg="#f0f4f8",
                    activebackground=C["accent"], activeforeground="#000000",
                    font=("Segoe UI", 11), bd=0, relief="flat")
        if self._pil_img and _WIN32:
            menu.add_command(label="Copier l'image", command=self._copier_image)
        if self._pil_img:
            menu.add_command(label="Enregistrer l'image…", command=self._enregistrer_image)
            menu.add_separator()
        menu.add_command(label="Copier le lien", command=self._copier_lien)
        menu.add_command(label="Ouvrir dans le navigateur",
                         command=lambda: webbrowser.open(self.annonce.url))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copier_image(self):
        if not _WIN32: return
        try:
            buf = BytesIO()
            self._pil_img.save(buf, format="BMP")
            bmp_data = buf.getvalue()[14:]
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
            win32clipboard.CloseClipboard()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de copier l'image :\n{e}")

    def _enregistrer_image(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("Tous", "*.*")],
            initialfile=f"{self._trunc(self.annonce.title, 40)}.jpg")
        if path:
            try: self._pil_img.save(path)
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible d'enregistrer :\n{e}")

    def _charger_image(self):
        if self.annonce.image_url:
            self.app._img_pool.submit(self._dl_image)
        else:
            self.lbl_image.configure(text="📷")

    def _dl_image(self):
        try:
            r = requests.get(self.annonce.image_url, timeout=8)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content))
            self._pil_img = img.convert("RGB")
            img_r = img.resize((self.IMAGE_W, self.IMAGE_H), Image.LANCZOS)
            ci = ctk.CTkImage(light_image=img_r, dark_image=img_r,
                              size=(self.IMAGE_W, self.IMAGE_H))
            self.after(0, lambda: (self.lbl_image.configure(image=ci, text=""),
                                   setattr(self, "_photo", ci)))
        except Exception:
            self.after(0, lambda: self.lbl_image.configure(text="✕"))

    @staticmethod
    def _trunc(s, n): return s if len(s) <= n else s[:n-1] + "…"


# ─── Ligne Annonce (mode liste) ───────────────────────────────────────────────

    def _construire(self, nouveau):
        self.grid_columnconfigure(0, weight=1)
        row = 0
        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.grid(row=row, column=0, padx=10, pady=(8, 0), sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)
        if nouveau:
            ctk.CTkLabel(top_row, text="● NEW",
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C["nouveau"], fg_color="transparent"
            ).grid(row=0, column=0, sticky="w")
        if self._sel_var is not None:
            ctk.CTkCheckBox(top_row, text="Comparer", variable=self._sel_var,
                            font=ctk.CTkFont(size=10), text_color=C["t3"],
                            fg_color=C["accent"], hover_color=C["accent_hover"],
                            border_color=C["border"], width=16, height=16,
                            command=self.app._maj_bouton_comparateur
            ).grid(row=0, column=1, sticky="e")
        row += 1
        self.lbl_image = ctk.CTkLabel(self, text="", width=self.IMAGE_W,
                                      height=self.IMAGE_H, fg_color="#2C2C2C",
                                      corner_radius=12, text_color=C["t3"],
                                      font=ctk.CTkFont(family=FONT, size=22))
        self.lbl_image.grid(row=row, column=0, padx=12, pady=(4, 6), sticky="ew")
        self.lbl_image.bind("<Button-3>", self._menu_image)
        self.lbl_image.bind("<Button-1>",
                            lambda _: FenetreApercu(self.winfo_toplevel(), self.annonce))
        self.lbl_image.configure(cursor="hand2")
        row += 1
        ctk.CTkLabel(self, text=self._trunc(self.annonce.title, 32),
                     font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
                     text_color=C["t1"], wraplength=220, justify="left"
        ).grid(row=row, column=0, padx=12, pady=(0, 4), sticky="w")
        row += 1
        row_info = ctk.CTkFrame(self, fg_color="transparent")
        row_info.grid(row=row, column=0, padx=12, pady=(0, 6), sticky="ew")
        row_info.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row_info, text=self.annonce.prix_affiche(),
                     font=ctk.CTkFont(family=FONT, size=17, weight="bold"), text_color=C["prix"]
        ).grid(row=0, column=0, sticky="w")
        tags = [t for t in [self.annonce.brand, self.annonce.size] if t]
        if tags:
            tf = ctk.CTkFrame(row_info, fg_color="transparent")
            tf.grid(row=0, column=1, sticky="e")
            for tag in tags[:2]:
                ctk.CTkLabel(tf, text=tag, font=ctk.CTkFont(size=10),
                             text_color=C["tag_fg"], fg_color=C["tag_bg"],
                             corner_radius=6, padx=6, pady=2
                ).pack(side="left", padx=2)
        row += 1
        if self.annonce.condition:
            ctk.CTkLabel(self, text=f"✓  {self.annonce.condition}",
                         font=ctk.CTkFont(family=FONT, size=10), text_color=C["t2"],
                         fg_color=C["tag_bg"], corner_radius=6, padx=8, pady=3
            ).grid(row=row, column=0, padx=12, pady=(0, 4), sticky="w")
            row += 1
        ctk.CTkFrame(self, fg_color=C["border"], height=1).grid(
            row=row, column=0, sticky="ew", padx=12, pady=4)
        row += 1
        # Boutons — rangée 1 : Voir (filled cyan), Historique, Favori
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=row, column=0, padx=12, pady=(2, 4), sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(btn_row, text="Voir →", height=36, corner_radius=8,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#000000", font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
                      command=lambda: webbrowser.open(self.annonce.url)
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(btn_row, text="📈", width=36, height=36, corner_radius=8,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=14),
                      command=lambda: FenetreHistorique(
                          self.winfo_toplevel(), str(self.annonce.id),
                          self.annonce.title)
        ).grid(row=0, column=1, padx=(0, 4))
        fav_color = C["fav"] if data.est_favori(self.annonce.id) else "transparent"
        self.btn_fav = ctk.CTkButton(btn_row, text="♥", width=36, height=36,
                                     corner_radius=8,
                                     fg_color=fav_color,
                                     border_width=1, border_color=C["fav"] if data.est_favori(self.annonce.id) else C["border"],
                                     hover_color=C["fav"], text_color=C["fav"],
                                     font=ctk.CTkFont(size=14),
                                     command=self._toggle_fav)
        self.btn_fav.grid(row=0, column=2)
        row += 1
        # Bouton — rangée 2 : Analyser (outline cyan)
        ctk.CTkButton(self, text="🎯  Analyser & Cibler", height=32, corner_radius=8,
                      fg_color="transparent", hover_color=C["cible"],
                      border_width=1, border_color=C["cible"],
                      text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=11, weight="bold"),
                      command=self._ouvrir_analyse
        ).grid(row=row, column=0, padx=12, pady=(0, 14), sticky="ew")

    def _ouvrir_analyse(self):
        app = self.winfo_toplevel()
        marche = getattr(app, "_annonces", [])
        FenetreAnalyse(app, self.annonce, marche)

    def _menu_image(self, event):
        menu = Menu(self, tearoff=0, bg="#1a2333", fg="#f0f4f8",
                    activebackground=C["accent"], activeforeground="#000000",
                    font=("Segoe UI", 11), bd=0, relief="flat")
        if self._pil_img and _WIN32:
            menu.add_command(label="📋  Copier l'image", command=self._copier_image)
        if self._pil_img:
            menu.add_command(label="💾  Enregistrer l'image…", command=self._enregistrer_image)
            menu.add_separator()
        menu.add_command(label="🔗  Copier le lien", command=self._copier_lien)
        menu.add_command(label="🌐  Ouvrir dans le navigateur",
                         command=lambda: webbrowser.open(self.annonce.url))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copier_image(self):
        if not _WIN32: return
        try:
            buf = BytesIO()
            self._pil_img.save(buf, format="BMP")
            bmp_data = buf.getvalue()[14:]
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
            win32clipboard.CloseClipboard()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de copier l'image :\n{e}")

    def _enregistrer_image(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("Tous", "*.*")],
            initialfile=f"{self._trunc(self.annonce.title, 40)}.jpg")
        if path:
            try: self._pil_img.save(path)
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible d'enregistrer :\n{e}")

    def _copier_lien(self):
        self.clipboard_clear()
        self.clipboard_append(self.annonce.url)

    def _toggle_fav(self):
        ajout = data.toggle_favori(self.annonce)
        self.btn_fav.configure(fg_color=C["fav"] if ajout else C["border"])
        self.app.rafraichir_favoris()

    def _charger_image(self):
        if self.annonce.image_url:
            self.app._img_pool.submit(self._dl_image)
        else:
            self.lbl_image.configure(text="📷")

    def _dl_image(self):
        try:
            r = requests.get(self.annonce.image_url, timeout=8)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content))
            self._pil_img = img.convert("RGB")
            img_r = img.resize((self.IMAGE_W, self.IMAGE_H), Image.LANCZOS)
            ci = ctk.CTkImage(light_image=img_r, dark_image=img_r,
                              size=(self.IMAGE_W, self.IMAGE_H))
            self.after(0, lambda: (self.lbl_image.configure(image=ci, text=""),
                                   setattr(self, "_photo", ci)))
        except Exception:
            self.after(0, lambda: self.lbl_image.configure(text="✕"))

    @staticmethod
    def _trunc(s, n): return s if len(s) <= n else s[:n-1] + "…"


# ─── Ligne Annonce (mode liste) ───────────────────────────────────────────────

class LigneAnnonce(ctk.CTkFrame):
    IMG_S = 56

    def __init__(self, parent, annonce: scraper.Annonce, app, nouveau=False,
                 selection_var=None, **kwargs):
        super().__init__(parent, corner_radius=10, fg_color=C["liste_bg"],
                         border_width=1, border_color=C["nouveau"] if nouveau else C["border"],
                         height=72, **kwargs)
        self.grid_propagate(False)
        self.annonce  = annonce
        self.app      = app
        self._photo   = None
        self._sel_var = selection_var
        self.grid_columnconfigure(2, weight=1)
        self._construire(nouveau)
        self._charger_image()
        self.bind("<Enter>", lambda _: self.configure(fg_color=C["liste_hover"]))
        self.bind("<Leave>", lambda _: self.configure(fg_color=C["liste_bg"]))

    def _construire(self, nouveau):
        col = 0
        if self._sel_var is not None:
            ctk.CTkCheckBox(self, text="", variable=self._sel_var, width=20,
                            fg_color=C["accent"], hover_color=C["accent_hover"],
                            border_color=C["border"],
                            command=self.app._maj_bouton_comparateur
            ).grid(row=0, column=col, padx=(10, 0), pady=8)
            col += 1
        self.lbl_img = ctk.CTkLabel(self, text="…", width=self.IMG_S,
                                    height=self.IMG_S, fg_color="#1a2333",
                                    corner_radius=8, text_color=C["t3"])
        self.lbl_img.grid(row=0, column=col, padx=(8, 6), pady=8)
        self.lbl_img.bind("<Button-1>",
                          lambda _: FenetreApercu(self.winfo_toplevel(), self.annonce))
        self.lbl_img.configure(cursor="hand2")
        col += 1
        txt = ctk.CTkFrame(self, fg_color="transparent")
        txt.grid(row=0, column=col, padx=6, pady=8, sticky="ew")
        txt.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(txt, text=CarteAnnonce._trunc(self.annonce.title, 60),
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t1"] if not nouveau else C["nouveau"],                     anchor="w").grid(row=0, column=0, sticky="ew")
        sub = " • ".join(filter(None, [self.annonce.brand, self.annonce.size,
                                       self.annonce.condition,
                                       getattr(self.annonce, "vendeur_nom", "")]))
        ctk.CTkLabel(txt, text=sub, font=ctk.CTkFont(size=10),
                     text_color=C["t3"], anchor="w").grid(row=1, column=0, sticky="ew")
        col += 1
        ctk.CTkLabel(self, text=self.annonce.prix_affiche(),
                     font=ctk.CTkFont(size=15, weight="bold"), text_color=C["prix"]
        ).grid(row=0, column=col, padx=12)
        col += 1
        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.grid(row=0, column=col, padx=(0, 10), pady=8)
        ctk.CTkButton(btn_f, text="Voir →", width=72, height=30, corner_radius=7,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"),
                      command=lambda: webbrowser.open(self.annonce.url)
        ).pack(side="left", padx=2)
        ctk.CTkButton(btn_f, text="📈", width=30, height=30, corner_radius=7,
                      fg_color=C["border"], hover_color="#2d3a50", text_color=C["t2"],
                      command=lambda: FenetreHistorique(
                          self.winfo_toplevel(), str(self.annonce.id),
                          self.annonce.title)
        ).pack(side="left", padx=2)
        ctk.CTkButton(btn_f, text="🎯", width=30, height=30, corner_radius=7,
                      fg_color=C["cible"], hover_color="#6d28d9", text_color="#fff",
                      command=self._ouvrir_analyse
        ).pack(side="left", padx=2)
        fav_color = C["fav"] if data.est_favori(self.annonce.id) else C["border"]
        self.btn_fav = ctk.CTkButton(btn_f, text="♥", width=30, height=30,
                                     corner_radius=7, fg_color=fav_color,
                                     hover_color=C["fav"], text_color=C["t1"],
                                     command=self._toggle_fav)
        self.btn_fav.pack(side="left", padx=2)

    def _ouvrir_analyse(self):
        app = self.winfo_toplevel()
        marche = getattr(app, "_annonces", [])
        FenetreAnalyse(app, self.annonce, marche)

    def _charger_image(self):
        if self.annonce.image_url:
            self.app._img_pool.submit(self._dl_image)
        else:
            self.lbl_img.configure(text="📷")

    def _dl_image(self):
        try:
            r = requests.get(self.annonce.image_url, timeout=8)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).resize(
                (self.IMG_S, self.IMG_S), Image.LANCZOS)
            ci = ctk.CTkImage(light_image=img, dark_image=img,
                              size=(self.IMG_S, self.IMG_S))
            self._photo = ci
            self.after(0, lambda: self.lbl_img.configure(image=ci, text=""))
        except Exception:
            self.after(0, lambda: self.lbl_img.configure(text="✕"))

    def _toggle_fav(self):
        ajout = data.toggle_favori(self.annonce)
        self.btn_fav.configure(fg_color=C["fav"] if ajout else C["border"])
        self.app.rafraichir_favoris()


# ─── Application principale ───────────────────────────────────────────────────

class AppVinted(ctk.CTk):
    ARTICLES_PAR_PAGE = 10
    SIDEBAR_FULL      = 340
    SIDEBAR_MINI      = 60
    CARD_MIN_W        = 280
    COLONNES          = 3

    def __init__(self):
        super().__init__()
        self.title("VintedScrap")
        self.configure(fg_color=C["bg"])

        # ── Ajustement automatique de la fenêtre ──────────────────────────────
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Taille idéale : 75% de l'écran, minimum 1080x700
        w = max(1080, min(1400, int(sw * 0.78)))
        h = max(700,  min(920,  int(sh * 0.85)))
        x = (sw - w) // 2
        y = max(0, (sh - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(max(900, int(sw * 0.55)), max(600, int(sh * 0.60)))

        self.scraper   = scraper.VintedScraper(delai_entre_requetes=1.0)
        self._img_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="img")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._annonces:        list = []
        self._ordre_tri:       str  = "prix_asc"
        self._page_courante:   int  = 1
        self._etats_actifs:    set  = set()
        self._sidebar_mini:   bool = False
        self._derniere_cols:  int  = 3
        self._mode_liste:      bool = False
        self._sel_vars:        list = []
        self._anim_job              = None
        self._render_job            = None
        self._anim_iter             = itertools.cycle(["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"])
        self._alerte_active:   bool = False
        self._alerte_job            = None
        self._alerte_ids:      set  = set()
        self._titre_recherche: str  = ""
        self._suggest_job           = None
        self._suggest_visible: bool = False

        self._construire_ui()
        self.bind("<Configure>", self._maj_layout)
        self.after(300, self._maj_layout)
        threading.Thread(target=data.purger_historique_ancien, daemon=True).start()
        # Afficher les recommandations dès le démarrage si historique disponible
        self.after(800, self._afficher_recommandations_accueil)


    # ══ Elastic Layout ════════════════════════════════════════════════════════

    def _colonnes_pour_largeur(self) -> int:
        """Calcule le nb de colonnes selon la largeur disponible de zone_scroll."""
        try:
            self.zone_scroll.update_idletasks()
            w = self.zone_scroll.winfo_width()
        except Exception:
            w = 900
        if w < 330:   return 1
        if w < 600:   return 2
        if w < 880:   return 3
        return max(3, w // self.CARD_MIN_W)

    def _maj_layout(self, event=None):
        """Appelé sur <Configure> de la fenêtre — adapte sidebar + colonnes."""
        try:
            self.update_idletasks()
            win_w = self.winfo_width()
        except Exception:
            return

        # ── Sidebar auto-collapse ──────────────────────────────────────────
        seuil_mini = 1100
        nouveau_mini = win_w < seuil_mini
        if nouveau_mini != self._sidebar_mini:
            self._sidebar_mini = nouveau_mini
            self._animer_sidebar(cible=self.SIDEBAR_MINI if nouveau_mini else self.SIDEBAR_FULL)

        # ── Grille dynamique ──────────────────────────────────────────────
        cols = self._colonnes_pour_largeur()
        if cols != getattr(self, "_derniere_cols", -1):
            self._derniere_cols = cols
            # Reconfigurer les colonnes du scroll
            try:
                # Reset toutes les anciennes colonnes
                for c in range(10):
                    try:
                        self.zone_scroll.grid_columnconfigure(c, weight=0, minsize=0)
                    except Exception:
                        pass
                for c in range(cols):
                    self.zone_scroll.grid_columnconfigure(c, weight=1, uniform="col")
            except Exception:
                pass
            # Re-render si on a des annonces
            if self._annonces:
                self._rendre_cartes(self._annonces)

        # ── Header overflow ───────────────────────────────────────────────
        self._maj_header_overflow(win_w)

    def _animer_sidebar(self, cible: int, duree: int = 200, pas: int = 20):
        """Animation fluide sidebar expand/collapse."""
        try:
            actuelle = self._sb_frame.winfo_width()
        except Exception:
            return
        delta = cible - actuelle
        if abs(delta) <= 2:
            self._sb_frame.configure(width=cible)
            self._maj_contenu_sidebar(cible <= self.SIDEBAR_MINI + 20)
            return
        etape = max(2, abs(delta) * pas // duree)
        nouvelle = actuelle + (etape if delta > 0 else -etape)
        self._sb_frame.configure(width=nouvelle)
        self.after(16, lambda: self._animer_sidebar(cible, duree, pas))

    def _maj_contenu_sidebar(self, mini: bool):
        """Bascule logo/labels selon mode mini ou plein."""
        try:
            if mini:
                self._lbl_logo_text.grid_remove()
                self._lbl_logo_sub.grid_remove()
                self._tabs_sidebar.grid_remove()
                self._btn_toggle_sb.configure(text="▶")
                self.lbl_stats.grid_remove()
            else:
                self._lbl_logo_text.grid()
                self._lbl_logo_sub.grid()
                self._tabs_sidebar.grid()
                self._btn_toggle_sb.configure(text="◀")
                self.lbl_stats.grid()
        except Exception:
            pass

    def _toggle_sidebar_manuel(self):
        """Bouton toggle manuel de la sidebar."""
        self._sidebar_mini = not self._sidebar_mini
        cible = self.SIDEBAR_MINI if self._sidebar_mini else self.SIDEBAR_FULL
        self._animer_sidebar(cible)

    def _maj_header_overflow(self, win_w: int):
        """Cache/montre le bouton overflow selon la largeur."""
        seuil_overflow = 1050
        try:
            if win_w < seuil_overflow:
                self.btn_comparer.pack_forget()
                self.btn_dashboard.pack_forget()
                self.btn_export.pack_forget()
                self._btn_overflow.pack(side="left", padx=4)
            else:
                self._btn_overflow.pack_forget()
                self.btn_comparer.pack(side="left", padx=4)
                self.btn_dashboard.pack(side="left", padx=4)
                self.btn_export.pack(side="left", padx=4)
        except Exception:
            pass

    def _on_close(self):
        self._img_pool.shutdown(wait=False)
        self.scraper.close()
        self.destroy()

    # ══ UI ════════════════════════════════════════════════════════════════════

    def _construire_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._construire_sidebar()
        self._construire_zone_principale()

    @staticmethod
    def _sep(parent, row):
        ctk.CTkFrame(parent, fg_color=C["border"], height=1).grid(
            row=row, column=0, sticky="ew", padx=16, pady=6)

    @staticmethod
    def _slabel(parent, row, text, icon=""):
        label = f"{icon}  {text}" if icon else text
        ctk.CTkLabel(parent, text=label,
                     font=ctk.CTkFont(family=FONT, size=9, weight="bold"),
                     text_color=C["t3"], anchor="w"
        ).grid(row=row, column=0, padx=18, pady=(12, 2), sticky="w")

    # ── Sidebar ────────────────────────────────────────────────────────────────

    def _construire_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=C["sidebar"], corner_radius=0, width=340)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(2, weight=1)

        # Logo
        lf = ctk.CTkFrame(sb, fg_color="transparent")
        lf.grid(row=0, column=0, padx=20, pady=(24, 18), sticky="w")
        ctk.CTkLabel(lf, text="◈",
                     font=ctk.CTkFont(family=FONT, size=22, weight="bold"),
                     text_color=C["accent"], fg_color="transparent"
        ).pack(side="left", padx=(0, 10))
        tc = ctk.CTkFrame(lf, fg_color="transparent")
        tc.pack(side="left")
        ctk.CTkLabel(tc, text="VintedScrap",
                     font=ctk.CTkFont(family=FONT, size=16, weight="bold"),
                     text_color=C["t1"]).pack(anchor="w")
        ctk.CTkLabel(tc, text="Scout  ·  Analyse  ·  Multi-pays",
                     font=ctk.CTkFont(family=FONT, size=9), text_color=C["t3"]).pack(anchor="w")

        ctk.CTkFrame(sb, fg_color=C["border"], height=1).grid(
            row=1, column=0, sticky="ew")

        tabs = ctk.CTkTabview(sb, fg_color=C["sidebar"],
                              segmented_button_fg_color=C["bg"],
                              segmented_button_selected_color=C["accent"],
                              segmented_button_selected_hover_color=C["accent_hover"],
                              segmented_button_unselected_color=C["bg"],
                              segmented_button_unselected_hover_color=C["border"],
                              text_color=C["t1"], text_color_disabled=C["t3"],
                              anchor="nw")
        tabs.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        tabs.add("Recherche")
        tabs.add("Favoris")
        tabs.add("Sauv.")
        tabs.add("Ciblage")
        tabs.add("Revente")

        self._construire_tab_recherche(tabs.tab("Recherche"))
        self._construire_tab_favoris(tabs.tab("Favoris"))
        self._construire_tab_sauvegardes(tabs.tab("Sauv."))
        self._construire_tab_ciblage(tabs.tab("Ciblage"))
        self._construire_tab_revente(tabs.tab("Revente"))

        self.lbl_stats = ctk.CTkLabel(sb, text="", font=ctk.CTkFont(size=10),
                                      text_color=C["t3"], justify="center")
        self.lbl_stats.grid(row=3, column=0, pady=(4, 14))

    # ── Tab Recherche ──────────────────────────────────────────────────────────

    def _construire_tab_recherche(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        row = 0
        self._slabel(tab, row, "LOCALISATION", "🌐"); row += 1
        self.menu_pays = ctk.CTkOptionMenu(
            tab, values=list(scraper.PAYS_DISPONIBLES.keys()),
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"],
            font=ctk.CTkFont(family=FONT, size=12), command=self._changer_pays)
        self.menu_pays.set("🇫🇷 France")
        self.menu_pays.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        self._slabel(tab, row, "MOTS-CLÉS", "🔍"); row += 1
        self.champ_recherche = ctk.CTkEntry(
            tab, placeholder_text="ex : op12 display, luffy sr...",
            height=40, corner_radius=8, font=ctk.CTkFont(family=FONT, size=13),
            fg_color=C["input_bg"], border_color=C["accent"],
            border_width=1, text_color=C["t1"])
        self.champ_recherche.grid(row=row, column=0, padx=16, pady=(4, 2), sticky="ew"); row += 1
        self.champ_recherche.bind("<Return>", lambda _: self._lancer_recherche())
        self.champ_recherche.bind("<KeyRelease>", self._on_recherche_key)
        self.champ_recherche.bind("<Escape>", lambda _: self._cacher_suggestions())
        self.champ_recherche.bind("<FocusOut>", lambda _: self.after(150, self._cacher_suggestions))

        # Frame suggestions (autocomplete)
        self._frame_suggestions = ctk.CTkFrame(tab, fg_color=C["card"],
                                               corner_radius=8, border_width=1,
                                               border_color=C["accent"])
        # N'est pas griddée par défaut — apparaît dynamiquement
        ctk.CTkLabel(tab, text="Virgule = plusieurs termes",
                     font=ctk.CTkFont(family=FONT, size=10), text_color=C["t3"]
        ).grid(row=row, column=0, padx=16, pady=(0, 4), sticky="w"); row += 1
        self._slabel(tab, row, "BUDGET (€)", "🏷️"); row += 1
        pr = ctk.CTkFrame(tab, fg_color="transparent")
        pr.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        pr.grid_columnconfigure((0, 2), weight=1)
        self.champ_prix_min = ctk.CTkEntry(pr, placeholder_text="Min", height=36,
            corner_radius=8, fg_color=C["input_bg"], border_color=C["border"], text_color=C["t1"])
        self.champ_prix_min.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(pr, text="—", text_color=C["t3"]).grid(row=0, column=1, padx=6)
        self.champ_prix_max = ctk.CTkEntry(pr, placeholder_text="Max", height=36,
            corner_radius=8, fg_color=C["input_bg"], border_color=C["border"], text_color=C["t1"])
        self.champ_prix_max.grid(row=0, column=2, sticky="ew")
        self._slabel(tab, row, "CATÉGORIE"); row += 1
        self.menu_categorie = ctk.CTkOptionMenu(
            tab, values=["— Toutes —"] + list(scraper.CATEGORIES.keys()),
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=11))
        self.menu_categorie.set("— Toutes —")
        self.menu_categorie.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        self._slabel(tab, row, "COULEUR"); row += 1
        self.menu_couleur = ctk.CTkOptionMenu(
            tab, values=["— Toutes —"] + list(scraper.COULEURS.keys()),
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=11))
        self.menu_couleur.set("— Toutes —")
        self.menu_couleur.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        self._slabel(tab, row, "VENDEUR"); row += 1
        self.champ_vendeur = ctk.CTkEntry(
            tab, placeholder_text="ID numérique du vendeur", height=34, corner_radius=8,
            font=ctk.CTkFont(family=FONT, size=12), fg_color=C["input_bg"], border_color=C["border"],
            text_color=C["t1"])
        self.champ_vendeur.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        self._slabel(tab, row, "TRIER PAR"); row += 1
        tf = ctk.CTkFrame(tab, fg_color="transparent")
        tf.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        tf.grid_columnconfigure((0, 1), weight=1)
        self.btn_tri_asc = ctk.CTkButton(tf, text="Prix ↑", height=32,
            corner_radius=8, fg_color=C["accent"], hover_color=C["accent_hover"],
            text_color="#000000", font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
            command=lambda: self._trier("prix_asc"))
        self.btn_tri_asc.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.btn_tri_desc = ctk.CTkButton(tf, text="Prix ↓", height=32,
            corner_radius=8, fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            command=lambda: self._trier("prix_desc"))
        self.btn_tri_desc.grid(row=0, column=1, padx=(4, 0), sticky="ew")
        tf2 = ctk.CTkFrame(tab, fg_color="transparent")
        tf2.grid(row=row, column=0, padx=16, pady=(0, 8), sticky="ew"); row += 1
        tf2.grid_columnconfigure(0, weight=1)
        self.btn_tri_recent = ctk.CTkButton(tf2, text="Récent d'abord", height=32,
            corner_radius=8, fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            command=lambda: self._trier("recent"))
        self.btn_tri_recent.grid(row=0, column=0, sticky="ew")
        self._slabel(tab, row, "ÉTAT"); row += 1
        etat_frame = ctk.CTkFrame(tab, fg_color="transparent")
        etat_frame.grid(row=row, column=0, padx=16, pady=(4, 4), sticky="ew"); row += 1
        etat_frame.grid_columnconfigure((0,1,2,3), weight=1)
        self._btns_etat = {}
        for col, (label, ids) in enumerate([("Neuf", {4,6}), ("Très bon", {1}),
                                             ("Bon", {2}), ("Satisf.", {3})]):
            b = ctk.CTkButton(etat_frame, text=label, height=30, corner_radius=8,
                fg_color="transparent", hover_color=C["border"],
                border_width=1, border_color=C["border"],
                text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=11),
                command=lambda i=ids, l=label: self._toggle_etat(i, l))
            b.grid(row=0, column=col, padx=2, sticky="ew")
            self._btns_etat[label] = (b, ids)
        self._sep(tab, row); row += 1
        self.btn_rechercher = ctk.CTkButton(tab, text="  🔍  Rechercher  ", height=48,
            corner_radius=10, fg_color=C["accent"], hover_color=C["accent_hover"],
            text_color="#000000", font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
            command=self._lancer_recherche)
        self.btn_rechercher.grid(row=row, column=0, padx=16, pady=(4, 4), sticky="ew"); row += 1
        ab = ctk.CTkFrame(tab, fg_color="transparent")
        ab.grid(row=row, column=0, padx=16, pady=(0, 4), sticky="ew"); row += 1
        ab.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(ab, text="↺ Actualiser", height=32, corner_radius=10,
            fg_color="transparent", hover_color=C["border"], text_color=C["t1"],
            border_width=1, border_color=C["border"], font=ctk.CTkFont(family=FONT, size=12),
            command=self._lancer_recherche).grid(row=0, column=0, padx=(0,4), sticky="ew")
        ctk.CTkButton(ab, text="Sauvegarder", height=32, corner_radius=10,
            fg_color="transparent", hover_color=C["border"], text_color=C["t1"],
            border_width=1, border_color=C["border"], font=ctk.CTkFont(family=FONT, size=12),
            command=self._sauvegarder_recherche).grid(row=0, column=1, padx=(4,0), sticky="ew")
        self._sep(tab, row); row += 1
        self._slabel(tab, row, "ALERTE AUTOMATIQUE", "🔔"); row += 1
        al = ctk.CTkFrame(tab, fg_color="transparent")
        al.grid(row=row, column=0, padx=16, pady=(4, 6), sticky="ew"); row += 1
        al.grid_columnconfigure(0, weight=1)
        self.btn_alerte = ctk.CTkButton(al, text="Activer l'alerte", height=34,
            corner_radius=10, fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=12), command=self._toggle_alerte)
        self.btn_alerte.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(al, text="Intervalle :", font=ctk.CTkFont(family=FONT, size=11),
                     text_color=C["t3"]).grid(row=1, column=0, sticky="w")
        self.menu_intervalle = ctk.CTkOptionMenu(
            al, values=["5 min","10 min","15 min","30 min"],
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=12))
        self.menu_intervalle.set("10 min")
        self.menu_intervalle.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        al.grid_columnconfigure(1, weight=1)
        self.lbl_alerte_status = ctk.CTkLabel(tab, text="● Inactive",
            font=ctk.CTkFont(family=FONT, size=11), text_color=C["t3"])
        self.lbl_alerte_status.grid(row=row, column=0, padx=16, pady=(0, 8), sticky="w")

    # ── Tab Favoris ────────────────────────────────────────────────────────────

    def _construire_tab_favoris(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self.scroll_favoris = ctk.CTkScrollableFrame(tab, fg_color="transparent",
            scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["accent"])
        self.scroll_favoris.grid(row=0, column=0, sticky="nsew")
        self.scroll_favoris.grid_columnconfigure(0, weight=1)
        self.rafraichir_favoris()

    def rafraichir_favoris(self):
        for w in self.scroll_favoris.winfo_children(): w.destroy()
        favs = data.charger_favoris()
        if not favs:
            ctk.CTkLabel(self.scroll_favoris, text="Aucun favori\npour l'instant.",
                         font=ctk.CTkFont(size=12), text_color=C["t3"],
                         justify="center").pack(pady=40)
            return
        for fav in favs:
            f = ctk.CTkFrame(self.scroll_favoris, fg_color=C["card"],
                             corner_radius=10, border_width=1, border_color=C["border"])
            f.pack(fill="x", padx=8, pady=4)
            f.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(f, text=CarteAnnonce._trunc(fav["title"], 30),
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["t1"], wraplength=180, justify="left"
            ).grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")
            sym = {"EUR":"€","GBP":"£","USD":"$"}.get(fav.get("currency","EUR"), "€")
            ctk.CTkLabel(f, text=f"{fav['price']:.2f} {sym}",
                         font=ctk.CTkFont(size=13, weight="bold"), text_color=C["prix"]
            ).grid(row=1, column=0, padx=10, pady=(0, 4), sticky="w")
            bf = ctk.CTkFrame(f, fg_color="transparent")
            bf.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="ew")
            bf.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(bf, text="Ouvrir →", height=28, corner_radius=6,
                fg_color=C["accent"], hover_color=C["accent_hover"], text_color="#ffffff",
                font=ctk.CTkFont(size=11), command=lambda u=fav["url"]: webbrowser.open(u)
            ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
            ctk.CTkButton(bf, text="✕", width=28, height=28, corner_radius=6,
                fg_color=C["border"], hover_color=C["fav"], text_color=C["t2"],
                command=lambda i=fav["id"]: (data.supprimer_favori(i), self.rafraichir_favoris())
            ).grid(row=0, column=1)

    # ── Tab Sauvegardées ───────────────────────────────────────────────────────

    def _construire_tab_sauvegardes(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self.scroll_sauvegardes = ctk.CTkScrollableFrame(tab, fg_color="transparent",
            scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["accent"])
        self.scroll_sauvegardes.grid(row=0, column=0, sticky="nsew")
        self.scroll_sauvegardes.grid_columnconfigure(0, weight=1)
        self._rafraichir_sauvegardes()

    def _rafraichir_sauvegardes(self):
        for w in self.scroll_sauvegardes.winfo_children(): w.destroy()
        recherches = data.charger_recherches()
        if not recherches:
            ctk.CTkLabel(self.scroll_sauvegardes, text="Aucune recherche\nsauvegardée.",
                         font=ctk.CTkFont(size=12), text_color=C["t3"],
                         justify="center").pack(pady=40)
            return
        for r in recherches:
            f = ctk.CTkFrame(self.scroll_sauvegardes, fg_color=C["card"],
                             corner_radius=10, border_width=1, border_color=C["border"])
            f.pack(fill="x", padx=8, pady=4)
            f.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(f, text=r["nom"], font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C["accent"]).grid(row=0, column=0, padx=10, pady=(8,1), sticky="w")
            ctk.CTkLabel(f, text=r["mots_cles"], font=ctk.CTkFont(size=10),
                         text_color=C["t2"], wraplength=180
            ).grid(row=1, column=0, padx=10, pady=(0,2), sticky="w")
            meta = [x for x in [r.get("pays"), f"≥{r['prix_min']}€" if r.get("prix_min") else None,
                                 f"≤{r['prix_max']}€" if r.get("prix_max") else None] if x]
            if meta:
                ctk.CTkLabel(f, text="  ".join(meta), font=ctk.CTkFont(size=10),
                             text_color=C["t3"]).grid(row=2, column=0, padx=10, pady=(0,4), sticky="w")
            bf = ctk.CTkFrame(f, fg_color="transparent")
            bf.grid(row=3, column=0, padx=10, pady=(0, 8), sticky="ew")
            bf.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(bf, text="▶ Charger", height=28, corner_radius=6,
                fg_color=C["accent"], hover_color=C["accent_hover"], text_color="#ffffff",
                font=ctk.CTkFont(size=11), command=lambda rec=r: self._charger_recherche(rec)
            ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
            ctk.CTkButton(bf, text="✕", width=28, height=28, corner_radius=6,
                fg_color=C["border"], hover_color=C["fav"], text_color=C["t2"],
                command=lambda n=r["nom"]: (data.supprimer_recherche(n), self._rafraichir_sauvegardes())
            ).grid(row=0, column=1)

    # ── Tab Ciblage ────────────────────────────────────────────────────────────

    def _construire_tab_ciblage(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # En-tête avec compteur
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        self.lbl_nb_cibles = ctk.CTkLabel(top, text="File de ciblage",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=C["t1"])
        self.lbl_nb_cibles.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(top, text="🗑 Nettoyer", width=80, height=26, corner_radius=6,
            fg_color=C["border"], hover_color=C["fav"], text_color=C["t2"],
            font=ctk.CTkFont(size=10), command=self._vider_cibles_traitees
        ).grid(row=0, column=1)

        self.scroll_cibles = ctk.CTkScrollableFrame(tab, fg_color="transparent",
            scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["accent"])
        self.scroll_cibles.grid(row=1, column=0, sticky="nsew")
        self.scroll_cibles.grid_columnconfigure(0, weight=1)
        self.rafraichir_cibles()

    def rafraichir_cibles(self):
        for w in self.scroll_cibles.winfo_children(): w.destroy()
        cibles = data.charger_cibles()
        en_attente = [c for c in cibles if c.get("statut") == "en_attente"]
        traites    = [c for c in cibles if c.get("statut") == "traite"]

        nb = len(en_attente)
        self.lbl_nb_cibles.configure(
            text=f"File de ciblage  •  {nb} en attente")

        if not cibles:
            ctk.CTkLabel(self.scroll_cibles,
                text="Aucune annonce ciblée.\n\nCliquez sur 🎯 sur une carte\npour analyser et cibler.",
                font=ctk.CTkFont(size=12), text_color=C["t3"], justify="center"
            ).pack(pady=40)
            return

        # ── En attente ──────────────────────────────────────────────────
        if en_attente:
            ctk.CTkLabel(self.scroll_cibles, text="EN ATTENTE",
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=C["cible"]).pack(padx=8, pady=(8, 4), anchor="w")
            for c in en_attente:
                self._carte_cible(c)

        # ── Traitées ────────────────────────────────────────────────────
        if traites:
            ctk.CTkLabel(self.scroll_cibles, text="TRAITÉS",
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=C["t3"]).pack(padx=8, pady=(12, 4), anchor="w")
            for c in traites:
                self._carte_cible(c, traite=True)

    def _carte_cible(self, c: dict, traite: bool = False):
        sym = {"EUR":"€","GBP":"£","USD":"$"}.get(c.get("currency","EUR"), "€")
        score = c.get("score")
        score_color = analyzer.couleur_score(score) if score is not None else C["t3"]

        f = ctk.CTkFrame(self.scroll_cibles, fg_color=C["card"], corner_radius=12,
                         border_width=1,
                         border_color=C["border"] if traite else C["cible"])
        f.pack(fill="x", padx=8, pady=4)
        f.grid_columnconfigure(0, weight=1)

        # Titre + prix
        header = ctk.CTkFrame(f, fg_color="transparent")
        header.grid(row=0, column=0, padx=10, pady=(10, 2), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=CarteAnnonce._trunc(c["title"], 28),
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["t3"] if traite else C["t1"],
                     wraplength=160, justify="left"
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text=f"{c['price']:.2f} {sym}",
                     font=ctk.CTkFont(size=13, weight="bold"), text_color=C["prix"]
        ).grid(row=0, column=1, padx=(4, 0))

        # Score + stratégie
        if score is not None:
            info_f = ctk.CTkFrame(f, fg_color="transparent")
            info_f.grid(row=1, column=0, padx=10, pady=2, sticky="ew")
            info_f.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(info_f, text=f"Score {score}/100",
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=score_color).grid(row=0, column=0, sticky="w")
            if c.get("strategie"):
                ctk.CTkLabel(info_f, text=analyzer.label_strategie(c["strategie"]),
                             font=ctk.CTkFont(size=10), text_color=C["t3"]
                ).grid(row=0, column=1, padx=(8, 0), sticky="w")

        # Offre suggérée
        if c.get("prix_suggere") is not None:
            ctk.CTkLabel(f, text=f"💡 Offre suggérée : {c['prix_suggere']:.2f} {sym}  (−{c.get('reduction_pct', 0):.0f}%)",
                         font=ctk.CTkFont(size=10), text_color=C["nouveau"]
            ).grid(row=2, column=0, padx=10, pady=2, sticky="w")

        # Message
        if c.get("message_suggere"):
            msg_f = ctk.CTkFrame(f, fg_color="#0c1820", corner_radius=8)
            msg_f.grid(row=3, column=0, padx=10, pady=4, sticky="ew")
            ctk.CTkLabel(msg_f, text=c["message_suggere"],
                         font=ctk.CTkFont(size=10, slant="italic"),
                         text_color=C["t2"], wraplength=230, justify="left"
            ).grid(row=0, column=0, padx=8, pady=6, sticky="w")

        # Boutons action
        if not traite:
            btn_f = ctk.CTkFrame(f, fg_color="transparent")
            btn_f.grid(row=4, column=0, padx=10, pady=(4, 10), sticky="ew")
            btn_f.grid_columnconfigure(0, weight=1)

            ctk.CTkButton(btn_f, text="📋 Copier", height=28, corner_radius=6,
                fg_color=C["border"], hover_color="#2d3a50", text_color=C["t1"],
                font=ctk.CTkFont(size=10),
                command=lambda msg=c.get("message_suggere", ""): (
                    self.clipboard_clear(), self.clipboard_append(msg))
            ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

            ctk.CTkButton(btn_f, text="Ouvrir →", height=28, corner_radius=6,
                fg_color=C["accent"], hover_color=C["accent_hover"], text_color="#ffffff",
                font=ctk.CTkFont(size=10),
                command=lambda u=c["url"]: (
                    webbrowser.open(u),
                    data.marquer_cible_traitee(c["id"]),
                    self.rafraichir_cibles())
            ).grid(row=0, column=1, padx=(0, 4), sticky="ew")

            ctk.CTkButton(btn_f, text="✕", width=28, height=28, corner_radius=6,
                fg_color=C["border"], hover_color=C["fav"], text_color=C["t2"],
                command=lambda i=c["id"]: (data.retirer_cible(i), self.rafraichir_cibles())
            ).grid(row=0, column=2)
        else:
            # Annonce traitée — bouton réouvrir discret
            ctk.CTkButton(f, text=f"✓ Traité  •  Ouvrir", height=26, corner_radius=6,
                fg_color="transparent", hover_color=C["border"], text_color=C["t3"],
                font=ctk.CTkFont(size=10),
                command=lambda u=c["url"]: webbrowser.open(u)
            ).grid(row=4, column=0, padx=10, pady=(0, 8), sticky="w")

    def _vider_cibles_traitees(self):
        data.vider_cibles_traitees()
        self.rafraichir_cibles()

    # ── Zone principale ────────────────────────────────────────────────────────

    # ── Tab Revente ────────────────────────────────────────────────────────────

    def _construire_tab_revente(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        row = 0

        ctk.CTkLabel(tab, text="💹  Achat-Revente",
                     font=ctk.CTkFont(family=FONT, size=13, weight="bold"),
                     text_color=C["accent"], anchor="w"
        ).grid(row=row, column=0, padx=16, pady=(14, 2), sticky="w"); row += 1

        ctk.CTkLabel(tab, text="Estimez votre revente avant d’acheter.",
                     font=ctk.CTkFont(size=10), text_color=C["t3"], anchor="w"
        ).grid(row=row, column=0, padx=16, pady=(0, 10), sticky="w"); row += 1

        ctk.CTkLabel(tab, text="PRODUIT",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=C["t3"], anchor="w"
        ).grid(row=row, column=0, padx=16, pady=(4, 2), sticky="w"); row += 1

        self._resell_produit = ctk.CTkEntry(
            tab, placeholder_text="ex : Nike Air Max 90, iPhone 13…",
            height=36, corner_radius=8, font=ctk.CTkFont(size=12),
            fg_color=C["input_bg"], border_color=C["border"],
            border_width=1, text_color=C["t1"])
        self._resell_produit.grid(
            row=row, column=0, padx=16, pady=(0, 8), sticky="ew"); row += 1
        self._resell_produit.bind("<Return>", lambda _: self._lancer_analyse_revente())

        ctk.CTkLabel(tab, text="PRIX D’ACHAT (€)",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=C["t3"], anchor="w"
        ).grid(row=row, column=0, padx=16, pady=(4, 2), sticky="w"); row += 1

        self._resell_prix = ctk.CTkEntry(
            tab, placeholder_text="ex : 25.00",
            height=36, corner_radius=8, font=ctk.CTkFont(size=12),
            fg_color=C["input_bg"], border_color=C["border"],
            border_width=1, text_color=C["t1"])
        self._resell_prix.grid(
            row=row, column=0, padx=16, pady=(0, 8), sticky="ew"); row += 1

        ctk.CTkLabel(tab, text="ÉTAT (optionnel)",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=C["t3"], anchor="w"
        ).grid(row=row, column=0, padx=16, pady=(4, 2), sticky="w"); row += 1

        self._resell_etat = ctk.CTkOptionMenu(
            tab, values=resell.CONDITIONS,
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"],
            font=ctk.CTkFont(size=11))
        self._resell_etat.set("Très bon état")
        self._resell_etat.grid(
            row=row, column=0, padx=16, pady=(0, 12), sticky="ew"); row += 1

        self._resell_btn = ctk.CTkButton(
            tab, text="🔍  Analyser le marché",
            height=38, corner_radius=10,
            fg_color=C["accent"], hover_color=C["accent_hover"],
            text_color="#000000",
            font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
            command=self._lancer_analyse_revente)
        self._resell_btn.grid(
            row=row, column=0, padx=16, pady=(0, 8), sticky="ew"); row += 1

        self._resell_status = ctk.CTkLabel(
            tab, text="", font=ctk.CTkFont(size=10),
            text_color=C["t3"], wraplength=280, justify="left")
        self._resell_status.grid(row=row, column=0, padx=16, sticky="ew")

    def _lancer_analyse_revente(self):
        produit = self._resell_produit.get().strip()
        if not produit:
            self._resell_status.configure(
                text="⚠️ Entrez un nom de produit.",
                text_color=C["alerte_on"])
            return
        prix_str = self._resell_prix.get().strip().replace(",", ".")
        try:
            prix_achat = float(prix_str) if prix_str else 0.0
        except ValueError:
            self._resell_status.configure(
                text="⚠️ Prix invalide.",
                text_color=C["alerte_on"])
            return
        etat = self._resell_etat.get()
        self._resell_btn.configure(
            state="disabled", text="⏳  Analyse en cours…")
        self._resell_status.configure(
            text=f"Recherche de « {produit} » sur Vinted…",
            text_color=C["t3"])

        def _run():
            try:
                analyse = resell.analyser_revente(
                    produit, prix_achat, etat, self.scraper)
                self.after(0, lambda a=analyse: self._afficher_resultat_revente(a))
            except Exception as ex:
                def _reset(e=ex):
                    self._resell_status.configure(
                        text=f"Erreur : {e}", text_color=C["fav"])
                    self._resell_btn.configure(
                        state="normal",
                        text="🔍  Analyser le marché")
                self.after(0, _reset)

        threading.Thread(target=_run, daemon=True).start()

    def _afficher_resultat_revente(self, analyse):
        self._resell_btn.configure(
            state="normal", text="🔍  Analyser le marché")
        self._resell_status.configure(text="")
        FenetreRevente(self, analyse)


    def _construire_zone_principale(self):
        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        topbar = ctk.CTkFrame(main, fg_color=C["sidebar"], corner_radius=0, height=56)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.grid_columnconfigure(0, weight=1)

        # Badge statut
        status_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        status_frame.grid(row=0, column=0, padx=16, sticky="w")
        ctk.CTkLabel(status_frame, text="●",
                     font=ctk.CTkFont(size=10), text_color=C["nouveau"]
        ).pack(side="left", padx=(0, 6))
        self.lbl_status = ctk.CTkLabel(status_frame,
            text="Prêt — entrez des mots-clés et lancez une recherche",
            font=ctk.CTkFont(family=FONT, size=12), text_color=C["t2"])
        self.lbl_status.pack(side="left")

        top_btns = ctk.CTkFrame(topbar, fg_color="transparent")
        top_btns.grid(row=0, column=1, padx=12, sticky="e")
        self.btn_mode = ctk.CTkButton(top_btns, text="☰  Liste", width=90, height=34,
            corner_radius=8, fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12), command=self._toggle_mode)
        self.btn_mode.pack(side="left", padx=4)
        self.btn_comparer = ctk.CTkButton(top_btns, text="⚖️  Comparer (0)",
            width=130, height=34, corner_radius=8,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t3"], font=ctk.CTkFont(family=FONT, size=12),
            state="disabled", command=self._ouvrir_comparateur)
        self.btn_comparer.pack(side="left", padx=4)
        self.btn_dashboard = ctk.CTkButton(top_btns, text="📊  Stats",
            width=88, height=34, corner_radius=8,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            state="disabled", command=self._ouvrir_dashboard)
        self.btn_dashboard.pack(side="left", padx=4)
        self.btn_export = ctk.CTkButton(top_btns, text="📤  CSV",
            width=80, height=34, corner_radius=8,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            state="disabled", command=self._exporter_csv)
        self.btn_export.pack(side="left", padx=4)
        self.lbl_count = ctk.CTkLabel(top_btns, text="",
            font=ctk.CTkFont(family=FONT, size=12, weight="bold"), text_color=C["accent"])
        self.lbl_count.pack(side="left", padx=8)

        self.zone_scroll = ctk.CTkScrollableFrame(main, fg_color=C["bg"],
            scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["accent"])
        self.zone_scroll.grid(row=1, column=0, sticky="nsew")
        for col in range(self.COLONNES):
            self.zone_scroll.grid_columnconfigure(col, weight=1, uniform="col")
        self._scroll_cmd = self.register(self._scroll_fluide)
        self.after(200, self._configurer_scroll)
        self.lbl_accueil = ctk.CTkLabel(self.zone_scroll,
            text="🔍\n\nEntrez des mots-clés\ndans la barre de gauche",
            font=ctk.CTkFont(size=18), text_color=C["t3"], justify="center")
        self.lbl_accueil.grid(row=0, column=0, columnspan=self.COLONNES, pady=120)
        self._construire_barre_pagination(main)

    def _construire_barre_pagination(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=C["sidebar"], corner_radius=0, height=56)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)
        self.btn_prev = ctk.CTkButton(bar, text="←", width=44, height=36,
            corner_radius=8, fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(size=16), command=self._page_precedente)
        self.btn_prev.grid(row=0, column=0, padx=(16, 8), pady=10)
        self.lbl_pagination = ctk.CTkLabel(bar, text="",
            font=ctk.CTkFont(family=FONT, size=12, weight="bold"), text_color=C["t2"])
        self.lbl_pagination.grid(row=0, column=1)
        self.btn_next = ctk.CTkButton(bar, text="→", width=44, height=36,
            corner_radius=8, fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(size=16), command=self._page_suivante)
        self.btn_next.grid(row=0, column=2, padx=(8, 16), pady=10)
        self.bar_pagination = bar
        self.bar_pagination.grid_remove()

    # ══ Autocomplete saisie intelligente ═════════════════════════════════════

    def _on_recherche_key(self, event=None):
        """Déclenche l'autocomplete avec un léger délai pour éviter le spam."""
        if self._suggest_job:
            self.after_cancel(self._suggest_job)
        self._suggest_job = self.after(180, self._mettre_a_jour_suggestions)

    def _mettre_a_jour_suggestions(self):
        texte = self.champ_recherche.get().strip()
        # Prend le dernier terme après virgule
        if "," in texte:
            prefixe = texte.split(",")[-1].strip()
        else:
            prefixe = texte
        suggestions = recommandations.obtenir_suggestions(prefixe, max_resultats=6)
        if not suggestions or not prefixe:
            self._cacher_suggestions()
            return
        # Ne pas afficher si la suggestion est exactement le texte déjà tapé
        suggestions = [s for s in suggestions if s.lower() != prefixe.lower()]
        if not suggestions:
            self._cacher_suggestions()
            return
        self._afficher_suggestions(suggestions, texte)

    def _afficher_suggestions(self, suggestions: list, texte_complet: str):
        """Affiche le panneau de suggestions sous le champ de recherche."""
        for w in self._frame_suggestions.winfo_children():
            w.destroy()
        for i, sug in enumerate(suggestions):
            btn = ctk.CTkButton(
                self._frame_suggestions,
                text=f"  🔍  {sug}",
                height=30,
                corner_radius=0,
                fg_color="transparent",
                hover_color=C["liste_hover"],
                text_color=C["t1"],
                anchor="w",
                font=ctk.CTkFont(size=12),
                command=lambda s=sug: self._appliquer_suggestion(s, texte_complet)
            )
            btn.pack(fill="x", padx=4, pady=1)
        # Placement dynamique sous le champ
        self._frame_suggestions.grid(
            row=4, column=0, padx=16, pady=(0, 4), sticky="ew"
        )
        self._suggest_visible = True

    def _appliquer_suggestion(self, suggestion: str, texte_complet: str):
        """Insère la suggestion dans le champ de recherche."""
        if "," in texte_complet:
            parties = texte_complet.split(",")
            parties[-1] = " " + suggestion
            nouveau = ",".join(parties)
        else:
            nouveau = suggestion
        self.champ_recherche.delete(0, "end")
        self.champ_recherche.insert(0, nouveau)
        self._cacher_suggestions()
        self.champ_recherche.focus()

    def _cacher_suggestions(self):
        """Cache le panneau de suggestions."""
        if self._suggest_visible:
            self._frame_suggestions.grid_remove()
            self._suggest_visible = False

    # ══ Recommandations ═══════════════════════════════════════════════════════

    def _afficher_recommandations_accueil(self):
        """Affiche des annonces recommandées au lancement si historique dispo."""
        if not recommandations.a_suffisamment_d_historique():
            return
        termes = recommandations.generer_requetes_recommandation(max_termes=3)
        if not termes:
            return
        self._set_status("✨ Chargement de vos recommandations…")
        self._vider_resultats()
        self.lbl_accueil.configure(
            text="✨  Recommandations personnalisées en cours…",
            font=ctk.CTkFont(size=14))
        self.lbl_accueil.grid(row=0, column=0, columnspan=self.COLONNES, pady=80)
        threading.Thread(
            target=self._thread_recommandations,
            args=(termes,),
            daemon=True
        ).start()

    def _thread_recommandations(self, termes: list):
        try:
            tous = []
            vus  = set()
            for terme in termes:
                try:
                    annonces = self.scraper.rechercher(terme, max_pages=1, par_page=20)
                    for a in annonces:
                        if a.id not in vus:
                            vus.add(a.id)
                            tous.append(a)
                except Exception:
                    pass
            self.after(0, self._afficher_recommandations_resultats, tous, termes)
        except Exception:
            pass

    def _afficher_recommandations_resultats(self, annonces: list, termes: list):
        if not annonces:
            return
        label = ", ".join(termes[:2])
        self._annonces     = sorted(annonces, key=lambda a: a.price)
        self._annonces_raw = list(annonces)
        self._page_courante = 1
        self._sel_vars      = []
        self._titre_recherche = f"Recommandations ({label})"
        self._rendre_cartes(annonces)
        self._set_status(f"✨ {len(annonces)} recommandation(s) basée(s) sur vos préférences")
        self.lbl_count.configure(text=f"{len(annonces)} reco.")
        self.btn_dashboard.configure(state="normal")
        self.btn_export.configure(state="normal")
        threading.Thread(target=data.enregistrer_historique,
                         args=(annonces,), daemon=True).start()

    # ══ Logique pays ══════════════════════════════════════════════════════════

    def _changer_pays(self, pays: str):
        self._set_status(f"🌍 Changement vers {pays}…")
        threading.Thread(target=lambda: (
            self.scraper.set_pays(pays),
            self.after(0, lambda: self._set_status(
                f"✅ Connecté à {scraper.PAYS_DISPONIBLES[pays]['url']}"))
        ), daemon=True).start()

    # ══ Logique recherche ═════════════════════════════════════════════════════

    def _lire_prix(self, champ):
        v = champ.get().strip().replace(",", ".")
        if not v: return None
        try:
            f = float(v); return f if f >= 0 else None
        except ValueError: return None

    def _get_filtres(self):
        cat_label = self.menu_categorie.get()
        col_label = self.menu_couleur.get()
        vendeur   = self.champ_vendeur.get().strip() or None
        cat_id = scraper.CATEGORIES.get(cat_label) if cat_label != "— Toutes —" else None
        col_id = scraper.COULEURS.get(col_label) if col_label != "— Toutes —" else None
        return cat_id, col_id, vendeur

    def _lancer_recherche(self, silent=False):
        mots = self.champ_recherche.get().strip()
        if not mots:
            if not silent:
                messagebox.showwarning("Champ vide", "Entrez des mots-clés avant de rechercher.")
            return
        self._titre_recherche = mots
        self._set_en_cours(True)
        self._vider_resultats()
        # Enregistre chaque terme pour le système de recommandation
        for terme in [t.strip() for t in mots.split(",") if t.strip()]:
            recommandations.enregistrer_terme(terme)
        self._cacher_suggestions()
        nb = len([t for t in mots.split(",") if t.strip()])
        self._set_status(f"Recherche de {nb} terme(s) — {self.scraper.pays_actuel}…")
        self._demarrer_animation()
        prix_min = self._lire_prix(self.champ_prix_min)
        prix_max = self._lire_prix(self.champ_prix_max)
        cat_id, col_id, vendeur = self._get_filtres()
        threading.Thread(target=self._thread_recherche,
                         args=(mots, prix_min, prix_max, cat_id, col_id, vendeur, silent),
                         daemon=True).start()

    def _thread_recherche(self, mots, prix_min, prix_max, cat_id, col_id, vendeur, silent=False):
        try:
            annonces = self.scraper.rechercher_multi(
                mots, prix_min, prix_max,
                category_id=cat_id, color_id=col_id, vendeur_id=vendeur)
            self.after(0, self._afficher_resultats, annonces, len(annonces), silent)
        except (ConnectionError, ValueError) as e:
            self.after(0, self._afficher_erreur, str(e))
        except Exception as e:
            self.after(0, self._afficher_erreur, f"Erreur inattendue : {e}")

    def _afficher_resultats(self, annonces, total_brut=0, silent=False):
        self._arreter_animation()
        self._set_en_cours(False)
        nouvelles_ids = set()
        if self._alerte_ids:
            nouvelles_ids = {str(a.id) for a in annonces} - self._alerte_ids
            if nouvelles_ids and silent:
                nb_new = len(nouvelles_ids)
                envoyer_toast("Nouvelles annonces !", f"{nb_new} nouvelle(s) annonce(s).")
                BannerNotif(self, "Nouvelles annonces !", f"{nb_new} nouvelle(s) trouvée(s).")
        self._alerte_ids  = {str(a.id) for a in annonces}
        self._verifier_baisse_favoris(annonces)
        self._annonces    = sorted(annonces, key=lambda a: a.price)
        self._annonces_raw = list(annonces)
        self._ordre_tri   = "prix_asc"
        self._page_courante = 1
        self._sel_vars    = []
        if not annonces:
            self._set_status("⚠️  Aucun résultat trouvé.")
            self.lbl_accueil.configure(
                text="😔\n\nAucun résultat.\n\nEssayez des termes différents.",
                font=ctk.CTkFont(size=14))
            self.lbl_accueil.grid(row=0, column=0, columnspan=self.COLONNES, pady=100)
            self.lbl_stats.configure(text="")
            self.btn_dashboard.configure(state="disabled")
            self.btn_export.configure(state="disabled")
            return
        self._rendre_cartes(annonces, nouvelles_ids)
        self._set_status(f"Recherche en ligne  ·  {len(annonces)} résultat(s)")
        self.lbl_count.configure(text=f"{len(annonces)} résultat(s)")
        self.lbl_stats.configure(text=f"{len(annonces)} annonces")
        self.btn_tri_asc.configure(fg_color=C["accent"], text_color="#000000")
        self.btn_tri_desc.configure(fg_color="transparent", text_color=C["t2"])
        self.btn_dashboard.configure(state="normal")
        self.btn_export.configure(state="normal")
        threading.Thread(target=data.enregistrer_historique,
                         args=(annonces,), daemon=True).start()

    def _rendre_cartes(self, annonces, nouvelles_ids=None):
        self._vider_resultats()
        if self._render_job:
            self.after_cancel(self._render_job)
            self._render_job = None
        nouvelles_ids = nouvelles_ids or set()
        toutes = self._annonces_filtrees(annonces)
        if not toutes:
            self.bar_pagination.grid_remove()
            return
        nb_total  = len(toutes)
        nb_pages  = max(1, (nb_total + self.ARTICLES_PAR_PAGE - 1) // self.ARTICLES_PAR_PAGE)
        self._page_courante = max(1, min(self._page_courante, nb_pages))
        debut     = (self._page_courante - 1) * self.ARTICLES_PAR_PAGE
        affichees = toutes[debut: debut + self.ARTICLES_PAR_PAGE]
        self._sel_vars = [tk.BooleanVar() for _ in affichees]
        BATCH = self.COLONNES * 2 if not self._mode_liste else 6

        def _render_batch(start: int):
            fin = min(start + BATCH, len(affichees))
            for idx in range(start, fin):
                a    = affichees[idx]
                sv   = self._sel_vars[idx]
                nouv = str(a.id) in nouvelles_ids
                if self._mode_liste:
                    widget = LigneAnnonce(self.zone_scroll, a, app=self,
                                         nouveau=nouv, selection_var=sv)
                    widget.grid(row=idx, column=0, columnspan=self.COLONNES,
                                padx=10, pady=4, sticky="ew")
                else:
                    ligne, col = divmod(idx, self.COLONNES)
                    widget = CarteAnnonce(self.zone_scroll, a, app=self,
                                         nouveau=nouv, selection_var=sv)
                    widget.grid(row=ligne, column=col, padx=10, pady=10, sticky="nsew")
                self._bind_scroll_recursif(widget)
            if fin < len(affichees):
                self._render_job = self.after(32, _render_batch, fin)
            else:
                self._maj_pagination(nb_total, nb_pages)

        _render_batch(0)

    def _annonces_filtrees(self, annonces):
        if not self._etats_actifs: return annonces
        return [a for a in annonces if a.condition_id in self._etats_actifs]

    # ── Pagination ─────────────────────────────────────────────────────────────

    def _maj_pagination(self, nb_total: int, nb_pages: int):
        if nb_pages <= 1:
            self.bar_pagination.grid_remove(); return
        self.bar_pagination.grid()
        debut = (self._page_courante - 1) * self.ARTICLES_PAR_PAGE + 1
        fin   = min(self._page_courante * self.ARTICLES_PAR_PAGE, nb_total)
        self.lbl_pagination.configure(
            text=f"Page {self._page_courante} sur {nb_pages}  ·  {debut}–{fin} sur {nb_total} résultats")
        for btn, cond in [(self.btn_prev, self._page_courante > 1),
                          (self.btn_next, self._page_courante < nb_pages)]:
            btn.configure(state="normal" if cond else "disabled",
                          fg_color=C["border"] if cond else C["bg"],
                          text_color=C["t2"] if cond else C["t3"])

    def _page_precedente(self):
        if self._page_courante > 1:
            self._page_courante -= 1
            self._rendre_cartes(self._annonces)
            try: self.zone_scroll._parent_canvas.yview_moveto(0)
            except Exception: pass

    def _page_suivante(self):
        toutes   = self._annonces_filtrees(self._annonces)
        nb_pages = max(1, (len(toutes) + self.ARTICLES_PAR_PAGE - 1) // self.ARTICLES_PAR_PAGE)
        if self._page_courante < nb_pages:
            self._page_courante += 1
            self._rendre_cartes(self._annonces)
            try: self.zone_scroll._parent_canvas.yview_moveto(0)
            except Exception: pass

    # ── Mode liste / grille ────────────────────────────────────────────────────

    def _toggle_mode(self):
        self._mode_liste = not self._mode_liste
        if self._mode_liste:
            self.btn_mode.configure(text="⊞ Grille", fg_color=C["accent"], text_color="#000")
            self.zone_scroll.grid_columnconfigure(0, weight=1)
            for col in range(1, self.COLONNES):
                self.zone_scroll.grid_columnconfigure(col, weight=0)
        else:
            self.btn_mode.configure(text="☰ Liste", fg_color=C["border"], text_color=C["t2"])
            for col in range(self.COLONNES):
                self.zone_scroll.grid_columnconfigure(col, weight=1, uniform="col")
        if self._annonces:
            self._page_courante = 1
            self._rendre_cartes(self._annonces)

    # ── Comparateur ────────────────────────────────────────────────────────────

    def _maj_bouton_comparateur(self):
        nb = sum(1 for v in self._sel_vars if v.get())
        if nb >= 2:
            self.btn_comparer.configure(text=f"⚖️ Comparer ({nb})", state="normal",
                                        fg_color=C["accent"], text_color="#000")
        else:
            self.btn_comparer.configure(text=f"⚖️ Comparer ({nb})", state="disabled",
                                        fg_color=C["border"], text_color=C["t3"])

    def _ouvrir_comparateur(self):
        toutes    = self._annonces_filtrees(self._annonces)
        debut     = (self._page_courante - 1) * self.ARTICLES_PAR_PAGE
        affichees = toutes[debut: debut + self.ARTICLES_PAR_PAGE]
        selection = [affichees[i] for i, v in enumerate(self._sel_vars)
                     if v.get() and i < len(affichees)]
        if len(selection) < 2:
            messagebox.showinfo("Comparateur", "Sélectionnez au moins 2 annonces.")
            return
        FenetreComparateur(self, selection[:3])

    # ── Dashboard ──────────────────────────────────────────────────────────────

    def _verifier_baisse_favoris(self, annonces: list):
        for a in annonces:
            fav = data.get_favori(a.id)
            if fav and a.price > 0 and a.price < fav["price"]:
                delta = fav["price"] - a.price
                sym   = {"EUR": "€", "GBP": "£", "USD": "$"}.get(a.currency, "€")
                titre = CarteAnnonce._trunc(fav["title"], 32)
                envoyer_toast(
                    "📉 Favori moins cher !",
                    f"{titre}\n{fav['price']:.2f}€ → {a.price:.2f}{sym}  (−{delta:.2f}{sym})"
                )
                BannerNotif(
                    self,
                    "📉 Favori moins cher !",
                    f"{titre}\n{fav['price']:.2f}€ → {a.price:.2f}{sym}  (−{delta:.2f}{sym})"
                )

    def _ouvrir_dashboard(self):
        FenetreDashboard(self, data.calculer_stats(self._annonces), self._titre_recherche)

    # ── Export CSV ─────────────────────────────────────────────────────────────

    def _exporter_csv(self):
        if not self._annonces: return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Tous", "*.*")],
            initialfile=f"vinted_{self._titre_recherche[:30].replace(' ','_')}.csv")
        if path:
            threading.Thread(target=scraper.VintedScraper.exporter_csv,
                             args=(self._annonces, path), daemon=True).start()
            self._set_status(f"✅  Export CSV : {os.path.basename(path)}")

    # ══ Tri & filtres ═════════════════════════════════════════════════════════

    def _toggle_etat(self, ids: set, label: str):
        b, _ = self._btns_etat[label]
        if ids.issubset(self._etats_actifs):
            self._etats_actifs -= ids
            b.configure(fg_color=C["border"], text_color=C["t1"])
        else:
            self._etats_actifs |= ids
            b.configure(fg_color=C["accent"], text_color="#ffffff")
        if self._annonces:
            self._page_courante = 1
            self._rendre_cartes(self._annonces)

    def _trier(self, ordre):
        if not self._annonces: return
        self._ordre_tri     = ordre
        self._page_courante = 1
        if ordre == "recent":
            self._annonces = list(getattr(self, "_annonces_raw", self._annonces))
        else:
            self._annonces = sorted(self._annonces, key=lambda a: a.price,
                                    reverse=(ordre == "prix_desc"))
        self._rendre_cartes(self._annonces)
        self.btn_tri_asc.configure(
            fg_color=C["accent"] if ordre == "prix_asc" else C["border"],
            text_color="#ffffff" if ordre == "prix_asc" else C["t2"])
        self.btn_tri_desc.configure(
            fg_color=C["accent"] if ordre == "prix_desc" else C["border"],
            text_color="#ffffff" if ordre == "prix_desc" else C["t2"])
        if hasattr(self, "btn_tri_recent"):
            self.btn_tri_recent.configure(
                fg_color=C["accent"] if ordre == "recent" else C["border"],
                text_color="#ffffff" if ordre == "recent" else C["t2"])

    # ══ Recherches sauvegardées ═══════════════════════════════════════════════

    def _sauvegarder_recherche(self):
        mots = self.champ_recherche.get().strip()
        if not mots:
            messagebox.showwarning("Champ vide", "Entrez des mots-clés avant de sauvegarder.")
            return
        nom = simpledialog.askstring("Sauvegarder", "Nom de la recherche :", parent=self)
        if not nom or not nom.strip(): return
        data.sauvegarder_recherche(nom.strip(), mots,
            self._lire_prix(self.champ_prix_min), self._lire_prix(self.champ_prix_max),
            pays=self.menu_pays.get())
        self._rafraichir_sauvegardes()
        self._set_status(f"✅  Recherche « {nom.strip()} » sauvegardée.")

    def _charger_recherche(self, rec: dict):
        self.champ_recherche.delete(0, "end")
        self.champ_recherche.insert(0, rec["mots_cles"])
        self.champ_prix_min.delete(0, "end")
        self.champ_prix_max.delete(0, "end")
        if rec.get("prix_min") is not None:
            self.champ_prix_min.insert(0, str(rec["prix_min"]))
        if rec.get("prix_max") is not None:
            self.champ_prix_max.insert(0, str(rec["prix_max"]))
        if rec.get("pays") and rec["pays"] in scraper.PAYS_DISPONIBLES:
            self.menu_pays.set(rec["pays"])
            self._changer_pays(rec["pays"])
        self._lancer_recherche()

    # ══ Alertes automatiques ══════════════════════════════════════════════════

    def _toggle_alerte(self):
        if self._alerte_active: self._arreter_alerte()
        else: self._demarrer_alerte()

    def _demarrer_alerte(self):
        mots = self.champ_recherche.get().strip()
        if not mots:
            messagebox.showwarning("Champ vide", "Entrez des mots-clés pour activer l'alerte.")
            return
        self._alerte_active = True
        self._alerte_ids    = set()
        self.btn_alerte.configure(fg_color=C["alerte_on"], text_color="#000",
                                  text="🔔 Alerte active — Arrêter")
        self.lbl_alerte_status.configure(text_color=C["alerte_on"])
        self._lancer_recherche(silent=True)
        self._planifier_prochain_tick()

    def _planifier_prochain_tick(self):
        val = self.menu_intervalle.get().replace(" min", "").strip()
        try: minutes = int(val)
        except ValueError: minutes = 10
        self.lbl_alerte_status.configure(text=f"● Prochaine vérif. dans {minutes} min")
        self._alerte_job = self.after(minutes * 60_000, self._tick_alerte)

    def _tick_alerte(self):
        if not self._alerte_active: return
        self._lancer_recherche(silent=True)
        self._planifier_prochain_tick()

    def _arreter_alerte(self):
        self._alerte_active = False
        if self._alerte_job:
            self.after_cancel(self._alerte_job)
            self._alerte_job = None
        self.btn_alerte.configure(fg_color=C["border"], text_color=C["t1"],
                                  text="Activer l'alerte")
        self.lbl_alerte_status.configure(text="● Inactive", text_color=C["t3"])

    # ══ Helpers ═══════════════════════════════════════════════════════════════

    def _vider_resultats(self):
        if self._render_job:
            self.after_cancel(self._render_job)
            self._render_job = None
        for w in self.zone_scroll.winfo_children():
            w.grid_forget(); w.destroy()
        self.lbl_accueil = ctk.CTkLabel(self.zone_scroll, text="",
            font=ctk.CTkFont(size=16), text_color=C["t3"])
        self.lbl_count.configure(text="")
        self._sel_vars = []
        self.btn_comparer.configure(text="⚖️ Comparer (0)", state="disabled",
                                    fg_color=C["border"], text_color=C["t3"])
        try: self.bar_pagination.grid_remove()
        except AttributeError: pass

    def _afficher_erreur(self, msg):
        self._arreter_animation()
        self._set_en_cours(False)
        self._set_status(f"❌  {msg}")
        messagebox.showerror("Erreur", msg)

    def _set_status(self, txt): self.lbl_status.configure(text=txt)

    def _set_en_cours(self, v):
        self.btn_rechercher.configure(state="disabled" if v else "normal",
                                      text="…" if v else "Rechercher")

    def _demarrer_animation(self):
        def _t():
            self.lbl_count.configure(text=next(self._anim_iter))
            self._anim_job = self.after(80, _t)
        _t()

    def _arreter_animation(self):
        if self._anim_job:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        self.lbl_count.configure(text="")

    def _bind_scroll_recursif(self, widget):
        try:
            tk_widget = widget._w if hasattr(widget, "_w") else widget
            self.tk.call("bind", tk_widget, "<MouseWheel>", self._scroll_cmd)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_scroll_recursif(child)

    def _configurer_scroll(self):
        try:
            canvas = self.zone_scroll._parent_canvas
            canvas.configure(yscrollincrement=1)
            self.tk.call("bind", canvas._w, "<MouseWheel>", self._scroll_cmd)
        except Exception:
            pass

    def _scroll_fluide(self, event=None):
        try:
            canvas = self.zone_scroll._parent_canvas
            delta  = getattr(event, "delta", 0)
            canvas.yview_scroll(int(-delta / 3), "units")
        except Exception:
            pass


# ─── Lancement ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    AppVinted().mainloop()
