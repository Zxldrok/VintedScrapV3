"""
core/ui_utils.py — Utilitaires pour une UI Tkinter stable et fluide
====================================================================
Problèmes traités :
  1. Flood d'events <Configure> → debounce
  2. Animations sidebar empilées → cancellation guard
  3. Appels UI depuis threads → safe_after
  4. Crash sur widgets détruits → winfo_exists guard
  5. Fullscreen glitch → lock layout pendant transition
"""

from __future__ import annotations
import functools
import threading
from typing import Callable, Any


# ══ 1. Debounce ═══════════════════════════════════════════════════════════════

class Debouncer:
    """
    Garantit qu'une fonction ne s'exécute qu'une seule fois après
    un délai d'inactivité, même si appelée en rafale.

    Usage dans AppVinted.__init__ :
        self._layout_debouncer = Debouncer(self, delay_ms=120)
    Usage dans _maj_layout :
        self._layout_debouncer.call(self._maj_layout_impl)
    """

    def __init__(self, widget, delay_ms: int = 120):
        self._widget   = widget
        self._delay    = delay_ms
        self._job      = None

    def call(self, fn: Callable, *args, **kwargs) -> None:
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self._job = self._widget.after(
            self._delay, lambda: self._run(fn, args, kwargs))

    def cancel(self) -> None:
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _run(self, fn, args, kwargs):
        self._job = None
        try:
            fn(*args, **kwargs)
        except Exception as e:
            import logging
            logging.getLogger("ui_utils").error(f"Debouncer callback error: {e}")


# ══ 2. Animation guard ════════════════════════════════════════════════════════

class SmoothAnimator:
    """
    Anime une valeur entière d'une origine à une cible avec easing,
    sans jamais empiler plusieurs animations simultanées.

    Usage :
        self._sb_anim = SmoothAnimator(self, fps=60)
        self._sb_anim.start(
            get_fn  = lambda: self._sb_frame.winfo_width(),
            set_fn  = lambda v: self._sb_frame.configure(width=v),
            target  = 340,
            on_done = lambda: self._maj_contenu_sidebar(False)
        )
    """

    def __init__(self, widget, fps: int = 60):
        self._widget  = widget
        self._delay   = max(8, 1000 // fps)
        self._job     = None
        self._target  = None

    def start(self, get_fn: Callable[[], int], set_fn: Callable[[int], None],
              target: int, on_done: Callable = None, speed: float = 0.25) -> None:
        """Lance (ou redirige) l'animation vers `target`."""
        self._cancel()
        self._target = target
        self._step(get_fn, set_fn, target, on_done, speed)

    def _cancel(self):
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _step(self, get_fn, set_fn, target, on_done, speed):
        try:
            current = get_fn()
        except Exception:
            return
        delta = target - current
        if abs(delta) <= 1:
            set_fn(target)
            if on_done:
                try: on_done()
                except Exception: pass
            return
        # Easing exponentiel : converge rapidement, finit en douceur
        step = max(1, int(abs(delta) * speed))
        new_val = current + (step if delta > 0 else -step)
        try:
            set_fn(new_val)
        except Exception:
            return
        self._job = self._widget.after(
            self._delay,
            lambda: self._step(get_fn, set_fn, target, on_done, speed))


# ══ 3. Thread-safe UI calls ═══════════════════════════════════════════════════

def safe_after(widget, fn: Callable, *args, delay: int = 0, **kwargs) -> None:
    """
    Planifie fn(*args, **kwargs) sur le thread principal Tkinter.
    Silencieux si le widget est déjà détruit.
    """
    def _call():
        try:
            if widget.winfo_exists():
                fn(*args, **kwargs)
        except Exception as e:
            import logging
            logging.getLogger("ui_utils").warning(f"safe_after error: {e}")
    try:
        widget.after(delay, _call)
    except Exception:
        pass


def ui_thread_only(fn: Callable) -> Callable:
    """
    Décorateur : si appelé depuis un thread secondaire, repousse
    l'exécution sur le thread principal via `self.after(0, ...)`.
    Requiert que le premier argument soit un widget Tkinter (`self`).
    """
    @functools.wraps(fn)
    def wrapper(self_widget, *args, **kwargs):
        if threading.current_thread() is threading.main_thread():
            return fn(self_widget, *args, **kwargs)
        try:
            self_widget.after(0, lambda: fn(self_widget, *args, **kwargs))
        except Exception:
            pass
    return wrapper


# ══ 4. Widget safety guard ════════════════════════════════════════════════════

def widget_exists(widget) -> bool:
    """Vérifie si un widget Tkinter est encore valide, sans lever d'exception."""
    try:
        return bool(widget.winfo_exists())
    except Exception:
        return False


def safe_configure(widget, **kwargs) -> bool:
    """Configure un widget seulement s'il existe encore. Retourne True si OK."""
    try:
        if widget.winfo_exists():
            widget.configure(**kwargs)
            return True
    except Exception:
        pass
    return False


# ══ 5. Resize / fullscreen lock ═══════════════════════════════════════════════

class ResizeLock:
    """
    Bloque temporairement les callbacks de redimensionnement
    pendant les transitions fullscreen / restore.

    Usage :
        self._resize_lock = ResizeLock()
        # Dans le handler fullscreen :
        with self._resize_lock:
            self.attributes("-fullscreen", True)
    """

    def __init__(self):
        self._locked = False

    @property
    def locked(self) -> bool:
        return self._locked

    def __enter__(self):
        self._locked = True
        return self

    def __exit__(self, *_):
        self._locked = False
