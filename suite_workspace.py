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
    st.session_state[SESSION_KEY] = ws
    persist_active_workspace_id(ws)
    return ws


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
    if st.session_state.get(_INITIALIZED_KEY):
        return get_active_workspace_id(st)

    from_url = _qp_get(st, _QUERY_PARAM)
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
    st.caption(f"Active profile: **{workspace_label(current)}** (`{current}`)")
    return current


def workspace_badge_html(workspace_id: str | None = None) -> str:
    ws = normalize_workspace_id(workspace_id or load_persisted_workspace_id())
    return f'Profile: {workspace_label(ws)}'


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
