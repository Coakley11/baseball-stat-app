"""
Per-app persistent user state for Daniel AI Streamlit apps.

Local JSON under ``data/{app_id}_user_state.json`` plus optional Supabase
``metrics.full_session`` for cross-device restore on direct app open.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

STATE_VERSION = 1
DATA_DIR = Path(__file__).resolve().parent / "data"

APP_IDS = frozenset(
    {"music", "investment", "baseball", "basketball", "nba", "future_lens"}
)

_LEGACY_COMBINED_FILE = DATA_DIR / "app_state.json"

_SESSION_RESTORED_PREFIX = "_suite_disk_state_restored::"
_SESSION_BANNER_KEY = "_suite_persist_banner"
_SESSION_SAVED_FLASH_KEY = "_suite_persist_saved_flash"
_SESSION_INVALID_WARN_KEY = "_suite_persist_invalid_warn"
_SESSION_CLOUD_BANNER_KEY = "_suite_persist_cloud_banner"
_LOCAL_DIRTY_PREFIX = "_suite_persist_local_dirty::"
_APPLIED_CLOUD_TS_PREFIX = "_suite_applied_cloud_ts::"
_RESTORED_FP_PREFIX = "_suite_restored_state_fp::"


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


def _load_raw(app_id: str) -> tuple[dict[str, Any], str | None, str | None]:
    """Return ``(state_dict, warning, saved_at_iso)``."""
    path = state_file_path(app_id)
    raw = _read_json(path)
    if raw is None:
        raw = _migrate_legacy_combined(app_id)
    if raw is None:
        return {}, None, None

    version = raw.get("version", STATE_VERSION)
    if version != STATE_VERSION:
        return {}, f"Saved settings used an older format (v{version}); using defaults.", None

    state = raw.get("state")
    if not isinstance(state, dict):
        return {}, "Saved settings were invalid; using defaults.", None

    saved_at = str(raw.get("saved_at") or "") or None
    try:
        return copy.deepcopy(state), None, saved_at
    except Exception:
        return {}, "Could not read saved settings; using defaults.", None


def load_user_state(app_id: str) -> tuple[dict[str, Any], str | None]:
    state, warning, _ = _load_raw(app_id)
    return state, warning


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


def _local_dirty_key(app_id: str) -> str:
    return f"{_LOCAL_DIRTY_PREFIX}{app_id}"


def _applied_cloud_ts_key(app_id: str) -> str:
    return f"{_APPLIED_CLOUD_TS_PREFIX}{app_id}"


def _restored_fp_key(app_id: str) -> str:
    return f"{_RESTORED_FP_PREFIX}{app_id}"


def _record_restore_debug_meta(
    st: Any,
    app_id: str,
    *,
    cloud_ts: str | None,
    disk_ts: str | None,
    pick_source: str,
    pick_reason: str,
    local_dirty: bool,
) -> None:
    st.session_state["_suite_persist_debug_cloud_ts"] = cloud_ts
    st.session_state["_suite_persist_debug_disk_ts"] = disk_ts
    st.session_state["_suite_persist_debug_pick_source"] = pick_source
    st.session_state["_suite_persist_debug_pick_reason"] = pick_reason
    st.session_state[_local_dirty_key(app_id)] = local_dirty


def _set_restore_skip_reason(st: Any, reason: str) -> None:
    st.session_state["_suite_persist_restore_skip_reason"] = reason


def restore_once(
    st: Any,
    app_id: str,
    *,
    apply_state: Callable[[Any, dict[str, Any]], None],
) -> bool:
    """
    Restore on direct open; re-apply when cloud is newer than last apply.

    Skipped when Continue/deep-link query params are present, or when this
    device has unsaved local edits (``_suite_persist_local_dirty``).
    """
    st.session_state["_suite_persist_app_id"] = app_id
    st.session_state.pop("_suite_persist_restore_skip_reason", None)
    flag = f"{_SESSION_RESTORED_PREFIX}{app_id}"
    dirty_key = _local_dirty_key(app_id)
    applied_cloud_key = _applied_cloud_ts_key(app_id)
    local_dirty = bool(st.session_state.get(dirty_key))

    disk_state, disk_warn, disk_ts = _load_raw(app_id)
    if disk_warn:
        st.session_state[_SESSION_INVALID_WARN_KEY] = disk_warn

    skip_cloud = False
    try:
        from suite_cloud_state import has_resume_query_params

        skip_cloud = has_resume_query_params(st, app_id)
    except ImportError:
        pass

    if skip_cloud:
        _set_restore_skip_reason(st, "resume query params or deep-link launch (restore skipped)")
        st.session_state[flag] = True
        _record_restore_debug_meta(
            st,
            app_id,
            cloud_ts=None,
            disk_ts=disk_ts,
            pick_source="skipped",
            pick_reason="resume query params",
            local_dirty=local_dirty,
        )
        return False

    cloud_state: dict[str, Any] = {}
    cloud_ts: str | None = None
    pick_source = "none"
    pick_reason = "none"
    from_cloud = False
    state: dict[str, Any] = {}

    try:
        from suite_cloud_state import load_cloud_full_session, pick_restore_session, parse_persist_timestamp

        cloud_state, cloud_ts = load_cloud_full_session(app_id)
        already_restored = st.session_state.get(flag)
        applied_cloud_ts = st.session_state.get(applied_cloud_key)

        if already_restored:
            if local_dirty:
                _set_restore_skip_reason(st, "already restored this session; local unsaved edits")
                _record_restore_debug_meta(
                    st,
                    app_id,
                    cloud_ts=cloud_ts,
                    disk_ts=disk_ts,
                    pick_source="skipped",
                    pick_reason="local unsaved edits",
                    local_dirty=True,
                )
                return False
            if cloud_state and parse_persist_timestamp(cloud_ts) <= parse_persist_timestamp(applied_cloud_ts):
                _set_restore_skip_reason(st, "already restored this session; cloud not newer than last apply")
                _record_restore_debug_meta(
                    st,
                    app_id,
                    cloud_ts=cloud_ts,
                    disk_ts=disk_ts,
                    pick_source="skipped",
                    pick_reason="cloud not newer than last apply",
                    local_dirty=False,
                )
                return False

        picked = pick_restore_session(
            cloud_state,
            cloud_ts,
            disk_state,
            disk_ts,
            local_dirty=local_dirty,
        )
        state = picked.state
        pick_source = picked.source
        pick_reason = picked.reason
        from_cloud = picked.source == "cloud"

        st.session_state["_suite_persist_debug_cloud_ts"] = cloud_ts
        st.session_state["_suite_persist_debug_disk_ts"] = disk_ts
        st.session_state["_suite_persist_debug_pick_source"] = pick_source
        st.session_state["_suite_persist_debug_pick_reason"] = pick_reason
    except ImportError:
        state = disk_state
        pick_source = "disk"
        pick_reason = "cloud module missing"
        _set_restore_skip_reason(st, "cloud module missing; disk-only pick")
    except Exception as exc:
        state = disk_state
        pick_source = "disk"
        pick_reason = "cloud load error"
        _set_restore_skip_reason(st, f"cloud load error: {exc}; disk-only pick")

    if not state:
        _set_restore_skip_reason(
            st,
            "no restore source loaded "
            f"(cloud_blob={'yes' if cloud_state else 'no'}, disk_blob={'yes' if disk_state else 'no'}, "
            f"pick_reason={pick_reason!r})",
        )
        return False

    try:
        apply_state(st, state)
    except Exception as exc:
        _set_restore_skip_reason(st, f"apply_state failed: {exc}")
        st.session_state[_SESSION_INVALID_WARN_KEY] = (
            "Some saved settings could not be restored; using defaults."
        )
        return False

    st.session_state[flag] = True

    try:
        import hashlib
        import json

        blob = json.dumps(state, sort_keys=True, default=str)
        st.session_state[_restored_fp_key(app_id)] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
    except Exception:
        pass

    st.session_state[applied_cloud_key] = cloud_ts
    st.session_state[dirty_key] = False

    if from_cloud:
        save_user_state(app_id, state)

    st.session_state["_suite_persist_last_restore_at"] = _utc_now_iso()
    st.session_state["_suite_persist_last_restore_source"] = pick_source
    st.session_state["_suite_persist_last_restore_reason"] = pick_reason

    if from_cloud:
        st.session_state[_SESSION_CLOUD_BANNER_KEY] = True
    else:
        st.session_state[_SESSION_BANNER_KEY] = "Loaded your last session"
    return True


def _parse_ts_simple(ts: str | None) -> float:
    try:
        from suite_cloud_state import parse_persist_timestamp

        return parse_persist_timestamp(ts)
    except ImportError:
        if not ts:
            return 0.0
        try:
            return datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00")[:26]).timestamp()
        except ValueError:
            return 0.0


def autosave_if_changed(
    st: Any,
    app_id: str,
    *,
    build_state: Callable[[Any], dict[str, Any]],
) -> None:
    """Persist to disk and Supabase when the session snapshot changes."""
    try:
        import hashlib

        state = build_state(st)
        blob = json.dumps(state, sort_keys=True, default=str)
        fp = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
        key = f"_suite_autosave_fp::{app_id}"
        restored_fp = st.session_state.get(_restored_fp_key(app_id))
        if restored_fp and fp != restored_fp:
            st.session_state[_local_dirty_key(app_id)] = True
        if st.session_state.get(key) == fp:
            return
        saved_disk = save_user_state(app_id, state)
        saved_cloud = False
        cloud_err = ""
        try:
            from suite_cloud_state import save_cloud_full_session, session_page_summary

            page, summary = session_page_summary(app_id, state)
            saved_cloud = bool(
                save_cloud_full_session(app_id, state, page=page, summary=summary)
            )
        except Exception as exc:
            cloud_err = str(exc)
        if saved_disk or saved_cloud:
            st.session_state[key] = fp
            st.session_state[_restored_fp_key(app_id)] = fp
            if saved_cloud:
                st.session_state[_local_dirty_key(app_id)] = False
                st.session_state[_applied_cloud_ts_key(app_id)] = _utc_now_iso()
            st.session_state["_suite_persist_last_save_at"] = _utc_now_iso()
            st.session_state["_suite_persist_last_save_disk"] = saved_disk
            st.session_state["_suite_persist_last_save_cloud"] = saved_cloud
            if cloud_err:
                st.session_state["_suite_persist_last_cloud_error"] = cloud_err
            st.session_state[_SESSION_SAVED_FLASH_KEY] = True
    except Exception:
        pass


def show_persistence_messages(st: Any) -> None:
    warn = st.session_state.pop(_SESSION_INVALID_WARN_KEY, None)
    if warn:
        st.warning(str(warn))
    if st.session_state.pop(_SESSION_CLOUD_BANNER_KEY, None):
        st.success("Restored your last session from the cloud")
    else:
        banner = st.session_state.pop(_SESSION_BANNER_KEY, None)
        if banner:
            st.success(str(banner))
    if st.session_state.pop(_SESSION_SAVED_FLASH_KEY, False):
        st.toast("Settings saved", icon="💾")


def reset_confirm_session_key(app_id: str) -> str:
    return f"_suite_reset_confirm::{app_id}"


def clear_reset_confirm_state(session_state: Any, app_id: str) -> None:
    session_state.pop(reset_confirm_session_key(app_id), None)


def request_reset_confirm_state(session_state: Any, app_id: str) -> None:
    session_state[reset_confirm_session_key(app_id)] = True


def _clear_suite_reset_cache_keys(
    session_state: Any,
    app_id: str,
    *,
    extra_prefixes: tuple[str, ...] = (),
) -> None:
    prefixes = (_SESSION_RESTORED_PREFIX, "_suite_autosave_fp::", *extra_prefixes)
    confirm_key = reset_confirm_session_key(app_id)
    for key in list(session_state.keys()):
        sk = str(key)
        if sk == confirm_key:
            session_state.pop(key, None)
            continue
        if any(sk.startswith(prefix) for prefix in prefixes):
            session_state.pop(key, None)


def execute_suite_reset(
    st: Any,
    app_id: str,
    on_reset: Callable[[Any], None],
    *,
    extra_prefixes: tuple[str, ...] = (),
) -> None:
    session_state = st.session_state
    clear_reset_confirm_state(session_state, app_id)
    reset_user_state(app_id)
    _clear_suite_reset_cache_keys(session_state, app_id, extra_prefixes=extra_prefixes)
    on_reset(st)
    session_state[_SESSION_BANNER_KEY] = "Reset to defaults"


def render_reset_controls(
    st: Any,
    app_id: str,
    *,
    on_reset: Callable[[Any], None],
    label: str = "Reset to default",
    help_text: str = "Clears your saved session for this app only.",
    extra_reset_clear_prefixes: tuple[str, ...] = (
        _LOCAL_DIRTY_PREFIX,
        _APPLIED_CLOUD_TS_PREFIX,
        _RESTORED_FP_PREFIX,
    ),
) -> None:
    pending = bool(st.session_state.get(reset_confirm_session_key(app_id)))
    with st.sidebar.expander("Saved session", expanded=pending):
        st.caption("Your last page, filters, and inputs reload automatically.")
        if pending:
            st.warning("This clears saved preferences for this app. Continue?")
            c1, c2 = st.columns(2)
            with c1:
                st.button(
                    "Yes, reset",
                    key=f"suite_reset_yes::{app_id}",
                    type="primary",
                    on_click=execute_suite_reset,
                    kwargs={
                        "st": st,
                        "app_id": app_id,
                        "on_reset": on_reset,
                        "extra_prefixes": extra_reset_clear_prefixes,
                    },
                )
            with c2:
                st.button(
                    "Cancel",
                    key=f"suite_reset_no::{app_id}",
                    on_click=clear_reset_confirm_state,
                    kwargs={"session_state": st.session_state, "app_id": app_id},
                )
        else:
            st.button(
                label,
                key=f"suite_reset_btn::{app_id}",
                help=help_text,
                on_click=request_reset_confirm_state,
                kwargs={"session_state": st.session_state, "app_id": app_id},
            )


def finalize_suite_reset(
    st: Any,
    app_id: str,
    fresh_state: dict[str, Any],
    *,
    page: str = "",
    summary: str = "Reset to defaults",
) -> None:
    """Persist fresh defaults to disk and cloud after ``reset_user_state`` removed the local file."""
    save_user_state(app_id, fresh_state)
    try:
        from suite_cloud_state import (
            clear_cloud_full_session,
            save_cloud_full_session,
            session_page_summary,
        )

        clear_cloud_full_session(app_id)
        auto_page, auto_summary = session_page_summary(app_id, fresh_state)
        save_cloud_full_session(
            app_id,
            fresh_state,
            page=page or auto_page,
            summary=summary or auto_summary or "Reset to defaults",
        )
    except Exception:
        pass
    st.session_state[f"{_SESSION_RESTORED_PREFIX}{app_id}"] = True
    st.session_state.pop(f"_suite_autosave_fp::{app_id}", None)
    st.session_state.pop(_local_dirty_key(app_id), None)
    st.session_state.pop(_applied_cloud_ts_key(app_id), None)
    st.session_state.pop(_restored_fp_key(app_id), None)
