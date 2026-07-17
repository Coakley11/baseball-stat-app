"""Shared per-user / per-workspace page preference framework.

Persists configuration (not transient UI) via page_filter_state + baseball workspace blob.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

PREFS_SCHEMA_VERSION = 1
PREFS_INIT_FLAG_PREFIX = "_prefs_initialized:"
PREFS_DIRTY_PREFIX = "_prefs_dirty:"
PAGE_KEY_LIVE_DRAFT_SETUP = "live_draft_setup"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_ids(session: dict[str, Any] | None) -> tuple[str, str]:
    session = session if isinstance(session, dict) else {}
    user_id = ""
    workspace_id = ""
    try:
        from suite_auth import AUTH_USER_ID_KEY

        user_id = str(session.get(AUTH_USER_ID_KEY) or "").strip()
    except ImportError:
        user_id = str(session.get("auth_user_id") or "").strip()
    try:
        from suite_user import current_workspace_id

        workspace_id = str(current_workspace_id(session) or "").strip()
    except ImportError:
        workspace_id = str(session.get("workspace_id") or session.get("active_workspace_id") or "").strip()
    return user_id, workspace_id


def preferences_initialized(session: dict[str, Any], page_key: str) -> bool:
    return bool(session.get(f"{PREFS_INIT_FLAG_PREFIX}{page_key}"))


def mark_preferences_initialized(session: dict[str, Any], page_key: str) -> None:
    session[f"{PREFS_INIT_FLAG_PREFIX}{page_key}"] = True


def mark_preferences_dirty(session: dict[str, Any], page_key: str) -> None:
    session[f"{PREFS_DIRTY_PREFIX}{page_key}"] = True


def clear_preferences_dirty(session: dict[str, Any], page_key: str) -> None:
    session.pop(f"{PREFS_DIRTY_PREFIX}{page_key}", None)


def is_preferences_dirty(session: dict[str, Any], page_key: str) -> bool:
    return bool(session.get(f"{PREFS_DIRTY_PREFIX}{page_key}"))


def _prefs_block(session: dict[str, Any]) -> dict[str, Any]:
    root = session.setdefault("page_filter_state", {})
    if not isinstance(root, dict):
        root = {}
        session["page_filter_state"] = root
    block = root.setdefault("_user_page_preferences", {})
    if not isinstance(block, dict):
        block = {}
        root["_user_page_preferences"] = block
    return block


def get_user_page_preferences(
    user_id: str,
    workspace_id: str,
    page_key: str,
    *,
    session: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return persisted settings dict for a page, or None when absent."""
    session = session if isinstance(session, dict) else {}
    uid, wid = _resolve_ids(session)
    user_id = str(user_id or uid or "").strip()
    workspace_id = str(workspace_id or wid or "").strip()
    key = str(page_key or "").strip()
    if not key:
        return None
    block = _prefs_block(session)
    entry = block.get(key)
    if not isinstance(entry, dict):
        return None
    # Soft scope check — allow restore when ids were empty at save time.
    saved_user = str(entry.get("user_id") or "").strip()
    saved_ws = str(entry.get("workspace_id") or "").strip()
    if user_id and saved_user and saved_user != user_id:
        return None
    if workspace_id and saved_ws and saved_ws != workspace_id:
        return None
    settings = entry.get("settings")
    return copy.deepcopy(settings) if isinstance(settings, dict) else None


def save_user_page_preferences(
    user_id: str,
    workspace_id: str,
    page_key: str,
    settings: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
    st: Any = None,
    force_disk: bool = True,
) -> dict[str, Any]:
    """Persist page settings into page_filter_state (+ optional workspace disk/cloud)."""
    session = session if isinstance(session, dict) else {}
    uid, wid = _resolve_ids(session)
    user_id = str(user_id or uid or "").strip()
    workspace_id = str(workspace_id or wid or "").strip()
    key = str(page_key or "").strip()
    if not key:
        raise ValueError("page_key required")
    payload = {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "page_key": key,
        "schema_version": PREFS_SCHEMA_VERSION,
        "settings": copy.deepcopy(settings if isinstance(settings, dict) else {}),
        "updated_at": _utc_now_iso(),
    }
    block = _prefs_block(session)
    block[key] = payload
    clear_preferences_dirty(session, key)
    if force_disk and st is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st, reason=f"user_page_prefs:{key}")
        except Exception:
            pass
    return copy.deepcopy(payload)


def reset_user_page_preferences(
    user_id: str,
    workspace_id: str,
    page_key: str,
    *,
    session: dict[str, Any] | None = None,
    st: Any = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace persisted settings with defaults (empty dict if none provided)."""
    defaults = copy.deepcopy(defaults) if isinstance(defaults, dict) else {}
    return save_user_page_preferences(
        user_id,
        workspace_id,
        page_key,
        defaults,
        session=session,
        st=st,
        force_disk=True,
    )


def collect_live_draft_setup_settings(session: dict[str, Any]) -> dict[str, Any]:
    """Snapshot Live Draft setup controls that should survive reboot."""
    try:
        from live_draft_state import LIVE_DRAFT_SETTINGS_KEYS
    except ImportError:
        LIVE_DRAFT_SETTINGS_KEYS = ()
    out: dict[str, Any] = {}
    for key in LIVE_DRAFT_SETTINGS_KEYS:
        if key in session:
            out[key] = session[key]
    for key, val in list(session.items()):
        if str(key).startswith("live_slot_") or str(key).startswith("live_draft_team_name_"):
            out[str(key)] = val
    if "live_draft_setup_mode" in session:
        out["live_draft_setup_mode"] = session["live_draft_setup_mode"]
    return out


def apply_live_draft_setup_settings(session: dict[str, Any], settings: dict[str, Any]) -> None:
    """Seed session keys from persisted setup before widgets render."""
    if not isinstance(settings, dict):
        return
    for key, val in settings.items():
        if key.startswith("_"):
            continue
        session[key] = val


def ensure_live_draft_setup_preferences_loaded(session: dict[str, Any]) -> bool:
    """Load persisted Live Draft setup once per session before widget defaults win.

    Returns True when settings were applied from persistence.
    """
    page_key = PAGE_KEY_LIVE_DRAFT_SETUP
    if preferences_initialized(session, page_key):
        return False
    session["_live_draft_setup_seeding"] = True
    try:
        # Active in-progress draft config wins over generic saved preferences.
        room = session.get("live_draft_room")
        if isinstance(room, dict) and str(room.get("status") or "") in ("in_progress", "paused"):
            mark_preferences_initialized(session, page_key)
            return False
        uid, wid = _resolve_ids(session)
        settings = get_user_page_preferences(uid, wid, page_key, session=session)
        if not settings:
            # Fallback: page_filter_state Live Draft Room snapshot keys.
            try:
                from live_draft_state import LIVE_DRAFT_SETTINGS_KEYS

                pfs = session.get("page_filter_state") or {}
                block = pfs.get("Live Draft Room") if isinstance(pfs, dict) else None
                if isinstance(block, dict):
                    settings = {k: block[k] for k in LIVE_DRAFT_SETTINGS_KEYS if k in block}
                    for k, v in block.items():
                        if str(k).startswith("live_slot_") or str(k).startswith("live_draft_team_name_"):
                            settings[str(k)] = v
            except ImportError:
                settings = None
        applied = False
        if isinstance(settings, dict) and settings:
            apply_live_draft_setup_settings(session, settings)
            applied = True
        mark_preferences_initialized(session, page_key)
        return applied
    finally:
        session.pop("_live_draft_setup_seeding", None)


def persist_live_draft_setup_preferences(
    session: dict[str, Any],
    *,
    st: Any = None,
    force_disk: bool = True,
) -> dict[str, Any]:
    """Autosave Live Draft setup into the shared preference record."""
    uid, wid = _resolve_ids(session)
    settings = collect_live_draft_setup_settings(session)
    return save_user_page_preferences(
        uid,
        wid,
        PAGE_KEY_LIVE_DRAFT_SETUP,
        settings,
        session=session,
        st=st,
        force_disk=force_disk,
    )


def default_live_draft_setup_settings() -> dict[str, Any]:
    """Application defaults for Reset Setup."""
    return {
        "live_draft_team_count": 2,
        "live_draft_num_teams": 2,
        "live_draft_picks_per_team": 4,
        "live_draft_timer": "30 seconds",
        "live_draft_type": "Snake",
        "live_draft_scoring": "Points",
        "live_draft_proj_window": "3 years",
        "live_draft_proj_style": "Balanced",
        "live_draft_auto_rule": "Best Available",
        "live_draft_league_name": "",
    }


def reset_live_draft_setup_to_defaults(
    session: dict[str, Any],
    *,
    st: Any = None,
) -> dict[str, Any]:
    """Reset persisted + session setup to defaults (does not wipe an active draft board)."""
    defaults = default_live_draft_setup_settings()
    apply_live_draft_setup_settings(session, defaults)
    # Clear dynamic team-name / slot widgets so defaults re-seed cleanly.
    for key in list(session.keys()):
        if str(key).startswith("live_draft_team_name_") or str(key).startswith("live_slot_"):
            session.pop(key, None)
    uid, wid = _resolve_ids(session)
    return reset_user_page_preferences(
        uid,
        wid,
        PAGE_KEY_LIVE_DRAFT_SETUP,
        session=session,
        st=st,
        defaults=defaults,
    )
