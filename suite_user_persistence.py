"""
Per-app persistent user state for Daniel AI Streamlit apps.

Each app stores JSON under ``data/{app_id}_user_state.json``. Loads are defensive:
missing or corrupt files fall back to defaults without crashing.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

STATE_VERSION = 1
DATA_DIR = Path(__file__).resolve().parent / "data"

# App ids must match keys used across the suite (command center registry).
APP_IDS = frozenset({"music", "investment", "baseball", "basketball", "nba"})

_LEGACY_COMBINED_FILE = DATA_DIR / "app_state.json"

_SESSION_RESTORED_PREFIX = "_suite_disk_state_restored::"
_SESSION_BANNER_KEY = "_suite_persist_banner"
_SESSION_SAVED_FLASH_KEY = "_suite_persist_saved_flash"
_SESSION_INVALID_WARN_KEY = "_suite_persist_invalid_warn"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def state_file_path(app_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(app_id or "app"))
    return DATA_DIR / f"{safe}_user_state.json"


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


def _migrate_legacy_combined(app_id: str) -> dict[str, Any] | None:
    """One-time read from legacy ``data/app_state.json`` nested by app key."""
    combined = _read_json(_LEGACY_COMBINED_FILE)
    if not combined:
        return None
    block = combined.get(app_id)
    if not isinstance(block, dict):
        return None
    out = {k: v for k, v in block.items() if k != "updated_at"}
    out["version"] = STATE_VERSION
    out["saved_at"] = block.get("updated_at") or _utc_now_iso()
    _write_json(state_file_path(app_id), out)
    return out


def load_user_state(app_id: str) -> tuple[dict[str, Any], str | None]:
    """
    Return ``(state_dict, warning_message)``.

    ``state_dict`` is empty when nothing valid was loaded.
    """
    path = state_file_path(app_id)
    raw = _read_json(path)
    if raw is None:
        raw = _migrate_legacy_combined(app_id)
    if raw is None:
        return {}, None

    version = raw.get("version", STATE_VERSION)
    if version != STATE_VERSION:
        return {}, f"Saved settings used an older format (v{version}); using defaults."

    state = raw.get("state")
    if not isinstance(state, dict):
        return {}, "Saved settings were invalid; using defaults."

    try:
        return copy.deepcopy(state), None
    except Exception:
        return {}, "Could not read saved settings; using defaults."


def save_user_state(app_id: str, state: dict[str, Any]) -> bool:
    if not isinstance(state, dict):
        return False
    payload = {
        "version": STATE_VERSION,
        "app": app_id,
        "saved_at": _utc_now_iso(),
        "state": state,
    }
    return _write_json(state_file_path(app_id), payload)


def reset_user_state(app_id: str) -> bool:
    path = state_file_path(app_id)
    try:
        if path.is_file():
            path.unlink()
        return True
    except OSError:
        return False


def restore_once(
    st: Any,
    app_id: str,
    *,
    apply_state: Callable[[Any, dict[str, Any]], None],
) -> bool:
    """Load disk state into session once per browser session."""
    flag = f"{_SESSION_RESTORED_PREFIX}{app_id}"
    if st.session_state.get(flag):
        return False
    st.session_state[flag] = True

    loaded, warning = load_user_state(app_id)
    if warning:
        st.session_state[_SESSION_INVALID_WARN_KEY] = warning
    if not loaded:
        return False

    try:
        apply_state(st, loaded)
    except Exception:
        st.session_state[_SESSION_INVALID_WARN_KEY] = (
            "Some saved settings could not be restored; using defaults."
        )
        return False

    st.session_state[_SESSION_BANNER_KEY] = "Loaded your last session"
    return True


def autosave_if_changed(
    st: Any,
    app_id: str,
    *,
    build_state: Callable[[Any], dict[str, Any]],
) -> None:
    """Persist when the built snapshot fingerprint changes."""
    try:
        import hashlib

        state = build_state(st)
        blob = json.dumps(state, sort_keys=True, default=str)
        fp = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
        key = f"_suite_autosave_fp::{app_id}"
        if st.session_state.get(key) == fp:
            return
        if save_user_state(app_id, state):
            st.session_state[key] = fp
            st.session_state[_SESSION_SAVED_FLASH_KEY] = True
    except Exception:
        pass


def show_persistence_messages(st: Any) -> None:
    warn = st.session_state.pop(_SESSION_INVALID_WARN_KEY, None)
    if warn:
        st.warning(str(warn))
    banner = st.session_state.pop(_SESSION_BANNER_KEY, None)
    if banner:
        st.success(str(banner))
    if st.session_state.pop(_SESSION_SAVED_FLASH_KEY, False):
        st.toast("Settings saved", icon="💾")


def render_reset_controls(
    st: Any,
    app_id: str,
    *,
    on_reset: Callable[[Any], None],
    label: str = "Reset to Default Settings",
    help_text: str = "Clears your saved session for this app only. Core catalog data is not deleted.",
) -> None:
    """Sidebar expander with confirmed reset."""
    with st.sidebar.expander("Saved session", expanded=False):
        st.caption("Your last page, filters, and inputs reload automatically.")
        confirm_key = f"_suite_reset_confirm::{app_id}"
        if st.session_state.get(confirm_key):
            st.warning("This clears saved preferences for this app. Continue?")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Yes, reset", key=f"suite_reset_yes::{app_id}", type="primary"):
                    reset_user_state(app_id)
                    for k in list(st.session_state.keys()):
                        if str(k).startswith(_SESSION_RESTORED_PREFIX) or str(k).startswith(
                            "_suite_autosave_fp::"
                        ):
                            st.session_state.pop(k, None)
                    st.session_state.pop(confirm_key, None)
                    on_reset(st)
                    st.session_state[_SESSION_BANNER_KEY] = "Reset to defaults"
                    st.rerun()
            with c2:
                if st.button("Cancel", key=f"suite_reset_no::{app_id}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
        elif st.button(label, key=f"suite_reset_btn::{app_id}", help=help_text):
            st.session_state[confirm_key] = True
            st.rerun()
