"""
Unified account memory API — activity, state, saved items, and settings.

Logical schema (Supabase):
  users → suite_users
  app_activity → suite_activity_events (+ user_id)
  app_state → suite_app_current_state (+ user_id)
  saved_items → suite_saved_items
  user_settings → suite_user_settings

All apps must use the same ``suite_user_id`` in secrets for cross-device sync.
"""

from __future__ import annotations

from typing import Any

from suite_user import (
    account_mode,
    get_account_user_id,
    get_display_name,
    get_external_user_id,
    get_user_email,
)


def account_summary() -> dict[str, str]:
    email = get_user_email()
    return {
        "external_id": get_external_user_id(),
        "user_id": get_account_user_id(),
        "display_name": get_display_name(),
        "email": email,
        "mode": account_mode(),
    }


def _scoped_storage_app(app: str | None) -> str | None:
    """Map logical app id to workspace-scoped cloud key (Daniel keeps legacy unscoped)."""
    if not app:
        return None
    base = str(app or "").strip()
    if "__" in base:
        return base
    try:
        from suite_workspace import scoped_cloud_app_id

        return scoped_cloud_app_id(base)
    except Exception:
        return base or None


def remember_saved_item(
    app: str,
    item_type: str,
    item_key: str,
    *,
    title: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a song, player, portfolio, simulation, etc. for this account."""
    try:
        import suite_storage as storage
    except ImportError:
        import suite_storage_supabase as storage

    scoped_app = _scoped_storage_app(app) or str(app or "").strip()
    result = storage.upsert_saved_item(
        scoped_app, item_type, item_key, title=title, payload=payload
    )
    if isinstance(result, dict):
        return result
    return {"write_mode": "upsert", "duplicate_handled": False}


def forget_saved_item(app: str, item_type: str, item_key: str) -> None:
    """Mark saved item invalid — removes it from active dashboard surfaces."""
    import suite_storage as storage

    scoped_app = _scoped_storage_app(app) or str(app or "").strip()
    storage.invalidate_saved_item(scoped_app, item_type, item_key)
    storage.invalidate_resume_item(scoped_app, item_key)


def load_saved_items(
    *,
    app: str | None = None,
    item_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    import suite_storage as storage

    app_key = _scoped_storage_app(app)
    return storage.load_saved_items(app=app_key, item_type=item_type, limit=limit)


def save_settings(app: str, settings: dict[str, Any]) -> None:
    """Per-app settings, or ``_global`` for suite-wide preferences."""
    import suite_storage as storage

    storage.save_user_settings(app, settings)


def load_settings(app: str = "_global") -> dict[str, Any]:
    import suite_storage as storage

    return storage.load_user_settings(app)


def sync_local_state_to_cloud(app: str, state: dict[str, Any]) -> None:
    """
    Push a full app session blob into cloud app_state + optional settings key.
    Called from suite_activity_client when ``local_state`` is provided.
    """
    if not state:
        return
    import suite_storage as storage

    scoped_app = _scoped_storage_app(app) or str(app or "").strip()
    page = str(state.get("page") or "")
    summary = str(state.get("summary") or state.get("label") or "")
    metrics = {k: v for k, v in state.items() if k not in {"page", "summary", "label"}}
    storage.save_current_state(scoped_app, page=page, summary=summary, metrics=metrics)
    if state.get("settings") and isinstance(state["settings"], dict):
        storage.save_user_settings(app, state["settings"])
