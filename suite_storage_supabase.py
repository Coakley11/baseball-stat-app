"""
Supabase PostgREST backend for cross-deployment suite activity.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from suite_storage_config import SuiteCloudConfig, get_cloud_config

MAX_EVENTS = 2000
ACTIVE_APP_KEYS = frozenset(
    {
        "music",
        "investment",
        "baseball",
        "nba",
        "applied_intelligence",
        "future_lens",
    }
)

_TABLE_USERS = "suite_users"
_TABLE_EVENTS = "suite_activity_events"
_TABLE_STATE = "suite_app_current_state"
_TABLE_RESUME = "suite_resume_items"
_TABLE_SAVED = "suite_saved_items"
_TABLE_SETTINGS = "suite_user_settings"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _headers(cfg: SuiteCloudConfig, *, prefer: str = "return=minimal") -> dict[str, str]:
    return {
        "apikey": cfg.key,
        "Authorization": f"Bearer {cfg.key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _request(
    method: str,
    path: str,
    *,
    cfg: SuiteCloudConfig | None = None,
    params: dict[str, str] | None = None,
    json_body: Any = None,
    prefer: str = "return=minimal",
) -> Any:
    import requests  # lazy import — available in all suite apps

    config = cfg or get_cloud_config()
    if config is None:
        raise RuntimeError("Supabase is not configured")

    url = f"{config.url}/rest/v1/{path}"
    response = requests.request(
        method,
        url,
        headers=_headers(config, prefer=prefer),
        params=params,
        json=json_body,
        timeout=15,
    )
    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(f"Supabase {method} {path} failed ({response.status_code}): {detail}")
    if not response.content:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        return None


def normalize_app_key(app: str) -> str:
    cleaned = str(app or "").strip()
    if cleaned == "math":
        return "applied_intelligence"
    return cleaned


def ping() -> bool:
    cfg = get_cloud_config()
    if cfg is None:
        return False
    try:
        _request("GET", _TABLE_EVENTS, cfg=cfg, params={"select": "id", "limit": "1"})
        return True
    except Exception:
        return False


def append_event(
    app: str,
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
) -> None:
    app_key = normalize_app_key(app)
    if not app_key:
        return
    _request(
        "POST",
        _TABLE_EVENTS,
        json_body={
            "app": app_key,
            "event": event,
            "page": page or "",
            "timestamp": _now_iso(),
            "metrics": metrics or {},
        },
    )


def save_current_state(
    app: str,
    *,
    page: str = "",
    summary: str = "",
    metrics: dict[str, Any] | None = None,
) -> None:
    app_key = normalize_app_key(app)
    if app_key not in ACTIVE_APP_KEYS:
        return
    _request(
        "POST",
        _TABLE_STATE,
        json_body={
            "app": app_key,
            "page": page or "",
            "summary": summary or "",
            "metrics": metrics or {},
            "updated_at": _now_iso(),
        },
        prefer="resolution=merge-duplicates,return=minimal",
    )


def upsert_resume_item(
    app: str,
    item_key: str,
    *,
    title: str,
    subtitle: str = "",
    action_url: str = "",
) -> None:
    app_key = normalize_app_key(app)
    key = str(item_key or "").strip()
    title_clean = str(title or "").strip()
    if not app_key or not key or not title_clean:
        return
    if app_key not in ACTIVE_APP_KEYS:
        return
    _request(
        "POST",
        _TABLE_RESUME,
        json_body={
            "app": app_key,
            "item_key": key,
            "title": title_clean,
            "subtitle": subtitle or "",
            "action_url": action_url or "",
            "valid": True,
            "updated_at": _now_iso(),
        },
        prefer="resolution=merge-duplicates,return=minimal",
    )


def invalidate_resume_item(app: str, item_key: str) -> None:
    app_key = normalize_app_key(app)
    key = str(item_key or "").strip()
    if not app_key or not key:
        return
    _request(
        "PATCH",
        _TABLE_RESUME,
        params={"app": f"eq.{app_key}", "item_key": f"eq.{key}"},
        json_body={"valid": False, "updated_at": _now_iso()},
    )


def invalidate_app_resume_items(app: str) -> None:
    app_key = normalize_app_key(app)
    if not app_key:
        return
    _request(
        "PATCH",
        _TABLE_RESUME,
        params={"app": f"eq.{app_key}"},
        json_body={"valid": False, "updated_at": _now_iso()},
    )


def load_events(limit: int = MAX_EVENTS) -> list[dict[str, Any]]:
    rows = _request(
        "GET",
        _TABLE_EVENTS,
        params={
            "select": "app,event,page,timestamp,metrics",
            "order": "id.desc",
            "limit": str(limit),
        },
        prefer="return=representation",
    )
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        out.append(
            {
                "app": str(row.get("app") or ""),
                "event": str(row.get("event") or ""),
                "page": str(row.get("page") or ""),
                "timestamp": str(row.get("timestamp") or "")[:19],
                "metrics": metrics,
            }
        )
    return out


def load_current_states() -> dict[str, dict[str, Any]]:
    rows = _request(
        "GET",
        _TABLE_STATE,
        params={"select": "app,page,summary,metrics,updated_at"},
        prefer="return=representation",
    )
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        app = str(row.get("app") or "")
        if app not in ACTIVE_APP_KEYS:
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        out[app] = {
            "page": str(row.get("page") or ""),
            "summary": str(row.get("summary") or ""),
            "metrics": metrics,
            "updated_at": str(row.get("updated_at") or "")[:19],
        }
    return out


def load_active_resume_items(limit: int = 8) -> list[dict[str, Any]]:
    rows = _request(
        "GET",
        _TABLE_RESUME,
        params={
            "select": "app,item_key,title,subtitle,action_url,updated_at",
            "user_id": f"eq.{_scoped_user_id()}",
            "valid": "eq.true",
            "order": "updated_at.desc",
            "limit": str(limit),
        },
        prefer="return=representation",
    )
    if not isinstance(rows, list):
        return []
    return [
        {
            "app": str(row.get("app") or ""),
            "item_key": str(row.get("item_key") or ""),
            "title": str(row.get("title") or ""),
            "subtitle": str(row.get("subtitle") or ""),
            "action_url": str(row.get("action_url") or ""),
            "updated_at": str(row.get("updated_at") or "")[:19],
        }
        for row in rows
        if isinstance(row, dict)
    ]


def upsert_saved_item(
    app: str,
    item_type: str,
    item_key: str,
    *,
    title: str,
    payload: dict[str, Any] | None = None,
) -> None:
    app_key = normalize_app_key(app)
    key = str(item_key or "").strip()
    title_clean = str(title or "").strip()
    itype = str(item_type or "item").strip() or "item"
    if not app_key or not key or not title_clean:
        return
    _request(
        "POST",
        _TABLE_SAVED,
        json_body={
            "user_id": _scoped_user_id(),
            "app": app_key,
            "item_type": itype,
            "item_key": key,
            "title": title_clean,
            "payload": payload or {},
            "valid": True,
            "updated_at": _now_iso(),
        },
        prefer="resolution=merge-duplicates,return=minimal",
    )


def invalidate_saved_item(app: str, item_type: str, item_key: str) -> None:
    app_key = normalize_app_key(app)
    key = str(item_key or "").strip()
    itype = str(item_type or "item").strip() or "item"
    if not app_key or not key:
        return
    _request(
        "PATCH",
        _TABLE_SAVED,
        params={
            "user_id": f"eq.{_scoped_user_id()}",
            "app": f"eq.{app_key}",
            "item_type": f"eq.{itype}",
            "item_key": f"eq.{key}",
        },
        json_body={"valid": False, "updated_at": _now_iso()},
    )


def load_saved_items(
    *,
    app: str | None = None,
    item_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "select": "app,item_type,item_key,title,payload,updated_at",
        "user_id": f"eq.{_scoped_user_id()}",
        "valid": "eq.true",
        "order": "updated_at.desc",
        "limit": str(limit),
    }
    if app:
        params["app"] = f"eq.{normalize_app_key(app)}"
    if item_type:
        params["item_type"] = f"eq.{item_type}"
    rows = _request("GET", _TABLE_SAVED, params=params, prefer="return=representation")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        out.append(
            {
                "app": str(row.get("app") or ""),
                "item_type": str(row.get("item_type") or ""),
                "item_key": str(row.get("item_key") or ""),
                "title": str(row.get("title") or ""),
                "payload": payload,
                "updated_at": str(row.get("updated_at") or "")[:19],
            }
        )
    return out


def save_user_settings(app: str, settings: dict[str, Any]) -> None:
    app_key = str(app or "_global").strip() or "_global"
    _request(
        "POST",
        _TABLE_SETTINGS,
        json_body={
            "user_id": _scoped_user_id(),
            "app": app_key,
            "settings": settings or {},
            "updated_at": _now_iso(),
        },
        prefer="resolution=merge-duplicates,return=minimal",
    )


def load_user_settings(app: str = "_global") -> dict[str, Any]:
    app_key = str(app or "_global").strip() or "_global"
    rows = _request(
        "GET",
        _TABLE_SETTINGS,
        params={
            "select": "settings,updated_at",
            "user_id": f"eq.{_scoped_user_id()}",
            "app": f"eq.{app_key}",
            "limit": "1",
        },
        prefer="return=representation",
    )
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        settings = rows[0].get("settings")
        if isinstance(settings, dict):
            return settings
    return {}


def record_activity(
    app: str,
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
    summary: str = "",
    resume_key: str = "",
    resume_title: str = "",
    resume_subtitle: str = "",
    action_url: str = "",
) -> None:
    append_event(app, event, page=page, metrics=metrics)
    if summary or page or metrics:
        save_current_state(app, page=page, summary=summary, metrics=metrics)
    if resume_key and resume_title:
        upsert_resume_item(
            app,
            resume_key,
            title=resume_title,
            subtitle=resume_subtitle,
            action_url=action_url,
        )
