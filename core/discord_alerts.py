"""
discord_alerts.py -- Alertes Discord persistantes pour les recherches VintedScrap.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import threading
from typing import Any, Optional

import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_DIR, "data")
_ALERTS_FILE = os.path.join(_DATA_DIR, "discord_alerts.json")
_LOCK = threading.RLock()


def _load() -> list[dict[str, Any]]:
    try:
        with open(_ALERTS_FILE, encoding="utf-8") as f:
            payload = json.load(f)
            return payload if isinstance(payload, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(alerts: list[dict[str, Any]]) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _alert_id(query: str, pays: str, filters: dict[str, Any] | None = None) -> str:
    raw = json.dumps(
        {
            "query": (query or "").strip().lower(),
            "pays": pays or "",
            "filters": filters or {},
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def is_valid_webhook(url: str) -> bool:
    value = (url or "").strip()
    return value.startswith("https://discord.com/api/webhooks/") or value.startswith(
        "https://discordapp.com/api/webhooks/"
    )


def list_alerts(active_only: bool = False) -> list[dict[str, Any]]:
    with _LOCK:
        alerts = _load()
    if active_only:
        return [a for a in alerts if a.get("active", True)]
    return alerts


def find_alert(query: str, pays: str, filters: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
    target_id = _alert_id(query, pays, filters)
    for alert in list_alerts(active_only=False):
        if alert.get("id") == target_id:
            return alert
    return None


def get_alert(alert_id: str) -> Optional[dict[str, Any]]:
    for alert in list_alerts(active_only=False):
        if alert.get("id") == alert_id:
            return alert
    return None


def upsert_alert(
    query: str,
    webhook_url: str,
    price_max: Optional[float],
    pays: str,
    filters: dict[str, Any] | None = None,
    baseline_ids: list[str] | None = None,
    active: Optional[bool] = None,
) -> dict[str, Any]:
    filters = dict(filters or {})
    alert_id = _alert_id(query, pays, filters)
    now = _now()
    payload = {
        "id": alert_id,
        "query": query.strip(),
        "webhook_url": webhook_url.strip(),
        "price_max": float(price_max) if price_max is not None else None,
        "pays": pays,
        "filters": filters,
        "active": True if active is None else bool(active),
        "baseline_ready": bool(baseline_ids),
        "last_seen_ids": [str(v) for v in (baseline_ids or [])][:80],
        "created_at": now,
        "updated_at": now,
        "last_check_at": None,
    }
    with _LOCK:
        alerts = _load()
        for idx, alert in enumerate(alerts):
            if alert.get("id") == alert_id:
                created_at = alert.get("created_at", now)
                payload["created_at"] = created_at
                payload["active"] = bool(alert.get("active", True)) if active is None else bool(active)
                payload["last_check_at"] = alert.get("last_check_at")
                if baseline_ids is None:
                    payload["baseline_ready"] = bool(alert.get("baseline_ready"))
                    payload["last_seen_ids"] = list(alert.get("last_seen_ids", []))
                alerts[idx] = payload
                _save(alerts)
                return payload
        alerts.append(payload)
        _save(alerts)
    return payload


def delete_alert(alert_id: str) -> bool:
    with _LOCK:
        alerts = _load()
        updated = [a for a in alerts if a.get("id") != alert_id]
        if len(updated) == len(alerts):
            return False
        _save(updated)
        return True


def set_alert_active(alert_id: str, active: bool) -> Optional[dict[str, Any]]:
    with _LOCK:
        alerts = _load()
        for alert in alerts:
            if alert.get("id") != alert_id:
                continue
            alert["active"] = bool(active)
            alert["updated_at"] = _now()
            _save(alerts)
            return alert
    return None


def update_runtime(alert_id: str, last_seen_ids: list[str], baseline_ready: bool = True) -> None:
    with _LOCK:
        alerts = _load()
        for alert in alerts:
            if alert.get("id") != alert_id:
                continue
            alert["last_seen_ids"] = [str(v) for v in last_seen_ids][:80]
            alert["baseline_ready"] = bool(baseline_ready)
            alert["last_check_at"] = _now()
            alert["updated_at"] = _now()
            break
        _save(alerts)


def send_annonce(alert: dict[str, Any], annonce) -> bool:
    webhook_url = (alert.get("webhook_url") or "").strip()
    if not is_valid_webhook(webhook_url):
        return False

    price_max = alert.get("price_max")
    try:
        if price_max is not None and float(getattr(annonce, "price", 0) or 0) > float(price_max):
            return False
    except (TypeError, ValueError):
        return False

    price_value = float(getattr(annonce, "price", 0) or 0)
    currency = getattr(annonce, "currency", "EUR")
    symbol = getattr(type(annonce), "SYMBOLES", {}).get(currency, currency)
    embed = {
        "title": f"Nouvelle annonce · {getattr(annonce, 'title', 'Annonce Vinted')}",
        "url": getattr(annonce, "url", ""),
        "color": 0x00E5FF,
        "description": (
            f"**{price_value:.2f} {symbol}**"
            f"\nRecherche : `{alert.get('query', '')}`"
            f"\nÉtat : {getattr(annonce, 'condition', '') or 'Non précisé'}"
        ),
        "footer": {
            "text": f"{getattr(annonce, 'brand', '') or 'Sans marque'} · "
            f"{getattr(annonce, 'vendeur_nom', '') or 'Vendeur inconnu'}"
        },
    }
    image_url = getattr(annonce, "image_url", "") or ""
    if image_url:
        embed["thumbnail"] = {"url": image_url}
    payload = {"embeds": [embed]}
    try:
        response = requests.post(webhook_url, json=payload, timeout=8)
        return response.status_code in (200, 204)
    except Exception:
        return False
