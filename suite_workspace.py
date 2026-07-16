"""
Suite workspace profiles — Phase 1 local isolation (no auth).

Command Center owns the active workspace. Apps inherit via query param or persisted file.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"

DEFAULT_WORKSPACE_ID = "daniel"
SESSION_KEY = "_suite_active_workspace_id"
_INITIALIZED_KEY = "_suite_workspace_initialized"
WORKSPACE_SELECTOR_WIDGET_KEY = "_suite_workspace_selector_widget"
_QUERY_PARAM = "suite_workspace"
_PERSISTED_FILE = DATA_DIR / "suite_active_workspace.json"

WORKSPACE_PRESETS: tuple[dict[str, str], ...] = (
    {"id": "daniel", "label": "Daniel"},
    {"id": "ariel", "label": "Ariel"},
    {"id": "guest", "label": "Guest"},
    {"id": "test_user", "label": "Test User"},
)

_VALID_IDS = frozenset(p["id"] for p in WORKSPACE_PRESETS)

_SUITE_STORAGE_APP_IDS: tuple[str, ...] = (
    "music",
    "investment",
    "baseball",
    "nba",
    "applied_intelligence",
    "future_lens",
)


def normalize_workspace_id(raw: str | None) -> str:
    text = str(raw or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return DEFAULT_WORKSPACE_ID
    aliases = {
        "test": "test_user",
        "testuser": "test_user",
        "default": DEFAULT_WORKSPACE_ID,
    }
    text = aliases.get(text, text)
    if text in _VALID_IDS:
        return text
    # Auth-scoped profile ids (e.g. coakley11) — do not fall back to shared daniel default.
    if re.fullmatch(r"[a-z0-9_]+", text):
        return text
    return DEFAULT_WORKSPACE_ID


def workspace_label(workspace_id: str) -> str:
    wid = normalize_workspace_id(workspace_id)
    for preset in WORKSPACE_PRESETS:
        if preset["id"] == wid:
            return preset["label"]
    return wid.replace("_", " ").title()


def workspace_dir(workspace_id: str | None = None) -> Path:
    ws = normalize_workspace_id(workspace_id)
    return DATA_DIR / "workspaces" / ws


def _load_legacy_persisted_workspace_id() -> str:
    """Legacy global workspace path — no account awareness, never delegates."""
    raw = _read_json(_PERSISTED_FILE)
    if isinstance(raw, dict):
        return normalize_workspace_id(str(raw.get("workspace_id") or raw.get("active_workspace_id") or ""))
    return DEFAULT_WORKSPACE_ID


def load_persisted_workspace_id(*, session_state: dict[str, Any] | None = None) -> str:
    """
    Resolve persisted workspace.

    Authenticated: delegates once to the account-owned path (which reads the
    account file directly and does NOT call back here). Unauthenticated/demo:
    resolves the legacy global workspace file with no delegation.
    """
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        account_aware = (
            isinstance(session_state, dict)
            and is_auth_enabled()
            and is_authenticated(session_state)
        )
    except ImportError:
        account_aware = False

    if account_aware:
        try:
            from suite_workspace_registry import load_persisted_workspace_for_account

            return load_persisted_workspace_for_account(session_state=session_state)
        except ImportError:
            pass
    return _load_legacy_persisted_workspace_id()


def persist_active_workspace_id(workspace_id: str, *, session_state: dict[str, Any] | None = None) -> bool:
    ws = normalize_workspace_id(workspace_id)
    try:
        from suite_workspace_registry import persist_active_workspace_for_account

        if persist_active_workspace_for_account(ws, session_state=session_state):
            return True
    except ImportError:
        pass
    payload = {
        "workspace_id": ws,
        "label": workspace_label(ws),
    }
    return _write_json(_PERSISTED_FILE, payload)


def resolve_workspace_id(*, st: Any | None = None, explicit: str | None = None) -> str:
    if explicit not in (None, ""):
        return normalize_workspace_id(explicit)
    ss: dict[str, Any] | None = None
    if st is not None:
        ss = st.session_state
        raw = ss.get(SESSION_KEY)
        if raw not in (None, ""):
            return normalize_workspace_id(str(raw))
    try:
        import streamlit as st_module  # noqa: WPS433

        if ss is None:
            ss = st_module.session_state
        raw = ss.get(SESSION_KEY)
        if raw not in (None, ""):
            return normalize_workspace_id(str(raw))
    except Exception:
        ss = None
    return load_persisted_workspace_id(session_state=ss)


def get_active_workspace_id(st: Any | None = None) -> str:
    return resolve_workspace_id(st=st)


def _sync_workspace_selector_widget(st: Any, workspace_id: str) -> None:
    """Keep sidebar selectbox aligned with SESSION_KEY (widget key can desync after auth clamp)."""
    try:
        st.session_state[WORKSPACE_SELECTOR_WIDGET_KEY] = workspace_label(workspace_id)
    except Exception:
        pass


def set_active_workspace_id(st: Any, workspace_id: str) -> str:
    ws = normalize_workspace_id(workspace_id)
    try:
        from suite_workspace_registry import workspace_access_allowed

        if not workspace_access_allowed(ws, session_state=st.session_state):
            from suite_workspace_registry import get_owned_workspace_id

            owned = get_owned_workspace_id(st.session_state)
            if owned:
                ws = normalize_workspace_id(owned)
    except ImportError:
        pass
    prev_raw = st.session_state.get(SESSION_KEY)
    prev = normalize_workspace_id(str(prev_raw)) if prev_raw not in (None, "") else None
    st.session_state[SESSION_KEY] = ws
    persist_active_workspace_id(ws, session_state=st.session_state)
    _sync_workspace_selector_widget(st, ws)
    if prev is not None and prev != ws:
        _on_active_workspace_changed(st)
    return ws


def _on_active_workspace_changed(st: Any) -> None:
    """Drop Command Center aggregation caches when the active profile changes."""
    ss = st.session_state
    for key in list(ss.keys()):
        sk = str(key)
        if sk.startswith(("_cc_", "_ami_", "activity_", "_suite_activity")):
            ss.pop(key, None)
        elif sk.startswith(("_suite_ai_", "ps_")) or sk in ("view_mode", "ps_library_problem"):
            ss.pop(key, None)
    for key in DEVELOPER_SESSION_FLAG_KEYS:
        ss.pop(key, None)
    try:
        import streamlit as st_module

        st_module.cache_data.clear()
    except Exception:
        pass


def logical_storage_app_key(storage_app: str) -> str:
    """Map cloud row key ``baseball__ariel`` → ``baseball`` for CC aggregation."""
    base = str(storage_app or "").strip()
    if base == "math":
        base = "applied_intelligence"
    if "__" in base:
        base = base.split("__", 1)[0]
    return base


def workspace_storage_app_keys(workspace_id: str | None = None) -> frozenset[str]:
    """Scoped Supabase ``app`` keys for the active (or given) workspace profile."""
    ws = normalize_workspace_id(
        workspace_id if workspace_id not in (None, "") else resolve_workspace_id()
    )
    return frozenset(scoped_cloud_app_id(app, ws) for app in _SUITE_STORAGE_APP_IDS)


def storage_app_in_workspace(storage_app: str, workspace_id: str | None = None) -> bool:
    return str(storage_app or "").strip() in workspace_storage_app_keys(workspace_id)


DEVELOPER_QUERY_PARAM = "dev"
DEVELOPER_SESSION_FLAG_KEYS: tuple[str, ...] = (
    "_suite_dev_mode",
    "cc_developer_mode",
    "app_developer_mode",
    "developer_mode",
    "investment_show_dev_diagnostics",
    "investment_pr1_diagnostics_enabled",
    "dev_lab_enabled",
)


def is_developer_workspace(*, st: Any | None = None, workspace_id: str | None = None) -> bool:
    """Legacy helper — Daniel workspace id. Prefer :func:`is_admin_session` for auth gates."""
    wid = workspace_id if workspace_id not in (None, "") else resolve_workspace_id(st=st)
    return normalize_workspace_id(wid) == DEFAULT_WORKSPACE_ID


def _session_state_from_st(st: Any | None = None) -> Any | None:
    try:
        if st is not None and hasattr(st, "session_state"):
            ss = st.session_state
            return ss if hasattr(ss, "get") else None
        import streamlit as st_module  # noqa: WPS433

        ss = st_module.session_state
        return ss if hasattr(ss, "get") else None
    except Exception:
        return None


def is_admin_session(*, st: Any | None = None) -> bool:
    """True when the current Streamlit session is an authorized admin account."""
    try:
        from suite_workspace_registry import is_admin_user

        return is_admin_user(session_state=_session_state_from_st(st))
    except Exception:
        return False


def _developer_query_enabled(st: Any | None = None) -> bool:
    val = _qp_get(st, DEVELOPER_QUERY_PARAM) if st is not None else ""
    if not val:
        try:
            import streamlit as st_module  # noqa: WPS433

            raw = st_module.query_params.get(DEVELOPER_QUERY_PARAM)
            if raw is None:
                return False
            val = str(raw[0] if isinstance(raw, list) else raw).strip()
        except Exception:
            return False
    return val.lower() in ("1", "true", "yes", "on")


def is_developer_mode_enabled(*, st: Any | None = None) -> bool:
    """True when ?dev=1 or a developer-mode session toggle is on (any workspace)."""
    if _developer_query_enabled(st):
        return True
    try:
        import streamlit as st_module  # noqa: WPS433

        ss = st.session_state if st is not None else st_module.session_state
        for key in DEVELOPER_SESSION_FLAG_KEYS:
            if ss.get(key):
                return True
    except Exception:
        pass
    return False


def can_show_developer_tools(*, st: Any | None = None) -> bool:
    """
    Admin accounts only, with explicit developer mode enabled.

    Fail-safe: non-admins never see developer / diagnostics / deploy tools,
    even if ``?dev=1`` or a session toggle is set.
    """
    if not is_admin_session(st=st):
        return False
    return is_developer_mode_enabled(st=st)


def _qp_get(st: Any, name: str) -> str:
    try:
        raw = st.query_params.get(name)
    except Exception:
        return ""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return str(raw[0] or "").strip()
    return str(raw).strip()


def bootstrap_suite_workspace(st: Any) -> str:
    """
    Restore authenticated account identity before workspace selection.

    Prevents a signed-in user from briefly loading another profile's persisted
    workspace (e.g. coakley11 seeing daniel) during app startup.
    """
    try:
        from suite_auth import enforce_workspace_ownership, is_auth_enabled, restore_auth_session

        if is_auth_enabled():
            restore_auth_session(st.session_state, st=st)
            if st.session_state.get("_suite_auth_session"):
                enforce_workspace_ownership(st.session_state)
    except ImportError:
        pass
    return init_suite_workspace(st)


def init_suite_workspace(st: Any) -> str:
    """
    Apply ?suite_workspace=, else session/persisted choice.
    Call once near app startup before restore/autosave.
    """
    try:
        from suite_auth import enforce_workspace_ownership, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(st.session_state):
            enforce_workspace_ownership(st.session_state)
    except ImportError:
        pass
    from_url = _qp_get(st, _QUERY_PARAM)
    if from_url:
        incoming = normalize_workspace_id(from_url)
        allowed_incoming = True
        try:
            from suite_workspace_registry import workspace_access_allowed

            allowed_incoming = workspace_access_allowed(incoming, session_state=st.session_state)
        except ImportError:
            pass
        current = normalize_workspace_id(
            str(st.session_state.get(SESSION_KEY) or load_persisted_workspace_id(session_state=st.session_state))
        )
        if allowed_incoming and incoming != current:
            set_active_workspace_id(st, incoming)
            st.session_state[_INITIALIZED_KEY] = True
            return incoming
        if not allowed_incoming:
            try:
                from suite_auth import enforce_workspace_ownership

                enforce_workspace_ownership(st.session_state)
            except ImportError:
                pass

    if st.session_state.get(_INITIALIZED_KEY):
        return get_active_workspace_id(st)

    if SESSION_KEY not in st.session_state:
        set_active_workspace_id(st, load_persisted_workspace_id(session_state=st.session_state))
    else:
        ws = normalize_workspace_id(str(st.session_state.get(SESSION_KEY) or ""))
        st.session_state[SESSION_KEY] = ws
        persist_active_workspace_id(ws, session_state=st.session_state)

    st.session_state[_INITIALIZED_KEY] = True
    try:
        from suite_auth import enforce_workspace_ownership, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(st.session_state):
            enforce_workspace_ownership(st.session_state)
    except ImportError:
        pass
    return get_active_workspace_id(st)


def legacy_state_file_path(app_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(app_id or "app"))
    return DATA_DIR / f"{safe}_user_state.json"


def migrate_legacy_app_state_to_daniel(app_id: str) -> bool:
    """Copy legacy flat file into Daniel workspace once."""
    legacy = legacy_state_file_path(app_id)
    if not legacy.is_file():
        return False
    target = workspace_dir("daniel") / legacy.name
    if target.is_file():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        return True
    except OSError:
        return False


def append_suite_workspace_param(url: str, workspace_id: str | None = None) -> str:
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    base = str(url or "").strip()
    if not base:
        return ""
    ws = normalize_workspace_id(workspace_id if workspace_id not in (None, "") else load_persisted_workspace_id())
    parsed = urlparse(base)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params[_QUERY_PARAM] = [ws]
    new_query = urlencode(params, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _workspace_presets_for_session(st: Any) -> tuple[dict[str, str], ...]:
    presets: tuple[dict[str, str], ...] = WORKSPACE_PRESETS
    try:
        from suite_auth import allowed_workspaces_for_session, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(st.session_state):
            allowed_ids = allowed_workspaces_for_session(st.session_state)
            allowed = frozenset(normalize_workspace_id(w) for w in allowed_ids)
            filtered = tuple(p for p in WORKSPACE_PRESETS if p["id"] in allowed)
            known = {p["id"] for p in filtered}
            extras = tuple(
                {"id": normalize_workspace_id(wid), "label": workspace_label(wid)}
                for wid in allowed_ids
                if normalize_workspace_id(wid) not in known
            )
            if extras:
                filtered = filtered + extras
            elif not filtered and allowed_ids:
                filtered = tuple(
                    {"id": normalize_workspace_id(wid), "label": workspace_label(wid)}
                    for wid in allowed_ids
                )
            if filtered:
                presets = filtered
    except ImportError:
        pass
    return presets


def build_workspace_ownership_diagnostics(*, st: Any) -> dict[str, Any]:
    """Dev diagnostics for account-owned workspace isolation."""
    ss = st.session_state
    diag: dict[str, Any] = {
        "suite_auth_enabled": False,
        "signed_in": False,
        "signed_in_email": "",
        "auth_external_id": "",
        "owner_user_id": "",
        "allowed_workspaces": [],
        "owned_workspace_id": "",
        "active_workspace_id": get_active_workspace_id(st),
        "can_switch_workspaces": True,
        "workspace_picker_visible": True,
        "workspace_picker_reason": "Legacy preset picker",
        "deploy_commit": "unknown",
        "deploy_branch": "unknown",
    }
    try:
        from suite_auth import (
            AUTH_USER_ID_KEY,
            allowed_workspaces_for_session,
            current_auth_email,
            is_auth_enabled,
            is_authenticated,
            resolve_auth_external_id,
        )

        diag["suite_auth_enabled"] = is_auth_enabled()
        if diag["suite_auth_enabled"]:
            diag["signed_in"] = is_authenticated(ss)
            if diag["signed_in"]:
                diag["signed_in_email"] = current_auth_email(ss)
                diag["auth_external_id"] = resolve_auth_external_id(ss)
                diag["owner_user_id"] = str(ss.get(AUTH_USER_ID_KEY) or "").strip()
                diag["allowed_workspaces"] = list(allowed_workspaces_for_session(ss))
    except ImportError:
        pass
    try:
        from suite_workspace_registry import can_switch_workspaces, get_owned_workspace_id

        diag["owned_workspace_id"] = get_owned_workspace_id(ss)
        diag["can_switch_workspaces"] = can_switch_workspaces(session_state=ss)
        diag["workspace_picker_visible"] = bool(diag["can_switch_workspaces"])
        if diag["workspace_picker_visible"]:
            diag["workspace_picker_reason"] = "Admin/dev multi-workspace picker enabled"
        else:
            diag["workspace_picker_reason"] = (
                "Account-owned workspace — picker hidden for non-admin accounts"
            )
    except ImportError:
        pass
    try:
        from suite_deploy_marker import resolve_git_branch, resolve_git_commit_short

        diag["deploy_commit"] = resolve_git_commit_short()
        diag["deploy_branch"] = resolve_git_branch()
    except ImportError:
        pass
    return diag


def render_workspace_ownership_diagnostics(st: Any, *, sidebar: bool = False) -> None:
    """Dev panel: auth/workspace ownership state for live isolation debugging."""
    try:
        from suite_workspace import can_show_developer_tools

        if not can_show_developer_tools(st=st):
            return
    except ImportError:
        return
    ui = st.sidebar if sidebar else st
    diag = build_workspace_ownership_diagnostics(st=st)
    with ui.expander("Workspace ownership (dev)", expanded=False):
        ui.markdown(
            f"| Field | Value |\n|---|---|\n"
            f"| **suite_auth_enabled** | `{diag.get('suite_auth_enabled')}` |\n"
            f"| **signed_in** | `{diag.get('signed_in')}` |\n"
            f"| **signed_in_email** | `{diag.get('signed_in_email') or '—'}` |\n"
            f"| **auth_external_id** | `{diag.get('auth_external_id') or '—'}` |\n"
            f"| **owner_user_id** | `{diag.get('owner_user_id') or '—'}` |\n"
            f"| **allowed_workspaces** | `{diag.get('allowed_workspaces')}` |\n"
            f"| **owned_workspace_id** | `{diag.get('owned_workspace_id') or '—'}` |\n"
            f"| **active_workspace_id** | `{diag.get('active_workspace_id') or '—'}` |\n"
            f"| **workspace_picker_visible** | `{diag.get('workspace_picker_visible')}` |\n"
            f"| **workspace_picker_reason** | {diag.get('workspace_picker_reason') or '—'} |\n"
            f"| **deploy_commit** | `{diag.get('deploy_commit')}` |\n"
            f"| **deploy_branch** | `{diag.get('deploy_branch')}` |"
        )


def render_workspace_selector_sidebar(st: Any) -> str:
    """Command Center sidebar profile selector. Returns active workspace id."""
    bootstrap_suite_workspace(st)
    try:
        from suite_auth import enforce_workspace_ownership

        enforce_workspace_ownership(st.session_state)
    except ImportError:
        pass
    current = get_active_workspace_id(st)
    try:
        from suite_workspace_registry import can_switch_workspaces

        if not can_switch_workspaces(session_state=st.session_state):
            _sync_workspace_selector_widget(st, current)
            st.caption(f"Active workspace: **{workspace_label(current)}**")
            return current
    except ImportError:
        pass
    presets = _workspace_presets_for_session(st)
    labels = [p["label"] for p in presets]
    ids = [p["id"] for p in presets]
    idx = ids.index(current) if current in ids else 0
    choice = st.selectbox(
        "Workspace profile",
        labels,
        index=idx,
        key=WORKSPACE_SELECTOR_WIDGET_KEY,
        help="Apps opened from Command Center use this profile. Each profile keeps separate saved state.",
    )
    selected = ids[labels.index(choice)]
    if selected != current:
        set_active_workspace_id(st, selected)
        current = selected
        try:
            st.rerun()
        except Exception:
            pass
    elif st.session_state.get(WORKSPACE_SELECTOR_WIDGET_KEY) != workspace_label(current):
        _sync_workspace_selector_widget(st, current)
    if can_show_developer_tools(st=st):
        st.caption(f"Active profile: **{workspace_label(current)}** (`{current}`)")
    else:
        st.caption(f"Active profile: **{workspace_label(current)}**")
    return current


def workspace_badge_html(workspace_id: str | None = None) -> str:
    ws = normalize_workspace_id(workspace_id or load_persisted_workspace_id())
    return f'Profile: {workspace_label(ws)}'


def scoped_cloud_app_id(app_id: str, workspace_id: str | None = None) -> str:
    """
    Supabase ``app`` row key namespaced by workspace.

    Daniel keeps the legacy unscoped key (``investment``) for phone/Dell continuity.
    Other profiles use ``{app}__{workspace_id}`` (e.g. ``investment__ariel``).
    """
    base = str(app_id or "").strip()
    if base == "math":
        base = "applied_intelligence"
    ws = normalize_workspace_id(
        workspace_id if workspace_id not in (None, "") else resolve_workspace_id()
    )
    if ws == DEFAULT_WORKSPACE_ID:
        return base
    return f"{base}__{ws}"


def workspace_restore_cloud_first(*, has_disk_state: bool) -> bool:
    """
    Phase 1 workspace isolation: prefer workspace-local disk when it exists.

    Prevents a shared legacy cloud row from overwriting another profile's saved state.
    """
    if has_disk_state:
        return False
    return True


def workspace_persistence_meta(
    app_id: str,
    *,
    st: Any | None = None,
    workspace_id: str | None = None,
) -> dict[str, str]:
    """Diagnostic fields for save/restore traces (workspace_id, paths, cloud key)."""
    ws = normalize_workspace_id(
        workspace_id if workspace_id not in (None, "") else get_active_workspace_id(st)
    )
    try:
        from suite_user_persistence import state_file_path

        local_path = str(state_file_path(app_id, ws))
    except Exception:
        local_path = str(workspace_dir(ws) / f"{app_id}_user_state.json")
    return {
        "active_workspace_id": ws,
        "local_state_path": local_path,
        "cloud_app_key": scoped_cloud_app_id(app_id, ws),
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> bool:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False
