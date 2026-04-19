"""
main.py — Interface graphique VintedScrap
v3.0 : compte Vinted, ciblage d'annonces, analyse de prix intelligente.
"""

import threading, webbrowser, itertools, os, sys, datetime
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from tkinter import messagebox, simpledialog, Menu, filedialog
from urllib.parse import quote_plus
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

from core import (
    scraper, data, analyzer, recommandations, comparateur_prix, auth,
    user_profile, resell, market_insights, discord_alerts,
)

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

_IMAGE_CACHE_LOCK = threading.RLock()
_IMAGE_BYTES_CACHE = OrderedDict()
_IMAGE_CACHE_MAX = 96


def _widget_exists(widget) -> bool:
    try:
        return widget is not None and bool(int(widget.winfo_exists()))
    except Exception:
        return False


def _safe_after(widget, callback, scheduler=None, delay: int = 0):
    if not _widget_exists(widget):
        return
    target = scheduler if _widget_exists(scheduler) else widget

    def _run():
        if not _widget_exists(widget):
            return
        try:
            callback()
        except tk.TclError:
            pass

    try:
        target.after(delay, _run)
    except Exception:
        pass


def _get_image_bytes(url: str, timeout: int = 8) -> bytes:
    with _IMAGE_CACHE_LOCK:
        cached = _IMAGE_BYTES_CACHE.get(url)
        if cached is not None:
            _IMAGE_BYTES_CACHE.move_to_end(url)
            return cached

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.content

    with _IMAGE_CACHE_LOCK:
        _IMAGE_BYTES_CACHE[url] = payload
        _IMAGE_BYTES_CACHE.move_to_end(url)
        while len(_IMAGE_BYTES_CACHE) > _IMAGE_CACHE_MAX:
            _IMAGE_BYTES_CACHE.popitem(last=False)
    return payload


def _load_cached_image(url: str, size: tuple[int, int], timeout: int = 8):
    payload = _get_image_bytes(url, timeout=timeout)
    pil = Image.open(BytesIO(payload)).convert("RGB")
    resized = pil.resize(size, Image.LANCZOS)
    ctk_img = ctk.CTkImage(light_image=resized, dark_image=resized, size=size)
    return pil, ctk_img


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


def jouer_son_alerte():
    if _WINSOUND:
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
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
        self.app = master if hasattr(master, "scraper") else master.winfo_toplevel()
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
        ).grid(row=0, column=2, padx=(4, 0))

    def _dl_description(self, annonce):
        try:
            if hasattr(self.app, 'scraper'):
                self.app.scraper.fetch_description(annonce)
            desc = annonce.description or "Aucune description fournie par le vendeur."
            if len(desc) > 500:
                desc = desc[:497] + "…"
        except Exception:
            desc = "Impossible de charger la description."
        _safe_after(self.lbl_desc,
                    lambda: self.lbl_desc.configure(text=desc),
                    scheduler=self.app)

    def _dl_image(self, url):
        try:
            _, ci = _load_cached_image(url, (self.IMG_W, self.IMG_H), timeout=10)
            self._photo = ci
            _safe_after(self.lbl_img,
                        lambda: self.lbl_img.configure(image=ci, text=""),
                        scheduler=self.app)
        except Exception:
            _safe_after(self.lbl_img,
                        lambda: self.lbl_img.configure(text="✕"),
                        scheduler=self.app)


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
            _, ci = _load_cached_image(url, (280, 220))
            self._keep = getattr(self, "_keep", [])
            self._keep.append(ci)
            _safe_after(lbl, lambda: lbl.configure(image=ci, text=""), scheduler=self)
        except Exception:
            _safe_after(lbl, lambda: lbl.configure(text="✕"), scheduler=self)


# ─── Dashboard Stats ──────────────────────────────────────────────────────────

class FenetreDashboard(ctk.CTkToplevel):
    W, H = 860, 700

    def __init__(self, master, stats: dict, titre_recherche: str = ""):
        super().__init__(master)
        self.title("📊 Dashboard")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.geometry(f"{self.W}x{self.H}")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=0, height=84)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        title = titre_recherche or "Résultats"
        ctk.CTkLabel(
            header,
            text="DASHBOARD MARCHE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=C["accent"],
        ).grid(row=0, column=0, padx=20, pady=(14, 2), sticky="w")
        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["t1"],
        ).grid(row=1, column=0, padx=20, pady=(0, 2), sticky="w")
        ctk.CTkLabel(
            header,
            text="Vue synthétique de la recherche : densité marché, pression prix et qualité du signal.",
            font=ctk.CTkFont(size=11),
            text_color=C["t2"],
        ).grid(row=2, column=0, padx=20, pady=(0, 14), sticky="w")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                         scrollbar_button_color=C["border"])
        scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=(14, 8))
        scroll.grid_columnconfigure((0, 1, 2, 3), weight=1)
        if not stats:
            ctk.CTkLabel(scroll, text="Aucune donnée disponible.",
                         text_color=C["t3"]).pack(pady=40)
            return

        hero = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=18,
                            border_width=1, border_color=C["border"])
        hero.grid(row=0, column=0, columnspan=4, padx=6, pady=6, sticky="ew")
        hero.grid_columnconfigure(0, weight=1)
        hero.grid_columnconfigure(1, weight=0)
        spread = max(0.0, float(stats.get("prix_max", 0) or 0) - float(stats.get("prix_min", 0) or 0))
        image_ratio = 0
        if stats.get("total", 0):
            image_ratio = (float(stats.get("avec_image", 0) or 0) / float(stats.get("total", 1))) * 100
        summary = (
            f"{stats.get('total', 0)} annonces • {stats.get('vendeurs_uniques', 0)} vendeurs • "
            f"{stats.get('marques_uniques', 0)} marques • {stats.get('haute_affinite', 0)} annonce(s) à forte affinité"
        )
        ctk.CTkLabel(
            hero,
            text="VUE D'ENSEMBLE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=C["accent"],
        ).grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        ctk.CTkLabel(
            hero,
            text=summary,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=C["t1"],
            wraplength=560,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            hero,
            text=f"Amplitude prix {spread:.2f} € • {image_ratio:.0f}% des annonces avec visuel • Affinité moyenne {stats.get('affinite_moyenne', 0):.0f}/100",
            font=ctk.CTkFont(size=11),
            text_color=C["t2"],
            wraplength=560,
            justify="left",
        ).grid(row=2, column=0, padx=16, pady=(0, 14), sticky="w")
        ctk.CTkLabel(
            hero,
            text=f"{stats.get('haute_affinite', 0)}\nhaute affinité",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["cible"],
            justify="center",
        ).grid(row=0, column=1, rowspan=3, padx=18, pady=16, sticky="e")

        def metrique(parent, row, col, label, valeur, couleur=C["t1"], subtitle=""):
            f = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                              border_width=1, border_color=C["border"])
            f.grid(row=row, column=col, padx=6, pady=6, sticky="ew")
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=10),
                         text_color=C["t3"]).pack(padx=14, pady=(10, 2), anchor="w")
            ctk.CTkLabel(f, text=valeur, font=ctk.CTkFont(size=18, weight="bold"),
                         text_color=couleur).pack(padx=14, pady=(0, 10), anchor="w")
            if subtitle:
                ctk.CTkLabel(
                    f,
                    text=subtitle,
                    font=ctk.CTkFont(size=10),
                    text_color=C["t2"],
                    wraplength=180,
                    justify="left",
                ).pack(padx=14, pady=(0, 10), anchor="w")

        metrique(scroll, 1, 0, "Annonces", str(stats.get("total", 0)), C["accent"], "Volume total exploitable")
        metrique(scroll, 1, 1, "Prix moyen", f"{stats.get('prix_moyen', 0):.2f} €", C["prix"], "Repère central du marché")
        metrique(scroll, 1, 2, "Prix min", f"{stats.get('prix_min', 0):.2f} €", C["nouveau"], "Point d'entrée le plus bas")
        metrique(scroll, 1, 3, "Prix médian", f"{stats.get('prix_median', 0):.2f} €", C["t1"], "Moins sensible aux extrêmes")
        metrique(scroll, 2, 0, "Vendeurs", str(stats.get("vendeurs_uniques", 0)), C["tag_fg"], "Diversité de l'offre")
        metrique(scroll, 2, 1, "Marques", str(stats.get("marques_uniques", 0)), C["accent"], "Largeur du catalogue")
        metrique(scroll, 2, 2, "Doublons", str(stats.get("groupes_doublons", 0)), C["alerte_on"], "Signal de reposts / variantes")
        metrique(scroll, 2, 3, "Affinité", f"{stats.get('affinite_moyenne', 0):.0f}/100", C["cible"], "Adéquation au profil utilisateur")
        self._section(scroll, 3, "🏷️  Top Marques",   stats.get("top_brands", []),   C["accent"])
        self._section(scroll, 4, "📦  États",          stats.get("etats", []),         C["prix"])
        self._section(scroll, 5, "👤  Top Vendeurs",   stats.get("top_vendeurs", []), C["tag_fg"])
        if stats.get("buckets"):
            self._section(scroll, 6, "💸  Tranches de prix", stats.get("buckets", []), C["alerte_on"])
            graph_row = 7
        else:
            graph_row = 6
        self._graphique_barres(scroll, graph_row, stats)
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            footer, text="Fermer", height=36, corner_radius=10,
            fg_color=C["border"], hover_color=C["card_hover"], text_color=C["t1"],
            command=self.destroy
        ).grid(row=0, column=0, sticky="e")

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

class FenetreProfilUtilisateur(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Profil utilisateur")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.geometry("760x760")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        snapshot = user_profile.get_profile_snapshot()
        events = user_profile.get_recent_events(12)

        header = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=0, height=84)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="PROFIL UTILISATEUR",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["accent"]).grid(row=0, column=0, padx=18, pady=(14, 2), sticky="w")
        ctk.CTkLabel(header, text="Ce que l'app a appris de vos comportements",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["t1"]).grid(row=1, column=0, padx=18, pady=(0, 2), sticky="w")
        ctk.CTkLabel(header, text=f"Dernière mise à jour : {snapshot.get('updated_at') or 'profil en apprentissage'}",
                     font=ctk.CTkFont(size=11), text_color=C["t2"]).grid(row=2, column=0, padx=18, pady=(0, 14), sticky="w")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                         scrollbar_button_color=C["border"])
        scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=(14, 8))
        scroll.grid_columnconfigure(0, weight=1)

        hero = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=16,
                            border_width=1, border_color=C["border"])
        hero.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        hero.grid_columnconfigure(0, weight=1)
        hero.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(hero, text="CE QUE L'APP A COMPRIS",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["accent"]).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        ctk.CTkLabel(hero, text=snapshot.get("summary", "Profil en cours d'apprentissage."),
                     font=ctk.CTkFont(size=13, weight="bold"),
                      text_color=C["t1"], wraplength=560, justify="left"
        ).grid(row=1, column=0, padx=14, pady=(0, 8), sticky="w")
        price_min = snapshot.get("price_min_pref")
        price_max = snapshot.get("price_max_pref")
        price_avg = snapshot.get("price_avg_pref")
        if any(v is not None for v in (price_min, price_max, price_avg)):
            price_text = " • ".join(filter(None, [
                f"Mini {price_min:.0f} €" if isinstance(price_min, (int, float)) else None,
                f"Moyenne {price_avg:.0f} €" if isinstance(price_avg, (int, float)) else None,
                f"Maxi {price_max:.0f} €" if isinstance(price_max, (int, float)) else None,
            ]))
        else:
            price_text = "Fourchette prix encore en apprentissage"
        ctk.CTkLabel(hero, text=price_text,
                     font=ctk.CTkFont(size=11), text_color=C["t2"]).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
        ctk.CTkLabel(hero, text=f"{snapshot.get('search_count', 0)}\nrecherches",
                     font=ctk.CTkFont(size=18, weight="bold"), text_color=C["accent"],
                     justify="center").grid(row=0, column=1, rowspan=3, padx=16, pady=14, sticky="e")

        metrics = ctk.CTkFrame(scroll, fg_color="transparent")
        metrics.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        for col in range(4):
            metrics.grid_columnconfigure(col, weight=1)

        for col, (label, value, color) in enumerate([
            ("Recherches", snapshot.get("search_count", 0), C["accent"]),
            ("Ouvertures", snapshot.get("open_count", 0), C["t1"]),
            ("Favoris", snapshot.get("favorite_count", 0), C["fav"]),
            ("Ciblages", snapshot.get("target_count", 0), C["cible"]),
        ]):
            box = ctk.CTkFrame(metrics, fg_color=C["card"], corner_radius=12,
                               border_width=1, border_color=C["border"])
            box.grid(row=0, column=col, padx=4, sticky="ew")
            ctk.CTkLabel(box, text=label, font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C["t3"]).pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkLabel(box, text=str(value), font=ctk.CTkFont(size=17, weight="bold"),
                         text_color=color).pack(anchor="w", padx=12, pady=(0, 10))

        def section(row, title, values):
            frame = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=14,
                                 border_width=1, border_color=C["border"])
            frame.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
            ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["t1"]).pack(anchor="w", padx=14, pady=(10, 6))
            if not values:
                ctk.CTkLabel(frame, text="Pas encore assez de signal.",
                             font=ctk.CTkFont(size=11), text_color=C["t3"]).pack(anchor="w", padx=14, pady=(0, 10))
                return
            wrap = ctk.CTkFrame(frame, fg_color="transparent")
            wrap.pack(fill="x", padx=12, pady=(0, 10))
            for value in values:
                ctk.CTkLabel(wrap, text=value, fg_color=C["tag_bg"], text_color=C["tag_fg"],
                             corner_radius=8, padx=9, pady=4,
                             font=ctk.CTkFont(size=10, weight="bold")).pack(side="left", padx=2)

        section(2, "Termes favoris", snapshot.get("preferred_terms", []))
        section(3, "Marques repérées", snapshot.get("preferred_brands", []))
        section(4, "États privilégiés", snapshot.get("preferred_conditions", []))
        section(5, "Vendeurs familiers", snapshot.get("preferred_sellers", []))

        searches = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=14,
                                border_width=1, border_color=C["border"])
        searches.grid(row=6, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(searches, text="Dernieres recherches",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["t1"]).pack(anchor="w", padx=14, pady=(10, 6))
        if snapshot.get("last_searches"):
            for value in snapshot["last_searches"]:
                ctk.CTkLabel(searches, text=f"• {value}",
                             font=ctk.CTkFont(size=11), text_color=C["t2"]).pack(anchor="w", padx=14, pady=1)
        else:
            ctk.CTkLabel(searches, text="Aucune recherche recente.",
                         font=ctk.CTkFont(size=11), text_color=C["t3"]).pack(anchor="w", padx=14, pady=(0, 10))

        events_frame = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=14,
                                    border_width=1, border_color=C["border"])
        events_frame.grid(row=7, column=0, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(events_frame, text="Historique visible",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["t1"]).pack(anchor="w", padx=14, pady=(10, 6))
        if not events:
            ctk.CTkLabel(events_frame, text="Aucun evenement pour le moment.",
                         font=ctk.CTkFont(size=11), text_color=C["t3"]).pack(anchor="w", padx=14, pady=(0, 10))
        else:
            for event in events:
                label = event.get("type", "").replace("_", " ").title()
                annonce = event.get("annonce", {})
                details = annonce.get("title") if isinstance(annonce, dict) else ", ".join(event.get("terms", []))
                row = ctk.CTkFrame(events_frame, fg_color="transparent")
                row.pack(fill="x", padx=14, pady=4)
                ctk.CTkLabel(row, text="•", font=ctk.CTkFont(size=14, weight="bold"),
                             text_color=C["accent"]).pack(side="left", padx=(0, 8))
                text = f"{label} • {event.get('timestamp', '')}"
                if details:
                    text += f"\n{details[:72]}"
                ctk.CTkLabel(row, text=text,
                             font=ctk.CTkFont(size=10), text_color=C["t2"],
                             wraplength=590, justify="left").pack(side="left", anchor="w")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Fermer", height=36, corner_radius=10,
                      fg_color=C["border"], hover_color=C["card_hover"],
                      text_color=C["t1"], command=self.destroy
        ).grid(row=0, column=0, sticky="e")


class FenetreParametres(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Paramètres")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.grid_columnconfigure(0, weight=1)

        self.app = master
        self.settings = dict(self.app.settings)
        self._construire()
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _construire(self):
        ctk.CTkLabel(self, text="Paramètres de l'application",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=C["t1"]).grid(row=0, column=0, padx=18, pady=(18, 10), sticky="w")

        panel = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=16,
                             border_width=1, border_color=C["border"])
        panel.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        panel.grid_columnconfigure(0, weight=1)

        appearance_map = {"Sombre": "dark", "Clair": "light", "Système": "system"}
        reverse_appearance = {v: k for k, v in appearance_map.items()}
        self.mode_liste_var = tk.BooleanVar(value=self.settings.get("mode_liste_par_defaut", False))
        self.sidebar_auto_var = tk.BooleanVar(value=self.settings.get("sidebar_auto_collapsing", True))
        self.sidebar_animation_var = tk.BooleanVar(value=self.settings.get("sidebar_animation", True))
        self.restore_last_search_var = tk.BooleanVar(value=self.settings.get("restaurer_derniere_recherche", True))
        self.appearance_mode_var = tk.StringVar(value=reverse_appearance.get(self.settings.get("appearance_mode", "dark"), "Sombre"))
        self.page_size_var = tk.StringVar(value=str(self.settings.get("articles_par_page", 10)))

        ctk.CTkLabel(panel, text="Mode liste par défaut",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t1"]).grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")
        ctk.CTkLabel(panel, text="Ouvre les résultats en mode liste à chaque lancement.",
                     font=ctk.CTkFont(size=11), text_color=C["t2"], wraplength=420,
                     justify="left").grid(row=1, column=0, padx=16, sticky="w")
        ctk.CTkCheckBox(panel, text="Activer", variable=self.mode_liste_var,
                        fg_color=C["accent"], button_color=C["accent"],
                        text_color=C["t1"]).grid(row=2, column=0, padx=16, pady=(4, 14), sticky="w")

        ctk.CTkLabel(panel, text="Barre latérale automatique",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t1"]).grid(row=3, column=0, padx=16, pady=(0, 4), sticky="w")
        ctk.CTkLabel(panel, text="Permet à la barre latérale de se réduire automatiquement\nselon la largeur de la fenêtre.", font=ctk.CTkFont(size=11),
                     text_color=C["t2"], wraplength=420, justify="left").grid(row=4, column=0, padx=16, sticky="w")
        ctk.CTkCheckBox(panel, text="Activer", variable=self.sidebar_auto_var,
                        fg_color=C["accent"], button_color=C["accent"],
                        text_color=C["t1"]).grid(row=5, column=0, padx=16, pady=(4, 14), sticky="w")

        ctk.CTkLabel(panel, text="Animation de la barre latérale",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t1"]).grid(row=6, column=0, padx=16, pady=(0, 4), sticky="w")
        ctk.CTkLabel(panel, text="Active une transition fluide lorsque la sidebar se réduit.",
                     font=ctk.CTkFont(size=11), text_color=C["t2"], wraplength=420,
                     justify="left").grid(row=7, column=0, padx=16, sticky="w")
        ctk.CTkCheckBox(panel, text="Activer", variable=self.sidebar_animation_var,
                        fg_color=C["accent"], button_color=C["accent"],
                        text_color=C["t1"]).grid(row=8, column=0, padx=16, pady=(4, 14), sticky="w")

        ctk.CTkLabel(panel, text="Apparence",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      text_color=C["t1"]).grid(row=9, column=0, padx=16, pady=(0, 4), sticky="w")
        ctk.CTkLabel(panel, text="Choisissez le thème de l’interface.",
                     font=ctk.CTkFont(size=11), text_color=C["t2"], wraplength=420,
                     justify="left").grid(row=10, column=0, padx=16, sticky="w")
        ctk.CTkOptionMenu(panel, values=["Sombre", "Clair", "Système"], variable=self.appearance_mode_var,
                          fg_color=C["input_bg"], button_color=C["border"],
                          button_hover_color=C["card_hover"],
                          text_color=C["t1"], width=140).grid(row=11, column=0,
                          padx=16, pady=(6, 16), sticky="w")

        ctk.CTkLabel(panel, text="Restaurer la dernière recherche",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t1"]).grid(row=12, column=0, padx=16, pady=(0, 4), sticky="w")
        ctk.CTkLabel(panel, text="Recharge automatiquement la dernière requête, les filtres et le tri au lancement.",
                     font=ctk.CTkFont(size=11), text_color=C["t2"], wraplength=420,
                     justify="left").grid(row=13, column=0, padx=16, sticky="w")
        ctk.CTkCheckBox(panel, text="Activer", variable=self.restore_last_search_var,
                        fg_color=C["accent"], button_color=C["accent"],
                        text_color=C["t1"]).grid(row=14, column=0, padx=16, pady=(4, 14), sticky="w")

        ctk.CTkLabel(panel, text="Articles par page",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["t1"]).grid(row=15, column=0, padx=16, pady=(0, 4), sticky="w")
        ctk.CTkLabel(panel, text="Choisissez le nombre d'annonces affichées par page.",
                     font=ctk.CTkFont(size=11), text_color=C["t2"], wraplength=420,
                     justify="left").grid(row=16, column=0, padx=16, sticky="w")
        ctk.CTkOptionMenu(panel, values=["10", "20", "30"], variable=self.page_size_var,
                          fg_color=C["input_bg"], button_color=C["border"],
                          button_hover_color=C["card_hover"],
                          text_color=C["t1"], width=140).grid(row=17, column=0,
                          padx=16, pady=(6, 16), sticky="w")

        ctk.CTkLabel(self, text="Les modifications sont enregistrées et appliquées immédiatement.",
                     font=ctk.CTkFont(size=10), text_color=C["t2"], wraplength=520,
                     justify="left").grid(row=2, column=0, padx=18, pady=(0, 0), sticky="w")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, pady=(12, 16), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Enregistrer",
                      width=140, height=38, corner_radius=12,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#000000", command=self._enregistrer).grid(row=0, column=0,
                      padx=16, sticky="e")
        ctk.CTkButton(footer, text="Fermer",
                      width=140, height=38, corner_radius=12,
                      fg_color=C["border"], hover_color=C["card_hover"],
                      text_color=C["t1"], command=self.destroy).grid(row=0, column=1,
                      padx=16, sticky="e")

    def _enregistrer(self):
        appearance_map = {"Sombre": "dark", "Clair": "light", "Système": "system"}
        try:
            self.settings["mode_liste_par_defaut"] = bool(self.mode_liste_var.get())
            self.settings["sidebar_auto_collapsing"] = bool(self.sidebar_auto_var.get())
            self.settings["sidebar_animation"] = bool(self.sidebar_animation_var.get())
            self.settings["restaurer_derniere_recherche"] = bool(self.restore_last_search_var.get())
            self.settings["appearance_mode"] = appearance_map.get(self.appearance_mode_var.get(), "dark")
            self.settings["articles_par_page"] = int(self.page_size_var.get())
        except ValueError:
            messagebox.showerror("Paramètres", "La valeur des articles par page est invalide.")
            return
        if not self.settings["restaurer_derniere_recherche"]:
            self.settings["last_search_state"] = {}
        data.sauvegarder_parametres(self.settings)
        self.app.settings = dict(self.settings)
        self.app._appliquer_parametres()
        self.destroy()


class FenetreVendeur(ctk.CTkToplevel):
    def __init__(self, master, annonce, annonces_marche: list):
        super().__init__(master)
        self.title(f"Analyse vendeur - {getattr(annonce, 'vendeur_nom', '')[:30]}")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.geometry("720x680")
        stats = market_insights.analyse_vendeur(annonces_marche, getattr(annonce, "vendeur_nom", ""))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=0, height=86)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="ANALYSE VENDEUR",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["accent"]).grid(row=0, column=0, padx=18, pady=(14, 2), sticky="w")
        ctk.CTkLabel(header, text=stats.get("vendeur") or "Vendeur inconnu",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["t1"]).grid(row=1, column=0, padx=18, pady=(0, 2), sticky="w")
        ctk.CTkLabel(header, text="Positionnement prix, cohérence du catalogue et signal dans la recherche courante.",
                     font=ctk.CTkFont(size=11), text_color=C["t2"]).grid(row=2, column=0, padx=18, pady=(0, 14), sticky="w")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                        scrollbar_button_color=C["border"])
        scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=(14, 8))
        scroll.grid_columnconfigure(0, weight=1)

        hero = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=16,
                            border_width=1, border_color=C["border"])
        hero.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        hero.grid_columnconfigure(0, weight=1)
        hero.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(hero, text="SIGNAL MARCHE",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["accent"]).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        ctk.CTkLabel(hero, text=f"{stats.get('total', 0)} annonce(s) visibles dans cette recherche",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=C["t1"]).grid(row=1, column=0, padx=14, pady=(0, 6), sticky="w")
        hero_text = (
            f"{stats.get('total', 0)} annonce(s) · prix moyen {stats.get('prix_moyen', 0):.2f} € · "
            f"affinité moyenne {stats.get('relevance_moyenne', 0):.0f}/100"
        )
        ctk.CTkLabel(hero, text=hero_text, font=ctk.CTkFont(size=11),
                     text_color=C["t2"]).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
        ctk.CTkLabel(hero, text=f"{stats.get('valeur_totale', 0):.0f} €\nvaleur visible",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=C["prix"], justify="center").grid(row=0, column=1, rowspan=3, padx=16, pady=14, sticky="e")

        metrics = ctk.CTkFrame(scroll, fg_color="transparent")
        metrics.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        for col in range(4):
            metrics.grid_columnconfigure(col, weight=1)
        for col, (label, value, color) in enumerate([
            ("Annonces", stats.get("total", 0), C["accent"]),
            ("Mini", f"{stats.get('prix_min', 0):.2f} €", C["nouveau"]),
            ("Maxi", f"{stats.get('prix_max', 0):.2f} €", C["fav"]),
            ("Doublons", stats.get("duplicate_like", 0), C["t1"]),
        ]):
            box = ctk.CTkFrame(metrics, fg_color=C["card"], corner_radius=12,
                               border_width=1, border_color=C["border"])
            box.grid(row=0, column=col, padx=4, sticky="ew")
            ctk.CTkLabel(box, text=label, font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C["t3"]).pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkLabel(box, text=str(value), font=ctk.CTkFont(size=16, weight="bold"),
                         text_color=color).pack(anchor="w", padx=12, pady=(0, 10))

        for row_idx, (title, values, color) in enumerate([
            ("Marques les plus vues", stats.get("top_brands", []), C["tag_fg"]),
            ("États proposés", stats.get("conditions", []), C["prix"]),
        ], start=2):
            frame = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=14,
                                 border_width=1, border_color=C["border"])
            frame.grid(row=row_idx, column=0, sticky="ew", padx=4, pady=4)
            ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["t1"]).pack(anchor="w", padx=14, pady=(10, 6))
            if not values:
                ctk.CTkLabel(frame, text="Aucune tendance forte visible.",
                             font=ctk.CTkFont(size=11), text_color=C["t3"]).pack(anchor="w", padx=14, pady=(0, 10))
                continue
            for label, count in values:
                line = ctk.CTkFrame(frame, fg_color="transparent")
                line.pack(fill="x", padx=14, pady=2)
                ctk.CTkLabel(line, text=label, font=ctk.CTkFont(size=11),
                             text_color=C["t2"]).pack(side="left")
                ctk.CTkLabel(line, text=f"x{count}", font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=color).pack(side="right")

        refs = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=14,
                            border_width=1, border_color=C["border"])
        refs.grid(row=4, column=0, sticky="ew", padx=4, pady=4)
        ctk.CTkLabel(refs, text="Annonces du vendeur dans la recherche",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["t1"]).pack(anchor="w", padx=14, pady=(10, 6))
        annonces_vendeur = stats.get("annonces", [])[:6]
        if not annonces_vendeur:
            ctk.CTkLabel(refs, text="Aucune autre annonce visible pour ce vendeur.",
                         font=ctk.CTkFont(size=11), text_color=C["t3"]).pack(anchor="w", padx=14, pady=(0, 10))
        else:
            for annonce_item in annonces_vendeur:
                row = ctk.CTkFrame(refs, fg_color=C["bg"], corner_radius=10,
                                   border_width=1, border_color=C["border"])
                row.pack(fill="x", padx=14, pady=4)
                row.grid_columnconfigure(0, weight=1)
                titre = getattr(annonce_item, "title", "")
                ctk.CTkLabel(row, text=titre[:64] + ("…" if len(titre) > 64 else ""),
                             font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=C["t1"]).grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")
                sub = " • ".join(filter(None, [
                    getattr(annonce_item, "brand", ""),
                    getattr(annonce_item, "condition", ""),
                    getattr(annonce_item, "size", ""),
                ]))
                if sub:
                    ctk.CTkLabel(row, text=sub, font=ctk.CTkFont(size=10),
                                 text_color=C["t3"]).grid(row=1, column=0, padx=10, pady=(0, 8), sticky="w")
                ctk.CTkLabel(row, text=getattr(annonce_item, "prix_affiche", lambda: "")(),
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=C["prix"]).grid(row=0, column=1, rowspan=2, padx=10, pady=8, sticky="e")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=14, pady=(0, 14), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Fermer", height=36, corner_radius=10,
                      fg_color=C["border"], hover_color=C["card_hover"],
                      text_color=C["t1"], command=self.destroy
        ).grid(row=0, column=0, sticky="e")


class FenetreAccueilIntelligent(ctk.CTkToplevel):
    def __init__(self, master, titre_recherche: str = ""):
        super().__init__(master)
        self.title("Accueil intelligent")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.geometry("760x720")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        snapshot = user_profile.get_profile_snapshot()
        portfolio = market_insights.get_portfolio_snapshot()

        ctk.CTkLabel(self, text="Accueil intelligent",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=C["t1"]).grid(row=0, column=0, padx=18, pady=(18, 8), sticky="w")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                        scrollbar_button_color=C["border"])
        scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 8))
        scroll.grid_columnconfigure((0, 1), weight=1)

        hero = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=18,
                            border_width=1, border_color=C["border"])
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
        hero.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hero, text="TABLEAU DE BORD PERSONNEL",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["accent"]).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        ctk.CTkLabel(hero, text=snapshot.get("summary", "Profil en cours d'apprentissage."),
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C["t1"], wraplength=680, justify="left"
        ).grid(row=1, column=0, padx=14, pady=(0, 6), sticky="w")
        ctk.CTkLabel(hero, text=f"Recherche active : {titre_recherche or 'aucune'}",
                     font=ctk.CTkFont(size=11), text_color=C["t2"]).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")

        cards = [
            ("Favoris", portfolio.get("favoris_count", 0), f"{portfolio.get('favoris_value', 0):.2f} € en suivi", C["fav"]),
            ("Ciblage", portfolio.get("cibles_count", 0), f"{portfolio.get('cibles_value', 0):.2f} € en attente", C["cible"]),
            ("Revente", portfolio.get("analyses_count", 0), f"{portfolio.get('marge_potentielle', 0):.2f} € de marge potentielle", C["prix"]),
            ("Affinite", len(snapshot.get("preferred_terms", [])), "termes forts detectes", C["accent"]),
        ]
        for idx, (title, value, subtitle, color) in enumerate(cards):
            box = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=14,
                               border_width=1, border_color=C["border"])
            box.grid(row=1 + idx // 2, column=idx % 2, sticky="ew", padx=6, pady=6)
            ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=C["t3"]).pack(anchor="w", padx=14, pady=(10, 2))
            ctk.CTkLabel(box, text=str(value), font=ctk.CTkFont(size=24, weight="bold"),
                         text_color=color).pack(anchor="w", padx=14)
            ctk.CTkLabel(box, text=subtitle, font=ctk.CTkFont(size=10),
                         text_color=C["t2"], wraplength=280, justify="left").pack(anchor="w", padx=14, pady=(2, 10))

        for row_idx, (title, values) in enumerate([
            ("Termes a surveiller", snapshot.get("preferred_terms", [])),
            ("Recherches recentes", snapshot.get("last_searches", [])),
        ], start=3):
            frame = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=14,
                                 border_width=1, border_color=C["border"])
            frame.grid(row=row_idx, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
            ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["t1"]).pack(anchor="w", padx=14, pady=(10, 6))
            if not values:
                ctk.CTkLabel(frame, text="Pas encore assez de donnees.",
                             font=ctk.CTkFont(size=11), text_color=C["t3"]).pack(anchor="w", padx=14, pady=(0, 10))
                continue
            wrap = ctk.CTkFrame(frame, fg_color="transparent")
            wrap.pack(fill="x", padx=12, pady=(0, 10))
            for value in values:
                ctk.CTkLabel(wrap, text=str(value), fg_color=C["tag_bg"], text_color=C["tag_fg"],
                             corner_radius=8, padx=9, pady=4,
                             font=ctk.CTkFont(size=10, weight="bold")).pack(side="left", padx=2)

        recent = ctk.CTkFrame(scroll, fg_color=C["card"], corner_radius=14,
                              border_width=1, border_color=C["border"])
        recent.grid(row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(recent, text="Dernieres analyses achat / revente",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["t1"]).pack(anchor="w", padx=14, pady=(10, 6))
        analyses = portfolio.get("recent_analyses", [])
        if not analyses:
            ctk.CTkLabel(recent, text="Aucune analyse de revente enregistree pour l'instant.",
                         font=ctk.CTkFont(size=11), text_color=C["t3"]).pack(anchor="w", padx=14, pady=(0, 10))
        else:
            for item in analyses[:5]:
                line = ctk.CTkFrame(recent, fg_color="transparent")
                line.pack(fill="x", padx=14, pady=2)
                produit = item.get("produit", "")
                ctk.CTkLabel(line, text=produit[:42] + ("…" if len(produit) > 42 else ""),
                             font=ctk.CTkFont(size=10), text_color=C["t2"]).pack(side="left")
                ctk.CTkLabel(line, text=f"{item.get('marge_estimee', 0):+.2f} €",
                             font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=C["prix"] if item.get("marge_estimee", 0) >= 0 else C["fav"]).pack(side="right")

        ctk.CTkButton(self, text="Fermer", height=36, corner_radius=8,
                      fg_color=C["border"], hover_color=C["card_hover"],
                      text_color=C["t1"], command=self.destroy
        ).grid(row=2, column=0, pady=(0, 14))


class FenetreAlerteDiscord(ctk.CTkToplevel):
    def __init__(self, master, search_snapshot: dict, on_change=None):
        super().__init__(master)
        self.app = master if hasattr(master, "_planifier_surveillance_discord") else master.winfo_toplevel()
        self.snapshot = dict(search_snapshot or {})
        self._on_change = on_change
        self.title("Alerte Discord")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._existing = discord_alerts.find_alert(
            self.snapshot.get("query", ""),
            self.snapshot.get("pays", self.app.scraper.pays_actuel),
            self.snapshot.get("filters", {}),
        )
        self._construire()
        self.after(20, self._adapter_fenetre)

    def _construire(self):
        self.body = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"],
        )
        self.body.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

        panel = ctk.CTkFrame(self.body, fg_color=C["card"], corner_radius=18,
                             border_width=1, border_color=C["border"])
        panel.grid(row=0, column=0, padx=18, pady=18, sticky="ew")
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text="🔔 ALERTE DISCORD",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["accent"]).grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        ctk.CTkLabel(panel, text=self.snapshot.get("query", "Recherche vide"),
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["t1"], wraplength=460, justify="left"
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        ctk.CTkLabel(
            panel,
            text="Les nouvelles annonces les plus récentes seront vérifiées environ toutes les 30 secondes, sans utiliser le cache de recherche.",
            font=ctk.CTkFont(size=11),
            text_color=C["t2"],
            wraplength=460,
            justify="left",
        ).grid(row=2, column=0, padx=16, pady=(0, 12), sticky="w")

        ctk.CTkLabel(panel, text="Webhook Discord",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["t1"]).grid(row=3, column=0, padx=16, pady=(0, 4), sticky="w")
        self.entry_webhook = ctk.CTkEntry(
            panel,
            placeholder_text="https://discord.com/api/webhooks/...",
            height=38,
            fg_color=C["input_bg"],
            border_color=C["border"],
            text_color=C["t1"],
        )
        self.entry_webhook.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="ew")

        ctk.CTkLabel(panel, text="Prix maximum",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["t1"]).grid(row=5, column=0, padx=16, pady=(0, 4), sticky="w")
        self.entry_prix_max = ctk.CTkEntry(
            panel,
            placeholder_text="150",
            height=38,
            fg_color=C["input_bg"],
            border_color=C["border"],
            text_color=C["t1"],
        )
        self.entry_prix_max.grid(row=6, column=0, padx=16, pady=(0, 8), sticky="ew")

        active_default = bool(self._existing.get("active", True)) if self._existing else True
        self.var_active = tk.BooleanVar(value=active_default)
        self.switch_active = ctk.CTkSwitch(
            panel,
            text="Surveillance active",
            variable=self.var_active,
            onvalue=True,
            offvalue=False,
            progress_color=C["alerte_on"],
            button_color=C["t1"],
            button_hover_color=C["t2"],
            text_color=C["t1"],
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.switch_active.grid(row=7, column=0, padx=16, pady=(0, 8), sticky="w")

        if self._existing:
            if self._existing.get("active", True):
                status_text = "Une alerte active existe déjà pour cette recherche."
                status_color = C["alerte_on"]
            else:
                status_text = "Une alerte existe déjà pour cette recherche, mais elle est actuellement désactivée."
                status_color = C["t2"]
        else:
            status_text = "Le son de notification sera joué à chaque nouvelle annonce détectée."
            status_color = C["t2"]

        self.lbl_status = ctk.CTkLabel(
            panel,
            text=status_text,
            font=ctk.CTkFont(size=10),
            text_color=status_color,
            wraplength=460,
            justify="left",
        )
        self.lbl_status.grid(row=8, column=0, padx=16, pady=(0, 12), sticky="w")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        footer.grid_columnconfigure(2, weight=1)

        if self._existing:
            self.entry_webhook.insert(0, self._existing.get("webhook_url", ""))
            existing_max = self._existing.get("price_max")
            if existing_max is not None:
                self.entry_prix_max.insert(0, str(existing_max))

        ctk.CTkButton(footer, text="Enregistrer", height=38, corner_radius=10,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._enregistrer
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        close_col = 2
        if self._existing:
            ctk.CTkButton(footer, text="Supprimer", height=38, corner_radius=10,
                          fg_color="transparent", hover_color=C["fav"],
                          border_width=1, border_color=C["fav"],
                          text_color=C["fav"], command=self._supprimer
            ).grid(row=0, column=1, padx=6)
        else:
            close_col = 1
        ctk.CTkButton(footer, text="Fermer", height=38, corner_radius=10,
                      fg_color=C["border"], hover_color=C["card_hover"],
                      text_color=C["t1"], command=self.destroy
        ).grid(row=0, column=close_col, padx=(6, 0), sticky="ew")

    def _adapter_fenetre(self):
        try:
            self.update_idletasks()
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            req_w = max(540, min(self.winfo_reqwidth() + 12, int(screen_w * 0.7)))
            req_h = max(430, min(self.winfo_reqheight() + 12, int(screen_h * 0.8)))
            self.minsize(520, 410)
            x = max(0, (screen_w - req_w) // 2)
            y = max(0, (screen_h - req_h) // 2 - 20)
            self.geometry(f"{req_w}x{req_h}+{x}+{y}")
        except Exception:
            pass

    def _parse_prix_max(self):
        raw = self.entry_prix_max.get().strip().replace(",", ".")
        if not raw:
            return None
        try:
            value = float(raw)
            return value if value >= 0 else None
        except ValueError:
            return None

    def _enregistrer(self):
        query = (self.snapshot.get("query") or "").strip()
        webhook = self.entry_webhook.get().strip()
        prix_max = self._parse_prix_max()
        if not query:
            messagebox.showwarning("Alerte Discord", "Lancez d'abord une recherche valide.")
            return
        if not discord_alerts.is_valid_webhook(webhook):
            messagebox.showwarning("Webhook invalide", "Entrez une URL de webhook Discord valide.")
            return
        if self.entry_prix_max.get().strip() and prix_max is None:
            messagebox.showwarning("Prix invalide", "Le prix maximum doit être un nombre positif.")
            return

        alert = discord_alerts.upsert_alert(
            query=query,
            webhook_url=webhook,
            price_max=prix_max,
            pays=self.snapshot.get("pays", self.app.scraper.pays_actuel),
            filters=self.snapshot.get("filters", {}),
            baseline_ids=self.snapshot.get("baseline_ids", []),
            active=bool(self.var_active.get()),
        )
        self.app._refresh_discord_alert_ui()
        self.app._planifier_surveillance_discord(1500)
        if callable(self._on_change):
            self._on_change()
        is_active = bool(alert.get("active", True))
        envoyer_toast(
            "Alerte Discord active" if is_active else "Alerte Discord enregistrée",
            f"Surveillance {'activée' if is_active else 'désactivée'} pour : {alert['query']}",
        )
        self.destroy()

    def _supprimer(self):
        if not self._existing:
            self.destroy()
            return
        discord_alerts.delete_alert(self._existing.get("id", ""))
        self.app._refresh_discord_alert_ui()
        self.app._planifier_surveillance_discord(1000)
        if callable(self._on_change):
            self._on_change()
        envoyer_toast("Alerte supprimée", "L'alerte Discord a été retirée.")
        self.destroy()


class FenetreGestionAlertesDiscord(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.app = master if hasattr(master, "_planifier_surveillance_discord") else master.winfo_toplevel()
        self.title("Gestion des alertes Discord")
        self.configure(fg_color=C["bg"])
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._switches = {}
        self._construire()
        self.after(20, self._adapter_fenetre)
        self._charger_alertes()

    def _ui_alive(self) -> bool:
        return (
            _widget_exists(self)
            and _widget_exists(getattr(self, "body", None))
            and _widget_exists(getattr(self, "lbl_resume_alertes", None))
        )

    def _refresh_if_alive(self):
        if self._ui_alive():
            self._charger_alertes()

    def _construire(self):
        header = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=18,
                              border_width=1, border_color=C["border"])
        header.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(
            header,
            text="Centre des alertes Discord",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=C["t1"],
        ).grid(row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        self.lbl_resume_alertes = ctk.CTkLabel(
            header,
            text="Chargement des alertes…",
            font=ctk.CTkFont(size=11),
            text_color=C["t2"],
        )
        self.lbl_resume_alertes.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")
        ctk.CTkButton(
            header,
            text="Actualiser",
            width=110,
            height=36,
            corner_radius=10,
            fg_color="transparent",
            hover_color=C["card_hover"],
            border_width=1,
            border_color=C["border"],
            text_color=C["t1"],
            command=self._charger_alertes,
        ).grid(row=0, column=1, rowspan=2, padx=16, pady=14, sticky="e")

        self.body = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"],
        )
        self.body.grid(row=1, column=0, padx=0, pady=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=18, pady=(10, 18), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            footer,
            text="Fermer",
            height=38,
            corner_radius=10,
            fg_color=C["border"],
            hover_color=C["card_hover"],
            text_color=C["t1"],
            command=self.destroy,
        ).grid(row=0, column=0, sticky="e")

    def _adapter_fenetre(self):
        try:
            self.update_idletasks()
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            req_w = max(720, min(self.winfo_reqwidth() + 18, int(screen_w * 0.78)))
            req_h = max(520, min(self.winfo_reqheight() + 18, int(screen_h * 0.84)))
            self.minsize(680, 500)
            x = max(0, (screen_w - req_w) // 2)
            y = max(0, (screen_h - req_h) // 2 - 20)
            self.geometry(f"{req_w}x{req_h}+{x}+{y}")
        except Exception:
            pass

    def _mask_webhook(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) <= 18:
            return value or "Webhook non renseigné"
        return f"{value[:18]}…{value[-8:]}"

    def _resume_filtres(self, filters: dict) -> str:
        if not isinstance(filters, dict):
            return "Aucun filtre supplémentaire"
        chunks = []
        price_min = filters.get("price_min")
        price_max = filters.get("search_price_max")
        if price_min is not None or price_max is not None:
            if price_min is not None and price_max is not None:
                chunks.append(f"Budget {price_min:.0f}-{price_max:.0f} €")
            elif price_min is not None:
                chunks.append(f"Min {price_min:.0f} €")
            elif price_max is not None:
                chunks.append(f"Max {price_max:.0f} €")
        if filters.get("category_id"):
            chunks.append("Catégorie ciblée")
        if filters.get("color_id"):
            chunks.append("Couleur ciblée")
        if filters.get("vendeur_id"):
            chunks.append("Vendeur précis")
        return " • ".join(chunks) if chunks else "Aucun filtre supplémentaire"

    def _snapshot_from_alert(self, alert: dict) -> dict:
        return {
            "query": alert.get("query", ""),
            "pays": alert.get("pays", self.app.scraper.pays_actuel),
            "filters": dict(alert.get("filters") or {}),
            "baseline_ids": list(alert.get("last_seen_ids", [])),
        }

    def _charger_alertes(self):
        if not self._ui_alive():
            return
        for widget in list(self.body.winfo_children()):
            widget.destroy()
        self._switches = {}

        alerts = sorted(
            discord_alerts.list_alerts(active_only=False),
            key=lambda a: (a.get("updated_at") or "", a.get("created_at") or ""),
            reverse=True,
        )
        active_count = sum(1 for alert in alerts if alert.get("active", True))
        if alerts:
            self.lbl_resume_alertes.configure(
                text=f"{len(alerts)} alerte(s) enregistrée(s) • {active_count} active(s) • {len(alerts) - active_count} désactivée(s)"
            )
        else:
            self.lbl_resume_alertes.configure(text="Aucune alerte enregistrée pour le moment.")

        if not alerts:
            empty = ctk.CTkFrame(self.body, fg_color=C["card"], corner_radius=18,
                                 border_width=1, border_color=C["border"])
            empty.grid(row=0, column=0, padx=18, pady=18, sticky="ew")
            ctk.CTkLabel(
                empty,
                text="Aucune alerte Discord enregistrée",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=C["t1"],
            ).pack(anchor="w", padx=18, pady=(18, 4))
            ctk.CTkLabel(
                empty,
                text="Crée une alerte depuis la cloche à côté du champ de recherche, puis reviens ici pour l’éditer, la désactiver ou la supprimer.",
                font=ctk.CTkFont(size=11),
                text_color=C["t2"],
                wraplength=560,
                justify="left",
            ).pack(anchor="w", padx=18, pady=(0, 18))
            return

        for idx, alert in enumerate(alerts):
            active = bool(alert.get("active", True))
            card = ctk.CTkFrame(
                self.body,
                fg_color=C["card"],
                corner_radius=18,
                border_width=1,
                border_color=C["alerte_on"] if active else C["border"],
            )
            card.grid(row=idx, column=0, padx=18, pady=(18 if idx == 0 else 0, 12), sticky="ew")
            card.grid_columnconfigure(0, weight=1)
            card.grid_columnconfigure(1, weight=0)

            ctk.CTkLabel(
                card,
                text=alert.get("query", "Recherche sans titre"),
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color=C["t1"],
                wraplength=480,
                justify="left",
            ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="w")
            badge_text = "Active" if active else "Désactivée"
            badge_fg = C["alerte_on"] if active else C["border"]
            badge_text_color = "#000000" if active else C["t2"]
            ctk.CTkLabel(
                card,
                text=badge_text,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=badge_fg,
                corner_radius=999,
                text_color=badge_text_color,
                padx=10,
                pady=5,
            ).grid(row=0, column=1, padx=16, pady=(14, 6), sticky="e")

            price_max = alert.get("price_max")
            price_text = f"Prix max {price_max:.2f} €" if price_max is not None else "Pas de prix maximum"
            ctk.CTkLabel(
                card,
                text=f"{alert.get('pays', self.app.scraper.pays_actuel)} • {price_text}",
                font=ctk.CTkFont(size=11),
                text_color=C["t2"],
            ).grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 4), sticky="w")
            ctk.CTkLabel(
                card,
                text=self._resume_filtres(alert.get("filters", {})),
                font=ctk.CTkFont(size=11),
                text_color=C["t2"],
                wraplength=600,
                justify="left",
            ).grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 4), sticky="w")
            ctk.CTkLabel(
                card,
                text=f"Webhook • {self._mask_webhook(alert.get('webhook_url', ''))}",
                font=ctk.CTkFont(size=10),
                text_color=C["t3"],
                wraplength=600,
                justify="left",
            ).grid(row=3, column=0, columnspan=2, padx=16, pady=(0, 4), sticky="w")
            last_check = alert.get("last_check_at") or "Pas encore vérifiée"
            ctk.CTkLabel(
                card,
                text=f"Dernière vérification : {last_check}",
                font=ctk.CTkFont(size=10),
                text_color=C["t3"],
            ).grid(row=4, column=0, columnspan=2, padx=16, pady=(0, 10), sticky="w")

            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.grid(row=5, column=0, columnspan=2, padx=16, pady=(0, 14), sticky="ew")
            actions.grid_columnconfigure(0, weight=1)

            var_active = tk.BooleanVar(value=active)
            self._switches[alert.get("id", f"alert-{idx}")] = var_active
            ctk.CTkSwitch(
                actions,
                text="Activer la surveillance",
                variable=var_active,
                onvalue=True,
                offvalue=False,
                progress_color=C["alerte_on"],
                button_color=C["t1"],
                button_hover_color=C["t2"],
                text_color=C["t1"],
                command=lambda aid=alert.get("id", ""), var=var_active: self._toggle_alert(aid, bool(var.get())),
            ).grid(row=0, column=0, padx=(0, 10), sticky="w")

            ctk.CTkButton(
                actions,
                text="Éditer",
                width=96,
                height=36,
                corner_radius=10,
                fg_color=C["accent"],
                hover_color=C["accent_hover"],
                text_color="#000000",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda a=dict(alert): self._editer_alert(a),
            ).grid(row=0, column=1, padx=5, sticky="e")
            ctk.CTkButton(
                actions,
                text="Supprimer",
                width=96,
                height=36,
                corner_radius=10,
                fg_color="transparent",
                hover_color=C["fav"],
                border_width=1,
                border_color=C["fav"],
                text_color=C["fav"],
                command=lambda aid=alert.get("id", ""), q=alert.get("query", "cette alerte"): self._supprimer_alert(aid, q),
            ).grid(row=0, column=2, padx=(5, 0), sticky="e")

    def _toggle_alert(self, alert_id: str, active: bool):
        alert = discord_alerts.set_alert_active(alert_id, active)
        if not alert:
            self._refresh_if_alive()
            return
        self.app._refresh_discord_alert_ui()
        self.app._planifier_surveillance_discord(1000)
        state = "activée" if active else "désactivée"
        envoyer_toast("Alerte Discord", f"Surveillance {state} pour : {alert.get('query', 'Recherche')}")
        self._refresh_if_alive()

    def _editer_alert(self, alert: dict):
        FenetreAlerteDiscord(self.app, self._snapshot_from_alert(alert), on_change=self._refresh_if_alive)

    def _supprimer_alert(self, alert_id: str, query: str):
        if not messagebox.askyesno("Supprimer l'alerte", f"Supprimer l'alerte « {query} » ?"):
            return
        if not discord_alerts.delete_alert(alert_id):
            self._refresh_if_alive()
            return
        self.app._refresh_discord_alert_ui()
        self.app._planifier_surveillance_discord(1000)
        envoyer_toast("Alerte supprimée", f"L'alerte « {query} » a été retirée.")
        self._refresh_if_alive()


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
        _safe_after(self, lambda: self._afficher(a), scheduler=self.master)

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
            user_profile.record_annonce_event("target_add", self._annonce)
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
        self._recommended = {p.nom for p in comparateur_prix.plateformes_recommandees(annonce)}

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
        ctk.CTkLabel(header,
                     text=comparateur_prix.explication_recommandation(self._annonce),
                     font=ctk.CTkFont(size=10),
                     text_color=C["accent"]).grid(row=2, column=0, padx=20, pady=(0, 4), sticky="w")

        # Champ de recherche modifiable
        champ_f = ctk.CTkFrame(header, fg_color="transparent")
        champ_f.grid(row=3, column=0, padx=20, pady=(4, 14), sticky="ew")
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
        bar.grid_columnconfigure(2, weight=1)

        ctk.CTkButton(bar, text="Selection intelligente", height=34, corner_radius=8,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["accent"],
                      text_color=C["accent"], font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._selection_intelligente
        ).grid(row=0, column=0, padx=(12, 4), pady=10)

        ctk.CTkButton(bar, text="Tout sélectionner", height=34, corner_radius=8,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=lambda: self._tout(True)
        ).grid(row=0, column=1, padx=4, pady=10)

        ctk.CTkButton(bar, text="Tout désélectionner", height=34, corner_radius=8,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=lambda: self._tout(False)
        ).grid(row=0, column=2, padx=4, pady=10, sticky="w")

        ctk.CTkButton(bar, text="🌐  Ouvrir la sélection", height=40, corner_radius=10,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#000000", font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._ouvrir_selection
        ).grid(row=0, column=3, padx=(4, 12), pady=8, sticky="e")

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
                var = tk.BooleanVar(value=p.nom in self._recommended)
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

    def _selection_intelligente(self):
        for nom, (var, _) in self._sel.items():
            var.set(nom in self._recommended)

    def _ouvrir_selection(self):
        query = self._champ_query.get().strip() or self._query
        sel = [p for nom, (var, p) in self._sel.items() if var.get()]
        if not sel:
            messagebox.showwarning("Sélection vide", "Sélectionnez au moins une plateforme.")
            return
        user_profile.record_annonce_event("compare_open", self._annonce)
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

        score_color = (
            C["prix"] if a.score_opportunite >= 75
            else C["alerte_on"] if a.score_opportunite >= 50
            else C["fav"]
        )
        fiabilite_color = (
            C["prix"] if a.fiabilite_marche >= 75
            else C["alerte_on"] if a.fiabilite_marche >= 45
            else C["fav"]
        )
        score_label = (
            "Très bon deal à surveiller de près" if a.score_opportunite >= 75
            else "Deal correct avec marge raisonnable" if a.score_opportunite >= 50
            else "Deal fragile, à confirmer avant achat"
        )
        base_url = getattr(getattr(self.master, "scraper", None), "base_url", "https://www.vinted.fr")

        hero = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=18,
                            border_width=2, border_color=score_color)
        hero.grid(row=row, column=0, padx=16, pady=(16, 8), sticky="ew"); row += 1
        hero.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hero, text="ACHAT / REVENTE",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["cible"]).grid(row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        ctk.CTkLabel(hero, text=a.produit,
                     font=ctk.CTkFont(family=FONT, size=20, weight="bold"),
                     text_color=C["t1"], wraplength=470, justify="left"
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")

        badges = ctk.CTkFrame(hero, fg_color="transparent")
        badges.grid(row=2, column=0, padx=16, pady=(0, 10), sticky="w")
        for label, fg, txt in [
            (a.etat, C["tag_bg"], C["t2"]),
            (f"Fiabilité marché {a.fiabilite_marche}/100", "#18241a", fiabilite_color),
        ]:
            ctk.CTkLabel(badges, text=label, fg_color=fg, text_color=txt,
                         corner_radius=8, padx=9, pady=4,
                         font=ctk.CTkFont(size=10, weight="bold")
            ).pack(side="left", padx=(0, 6))

        score_row = ctk.CTkFrame(hero, fg_color="transparent")
        score_row.grid(row=3, column=0, padx=16, pady=(0, 8), sticky="ew")
        score_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(score_row, text=f"{a.score_opportunite}/100",
                     font=ctk.CTkFont(family=FONT, size=36, weight="bold"),
                     text_color=score_color
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(score_row, text=score_label,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=score_color, wraplength=290, justify="left"
        ).grid(row=0, column=1, padx=(12, 0), sticky="w")

        ctk.CTkLabel(hero, text=a.conseil,
                     font=ctk.CTkFont(size=11), text_color=C["t2"],
                     wraplength=470, justify="left"
        ).grid(row=4, column=0, padx=16, pady=(0, 14), sticky="w")

        metrics = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                               border_width=1, border_color=C["border"])
        metrics.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
        for col in range(4):
            metrics.grid_columnconfigure(col, weight=1)

        def metric(par, row_idx, col, label, value, color=C["t1"]):
            box = ctk.CTkFrame(par, fg_color="transparent")
            box.grid(row=row_idx, column=col, padx=8, pady=10, sticky="ew")
            ctk.CTkLabel(box, text=label,
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C["t3"]).pack()
            ctk.CTkLabel(box, text=value,
                         font=ctk.CTkFont(family=FONT, size=15, weight="bold"),
                         text_color=color).pack(pady=(2, 0))

        metric(metrics, 0, 0, "ACHAT", a.fmt(a.prix_achat), C["t2"])
        metric(metrics, 0, 1, "VENTE RAPIDE", a.fmt(a.prix_vente_rapide), C["accent"])
        metric(metrics, 0, 2, "PRIX CIBLE", a.fmt(a.prix_suggere), C["prix"])
        metric(metrics, 0, 3, "PLANCHER", a.fmt(a.prix_min_rentable), C["t1"])
        marge_color = C["prix"] if a.marge_pct >= 0 else C["fav"]
        metric(metrics, 1, 0, "MARGE", f"{a.marge_estimee:+.2f} €", marge_color)
        metric(metrics, 1, 1, "ROI", f"{a.marge_pct:+.0f}%", marge_color)
        metric(metrics, 1, 2, "MARCHÉ MOYEN", a.fmt(a.prix_marche_moyen) if a.prix_marche_moyen else "N/A")
        metric(metrics, 1, 3, "MÉDIANE", a.fmt(a.prix_marche_mediane) if a.prix_marche_mediane else "N/A")

        market = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                              border_width=1, border_color=C["border"])
        market.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
        market.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(market, text="LECTURE MARCHÉ",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color=C["t1"]
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")
        market_text = (
            f"{a.nb_annonces} annonce(s) comparables observées. "
            f"Fourchette utile: {a.prix_marche_min:.0f}–{a.prix_marche_max:.0f} €."
            if a.nb_annonces > 0 else
            "Aucune référence propre trouvée. L'estimation repose surtout sur votre seuil rentable."
        )
        ctk.CTkLabel(market, text=market_text,
                     font=ctk.CTkFont(size=11), text_color=C["t2"],
                     wraplength=490, justify="left"
        ).grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")

        tf = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                          border_width=1, border_color=C["border"])
        tf.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
        tf.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tf, text="TITRE CONSEILLÉ",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color=C["t1"]
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")
        self._titre_var = ctk.StringVar(value=a.titre)
        ctk.CTkEntry(tf, textvariable=self._titre_var, height=38, corner_radius=8,
                     font=ctk.CTkFont(size=12),
                     fg_color=C["input_bg"], border_color=C["accent"],
                     text_color=C["t1"]
        ).grid(row=1, column=0, padx=14, pady=(0, 4), sticky="ew")
        ctk.CTkLabel(tf, text=f"{len(a.titre)}/60 caractères",
                     font=ctk.CTkFont(size=9), text_color=C["t3"]
        ).grid(row=2, column=0, padx=14, pady=(0, 10), sticky="w")

        df = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                          border_width=1, border_color=C["border"])
        df.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
        df.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(df, text="DESCRIPTION CONSEILLÉE",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color=C["t1"]
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")
        self._desc_box = ctk.CTkTextbox(df, height=190, corner_radius=8,
                                        font=ctk.CTkFont(size=11),
                                        fg_color=C["input_bg"], text_color=C["t1"],
                                        border_color=C["border"], border_width=1)
        self._desc_box.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="ew")
        self._desc_box.insert("1.0", a.description)

        if a.annonces_ref:
            refs = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=14,
                                border_width=1, border_color=C["border"])
            refs.grid(row=row, column=0, padx=16, pady=4, sticky="ew"); row += 1
            refs.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(refs, text="ANNONCES DE RÉFÉRENCE",
                         font=ctk.CTkFont(size=11, weight="bold"), text_color=C["t1"]
            ).grid(row=0, column=0, padx=14, pady=(10, 6), sticky="w")
            for idx, ann in enumerate(a.annonces_ref[:4], 1):
                item = ctk.CTkFrame(refs, fg_color=C["tag_bg"], corner_radius=8)
                item.grid(row=idx, column=0, padx=14, pady=3, sticky="ew")
                item.grid_columnconfigure(0, weight=1)
                title = ann.title if len(ann.title) <= 48 else ann.title[:47] + "…"
                ctk.CTkLabel(item, text=title, font=ctk.CTkFont(size=10),
                             text_color=C["t2"], anchor="w"
                ).grid(row=0, column=0, padx=8, pady=5, sticky="w")
                ctk.CTkLabel(item, text=ann.prix_affiche(),
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=C["prix"]
                ).grid(row=0, column=1, padx=8, pady=5)
                ctk.CTkButton(item, text="Ouvrir", width=58, height=26, corner_radius=7,
                              fg_color="transparent", hover_color=C["border"],
                              text_color=C["t3"], border_width=1, border_color=C["border"],
                              font=ctk.CTkFont(size=10),
                              command=lambda u=ann.url: webbrowser.open(u)
                ).grid(row=0, column=2, padx=(0, 6), pady=4)
            ctk.CTkFrame(refs, fg_color="transparent", height=8).grid(
                row=len(a.annonces_ref[:4]) + 1, column=0
            )

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=row, column=0, padx=16, pady=(8, 20), sticky="ew"); row += 1
        for col in range(3):
            actions.grid_columnconfigure(col, weight=1)
        ctk.CTkButton(actions, text="Copier le titre", height=38,
                      corner_radius=10, fg_color=C["border"],
                      hover_color=C["card_hover"], text_color=C["t1"],
                      font=ctk.CTkFont(size=12),
                      command=self._copier_titre
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(r4, text="Vendeur", height=28, corner_radius=7,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=lambda: self.app._ouvrir_analyse_vendeur(self.annonce)
        ).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(actions, text="Copier la description", height=38,
                      corner_radius=10, fg_color=C["border"],
                      hover_color=C["card_hover"], text_color=C["t1"],
                      font=ctk.CTkFont(size=12),
                      command=self._copier_description
        ).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(actions, text="Copier le pack annonce", height=38,
                      corner_radius=10, fg_color="transparent",
                      hover_color=C["border"], border_width=1, border_color=C["cible"],
                      text_color=C["t1"], font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._copier_pack
        ).grid(row=0, column=2, padx=(4, 0), sticky="ew")
        ctk.CTkButton(actions, text="Rechercher sur Vinted", height=40,
                      corner_radius=10, fg_color=C["accent"],
                      hover_color=C["accent_hover"], text_color="#000000",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: webbrowser.open(
                          f"{base_url}/catalog?search_text={quote_plus(self._analyse.produit)}")
        ).grid(row=1, column=0, columnspan=2, pady=(6, 0), padx=(0, 4), sticky="ew")
        ctk.CTkButton(actions, text="Fermer", height=40,
                      corner_radius=10, fg_color=C["border"],
                      hover_color=C["card_hover"], text_color=C["t1"],
                      font=ctk.CTkFont(size=12),
                      command=self.destroy
        ).grid(row=1, column=2, pady=(6, 0), padx=(4, 0), sticky="ew")

    def _copier_titre(self):
        self.clipboard_clear()
        self.clipboard_append(self._titre_var.get())
        envoyer_toast("Copié !", "Titre copié dans le presse-papier.")

    def _copier_description(self):
        self.clipboard_clear()
        self.clipboard_append(self._desc_box.get("1.0", "end").strip())
        envoyer_toast("Copié !", "Description copiée dans le presse-papier.")

    def _copier_pack(self):
        contenu = (
            f"{self._titre_var.get().strip()}\n\n"
            f"{self._desc_box.get('1.0', 'end').strip()}"
        )
        self.clipboard_clear()
        self.clipboard_append(contenu)
        envoyer_toast("Copié !", "Pack annonce copié dans le presse-papier.")


class AnnonceWidget(ctk.CTkFrame):
    """Base commune pour les widgets d'annonce (cartes et lignes)."""
    def __init__(self, parent, annonce: scraper.Annonce, app, nouveau=False,
                 selection_var=None, **kwargs):
        self.annonce      = annonce
        self.app          = app
        self._nouveau     = nouveau
        self._sel_var     = selection_var
        self._pil_img     = None
        self._photo       = None
        self._actions_built = False
        super().__init__(parent, **kwargs)

    def _build_selection_checkbox(self, parent, row=None, column=None, sticky="e", **grid_kwargs):
        if self._sel_var is None:
            return None
        checkbox = ctk.CTkCheckBox(parent, text="", variable=self._sel_var, width=20,
                                   fg_color=C["accent"], hover_color=C["accent_hover"],
                                   border_color=C["border"],
                                   command=self.app._maj_bouton_comparateur)
        if row is not None and column is not None:
            checkbox.grid(row=row, column=column, sticky=sticky, **grid_kwargs)
        return checkbox

    def _build_fav_button(self, parent, **grid_opts):
        fav_color = C["fav"] if data.est_favori(self.annonce.id) else "transparent"
        btn = ctk.CTkButton(parent, text="♥", width=34, height=34,
                            corner_radius=8, fg_color=fav_color,
                            hover_color=C["fav"], text_color=C["t1"],
                            command=self._toggle_fav)
        if grid_opts:
            btn.grid(**grid_opts)
        return btn

    def _toggle_fav(self):
        ajout = self.app._toggle_favori_annonce(self.annonce)
        if hasattr(self, "btn_fav"):
            self.btn_fav.configure(
                fg_color=C["fav"] if ajout else "transparent",
                border_color=C["fav"] if ajout else C["border"])

    def _charger_image(self, label, size):
        if self.annonce.image_url:
            self.app._img_pool.submit(self._dl_image, label, size)
        else:
            label.configure(text="📷")

    def _dl_image(self, label, size):
        try:
            self._pil_img, ci = _load_cached_image(self.annonce.image_url, size)
            self._photo = ci
            _safe_after(label,
                        lambda: (label.configure(image=ci, text="")),
                        scheduler=self.app)
        except Exception:
            _safe_after(label, lambda: label.configure(text="✕"), scheduler=self.app)

    @staticmethod
    def _trunc(s, n):
        return s if len(s) <= n else s[:n-1] + "…"


class CarteAnnonce(AnnonceWidget):
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
        self.app = app
        self.CARD_W, self.IMAGE_W, self.IMAGE_H = self.app._dimensions_carte()
        super().__init__(parent, annonce, app, nouveau=nouveau,
                         selection_var=selection_var,
                         corner_radius=16, fg_color=C["card"],
                         border_width=1, border_color=self._border_base,
                         width=self.CARD_W, **kwargs)
        self._etendu      = False
        self._construire(nouveau)
        self._charger_image(self.lbl_image, (self.IMAGE_W, self.IMAGE_H))
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
            self._build_selection_checkbox(top, row=0, column=1)
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
                     text_color=C["t1"], wraplength=self.IMAGE_W, justify="left")
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
        if getattr(self.annonce, "relevance_score", None) is not None:
            ctk.CTkLabel(self, text=f"AffinitÃ© {getattr(self.annonce, 'relevance_score', 0)}/100",
                         font=ctk.CTkFont(size=10, weight="bold"), text_color=C["cible"],
                         fg_color=C["tag_bg"], corner_radius=6, padx=8, pady=3
            ).grid(row=row, column=0, padx=12, pady=(0, 4), sticky="w")
            row += 1
        if getattr(self.annonce, "duplicate_count", 1) > 1:
            ctk.CTkLabel(self, text=getattr(self.annonce, "duplicate_hint", "Doublon"),
                         font=ctk.CTkFont(size=10, weight="bold"), text_color=C["alerte_on"],
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
                      command=lambda: self.app._ouvrir_annonce(self.annonce)
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
        r4.grid_columnconfigure(1, weight=1)
        r4.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(r4, text="🔍 Aperçu", height=28, corner_radius=7,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=lambda: self.app._ouvrir_apercu(self.annonce)
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(r4, text="👤 Vendeur", height=28, corner_radius=7,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=lambda: self.app._ouvrir_analyse_vendeur(self.annonce)
        ).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(r4, text="🔗 Lien", width=64, height=28, corner_radius=7,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], font=ctk.CTkFont(size=11),
                      command=self._copier_lien
        ).grid(row=0, column=2, padx=(4, 0), sticky="ew")

    # ── Toggle étendu ─────────────────────────────────────────────────────────

    def _toggle_etendu(self, event=None):
        self._etendu = not self._etendu
        if self._etendu:
            if not self._actions_built:
                self._construire_actions()
                self._actions_built = True
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
        FenetreAnalyse(self.app, self.annonce, getattr(self.app, "_annonces", []))

    def _ouvrir_comparateur_prix(self):
        self.app._ouvrir_comparateur_prix_annonce(self.annonce)

    def _toggle_fav(self):
        ajout = self.app._toggle_favori_annonce(self.annonce)
        self.btn_fav.configure(
            fg_color=C["fav"] if ajout else "transparent",
            border_color=C["fav"] if ajout else C["border"])

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

# ─── Ligne Annonce (mode liste) ───────────────────────────────────────────────

class LigneAnnonce(AnnonceWidget):
    IMG_S = 56

    def __init__(self, parent, annonce: scraper.Annonce, app, nouveau=False,
                 selection_var=None, **kwargs):
        super().__init__(parent, annonce, app, nouveau=nouveau,
                         selection_var=selection_var,
                         corner_radius=10, fg_color=C["liste_bg"],
                          border_width=1, border_color=C["nouveau"] if nouveau else C["border"],
                         height=118, **kwargs)
        self.grid_propagate(False)
        self.grid_columnconfigure(2, weight=1)
        self._construire(nouveau)
        self._charger_image()
        self.bind("<Enter>", lambda _: self.configure(fg_color=C["liste_hover"]))
        self.bind("<Leave>", lambda _: self.configure(fg_color=C["liste_bg"]))

    def _construire(self, nouveau):
        col = 0
        if self._sel_var is not None:
            self._build_selection_checkbox(
                self, row=0, column=col, padx=(10, 0), pady=8)
            col += 1
        self.lbl_img = ctk.CTkLabel(self, text="…", width=self.IMG_S,
                                    height=self.IMG_S, fg_color="#1a2333",
                                    corner_radius=8, text_color=C["t3"])
        self.lbl_img.grid(row=0, column=col, padx=(8, 8), pady=10, sticky="n")
        self.lbl_img.bind("<Button-1>",
                          lambda _: self.app._ouvrir_apercu(self.annonce))
        self.lbl_img.configure(cursor="hand2")
        col += 1
        txt = ctk.CTkFrame(self, fg_color="transparent")
        txt.grid(row=0, column=col, padx=6, pady=10, sticky="nsew")
        txt.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            txt, text=CarteAnnonce._trunc(self.annonce.title, 78),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C["nouveau"] if nouveau else C["t1"],
            anchor="w", justify="left"
        ).grid(row=0, column=0, sticky="ew")
        sub = " • ".join(filter(None, [self.annonce.brand, self.annonce.size,
                                        self.annonce.condition,
                                        getattr(self.annonce, "vendeur_nom", "")]))
        ctk.CTkLabel(txt, text=sub, font=ctk.CTkFont(size=10),
                     text_color=C["t3"], anchor="w").grid(row=1, column=0, sticky="ew")
        badge_row = ctk.CTkFrame(txt, fg_color="transparent")
        badge_row.grid(row=2, column=0, pady=(6, 0), sticky="w")
        if getattr(self.annonce, "relevance_score", None) is not None:
            ctk.CTkLabel(
                badge_row,
                text=f"Affinité {getattr(self.annonce, 'relevance_score', 0)}/100",
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=C["cible"],
                fg_color=C["tag_bg"],
                corner_radius=6,
                padx=7,
                pady=2,
            ).pack(side="left", padx=(0, 4))
        if getattr(self.annonce, "duplicate_count", 1) > 1:
            ctk.CTkLabel(
                badge_row,
                text=getattr(self.annonce, "duplicate_hint", "Doublon"),
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=C["alerte_on"],
                fg_color=C["tag_bg"],
                corner_radius=6,
                padx=7,
                pady=2,
            ).pack(side="left", padx=(0, 4))
        if nouveau:
            ctk.CTkLabel(
                badge_row,
                text="Nouveau",
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color="#000000",
                fg_color=C["nouveau"],
                corner_radius=6,
                padx=7,
                pady=2,
            ).pack(side="left")
        explanation = getattr(self.annonce, "relevance_explanation", "")
        if explanation:
            ctk.CTkLabel(
                txt, text=explanation,
                font=ctk.CTkFont(size=10),
                text_color=C["t2"],
                anchor="w", justify="left",
                wraplength=520,
            ).grid(row=3, column=0, pady=(6, 0), sticky="ew")
        col += 1
        side = ctk.CTkFrame(self, fg_color="transparent")
        side.grid(row=0, column=col, padx=(10, 10), pady=10, sticky="ne")
        side.grid_columnconfigure((0, 1, 2), weight=1)
        price_card = ctk.CTkFrame(side, fg_color=C["card"], corner_radius=10,
                                  border_width=1, border_color=C["border"])
        price_card.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(price_card, text=self.annonce.prix_affiche(),
                     font=ctk.CTkFont(size=16, weight="bold"), text_color=C["prix"]
        ).pack(anchor="w", padx=10, pady=(8, 0))
        ctk.CTkLabel(price_card, text=getattr(self.annonce, "brand", "") or "Annonce suivie",
                     font=ctk.CTkFont(size=9), text_color=C["t3"]
        ).pack(anchor="w", padx=10, pady=(0, 8))
        ctk.CTkButton(side, text="Voir →", width=74, height=30, corner_radius=8,
                      fg_color=C["accent"], hover_color=C["accent_hover"],
                      text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"),
                      command=lambda: self.app._ouvrir_annonce(self.annonce)
        ).grid(row=1, column=0, columnspan=2, padx=(0, 4), pady=(0, 4), sticky="ew")
        ctk.CTkButton(side, text="🎯", width=32, height=30, corner_radius=8,
                      fg_color=C["cible"], hover_color="#6d28d9", text_color="#fff",
                      command=self._ouvrir_analyse
        ).grid(row=1, column=2, pady=(0, 4), sticky="ew")
        ctk.CTkButton(side, text="📈", width=32, height=30, corner_radius=8,
                      fg_color=C["border"], hover_color="#2d3a50", text_color=C["t2"],
                      command=lambda: FenetreHistorique(
                          self.winfo_toplevel(), str(self.annonce.id),
                          self.annonce.title)
        ).grid(row=2, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(side, text="👤", width=32, height=30, corner_radius=8,
                      fg_color="transparent", hover_color=C["border"],
                      border_width=1, border_color=C["border"],
                      text_color=C["t2"], command=lambda: self.app._ouvrir_analyse_vendeur(self.annonce)
        ).grid(row=2, column=1, padx=2, sticky="ew")
        fav_color = C["fav"] if data.est_favori(self.annonce.id) else C["border"]
        self.btn_fav = ctk.CTkButton(side, text="♥", width=32, height=30,
                                     corner_radius=7, fg_color=fav_color,
                                     hover_color=C["fav"], text_color=C["t1"],
                                     command=self._toggle_fav)
        self.btn_fav.grid(row=2, column=2, padx=(4, 0), sticky="ew")

    def _ouvrir_analyse(self):
        app = self.winfo_toplevel()
        marche = getattr(app, "_annonces", [])
        FenetreAnalyse(app, self.annonce, marche)

    def _charger_image(self):
        super()._charger_image(self.lbl_img, (self.IMG_S, self.IMG_S))

    def _toggle_fav(self):
        ajout = self.app._toggle_favori_annonce(self.annonce)
        self.btn_fav.configure(fg_color=C["fav"] if ajout else C["border"])


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
        self._img_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="img")
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
        self._layout_job            = None
        self._sidebar_anim_job      = None
        self._render_version        = 0
        self._anim_iter             = itertools.cycle(["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"])
        self._alerte_active:   bool = False
        self._alerte_job            = None
        self._alerte_ids:      set  = set()
        self._alerte_config         = None
        self._alerte_poll_running   = False
        self._titre_recherche: str  = ""
        self._suggest_job           = None
        self._suggest_visible: bool = False
        self._discord_job           = None
        self._discord_poll_running  = False
        self._session_job           = None
        self._last_results_at       = None

        self.settings = data.charger_parametres()
        self._sidebar_auto = self.settings.get("sidebar_auto_collapsing", True)
        self._sidebar_animation = self.settings.get("sidebar_animation", True)
        self.articles_par_page = int(self.settings.get("articles_par_page", 10))

        self._construire_ui()
        self._appliquer_parametres()
        self._restaurer_session_recherche()
        self._bind_shortcuts()
        self.bind("<Configure>", self._maj_layout)
        self.after(300, self._appliquer_layout)
        threading.Thread(target=data.purger_historique_ancien, daemon=True).start()
        self.after(180, self._afficher_suggestions_initiales)
        self.after(320, self._afficher_recommandations_accueil)
        self.after(1200, self._planifier_surveillance_discord)
        self.after(420, lambda: self.champ_recherche.focus_set())


    # ══ Elastic Layout ════════════════════════════════════════════════════════

    def _colonnes_pour_largeur(self) -> int:
        """Calcule le nb de colonnes selon la largeur disponible de zone_scroll."""
        try:
            w = self.zone_scroll._parent_canvas.winfo_width() - 18
        except Exception:
            w = 900
        if self._mode_liste:
            return 1
        usable = max(self.CARD_MIN_W, w)
        return max(1, min(5, usable // self.CARD_MIN_W))

    def _dimensions_carte(self) -> tuple[int, int, int]:
        cols = max(1, getattr(self, "_derniere_cols", self.COLONNES))
        try:
            usable = self.zone_scroll._parent_canvas.winfo_width() - 24 - (cols * 20)
        except Exception:
            usable = cols * self.CARD_MIN_W
        card_w = max(250, int(usable / cols) - 8)
        image_w = max(190, min(260, card_w - 28))
        image_h = max(170, min(220, int(image_w * 0.9)))
        return card_w, image_w, image_h

    def _maj_layout(self, event=None):
        """Débounce les recalculs pour garder un resize fluide."""
        if event is not None and getattr(event, "widget", None) is not self:
            return
        if self._layout_job:
            try:
                self.after_cancel(self._layout_job)
            except Exception:
                pass
        self._layout_job = self.after(90, self._appliquer_layout)

    def _appliquer_layout(self):
        """Adapte sidebar + colonnes sans rerenders agressifs."""
        self._layout_job = None
        try:
            win_w = self.winfo_width()
        except Exception:
            return

        # ── Sidebar auto-collapse ──────────────────────────────────────────
        seuil_mini = 1100
        nouveau_mini = win_w < seuil_mini if self._sidebar_auto else False
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
                self.after(10, lambda: _widget_exists(self) and self._rendre_cartes(self._annonces))

        # ── Header overflow ───────────────────────────────────────────────
        self._maj_header_overflow(win_w)

    def _appliquer_parametres(self):
        self._sidebar_auto = self.settings.get("sidebar_auto_collapsing", True)
        self._sidebar_animation = self.settings.get("sidebar_animation", True)
        appearance = self.settings.get("appearance_mode", "dark")
        ctk.set_appearance_mode(appearance)
        self.articles_par_page = int(self.settings.get("articles_par_page", 10))
        if bool(self.settings.get("mode_liste_par_defaut", False)) != bool(self._mode_liste):
            self._toggle_mode()
        if self._annonces:
            self._rendre_cartes(self._annonces)
        self._refresh_search_summary()

    def _animer_sidebar(self, cible: int, duree: int = 200, pas: int = 20):
        """Animation fluide sidebar expand/collapse."""
        if not self._sidebar_animation:
            self._sb_frame.configure(width=cible)
            self._maj_contenu_sidebar(cible <= self.SIDEBAR_MINI + 20)
            return
        if self._sidebar_anim_job is not None:
            try:
                self.after_cancel(self._sidebar_anim_job)
            except Exception:
                pass
            self._sidebar_anim_job = None
        try:
            actuelle = self._sb_frame.winfo_width()
        except Exception:
            return
        delta = cible - actuelle
        if abs(delta) <= 2:
            self._sb_frame.configure(width=cible)
            self._maj_contenu_sidebar(cible <= self.SIDEBAR_MINI + 20)
            self._sidebar_anim_job = None
            return
        etape = max(3, int(abs(delta) * 0.18))
        nouvelle = actuelle + (etape if delta > 0 else -etape)
        self._sb_frame.configure(width=nouvelle)
        self._sidebar_anim_job = self.after(16, lambda: self._animer_sidebar(cible, duree, pas))

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
        self._sauvegarder_session_recherche(immediate=True)
        for job_name in ("_layout_job", "_render_job", "_anim_job", "_alerte_job", "_suggest_job", "_discord_job", "_session_job"):
            job = getattr(self, job_name, None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, job_name, None)
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
        search_row = ctk.CTkFrame(tab, fg_color="transparent")
        search_row.grid(row=row, column=0, padx=16, pady=(4, 2), sticky="ew"); row += 1
        search_row.grid_columnconfigure(0, weight=1)
        self.champ_recherche = ctk.CTkEntry(
            search_row, placeholder_text="ex : op12 display, luffy sr...",
            height=40, corner_radius=8, font=ctk.CTkFont(family=FONT, size=13),
            fg_color=C["input_bg"], border_color=C["accent"],
            border_width=1, text_color=C["t1"])
        self.champ_recherche.grid(row=0, column=0, sticky="ew")
        self.btn_discord_alert = ctk.CTkButton(
            search_row, text="🔔", width=40, height=40, corner_radius=10,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"], text_color=C["t3"],
            font=ctk.CTkFont(size=15), command=self._ouvrir_alerte_discord, state="disabled")
        self.btn_discord_alert.grid(row=0, column=1, padx=(8, 0))
        self.btn_discord_manage = ctk.CTkButton(
            search_row, text="Alertes", width=88, height=40, corner_radius=10,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"], text_color=C["t2"],
            font=ctk.CTkFont(family=FONT, size=11, weight="bold"),
            command=self._ouvrir_gestion_alertes_discord)
        self.btn_discord_manage.grid(row=0, column=2, padx=(8, 0))
        self.champ_recherche.bind("<Return>", lambda _: self._lancer_recherche())
        self.champ_recherche.bind("<KeyRelease>", self._on_recherche_key)
        self.champ_recherche.bind("<Escape>", lambda _: self._cacher_suggestions())
        self.champ_recherche.bind("<FocusOut>", lambda _: self.after(150, self._cacher_suggestions))
        self.champ_recherche.bind("<FocusIn>", lambda _: self._afficher_suggestions_initiales())

        # Frame suggestions (autocomplete)
        self._frame_suggestions = ctk.CTkFrame(tab, fg_color=C["card"],
                                               corner_radius=14, border_width=1,
                                               border_color=C["accent"])
        # N'est pas griddée par défaut — apparaît dynamiquement
        ctk.CTkLabel(tab, text="Virgule = plusieurs termes",
                     font=ctk.CTkFont(family=FONT, size=10), text_color=C["t3"]
        ).grid(row=row + 1, column=0, padx=16, pady=(0, 4), sticky="w"); row += 2
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
            button_hover_color=C["accent"], text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=11),
            command=lambda *_: self._on_search_control_change())
        self.menu_categorie.set("— Toutes —")
        self.menu_categorie.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        self._slabel(tab, row, "COULEUR"); row += 1
        self.menu_couleur = ctk.CTkOptionMenu(
            tab, values=["— Toutes —"] + list(scraper.COULEURS.keys()),
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=11),
            command=lambda *_: self._on_search_control_change())
        self.menu_couleur.set("— Toutes —")
        self.menu_couleur.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        self._slabel(tab, row, "VENDEUR"); row += 1
        self.champ_vendeur = ctk.CTkEntry(
            tab, placeholder_text="ID numérique du vendeur", height=34, corner_radius=8,
            font=ctk.CTkFont(family=FONT, size=12), fg_color=C["input_bg"], border_color=C["border"],
            text_color=C["t1"])
        self.champ_vendeur.grid(row=row, column=0, padx=16, pady=(4, 8), sticky="ew"); row += 1
        for field in (self.champ_prix_min, self.champ_prix_max, self.champ_vendeur):
            field.bind("<KeyRelease>", self._on_search_control_change)
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
        tf2.grid_columnconfigure((0, 1), weight=1)
        self.btn_tri_recent = ctk.CTkButton(tf2, text="Récent d'abord", height=32,
            corner_radius=8, fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            command=lambda: self._trier("recent"))
        self.btn_tri_recent.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.btn_tri_affinite = ctk.CTkButton(tf2, text="Pour vous", height=32,
            corner_radius=8, fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            command=lambda: self._trier("affinite"))
        self.btn_tri_affinite.grid(row=0, column=1, padx=(4, 0), sticky="ew")
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
        ab.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkButton(ab, text="↺ Actualiser", height=32, corner_radius=10,
            fg_color="transparent", hover_color=C["border"], text_color=C["t1"],
            border_width=1, border_color=C["border"], font=ctk.CTkFont(family=FONT, size=12),
            command=self._lancer_recherche).grid(row=0, column=0, padx=(0,4), sticky="ew")
        ctk.CTkButton(ab, text="Sauvegarder", height=32, corner_radius=10,
            fg_color="transparent", hover_color=C["border"], text_color=C["t1"],
            border_width=1, border_color=C["border"], font=ctk.CTkFont(family=FONT, size=12),
            command=self._sauvegarder_recherche).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(ab, text="Nettoyer", height=32, corner_radius=10,
            fg_color="transparent", hover_color=C["border"], text_color=C["t1"],
            border_width=1, border_color=C["border"], font=ctk.CTkFont(family=FONT, size=12),
            command=self._reinitialiser_recherche).grid(row=0, column=2, padx=(4,0), sticky="ew")
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
            al, values=["30 sec","1 min","2 min","5 min"],
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=12),
            command=lambda *_: self._on_search_control_change())
        self.menu_intervalle.set("30 sec")
        self.menu_intervalle.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        al.grid_columnconfigure(1, weight=1)
        self._alerte_exclure = ctk.CTkEntry(
            al, placeholder_text="Mots exclus (virgules)", height=32,
            corner_radius=8, fg_color=C["input_bg"], border_color=C["border"],
            text_color=C["t1"])
        self._alerte_exclure.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 4))
        self._alerte_ignore = ctk.CTkEntry(
            al, placeholder_text="Vendeurs ignores", height=32,
            corner_radius=8, fg_color=C["input_bg"], border_color=C["border"],
            text_color=C["t1"])
        self._alerte_ignore.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        self._alerte_prix_max = ctk.CTkEntry(
            al, placeholder_text="Prix max alerte", height=32,
            corner_radius=8, fg_color=C["input_bg"], border_color=C["border"],
            text_color=C["t1"])
        self._alerte_prix_max.grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))
        self.menu_affinite_alerte = ctk.CTkOptionMenu(
            al, values=["Toutes", "60+", "75+"],
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"], font=ctk.CTkFont(family=FONT, size=12),
            command=lambda *_: self._on_search_control_change())
        self.menu_affinite_alerte.set("Toutes")
        self.menu_affinite_alerte.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        for field in (self._alerte_exclure, self._alerte_ignore, self._alerte_prix_max):
            field.bind("<KeyRelease>", self._on_search_control_change)
        self.lbl_alerte_status = ctk.CTkLabel(tab, text="● Inactive",
            font=ctk.CTkFont(family=FONT, size=11), text_color=C["t3"])
        self.lbl_alerte_status.grid(row=row, column=0, padx=16, pady=(0, 8), sticky="w")
        self._refresh_discord_alert_ui()

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
            meta = [x for x in [
                r.get("pays"),
                f"≥{r['prix_min']}€" if r.get("prix_min") is not None else None,
                f"≤{r['prix_max']}€" if r.get("prix_max") is not None else None,
                r.get("categorie"),
                r.get("couleur"),
                f"Vendeur {r.get('vendeur')}" if r.get("vendeur") else None,
                self._label_tri(r.get("ordre")) if r.get("ordre") else None,
                "Vue liste" if r.get("mode_liste") else None,
            ] if x]
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

        hero = ctk.CTkFrame(tab, fg_color=C["card"], corner_radius=14,
                            border_width=1, border_color=C["border"])
        hero.grid(row=row, column=0, padx=16, pady=(14, 10), sticky="ew"); row += 1
        hero.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hero, text="ACHAT / REVENTE",
                     font=ctk.CTkFont(family=FONT, size=12, weight="bold"),
                     text_color=C["accent"], anchor="w"
        ).grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")
        ctk.CTkLabel(hero, text="Estimez la marge, le plancher rentable et le bon prix d'affichage avant d'acheter.",
                     font=ctk.CTkFont(size=10), text_color=C["t2"],
                     wraplength=280, justify="left", anchor="w"
        ).grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")

        ctk.CTkLabel(tab, text="PRODUIT",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=C["t3"], anchor="w"
        ).grid(row=row, column=0, padx=16, pady=(2, 2), sticky="w"); row += 1

        self._resell_produit = ctk.CTkEntry(
            tab, placeholder_text="Ex: Nike Air Max 90, iPhone 13, display OP12",
            height=40, corner_radius=10, font=ctk.CTkFont(size=12),
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
            tab, placeholder_text="Ex: 25.00",
            height=40, corner_radius=10, font=ctk.CTkFont(size=12),
            fg_color=C["input_bg"], border_color=C["border"],
            border_width=1, text_color=C["t1"])
        self._resell_prix.grid(
            row=row, column=0, padx=16, pady=(0, 8), sticky="ew"); row += 1
        self._resell_prix.bind("<Return>", lambda _: self._lancer_analyse_revente())
        self._resell_prix.bind("<KeyRelease>", self._maj_hint_revente)

        ctk.CTkLabel(tab, text="ÉTAT",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=C["t3"], anchor="w"
        ).grid(row=row, column=0, padx=16, pady=(4, 2), sticky="w"); row += 1

        self._resell_etat = ctk.CTkOptionMenu(
            tab, values=resell.CONDITIONS,
            fg_color=C["input_bg"], button_color=C["border"],
            button_hover_color=C["accent"], text_color=C["t1"],
            font=ctk.CTkFont(size=11), command=self._maj_hint_revente)
        self._resell_etat.set("Tous états")
        self._resell_etat.grid(
            row=row, column=0, padx=16, pady=(0, 12), sticky="ew"); row += 1

        self._resell_hint = ctk.CTkLabel(
            tab,
            text="Entrez un prix d'achat pour voir votre seuil rentable minimum.",
            font=ctk.CTkFont(size=10),
            text_color=C["t2"],
            wraplength=280,
            justify="left",
        )
        self._resell_hint.grid(row=row, column=0, padx=16, pady=(0, 10), sticky="ew"); row += 1

        self._resell_btn = ctk.CTkButton(
            tab, text="Analyser le potentiel",
            height=40, corner_radius=10,
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

        self._maj_hint_revente()

    def _maj_hint_revente(self, _=None):
        prix_str = self._resell_prix.get().strip().replace(",", ".")
        if not prix_str:
            self._resell_hint.configure(
                text="Entrez un prix d'achat pour voir votre seuil rentable minimum.",
                text_color=C["t2"],
            )
            return
        try:
            prix_achat = float(prix_str)
        except ValueError:
            self._resell_hint.configure(
                text="Prix invalide. Utilisez par exemple 25.00",
                text_color=C["fav"],
            )
            return
        if prix_achat <= 0:
            self._resell_hint.configure(
                text="Le prix d'achat doit être supérieur à 0.",
                text_color=C["fav"],
            )
            return

        seuil = prix_achat * 1.15
        buffer = {
            "Tous états": 1.18,
            "Neuf avec étiquette": 1.26,
            "Neuf sans étiquette": 1.23,
            "Très bon état": 1.20,
            "Bon état": 1.18,
            "Satisfaisant": 1.16,
        }.get(self._resell_etat.get(), 1.18)
        rapide = max(seuil, prix_achat * buffer)
        self._resell_hint.configure(
            text=f"Seuil mini rentable ≈ {seuil:.2f} € · zone de vente rapide ≈ {rapide:.2f} €",
            text_color=C["t2"],
        )

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
        if prix_achat <= 0:
            self._resell_status.configure(
                text="⚠️ Le prix d'achat doit être supérieur à 0.",
                text_color=C["alerte_on"])
            return
        etat = self._resell_etat.get()
        self._resell_btn.configure(
            state="disabled", text="Analyse en cours...")
        self._resell_status.configure(
            text=f"Scan du marché pour « {produit} »...",
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
                        text="Analyser le potentiel")
                self.after(0, _reset)

        threading.Thread(target=_run, daemon=True).start()

    def _afficher_resultat_revente(self, analyse):
        market_insights.record_resell_analysis(analyse)
        self._resell_btn.configure(
            state="normal", text="Analyser le potentiel")
        self._resell_status.configure(
            text=f"Dernière analyse : score {analyse.score_opportunite}/100 · cible {analyse.prix_suggere:.2f} €",
            text_color=C["t2"])
        FenetreRevente(self, analyse)


    def _construire_zone_principale(self):
        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

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
        self.btn_accueil = ctk.CTkButton(top_btns, text="Accueil",
            width=86, height=34, corner_radius=8,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            command=self._ouvrir_accueil_intelligent)
        self.btn_accueil.pack(side="left", padx=4)
        self.btn_settings = ctk.CTkButton(top_btns, text="⚙️ Paramètres",
            width=120, height=34, corner_radius=8,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            command=self._ouvrir_parametres)
        self.btn_settings.pack(side="left", padx=4)
        self.btn_actions = ctk.CTkButton(top_btns, text="Actions (0)",
            width=102, height=34, corner_radius=8,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t3"], font=ctk.CTkFont(family=FONT, size=12),
            state="disabled", command=self._ouvrir_actions_masse)
        self.btn_actions.pack(side="left", padx=4)
        self.btn_profil = ctk.CTkButton(top_btns, text="Profil",
            width=80, height=34, corner_radius=8,
            fg_color="transparent", hover_color=C["border"],
            border_width=1, border_color=C["border"],
            text_color=C["t2"], font=ctk.CTkFont(family=FONT, size=12),
            command=self._ouvrir_profil_utilisateur)
        self.btn_profil.pack(side="left", padx=4)
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

        contextbar = ctk.CTkFrame(main, fg_color=C["card"], corner_radius=0, height=64)
        contextbar.grid(row=1, column=0, sticky="ew")
        contextbar.grid_propagate(False)
        contextbar.grid_columnconfigure(0, weight=1)
        contextbar.grid_columnconfigure(1, weight=0)

        ctx_left = ctk.CTkFrame(contextbar, fg_color="transparent")
        ctx_left.grid(row=0, column=0, padx=16, pady=10, sticky="w")
        self.lbl_search_summary_title = ctk.CTkLabel(
            ctx_left,
            text="Console marché",
            font=ctk.CTkFont(family=FONT, size=18, weight="bold"),
            text_color=C["t1"],
        )
        self.lbl_search_summary_title.pack(anchor="w")
        self.lbl_search_summary_meta = ctk.CTkLabel(
            ctx_left,
            text="Prêt pour une nouvelle recherche",
            font=ctk.CTkFont(family=FONT, size=11),
            text_color=C["t2"],
        )
        self.lbl_search_summary_meta.pack(anchor="w", pady=(2, 0))

        ctx_right = ctk.CTkFrame(contextbar, fg_color="transparent")
        ctx_right.grid(row=0, column=1, padx=16, pady=10, sticky="e")
        self.lbl_search_summary_hint = ctk.CTkLabel(
            ctx_right,
            text="Ctrl+F recherche • F5 actualiser • Ctrl+L vue • Ctrl+S sauvegarder",
            font=ctk.CTkFont(family=FONT, size=10),
            text_color=C["t3"],
            justify="right",
        )
        self.lbl_search_summary_hint.pack(anchor="e")

        self.zone_scroll = ctk.CTkScrollableFrame(main, fg_color=C["bg"],
            scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["accent"])
        self.zone_scroll.grid(row=2, column=0, sticky="nsew")
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
        bar.grid(row=3, column=0, sticky="ew")
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

    def _bind_shortcuts(self):
        shortcuts = {
            "<Control-f>": self._focus_search,
            "<Control-F>": self._focus_search,
            "<F5>": self._shortcut_refresh,
            "<Control-l>": self._shortcut_toggle_mode,
            "<Control-L>": self._shortcut_toggle_mode,
            "<Control-s>": self._shortcut_save_search,
            "<Control-S>": self._shortcut_save_search,
            "<Control-k>": self._shortcut_reset_search,
            "<Control-K>": self._shortcut_reset_search,
            "<Control-Shift-A>": self._shortcut_open_alerts,
        }
        for sequence, handler in shortcuts.items():
            self.bind(sequence, handler)

    def _focus_search(self, event=None):
        self.champ_recherche.focus_set()
        self.champ_recherche.icursor("end")
        return "break"

    def _shortcut_refresh(self, event=None):
        if self.champ_recherche.get().strip():
            self._lancer_recherche()
        else:
            self._afficher_suggestions_initiales()
        return "break"

    def _shortcut_toggle_mode(self, event=None):
        self._toggle_mode()
        return "break"

    def _shortcut_save_search(self, event=None):
        if self.champ_recherche.get().strip():
            self._sauvegarder_recherche()
        return "break"

    def _shortcut_reset_search(self, event=None):
        self._reinitialiser_recherche()
        return "break"

    def _shortcut_open_alerts(self, event=None):
        self._ouvrir_gestion_alertes_discord()
        return "break"

    def _on_search_control_change(self, event=None):
        self._refresh_discord_alert_ui()
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()

    def _format_prix_resume(self, value):
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if value.is_integer():
            return f"{int(value)} €"
        return f"{value:.2f} €"

    def _label_tri(self, ordre: str | None = None) -> str:
        mapping = {
            "prix_asc": "Prix croissant",
            "prix_desc": "Prix décroissant",
            "recent": "Récent d'abord",
            "affinite": "Pour vous",
            "newest_first": "Récent d'abord",
        }
        return mapping.get(ordre or self._ordre_tri, "Prix croissant")

    def _ordonner_annonces(self, annonces, ordre: str):
        if ordre == "recent":
            return list(annonces)
        if ordre == "affinite":
            return sorted(annonces, key=lambda a: getattr(a, "relevance_score", 0), reverse=True)
        return sorted(annonces, key=lambda a: a.price, reverse=(ordre == "prix_desc"))

    def _rafraichir_boutons_tri(self):
        if hasattr(self, "btn_tri_asc"):
            self.btn_tri_asc.configure(
                fg_color=C["accent"] if self._ordre_tri == "prix_asc" else C["border"],
                text_color="#ffffff" if self._ordre_tri == "prix_asc" else C["t2"])
        if hasattr(self, "btn_tri_desc"):
            self.btn_tri_desc.configure(
                fg_color=C["accent"] if self._ordre_tri == "prix_desc" else C["border"],
                text_color="#ffffff" if self._ordre_tri == "prix_desc" else C["t2"])
        if hasattr(self, "btn_tri_recent"):
            self.btn_tri_recent.configure(
                fg_color=C["accent"] if self._ordre_tri == "recent" else C["border"],
                text_color="#ffffff" if self._ordre_tri == "recent" else C["t2"])
        if hasattr(self, "btn_tri_affinite"):
            self.btn_tri_affinite.configure(
                fg_color=C["accent"] if self._ordre_tri == "affinite" else C["border"],
                text_color="#ffffff" if self._ordre_tri == "affinite" else C["t2"])

    def _sync_etat_buttons(self):
        if not hasattr(self, "_btns_etat"):
            return
        for label, (button, ids) in self._btns_etat.items():
            active = ids.issubset(self._etats_actifs)
            button.configure(
                fg_color=C["accent"] if active else C["border"],
                text_color="#ffffff" if active else C["t1"],
            )

    def _set_etats_actifs(self, ids: set[int] | list[int] | tuple[int, ...]):
        self._etats_actifs = {int(v) for v in (ids or [])}
        self._sync_etat_buttons()

    def _capturer_etat_recherche(self) -> dict:
        return {
            "query": self.champ_recherche.get().strip(),
            "pays": self.menu_pays.get().strip(),
            "price_min": self.champ_prix_min.get().strip(),
            "price_max": self.champ_prix_max.get().strip(),
            "categorie": self.menu_categorie.get().strip(),
            "couleur": self.menu_couleur.get().strip(),
            "vendeur": self.champ_vendeur.get().strip(),
            "tri": self._ordre_tri,
            "mode_liste": bool(self._mode_liste),
            "etats": sorted(self._etats_actifs),
            "alerte_intervalle": self.menu_intervalle.get().strip() if hasattr(self, "menu_intervalle") else "30 sec",
            "alerte_exclure": self._alerte_exclure.get().strip() if hasattr(self, "_alerte_exclure") else "",
            "alerte_ignore": self._alerte_ignore.get().strip() if hasattr(self, "_alerte_ignore") else "",
            "alerte_prix_max": self._alerte_prix_max.get().strip() if hasattr(self, "_alerte_prix_max") else "",
            "alerte_affinite": self.menu_affinite_alerte.get().strip() if hasattr(self, "menu_affinite_alerte") else "Toutes",
        }

    def _appliquer_etat_recherche(self, state: dict, lancer_recherche: bool = False):
        if not isinstance(state, dict):
            return

        self.champ_recherche.delete(0, "end")
        self.champ_recherche.insert(0, state.get("query", ""))
        self.champ_prix_min.delete(0, "end")
        self.champ_prix_min.insert(0, state.get("price_min", ""))
        self.champ_prix_max.delete(0, "end")
        self.champ_prix_max.insert(0, state.get("price_max", ""))
        self.champ_vendeur.delete(0, "end")
        self.champ_vendeur.insert(0, state.get("vendeur", ""))

        categorie = state.get("categorie") or "— Toutes —"
        couleur = state.get("couleur") or "— Toutes —"
        self.menu_categorie.set(categorie if categorie in (["— Toutes —"] + list(scraper.CATEGORIES.keys())) else "— Toutes —")
        self.menu_couleur.set(couleur if couleur in (["— Toutes —"] + list(scraper.COULEURS.keys())) else "— Toutes —")
        intervalle = state.get("alerte_intervalle") or "30 sec"
        self.menu_intervalle.set(intervalle if intervalle in {"30 sec", "1 min", "2 min", "5 min"} else "30 sec")
        self._alerte_exclure.delete(0, "end")
        self._alerte_exclure.insert(0, state.get("alerte_exclure", ""))
        self._alerte_ignore.delete(0, "end")
        self._alerte_ignore.insert(0, state.get("alerte_ignore", ""))
        self._alerte_prix_max.delete(0, "end")
        self._alerte_prix_max.insert(0, state.get("alerte_prix_max", ""))
        affinite = state.get("alerte_affinite") or "Toutes"
        self.menu_affinite_alerte.set(affinite if affinite in {"Toutes", "60+", "75+"} else "Toutes")

        self._set_etats_actifs(state.get("etats", []))

        requested_mode = bool(state.get("mode_liste", False))
        if requested_mode != bool(self._mode_liste):
            self._toggle_mode()

        pays = state.get("pays")
        if pays and pays in scraper.PAYS_DISPONIBLES and pays != self.menu_pays.get():
            self.menu_pays.set(pays)
            self._changer_pays(pays)

        restored_tri = state.get("tri")
        if restored_tri == "newest_first":
            restored_tri = "recent"
        self._ordre_tri = restored_tri if restored_tri in {"prix_asc", "prix_desc", "recent", "affinite"} else "prix_asc"
        self._rafraichir_boutons_tri()
        self._refresh_discord_alert_ui()
        self._refresh_search_summary()
        if lancer_recherche and self.champ_recherche.get().strip():
            self._lancer_recherche()

    def _sauvegarder_session_recherche(self, immediate: bool = False):
        if not self.settings.get("restaurer_derniere_recherche", True):
            if immediate:
                self.settings["last_search_state"] = {}
                data.sauvegarder_parametres(self.settings)
            return

        def _commit():
            self._session_job = None
            self.settings["last_search_state"] = self._capturer_etat_recherche()
            data.sauvegarder_parametres(self.settings)

        if immediate:
            _commit()
            return
        if self._session_job:
            try:
                self.after_cancel(self._session_job)
            except Exception:
                pass
        self._session_job = self.after(320, _commit)

    def _restaurer_session_recherche(self):
        if not self.settings.get("restaurer_derniere_recherche", True):
            self._refresh_search_summary()
            return
        state = self.settings.get("last_search_state", {})
        if isinstance(state, dict) and state:
            self._appliquer_etat_recherche(state, lancer_recherche=False)
            self._set_status("Session restaurée — appuie sur Rechercher ou F5 pour relancer.")
        self._refresh_search_summary()

    def _refresh_search_summary(self):
        if not hasattr(self, "lbl_search_summary_title"):
            return
        query = self.champ_recherche.get().strip() if hasattr(self, "champ_recherche") else ""
        display_title = query or self._titre_recherche or "Console marché"
        if len(display_title) > 68:
            display_title = display_title[:65] + "…"

        meta = []
        if hasattr(self, "menu_pays"):
            meta.append(self.menu_pays.get())
        prix_min = self._lire_prix(self.champ_prix_min) if hasattr(self, "champ_prix_min") else None
        prix_max = self._lire_prix(self.champ_prix_max) if hasattr(self, "champ_prix_max") else None
        if prix_min is not None or prix_max is not None:
            min_label = self._format_prix_resume(prix_min)
            max_label = self._format_prix_resume(prix_max)
            if min_label and max_label:
                meta.append(f"Budget {min_label} → {max_label}")
            elif min_label:
                meta.append(f"Min {min_label}")
            elif max_label:
                meta.append(f"Max {max_label}")
        if hasattr(self, "menu_categorie") and self.menu_categorie.get() != "— Toutes —":
            meta.append(self.menu_categorie.get())
        if hasattr(self, "menu_couleur") and self.menu_couleur.get() != "— Toutes —":
            meta.append(self.menu_couleur.get())
        if hasattr(self, "champ_vendeur") and self.champ_vendeur.get().strip():
            meta.append(f"Vendeur {self.champ_vendeur.get().strip()}")
        if self._etats_actifs:
            labels = [label for label, (_, ids) in self._btns_etat.items() if ids.issubset(self._etats_actifs)]
            if labels:
                meta.append(f"État {' / '.join(labels)}")
        meta.append(f"Tri {self._label_tri()}")
        meta.append("Vue liste" if self._mode_liste else "Vue grille")
        if self._annonces and not self._anim_job:
            meta.append(f"{len(self._annonces_filtrees(self._annonces))} visible(s)")

        active_discord = len(discord_alerts.list_alerts(active_only=True))
        hints = []
        if self._alerte_active:
            hints.append("Alerte locale active")
        if active_discord:
            hints.append(f"{active_discord} alerte(s) Discord active(s)")
        if self._last_results_at:
            hints.append(f"Dernière maj {self._last_results_at}")
        if not hints:
            hints.append("Ctrl+F recherche • F5 actualiser • Ctrl+L vue • Ctrl+S sauvegarder • Ctrl+K nettoyer")

        self.lbl_search_summary_title.configure(text=display_title)
        self.lbl_search_summary_meta.configure(
            text=" • ".join(meta) if meta else "Prêt pour une nouvelle recherche"
        )
        self.lbl_search_summary_hint.configure(text=" • ".join(hints))

    # ══ Autocomplete saisie intelligente ═════════════════════════════════════

    def _snapshot_recherche_courante(self) -> dict:
        prix_min = self._lire_prix(self.champ_prix_min)
        prix_max = self._lire_prix(self.champ_prix_max)
        cat_id, col_id, vendeur = self._get_filtres()
        query = self.champ_recherche.get().strip()
        baseline_ids = []
        if query and self._titre_recherche.strip().lower() == query.lower():
            baseline_ids = [str(getattr(a, "id", "")) for a in getattr(self, "_annonces", [])[:80]]
        return {
            "query": query,
            "pays": self.scraper.pays_actuel,
            "filters": {
                "price_min": prix_min,
                "search_price_max": prix_max,
                "category_id": cat_id,
                "color_id": col_id,
                "vendeur_id": vendeur,
            },
            "baseline_ids": baseline_ids,
        }

    def _refresh_discord_alert_ui(self):
        if not hasattr(self, "btn_discord_alert"):
            return
        snapshot = self._snapshot_recherche_courante()
        has_query = bool(snapshot.get("query"))
        all_alerts = discord_alerts.list_alerts(active_only=False)
        alert_count = len(all_alerts)
        existing = discord_alerts.find_alert(
            snapshot.get("query", ""),
            snapshot.get("pays", self.scraper.pays_actuel),
            snapshot.get("filters", {}),
        ) if has_query else None
        existing_active = bool(existing.get("active", True)) if existing else False
        self.btn_discord_alert.configure(
            state="normal" if has_query else "disabled",
            fg_color=C["alerte_on"] if existing_active else "transparent",
            border_color=C["alerte_on"] if existing else C["border"],
            text_color="#000000" if existing_active else (C["alerte_on"] if existing else (C["t1"] if has_query else C["t3"])),
        )
        if hasattr(self, "btn_discord_manage"):
            self.btn_discord_manage.configure(
                text=f"Alertes ({alert_count})" if alert_count else "Alertes",
                fg_color=C["border"] if alert_count else "transparent",
                border_color=C["alerte_on"] if alert_count else C["border"],
                text_color=C["t1"] if alert_count else C["t2"],
            )
        self._refresh_search_summary()

    def _ouvrir_alerte_discord(self):
        snapshot = self._snapshot_recherche_courante()
        if not snapshot.get("query"):
            messagebox.showwarning("Alerte Discord", "Entrez d'abord une recherche.")
            return
        FenetreAlerteDiscord(self, snapshot)

    def _ouvrir_gestion_alertes_discord(self):
        FenetreGestionAlertesDiscord(self)

    def _afficher_suggestions_initiales(self):
        if not hasattr(self, "champ_recherche"):
            return
        texte = self.champ_recherche.get().strip()
        if texte:
            return
        suggestions = recommandations.generer_requetes_recommandation(max_termes=6)
        if not suggestions:
            suggestions = recommandations.obtenir_suggestions_populaires(max_resultats=6)
        if suggestions:
            self._afficher_suggestions(suggestions[:6], "")

    def _on_recherche_key(self, event=None):
        """Déclenche l'autocomplete avec un léger délai pour éviter le spam."""
        self._refresh_discord_alert_ui()
        self._sauvegarder_session_recherche()
        if self._suggest_job:
            self.after_cancel(self._suggest_job)
        self._suggest_job = self.after(180, self._mettre_a_jour_suggestions)

    def _mettre_a_jour_suggestions(self):
        texte = self.champ_recherche.get().strip()
        if not texte:
            self._afficher_suggestions_initiales()
            return
        # Prend le dernier terme après virgule
        if "," in texte:
            prefixe = texte.split(",")[-1].strip()
        else:
            prefixe = texte
        suggestions = recommandations.obtenir_suggestions(prefixe, max_resultats=6)
        if not suggestions:
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
        ctk.CTkLabel(
            self._frame_suggestions,
            text="Suggestions",
            font=ctk.CTkFont(family=FONT, size=10, weight="bold"),
            text_color=C["t3"],
            anchor="w"
        ).pack(fill="x", padx=12, pady=(10, 4))
        for i, sug in enumerate(suggestions):
            btn = ctk.CTkButton(
                self._frame_suggestions,
                text=f"🔍  {sug}",
                height=34,
                corner_radius=10,
                fg_color=C["bg"],
                hover_color=C["accent_hover"],
                text_color=C["t1"],
                anchor="w",
                font=ctk.CTkFont(size=12),
                command=lambda s=sug: self._appliquer_suggestion(s, texte_complet)
            )
            btn.pack(fill="x", padx=12, pady=4)
        self._frame_suggestions.grid(
            row=4, column=0, padx=16, pady=(0, 8), sticky="ew"
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
        self._refresh_discord_alert_ui()
        self.champ_recherche.focus()

    def _cacher_suggestions(self):
        """Cache le panneau de suggestions."""
        if self._suggest_visible:
            self._frame_suggestions.grid_remove()
            self._suggest_visible = False

    # ══ Recommandations ═══════════════════════════════════════════════════════

    def _afficher_recommandations_accueil(self):
        """Affiche des annonces recommandées au lancement si historique dispo."""
        if self.champ_recherche.get().strip() or self._titre_recherche.strip():
            return
        termes = recommandations.generer_requetes_recommandation(max_termes=3)
        if not termes:
            return
        personnalise = recommandations.a_suffisamment_d_historique()
        self._set_status("✨ Chargement de vos recommandations…" if personnalise else "✨ Chargement des suggestions du moment…")
        self._vider_resultats()
        self.lbl_accueil.configure(
            text="✨  Recommandations personnalisées en cours…" if personnalise else "✨  Suggestions du moment en cours…",
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
            user_profile.enrich_annonces(tous)
            market_insights.enrich_annonces(tous)
            self.after(0, self._afficher_recommandations_resultats, tous, termes)
        except Exception:
            pass

    def _afficher_recommandations_resultats(self, annonces: list, termes: list):
        if not annonces:
            return
        label = ", ".join(termes[:2])
        self._ordre_tri = "affinite"
        self._annonces     = self._ordonner_annonces(annonces, self._ordre_tri)
        self._annonces_raw = list(annonces)
        self._page_courante = 1
        self._sel_vars      = []
        self._titre_recherche = f"Recommandations ({label})"
        self._last_results_at = datetime.datetime.now().strftime("%H:%M")
        self._rendre_cartes(self._annonces)
        self._set_status(f"✨ {len(annonces)} recommandation(s) basée(s) sur vos préférences")
        self.lbl_count.configure(text=f"{len(annonces)} reco.")
        self._rafraichir_boutons_tri()
        self.btn_dashboard.configure(state="normal")
        self.btn_export.configure(state="normal")
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()
        threading.Thread(target=data.enregistrer_historique,
                         args=(annonces,), daemon=True).start()

    # ══ Logique pays ══════════════════════════════════════════════════════════

    def _changer_pays(self, pays: str):
        self._set_status(f"🌍 Changement vers {pays}…")
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()
        threading.Thread(target=lambda: (
            self.scraper.set_pays(pays),
            self.after(0, lambda: self._set_status(
                f"✅ Connecté à {scraper.PAYS_DISPONIBLES[pays]['url']}")),
            self.after(0, self._refresh_discord_alert_ui)
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

    def _get_regles_alerte(self):
        exclure = [s.strip() for s in self._alerte_exclure.get().split(",") if s.strip()] if hasattr(self, "_alerte_exclure") else []
        ignore = [s.strip() for s in self._alerte_ignore.get().split(",") if s.strip()] if hasattr(self, "_alerte_ignore") else []
        max_price = self._lire_prix(self._alerte_prix_max) if hasattr(self, "_alerte_prix_max") else None
        affinity_map = {"Toutes": None, "60+": 60, "75+": 75}
        min_affinity = affinity_map.get(self.menu_affinite_alerte.get(), None) if hasattr(self, "menu_affinite_alerte") else None
        return exclure, ignore, max_price, min_affinity

    def _snapshot_alerte_locale(self) -> dict:
        snapshot = self._snapshot_recherche_courante()
        exclure, ignore, max_price, min_affinity = self._get_regles_alerte()
        snapshot["alert_rules"] = {
            "excluded_terms": exclure,
            "ignored_sellers": ignore,
            "max_price": max_price,
            "min_affinity": min_affinity,
        }
        query = snapshot.get("query", "").strip()
        if query and self._titre_recherche.strip().lower() == query.lower():
            baseline = [str(getattr(a, "id", "")) for a in getattr(self, "_annonces", [])[:80]]
            if baseline:
                snapshot["baseline_ids"] = baseline
        return snapshot

    def _rechercher_snapshot_surveillance(self, snapshot: dict, worker) -> list:
        filters = snapshot.get("filters", {})
        annonces = worker.rechercher_multi(
            snapshot.get("query", ""),
            prix_min=filters.get("price_min"),
            prix_max=filters.get("search_price_max"),
            order="newest_first",
            color_id=filters.get("color_id"),
            category_id=filters.get("category_id"),
            vendeur_id=filters.get("vendeur_id"),
            max_pages=1,
            par_page=36,
            use_cache=False,
        )
        if snapshot.get("alert_rules"):
            user_profile.enrich_annonces(annonces)
            market_insights.enrich_annonces(annonces)
            annonces, _ = market_insights.filter_alert_results(
                annonces,
                excluded_terms=snapshot["alert_rules"].get("excluded_terms"),
                ignored_sellers=snapshot["alert_rules"].get("ignored_sellers"),
                max_price=snapshot["alert_rules"].get("max_price"),
                min_affinity=snapshot["alert_rules"].get("min_affinity"),
            )
        return annonces

    def _planifier_surveillance_discord(self, delay_ms: int = 30_000):
        if self._discord_job:
            try:
                self.after_cancel(self._discord_job)
            except Exception:
                pass
            self._discord_job = None
        if not discord_alerts.list_alerts(active_only=True):
            self._refresh_discord_alert_ui()
            return
        self._discord_job = self.after(delay_ms, self._tick_surveillance_discord)

    def _tick_surveillance_discord(self):
        if self._discord_poll_running:
            self._planifier_surveillance_discord(10_000)
            return
        self._discord_poll_running = True
        threading.Thread(target=self._thread_surveillance_discord, daemon=True).start()

    def _thread_surveillance_discord(self):
        total_sent = 0
        labels = []
        workers = {}
        try:
            for alert in discord_alerts.list_alerts(active_only=True):
                pays = alert.get("pays", self.scraper.pays_actuel)
                worker = workers.get(pays)
                if worker is None:
                    worker = scraper.VintedScraper(delai_entre_requetes=0.25)
                    if pays != worker.pays_actuel:
                        worker.set_pays(pays)
                    workers[pays] = worker
                snapshot = {
                    "query": alert.get("query", ""),
                    "pays": pays,
                    "filters": alert.get("filters", {}),
                }
                annonces = self._rechercher_snapshot_surveillance(snapshot, worker)
                current_ids = [str(getattr(a, "id", "")) for a in annonces[:80]]
                previous_ids = set(alert.get("last_seen_ids", []))
                if not alert.get("baseline_ready") or not previous_ids:
                    discord_alerts.update_runtime(alert.get("id", ""), current_ids, baseline_ready=True)
                    continue
                nouvelles = [a for a in annonces if str(getattr(a, "id", "")) not in previous_ids]
                sent_now = 0
                for annonce in reversed(nouvelles[:10]):
                    if discord_alerts.send_annonce(alert, annonce):
                        sent_now += 1
                discord_alerts.update_runtime(alert.get("id", ""), current_ids, baseline_ready=True)
                if sent_now:
                    total_sent += sent_now
                    labels.append(alert.get("query", "Recherche"))
        except Exception:
            pass
        finally:
            for worker in workers.values():
                try:
                    worker.close()
                except Exception:
                    pass
            _safe_after(self, lambda t=total_sent, l=labels: self._finaliser_surveillance_discord(t, l), scheduler=self)

    def _finaliser_surveillance_discord(self, total_sent: int, labels: list[str]):
        self._discord_poll_running = False
        if total_sent:
            jouer_son_alerte()
            label = ", ".join(labels[:2]) if labels else "vos alertes"
            envoyer_toast("Alerte Discord", f"{total_sent} nouvelle(s) annonce(s) envoyée(s) pour {label}.")
            BannerNotif(self, "Alerte Discord", f"{total_sent} annonce(s) récente(s) envoyée(s) sur Discord.")
            self._last_results_at = datetime.datetime.now().strftime("%H:%M")
        self._refresh_search_summary()
        self._planifier_surveillance_discord()

    def _lancer_recherche(self, silent=False):
        mots = self.champ_recherche.get().strip()
        self._refresh_discord_alert_ui()
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
        self._sauvegarder_session_recherche()
        self._demarrer_animation()
        prix_min = self._lire_prix(self.champ_prix_min)
        prix_max = self._lire_prix(self.champ_prix_max)
        cat_id, col_id, vendeur = self._get_filtres()
        if not silent:
            user_profile.record_search(
                [t.strip() for t in mots.split(",") if t.strip()],
                {
                    "price_min": prix_min,
                    "price_max": prix_max,
                    "category_id": cat_id,
                    "color_id": col_id,
                    "vendeur_id": vendeur,
                    "pays": self.scraper.pays_actuel,
                },
            )
        threading.Thread(target=self._thread_recherche,
                         args=(mots, prix_min, prix_max, cat_id, col_id, vendeur, silent),
                         daemon=True).start()

    def _thread_recherche(self, mots, prix_min, prix_max, cat_id, col_id, vendeur, silent=False):
        try:
            annonces = self.scraper.rechercher_multi(
                mots, prix_min, prix_max,
                category_id=cat_id, color_id=col_id, vendeur_id=vendeur)
            user_profile.enrich_annonces(annonces)
            market_insights.enrich_annonces(annonces)
            self.after(0, self._afficher_resultats, annonces, len(annonces), silent)
        except (ConnectionError, ValueError) as e:
            self.after(0, self._afficher_erreur, str(e))
        except Exception as e:
            self.after(0, self._afficher_erreur, f"Erreur inattendue : {e}")

    def _afficher_resultats(self, annonces, total_brut=0, silent=False):
        self._arreter_animation()
        self._set_en_cours(False)
        self._refresh_discord_alert_ui()
        if silent:
            exclure, ignore, max_price, min_affinity = self._get_regles_alerte()
            annonces, _ = market_insights.filter_alert_results(
                annonces,
                excluded_terms=exclure,
                ignored_sellers=ignore,
                max_price=max_price,
                min_affinity=min_affinity,
            )
        nouvelles_ids = set()
        if self._alerte_ids:
            nouvelles_ids = {str(a.id) for a in annonces} - self._alerte_ids
            if nouvelles_ids and silent:
                nb_new = len(nouvelles_ids)
                envoyer_toast("Nouvelles annonces !", f"{nb_new} nouvelle(s) annonce(s).")
                BannerNotif(self, "Nouvelles annonces !", f"{nb_new} nouvelle(s) trouvée(s).")
        self._alerte_ids  = {str(a.id) for a in annonces}
        self._verifier_baisse_favoris(annonces)
        self._annonces_raw = list(annonces)
        self._ordre_tri   = self._ordre_tri if self._ordre_tri in {"prix_asc", "prix_desc", "recent", "affinite"} else "prix_asc"
        self._annonces    = self._ordonner_annonces(annonces, self._ordre_tri)
        self._page_courante = 1
        self._sel_vars    = []
        if not annonces:
            self._set_status("⚠️  Aucun résultat trouvé.")
            self._last_results_at = datetime.datetime.now().strftime("%H:%M")
            self._refresh_search_summary()
            self.lbl_accueil.configure(
                text="😔\n\nAucun résultat.\n\nEssayez des termes différents.",
                font=ctk.CTkFont(size=14))
            self.lbl_accueil.grid(row=0, column=0, columnspan=self.COLONNES, pady=100)
            self.lbl_stats.configure(text="")
            self.btn_dashboard.configure(state="disabled")
            self.btn_export.configure(state="disabled")
            return
        self._last_results_at = datetime.datetime.now().strftime("%H:%M")
        self._rendre_cartes(self._annonces, nouvelles_ids)
        self._set_status(f"Recherche en ligne  ·  {len(annonces)} résultat(s)")
        self.lbl_count.configure(text=f"{len(annonces)} résultat(s)")
        self.lbl_stats.configure(text=f"{len(annonces)} annonces")
        self._rafraichir_boutons_tri()
        self.btn_dashboard.configure(state="normal")
        self.btn_export.configure(state="normal")
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()
        threading.Thread(target=data.enregistrer_historique,
                         args=(annonces,), daemon=True).start()

    def _rendre_cartes(self, annonces, nouvelles_ids=None):
        self._vider_resultats()
        if self._render_job:
            self.after_cancel(self._render_job)
            self._render_job = None
        self._render_version += 1
        render_version = self._render_version
        nouvelles_ids = nouvelles_ids or set()
        toutes = self._annonces_filtrees(annonces)
        if not toutes:
            self.bar_pagination.grid_remove()
            return
        nb_total  = len(toutes)
        nb_pages  = max(1, (nb_total + self.articles_par_page - 1) // self.articles_par_page)
        self._page_courante = max(1, min(self._page_courante, nb_pages))
        debut     = (self._page_courante - 1) * self.articles_par_page
        affichees = toutes[debut: debut + self.articles_par_page]
        self._sel_vars = [tk.BooleanVar() for _ in affichees]
        cols = max(1, getattr(self, "_derniere_cols", self.COLONNES))
        BATCH = max(cols * 3, 6) if not self._mode_liste else 8

        def _render_batch(start: int):
            if render_version != self._render_version or not _widget_exists(self.zone_scroll):
                return
            fin = min(start + BATCH, len(affichees))
            for idx in range(start, fin):
                a    = affichees[idx]
                sv   = self._sel_vars[idx]
                nouv = str(a.id) in nouvelles_ids
                if self._mode_liste:
                    widget = LigneAnnonce(self.zone_scroll, a, app=self,
                                         nouveau=nouv, selection_var=sv)
                    widget.grid(row=idx, column=0, columnspan=cols,
                                padx=10, pady=4, sticky="ew")
                else:
                    ligne, col = divmod(idx, cols)
                    widget = CarteAnnonce(self.zone_scroll, a, app=self,
                                         nouveau=nouv, selection_var=sv)
                    widget.grid(row=ligne, column=col, padx=10, pady=10, sticky="nsew")
                self._bind_scroll_recursif(widget)
            if fin < len(affichees):
                self._render_job = self.after(12, _render_batch, fin)
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
        debut = (self._page_courante - 1) * self.articles_par_page + 1
        fin   = min(self._page_courante * self.articles_par_page, nb_total)
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
        nb_pages = max(1, (len(toutes) + self.articles_par_page - 1) // self.articles_par_page)
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
            for col in range(max(self.COLONNES, getattr(self, "_derniere_cols", self.COLONNES))):
                self.zone_scroll.grid_columnconfigure(col, weight=0, minsize=0)
            self.zone_scroll.grid_columnconfigure(0, weight=1)
        else:
            self.btn_mode.configure(text="☰ Liste", fg_color=C["border"], text_color=C["t2"])
            for col in range(max(self.COLONNES, getattr(self, "_derniere_cols", self.COLONNES))):
                self.zone_scroll.grid_columnconfigure(col, weight=1, uniform="col")
        self._maj_layout()
        if self._annonces:
            self._page_courante = 1
            self._rendre_cartes(self._annonces)
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()

    # ── Comparateur ────────────────────────────────────────────────────────────

    def _maj_bouton_comparateur(self):
        nb = sum(1 for v in self._sel_vars if v.get())
        if nb >= 2:
            self.btn_comparer.configure(text=f"⚖️ Comparer ({nb})", state="normal",
                                        fg_color=C["accent"], text_color="#000")
        else:
            self.btn_comparer.configure(text=f"⚖️ Comparer ({nb})", state="disabled",
                                        fg_color=C["border"], text_color=C["t3"])

        if hasattr(self, "btn_actions"):
            self.btn_actions.configure(
                text=f"Actions ({nb})",
                state="normal" if nb else "disabled",
                fg_color=C["border"] if nb else "transparent",
                text_color=C["t1"] if nb else C["t3"])

    def _ouvrir_comparateur(self):
        toutes    = self._annonces_filtrees(self._annonces)
        debut     = (self._page_courante - 1) * self.articles_par_page
        affichees = toutes[debut: debut + self.articles_par_page]
        selection = [affichees[i] for i, v in enumerate(self._sel_vars)
                     if v.get() and i < len(affichees)]
        if len(selection) < 2:
            messagebox.showinfo("Comparateur", "Sélectionnez au moins 2 annonces.")
            return
        FenetreComparateur(self, selection[:3])

    def _selection_courante(self):
        toutes = self._annonces_filtrees(self._annonces)
        debut = (self._page_courante - 1) * self.articles_par_page
        affichees = toutes[debut: debut + self.articles_par_page]
        return [affichees[i] for i, var in enumerate(self._sel_vars) if var.get() and i < len(affichees)]

    def _ouvrir_actions_masse(self):
        selection = self._selection_courante()
        if not selection:
            messagebox.showinfo("Actions", "SÃ©lectionnez au moins une annonce.")
            return
        menu = Menu(self, tearoff=0, bg="#1a2333", fg="#f0f4f8",
                    activebackground=C["accent"], activeforeground="#000000",
                    font=("Segoe UI", 11), bd=0, relief="flat")
        menu.add_command(label="Ajouter la sÃ©lection aux favoris", command=self._ajouter_selection_favoris)
        menu.add_command(label="Analyser / cibler la sÃ©lection", command=self._cibler_selection)
        menu.add_command(label="Comparer la sÃ©lection sur le web", command=self._comparer_selection_web)
        menu.add_command(label="Exporter la sÃ©lection en CSV", command=self._exporter_selection_csv)
        try:
            x = self.btn_actions.winfo_rootx()
            y = self.btn_actions.winfo_rooty() + self.btn_actions.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _ouvrir_accueil_intelligent(self):
        FenetreAccueilIntelligent(self, self._titre_recherche)

    def _ouvrir_profil_utilisateur(self):
        FenetreProfilUtilisateur(self)

    def _ouvrir_parametres(self):
        FenetreParametres(self)

    def _ouvrir_analyse_vendeur(self, annonce):
        user_profile.record_annonce_event("seller_analysis", annonce)
        FenetreVendeur(self, annonce, getattr(self, "_annonces", []))

    def _ouvrir_apercu(self, annonce):
        user_profile.record_annonce_event("open_preview", annonce)
        FenetreApercu(self, annonce)

    def _ouvrir_annonce(self, annonce):
        user_profile.record_annonce_event("open_link", annonce)
        webbrowser.open(annonce.url)

    def _ouvrir_comparateur_prix_annonce(self, annonce):
        user_profile.record_annonce_event("compare_open", annonce)
        FenetreComparateurPrix(self, annonce)

    def _toggle_favori_annonce(self, annonce) -> bool:
        ajout = data.toggle_favori(annonce)
        if ajout:
            user_profile.record_annonce_event("favorite_add", annonce)
        self.rafraichir_favoris()
        return ajout

    def _ajouter_selection_favoris(self):
        selection = self._selection_courante()
        ajoutes = 0
        for annonce in selection:
            if self._toggle_favori_annonce(annonce):
                ajoutes += 1
        self._set_status(f"{ajoutes} favori(s) ajoutÃ©(s) depuis la sÃ©lection.")
        self._maj_bouton_comparateur()

    def _cibler_selection(self):
        selection = self._selection_courante()
        if not selection:
            return
        FenetreAnalyse(self, selection[0], getattr(self, "_annonces", []))
        if len(selection) > 1:
            self._set_status("Analyse ouverte pour la premiÃ¨re annonce sÃ©lectionnÃ©e.")

    def _comparer_selection_web(self):
        selection = self._selection_courante()
        if not selection:
            return
        for annonce in selection[:5]:
            user_profile.record_annonce_event("compare_open", annonce)
            comparateur_prix.ouvrir_comparaison(
                annonce,
                plateformes_selectionnees=comparateur_prix.plateformes_recommandees(annonce)[:4],
            )
        self._set_status(f"Comparaison web lancÃ©e pour {min(len(selection), 5)} annonce(s).")

    def _exporter_selection_csv(self):
        selection = self._selection_courante()
        if not selection:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Tous", "*.*")],
            initialfile="vinted_selection.csv")
        if path:
            threading.Thread(target=scraper.VintedScraper.exporter_csv,
                             args=(selection, path), daemon=True).start()
            self._set_status(f"SÃ©lection exportÃ©e : {os.path.basename(path)}")

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
        FenetreDashboard(self, market_insights.build_dashboard_stats(self._annonces), self._titre_recherche)

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
        if ids.issubset(self._etats_actifs):
            self._etats_actifs -= ids
        else:
            self._etats_actifs |= ids
        self._sync_etat_buttons()
        if self._annonces:
            self._page_courante = 1
            self._rendre_cartes(self._annonces)
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()

    def _trier(self, ordre):
        self._ordre_tri     = ordre
        self._rafraichir_boutons_tri()
        if self._annonces:
            self._page_courante = 1
            source = getattr(self, "_annonces_raw", self._annonces)
            self._annonces = self._ordonner_annonces(source, ordre)
            self._rendre_cartes(self._annonces)
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()

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
            pays=self.menu_pays.get(),
            ordre=self._ordre_tri,
            categorie=self.menu_categorie.get() if self.menu_categorie.get() != "— Toutes —" else None,
            couleur=self.menu_couleur.get() if self.menu_couleur.get() != "— Toutes —" else None,
            vendeur=self.champ_vendeur.get().strip() or None,
            etats=sorted(self._etats_actifs),
            mode_liste=self._mode_liste)
        self._rafraichir_sauvegardes()
        self._set_status(f"✅  Recherche « {nom.strip()} » sauvegardée.")

    def _charger_recherche(self, rec: dict):
        state = {
            "query": rec.get("mots_cles", ""),
            "pays": rec.get("pays", self.menu_pays.get()),
            "price_min": "" if rec.get("prix_min") is None else str(rec.get("prix_min")),
            "price_max": "" if rec.get("prix_max") is None else str(rec.get("prix_max")),
            "categorie": rec.get("categorie") or "— Toutes —",
            "couleur": rec.get("couleur") or "— Toutes —",
            "vendeur": rec.get("vendeur", ""),
            "tri": "recent" if rec.get("ordre") == "newest_first" else rec.get("ordre", "prix_asc"),
            "mode_liste": bool(rec.get("mode_liste", self._mode_liste)),
            "etats": rec.get("etats", []),
            "alerte_intervalle": self.menu_intervalle.get(),
            "alerte_exclure": self._alerte_exclure.get().strip(),
            "alerte_ignore": self._alerte_ignore.get().strip(),
            "alerte_prix_max": self._alerte_prix_max.get().strip(),
            "alerte_affinite": self.menu_affinite_alerte.get(),
        }
        self._appliquer_etat_recherche(state, lancer_recherche=True)

    def _reinitialiser_recherche(self):
        self.champ_recherche.delete(0, "end")
        self.champ_prix_min.delete(0, "end")
        self.champ_prix_max.delete(0, "end")
        self.champ_vendeur.delete(0, "end")
        self.menu_categorie.set("— Toutes —")
        self.menu_couleur.set("— Toutes —")
        self.menu_affinite_alerte.set("Toutes")
        self.menu_intervalle.set("30 sec")
        self._alerte_exclure.delete(0, "end")
        self._alerte_ignore.delete(0, "end")
        self._alerte_prix_max.delete(0, "end")
        self._set_etats_actifs(set())
        self._ordre_tri = "prix_asc"
        self._rafraichir_boutons_tri()
        self._titre_recherche = ""
        self._last_results_at = None
        if self._alerte_active:
            self._arreter_alerte()
        self._cacher_suggestions()
        self._vider_resultats()
        self._set_status("Filtres réinitialisés — prêt pour une nouvelle recherche.")
        self._refresh_discord_alert_ui()
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()
        self.after(80, self._afficher_suggestions_initiales)

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
        self._alerte_config = self._snapshot_alerte_locale()
        self._alerte_ids    = set(self._alerte_config.get("baseline_ids", []))
        self.btn_alerte.configure(fg_color=C["alerte_on"], text_color="#000",
                                  text="🔔 Alerte active — Arrêter")
        self.lbl_alerte_status.configure(text_color=C["alerte_on"])
        if not self._alerte_ids:
            self._tick_alerte()
        self._planifier_prochain_tick()
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()

    def _planifier_prochain_tick(self):
        raw = self.menu_intervalle.get().strip().lower()
        if "sec" in raw:
            try:
                seconds = int(raw.replace("sec", "").strip())
            except ValueError:
                seconds = 30
            label = f"● Prochaine vérif. dans {seconds} sec"
        else:
            try:
                minutes = int(raw.replace("min", "").strip())
            except ValueError:
                minutes = 1
            seconds = minutes * 60
            label = f"● Prochaine vérif. dans {minutes} min"
        self.lbl_alerte_status.configure(text=label)
        self._alerte_job = self.after(seconds * 1000, self._tick_alerte)

    def _tick_alerte(self):
        if not self._alerte_active or not self._alerte_config:
            return
        if self._alerte_poll_running:
            return
        self._alerte_poll_running = True
        threading.Thread(target=self._thread_verifier_alerte_locale, daemon=True).start()
        self._planifier_prochain_tick()

    def _thread_verifier_alerte_locale(self):
        snapshot = dict(self._alerte_config or {})
        current_ids = []
        nouvelles = []
        worker = scraper.VintedScraper(delai_entre_requetes=0.25)
        try:
            pays = snapshot.get("pays", self.scraper.pays_actuel)
            if pays != worker.pays_actuel:
                worker.set_pays(pays)
            annonces = self._rechercher_snapshot_surveillance(snapshot, worker)
            current_ids = [str(getattr(a, "id", "")) for a in annonces[:80]]
            nouvelles = [a for a in annonces if str(getattr(a, "id", "")) not in self._alerte_ids]
        except Exception:
            pass
        finally:
            try:
                worker.close()
            except Exception:
                pass
            _safe_after(self, lambda ids=current_ids, ann=nouvelles: self._finaliser_tick_alerte_locale(ids, ann), scheduler=self)

    def _finaliser_tick_alerte_locale(self, current_ids: list[str], nouvelles: list):
        self._alerte_poll_running = False
        if not self._alerte_active:
            return
        if current_ids:
            self._alerte_ids = set(current_ids)
        if nouvelles:
            nb_new = len(nouvelles)
            jouer_son_alerte()
            envoyer_toast("Nouvelles annonces !", f"{nb_new} nouvelle(s) annonce(s).")
            BannerNotif(self, "Nouvelles annonces !", f"{nb_new} nouvelle(s) trouvée(s).")

    def _arreter_alerte(self):
        self._alerte_active = False
        self._alerte_config = None
        self._alerte_poll_running = False
        if self._alerte_job:
            self.after_cancel(self._alerte_job)
            self._alerte_job = None
        self.btn_alerte.configure(fg_color=C["border"], text_color=C["t1"],
                                  text="Activer l'alerte")
        self.lbl_alerte_status.configure(text="● Inactive", text_color=C["t3"])
        self._refresh_search_summary()
        self._sauvegarder_session_recherche()

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
        if hasattr(self, "btn_actions"):
            self.btn_actions.configure(text="Actions (0)", state="disabled",
                                       fg_color="transparent", text_color=C["t3"])
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
                                      text="Recherche…" if v else "  🔍  Rechercher  ")

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
