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

from suite_user import account_mode, get_account_user_id, get_display_name, get_external_user_id


def account_summary() -> dict[str, str]:
    return {
        "external_id": get_external_user_id(),
        "user_id": get_account_user_id(),
        "display_name": get_display_name(),
        "mode": account_mode(),
    }


def remember_saved_item(
    app: str,
    item_type: str,
    item_key: str,
    *,
    title: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Persist a song, player, portfolio, simulation, etc. for this account."""
    import suite_storage as storage

    storage.upsert_saved_item(
        app, item_type, item_key, title=title, payload=payload
    )


def forget_saved_item(app: str, item_type: str, item_key: str) -> None:
    """Mark saved item invalid — removes it from active dashboard surfaces."""
    import suite_storage as storage

    storage.invalidate_saved_item(app, item_type, item_key)
    storage.invalidate_resume_item(app, item_key)


def load_saved_items(
    *,
    app: str | None = None,
    item_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    import suite_storage as storage

    return storage.load_saved_items(app=app, item_type=item_type, limit=limit)


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

    page = str(state.get("page") or "")
    summary = str(state.get("summary") or state.get("label") or "")
    metrics = {k: v for k, v in state.items() if k not in {"page", "summary", "label"}}
    storage.save_current_state(app, page=page, summary=summary, metrics=metrics)
    if state.get("settings") and isinstance(state["settings"], dict):
        storage.save_user_settings(app, state["settings"])
