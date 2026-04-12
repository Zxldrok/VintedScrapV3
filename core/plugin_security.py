"""
core/plugin_security.py — Validation et sandbox des extensions
===============================================================
Vérifie les manifests, liste blanche d'imports, et hash d'intégrité.
"""

from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from typing import Any

# ── Imports autorisés dans les plugins ───────────────────────────────────────
IMPORTS_AUTORISES = {
    # stdlib safe
    "os.path", "pathlib", "json", "re", "datetime", "time", "math",
    "collections", "itertools", "functools", "typing", "dataclasses",
    "threading", "queue", "copy", "enum", "uuid", "base64", "hashlib",
    "urllib.parse",
    # tiers autorisés
    "requests", "customtkinter", "tkinter", "PIL", "tkinter.messagebox",
}

# ── Patterns dangereux interdits ─────────────────────────────────────────────
PATTERNS_INTERDITS = [
    r"\bsubprocess\b", r"\bos\.system\b", r"\bos\.popen\b",
    r"\beval\s*\(", r"\bexec\s*\(",
    r"\b__import__\s*\(", r"\bimportlib\.import_module\b",
    r"\bopen\s*\(.*['\"]w['\"]",      # écriture fichier hors data_dir
    r"\bsocket\b", r"\bpickle\b",
    r"\bctypes\b", r"\bcffi\b",
]

SCHEMA_MANIFEST = {
    "required": ["id", "name", "version", "author", "description",
                 "min_app_version", "hooks", "permissions"],
    "version_pattern": r"^\d+\.\d+\.\d+$",
    "id_pattern":      r"^[a-z0-9_]{3,40}$",
    "max_permissions": 6,
}


class PluginSecurityError(Exception):
    pass


def valider_manifest(manifest: dict, plugin_dir: Path) -> None:
    """Lève PluginSecurityError si le manifest est invalide ou suspect."""
    for key in SCHEMA_MANIFEST["required"]:
        if key not in manifest:
            raise PluginSecurityError(f"Champ obligatoire manquant : '{key}'")

    pid = manifest["id"]
    if not re.match(SCHEMA_MANIFEST["id_pattern"], pid):
        raise PluginSecurityError(f"ID invalide : '{pid}' (lettres minuscules, chiffres, _)")

    for v_field in ("version", "min_app_version"):
        if not re.match(SCHEMA_MANIFEST["version_pattern"], manifest[v_field]):
            raise PluginSecurityError(f"Format de version invalide : '{manifest[v_field]}'")

    from core.plugin_api import PERMISSIONS, HOOKS
    for p in manifest.get("permissions", []):
        if p not in PERMISSIONS:
            raise PluginSecurityError(f"Permission inconnue : '{p}'")
    if len(manifest["permissions"]) > SCHEMA_MANIFEST["max_permissions"]:
        raise PluginSecurityError("Trop de permissions déclarées (max 6)")

    for h in manifest.get("hooks", []):
        if h not in HOOKS:
            raise PluginSecurityError(f"Hook inconnu déclaré : '{h}'")


def valider_code(plugin_py: Path) -> None:
    """Analyse statique du code Python du plugin."""
    source = plugin_py.read_text(encoding="utf-8")

    for pattern in PATTERNS_INTERDITS:
        if re.search(pattern, source):
            raise PluginSecurityError(
                f"Pattern interdit détecté dans le code : {pattern}")

    # Vérifie que la classe PluginBase est bien héritée
    if "PluginBase" not in source:
        raise PluginSecurityError("Le plugin doit hériter de PluginBase.")


def calculer_hash(plugin_dir: Path) -> str:
    """Calcule un SHA-256 combiné manifest + plugin.py pour détecter les modifications."""
    h = hashlib.sha256()
    for fname in ("manifest.json", "plugin.py"):
        fp = plugin_dir / fname
        if fp.exists():
            h.update(fp.read_bytes())
    return h.hexdigest()


def verifier_integrite(plugin_dir: Path, hash_attendu: str) -> bool:
    return calculer_hash(plugin_dir) == hash_attendu


def version_compatible(plugin_min: str, app_version: str) -> bool:
    """Vérifie que app_version >= plugin_min (comparaison sémantique)."""
    def to_tuple(v): return tuple(int(x) for x in v.split("."))
    try:
        return to_tuple(app_version) >= to_tuple(plugin_min)
    except Exception:
        return False
