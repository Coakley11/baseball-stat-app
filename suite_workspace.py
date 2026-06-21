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
    return text if text in _VALID_IDS else DEFAULT_WORKSPACE_ID


def workspace_label(workspace_id: str) -> str:
    wid = normalize_workspace_id(workspace_id)
    for preset in WORKSPACE_PRESETS:
        if preset["id"] == wid:
            return preset["label"]
    return wid.replace("_", " ").title()


def workspace_dir(workspace_id: str | None = None) -> Path:
    ws = normalize_workspace_id(workspace_id)
    return DATA_DIR / "workspaces" / ws


def load_persisted_workspace_id() -> str:
    raw = _read_json(_PERSISTED_FILE)
    if isinstance(raw, dict):
        return normalize_workspace_id(str(raw.get("workspace_id") or raw.get("active_workspace_id") or ""))
    return DEFAULT_WORKSPACE_ID


def persist_active_workspace_id(workspace_id: str) -> bool:
    ws = normalize_workspace_id(workspace_id)
    payload = {
        "workspace_id": ws,
        "label": workspace_label(ws),
    }
    return _write_json(_PERSISTED_FILE, payload)


def resolve_workspace_id(*, st: Any | None = None, explicit: str | None = None) -> str:
    if explicit not in (None, ""):
        return normalize_workspace_id(explicit)
    if st is not None:
        raw = st.session_state.get(SESSION_KEY)
        if raw not in (None, ""):
            return normalize_workspace_id(str(raw))
    try:
        import streamlit as st_module  # noqa: WPS433

        raw = st_module.session_state.get(SESSION_KEY)
        if raw not in (None, ""):
            return normalize_workspace_id(str(raw))
    except Exception:
        pass
    return load_persisted_workspace_id()


def get_active_workspace_id(st: Any | None = None) -> str:
    return resolve_workspace_id(st=st)


def set_active_workspace_id(st: Any, workspace_id: str) -> str:
    ws = normalize_workspace_id(workspace_id)
    prev_raw = st.session_state.get(SESSION_KEY)
    prev = normalize_workspace_id(str(prev_raw)) if prev_raw not in (None, "") else None
    st.session_state[SESSION_KEY] = ws
    persist_active_workspace_id(ws)
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
    """Daniel is the admin/developer workspace (Phase 1 — not auth)."""
    wid = workspace_id if workspace_id not in (None, "") else resolve_workspace_id(st=st)
    return normalize_workspace_id(wid) == DEFAULT_WORKSPACE_ID


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
    """Daniel workspace only, with explicit developer mode enabled."""
    return is_developer_workspace(st=st) and is_developer_mode_enabled(st=st)


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


def init_suite_workspace(st: Any) -> str:
    """
    Apply ?suite_workspace=, else session/persisted choice.
    Call once near app startup before restore/autosave.
    """
    from_url = _qp_get(st, _QUERY_PARAM)
    if from_url:
        incoming = normalize_workspace_id(from_url)
        current = normalize_workspace_id(
            str(st.session_state.get(SESSION_KEY) or load_persisted_workspace_id())
        )
        if incoming != current:
            set_active_workspace_id(st, incoming)
            st.session_state[_INITIALIZED_KEY] = True
            return incoming

    if st.session_state.get(_INITIALIZED_KEY):
        return get_active_workspace_id(st)

    if from_url:
        set_active_workspace_id(st, from_url)
    elif SESSION_KEY not in st.session_state:
        set_active_workspace_id(st, load_persisted_workspace_id())
    else:
        ws = normalize_workspace_id(str(st.session_state.get(SESSION_KEY) or ""))
        st.session_state[SESSION_KEY] = ws
        persist_active_workspace_id(ws)

    st.session_state[_INITIALIZED_KEY] = True
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
    base = str(url or "").strip()
    if not base:
        return ""
    ws = normalize_workspace_id(workspace_id or load_persisted_workspace_id())
    if f"{_QUERY_PARAM}=" in base:
        return base
    joiner = "&" if "?" in base else "?"
    sep = "" if base.endswith("?") or base.endswith("&") else joiner
    return f"{base}{sep}{_QUERY_PARAM}={ws}"


def render_workspace_selector_sidebar(st: Any) -> str:
    """Command Center sidebar profile selector. Returns active workspace id."""
    init_suite_workspace(st)
    current = get_active_workspace_id(st)
    labels = [p["label"] for p in WORKSPACE_PRESETS]
    ids = [p["id"] for p in WORKSPACE_PRESETS]
    idx = ids.index(current) if current in ids else 0
    choice = st.selectbox(
        "Workspace profile",
        labels,
        index=idx,
        key="_suite_workspace_selector_widget",
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
    st.caption(f"Active profile: **{workspace_label(current)}** (`{current}`)")
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
