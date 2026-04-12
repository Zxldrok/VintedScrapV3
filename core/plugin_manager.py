"""
core/plugin_manager.py — Chargeur dynamique des extensions VintedScrap
=======================================================================
Responsabilités :
  - Découverte et chargement des plugins depuis plugins/
  - Validation sécurité (manifest + code)
  - Registre d'état (activé / désactivé / erreur)
  - Dispatch des hooks vers les plugins actifs
  - Installation / désinstallation
"""

from __future__ import annotations
import importlib.util, json, logging, shutil, sys, threading, zipfile
from pathlib import Path
from typing import Any, Callable

from core.plugin_api import PluginAPI, HOOKS
from core.plugin_security import (
    valider_manifest, valider_code, calculer_hash,
    verifier_integrite, version_compatible, PluginSecurityError,
)

APP_VERSION = "3.1.0"
PLUGINS_DIR = Path(__file__).parent.parent / "plugins"
REGISTRY_FILE = Path(__file__).parent.parent / "data" / "plugins_registry.json"

log = logging.getLogger("plugin_manager")


class PluginRecord:
    """Représente un plugin dans le registre."""
    def __init__(self, manifest: dict, enabled: bool = True,
                 hash_: str = "", error: str = ""):
        self.manifest = manifest
        self.enabled  = enabled
        self.hash     = hash_
        self.error    = error
        self.instance = None     # instance de PluginBase
        self.api: PluginAPI | None = None

    @property
    def id(self): return self.manifest["id"]
    @property
    def name(self): return self.manifest["name"]
    @property
    def version(self): return self.manifest["version"]


class PluginManager:
    def __init__(self, app_ref=None):
        self._app     = app_ref
        self._plugins: dict[str, PluginRecord] = {}
        PLUGINS_DIR.mkdir(exist_ok=True)
        (PLUGINS_DIR / "__init__.py").touch(exist_ok=True)

    # ══ Cycle de vie ══════════════════════════════════════════════════════════

    def charger_tous(self) -> None:
        """Découvre et charge tous les plugins du dossier plugins/."""
        registry = self._lire_registry()
        for plugin_dir in sorted(PLUGINS_DIR.iterdir()):
            if not plugin_dir.is_dir() or plugin_dir.name.startswith("_"):
                continue
            self._charger_plugin(plugin_dir, registry)
        self._sauver_registry()

    def _charger_plugin(self, plugin_dir: Path, registry: dict) -> None:
        manifest_path = plugin_dir / "manifest.json"
        plugin_py     = plugin_dir / "plugin.py"
        if not manifest_path.exists() or not plugin_py.exists():
            return

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            valider_manifest(manifest, plugin_dir)
            valider_code(plugin_py)

            pid = manifest["id"]
            saved = registry.get(pid, {})
            enabled = saved.get("enabled", True)

            # Vérification intégrité si déjà connu
            current_hash = calculer_hash(plugin_dir)
            if pid in registry and registry[pid].get("hash"):
                if not verifier_integrite(plugin_dir, registry[pid]["hash"]):
                    log.warning(f"[{pid}] Hash modifié — rechargement sécurisé.")

            if not version_compatible(manifest["min_app_version"], APP_VERSION):
                raise PluginSecurityError(
                    f"Requiert app >= {manifest['min_app_version']}, actuelle = {APP_VERSION}")

            record = PluginRecord(manifest, enabled, current_hash)
            self._plugins[pid] = record

            if enabled:
                self._activer(record, plugin_dir, plugin_py)

        except Exception as e:
            try:
                pid = manifest.get("id", plugin_dir.name)
            except NameError:
                pid = plugin_dir.name
            log.error(f"[{pid}] Échec chargement : {e}")
            if pid not in self._plugins:
                self._plugins[pid] = PluginRecord(
                    {"id": pid, "name": pid, "version": "?", "author": "?",
                     "description": "", "min_app_version": "0.0.0",
                     "hooks": [], "permissions": []},
                    enabled=False, error=str(e))

    def _activer(self, record: PluginRecord, plugin_dir: Path, plugin_py: Path):
        """Importe et instancie le plugin de façon isolée."""
        spec = importlib.util.spec_from_file_location(
            f"plugins.{record.id}", plugin_py)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        perms    = record.manifest.get("permissions", [])
        toast_fn = getattr(self._app, "_toast_fn", None)
        api      = PluginAPI(record.id, perms, self, self._app, toast_fn=toast_fn)

        # Dossier de données isolé
        if "write_data" in perms:
            data_dir = Path(__file__).parent.parent / "data" / "plugins" / record.id
            data_dir.mkdir(parents=True, exist_ok=True)
            api._data_dir = data_dir

        instance = mod.Plugin(api)
        instance.on_load()

        record.api      = api
        record.instance = instance
        record.error    = ""
        log.info(f"[{record.id}] v{record.version} activé.")

    # ══ Activation / désactivation ════════════════════════════════════════════

    def activer_plugin(self, plugin_id: str) -> None:
        record = self._plugins.get(plugin_id)
        if not record or record.enabled:
            return
        plugin_dir = PLUGINS_DIR / plugin_id
        plugin_py  = plugin_dir / "plugin.py"
        try:
            self._activer(record, plugin_dir, plugin_py)
            record.enabled = True
            self._sauver_registry()
        except Exception as e:
            record.error = str(e)
            log.error(f"[{plugin_id}] Activation échouée : {e}")

    def desactiver_plugin(self, plugin_id: str) -> None:
        record = self._plugins.get(plugin_id)
        if not record or not record.enabled:
            return
        try:
            if record.instance:
                record.instance.on_unload()
        except Exception:
            pass
        record.instance = None
        record.api      = None
        record.enabled  = False
        self._sauver_registry()
        log.info(f"[{plugin_id}] Désactivé.")

    # ══ Installation ══════════════════════════════════════════════════════════

    def installer_depuis_zip(self, zip_path: str) -> str:
        """
        Installe un plugin depuis un fichier .vsext (zip renommé).
        Retourne l'id du plugin installé.
        """
        zip_path = Path(zip_path)
        if not zipfile.is_zipfile(zip_path):
            raise ValueError("Le fichier n'est pas une archive .vsext valide.")

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if "manifest.json" not in names or "plugin.py" not in names:
                raise ValueError("Archive incomplète (manifest.json ou plugin.py manquant).")

            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            pid = manifest.get("id", "")

        # Pré-validation avant extraction
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp) / pid
            tmp_dir.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in ("manifest.json", "plugin.py"):
                    if name in zf.namelist():
                        (tmp_dir / name).write_bytes(zf.read(name))
            valider_manifest(manifest, tmp_dir)
            valider_code(tmp_dir / "plugin.py")

        # Extraction finale
        dest = PLUGINS_DIR / pid
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir()
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in ("manifest.json", "plugin.py", "README.md"):
                if name in zf.namelist():
                    (dest / name).write_bytes(zf.read(name))

        registry = self._lire_registry()
        self._charger_plugin(dest, registry)
        self._sauver_registry()
        return pid

    def desinstaller_plugin(self, plugin_id: str) -> None:
        self.desactiver_plugin(plugin_id)
        plugin_dir = PLUGINS_DIR / plugin_id
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)
        self._plugins.pop(plugin_id, None)
        registry = self._lire_registry()
        registry.pop(plugin_id, None)
        self._sauver_registry()
        log.info(f"[{plugin_id}] Désinstallé.")

    # ══ Dispatch hooks ════════════════════════════════════════════════════════

    def fire(self, hook_name: str, **kwargs) -> None:
        """Déclenche un hook sur tous les plugins actifs (thread-safe, silencieux)."""
        for record in self._plugins.values():
            if not record.enabled or not record.api:
                continue
            callbacks = record.api._hooks.get(hook_name, [])
            for cb in callbacks:
                try:
                    threading.Thread(target=cb, kwargs=kwargs, daemon=True).start()
                except Exception as e:
                    log.error(f"[{record.id}] Hook '{hook_name}' erreur : {e}")

    # ══ Introspection ═════════════════════════════════════════════════════════

    def liste_plugins(self) -> list[PluginRecord]:
        return list(self._plugins.values())

    def get_plugin(self, pid: str) -> PluginRecord | None:
        return self._plugins.get(pid)

    # ══ Persistance registre ══════════════════════════════════════════════════

    def _lire_registry(self) -> dict:
        if REGISTRY_FILE.exists():
            try:
                return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _sauver_registry(self) -> None:
        REGISTRY_FILE.parent.mkdir(exist_ok=True)
        data = {
            pid: {"enabled": r.enabled, "hash": r.hash, "version": r.version}
            for pid, r in self._plugins.items()
        }
        REGISTRY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
