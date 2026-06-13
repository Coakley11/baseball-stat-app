"""Canonical Live Draft Room state — JSON-safe persistence for board, pool, and settings."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

LIVE_DRAFT_STATE_KEY = "live_draft_state"
LIVE_DRAFT_ROOM_KEY = "live_draft_room"
LIVE_DRAFT_DIRTY_KEY = "live_draft_state_dirty"
LIVE_DRAFT_LOCAL_EDIT_TS_KEY = "live_draft_state_last_local_edit_ts"
LIVE_DRAFT_PAGE_BLOCK = "Live Draft Room"
LIVE_DRAFT_PERSIST_SCHEMA = 1

LIVE_DRAFT_SETTINGS_KEYS = (
    "live_draft_league_name",
    "live_draft_team_count",
    "live_draft_num_teams",
    "live_draft_picks_per_team",
    "live_draft_type",
    "live_draft_scoring",
    "live_draft_timer",
    "live_draft_auto_rule",
    "live_draft_proj_style",
    "live_draft_proj_window",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    return str(value)


def is_runtime_room(room: Any) -> bool:
    if not isinstance(room, dict):
        return False
    pool = room.get("pool")
    return pool is None or hasattr(pool, "to_dict")


def is_persisted_room_blob(data: Any) -> bool:
    return isinstance(data, dict) and (
        "pool_records" in data or data.get("_persist_schema") == LIVE_DRAFT_PERSIST_SCHEMA
    )


def room_to_persist_dict(room: dict[str, Any] | None) -> dict[str, Any]:
    """Convert in-memory live draft room to JSON-safe canonical blob."""
    if not room:
        return {}
    out: dict[str, Any] = {}
    for key, val in room.items():
        if key == "pool":
            pool = val
            if pool is None:
                out["pool_records"] = []
                out["pool_columns"] = []
            elif hasattr(pool, "to_dict"):
                out["pool_records"] = _json_safe(pool.to_dict(orient="records"))
                out["pool_columns"] = [str(c) for c in pool.columns]
            elif isinstance(val, dict) and "pool_records" in val:
                out["pool_records"] = _json_safe(val.get("pool_records") or [])
                out["pool_columns"] = [str(c) for c in (val.get("pool_columns") or [])]
            else:
                out["pool_records"] = []
                out["pool_columns"] = []
        else:
            out[key] = _json_safe(val)
    out.pop("pool", None)
    out["timer_started_at"] = None
    out["timer_handled_index"] = -1
    if room.get("status") == "in_progress":
        out["_resume_timer_on_load"] = True
    out["_persist_schema"] = LIVE_DRAFT_PERSIST_SCHEMA
    out["_persisted_at"] = _utc_now_iso()
    return out


def room_from_persist_dict(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rebuild runtime room (DataFrame pool) from canonical blob."""
    if not isinstance(data, dict) or not data:
        return None
    out = copy.deepcopy(data)
    records = out.pop("pool_records", None)
    columns = out.pop("pool_columns", None)
    out.pop("_persist_schema", None)
    out.pop("_persisted_at", None)
    resume_timer = bool(out.pop("_resume_timer_on_load", False))
    out.pop("pool", None)
    if records is not None:
        if records:
            df = pd.DataFrame(records)
            if columns:
                ordered = [c for c in columns if c in df.columns]
                extras = [c for c in df.columns if c not in ordered]
                df = df[ordered + extras]
        else:
            df = pd.DataFrame(columns=list(columns or []))
        out["pool"] = df
    elif isinstance(data.get("pool"), str):
        out["pool"] = pd.DataFrame()
    if resume_timer and out.get("status") == "in_progress":
        import time

        out["timer_started_at"] = time.time()
    return out


def canonical_live_draft(session: dict[str, Any]) -> dict[str, Any] | None:
    meta = session.get(LIVE_DRAFT_STATE_KEY)
    return copy.deepcopy(meta) if isinstance(meta, dict) and meta.get("draft_room_id") else None


def has_active_live_draft(session: dict[str, Any]) -> bool:
    """True when a resumable live draft exists in session (any page)."""
    blob = canonical_live_draft(session)
    if not blob:
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(room, dict) and room.get("draft_room_id"):
            blob = room_to_persist_dict(room) if is_runtime_room(room) else room
        elif is_persisted_room_blob(room):
            blob = room
    if not isinstance(blob, dict) or not blob.get("draft_room_id"):
        return False
    status = str(blob.get("status") or "").strip()
    return status in ("in_progress", "paused", "not_started")


def is_live_draft_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(LIVE_DRAFT_DIRTY_KEY))


def mark_live_draft_local_edit(session: dict[str, Any]) -> None:
    session[LIVE_DRAFT_DIRTY_KEY] = True
    session[LIVE_DRAFT_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_live_draft_local_edit(session: dict[str, Any]) -> None:
    session.pop(LIVE_DRAFT_DIRTY_KEY, None)
    session.pop(LIVE_DRAFT_LOCAL_EDIT_TS_KEY, None)


def _sync_page_filter_live_draft_block(session: dict[str, Any], *, blob: dict[str, Any] | None = None) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(LIVE_DRAFT_PAGE_BLOCK, {})
    if not isinstance(block, dict):
        block = {}
        pf[LIVE_DRAFT_PAGE_BLOCK] = block
    src = blob if isinstance(blob, dict) else canonical_live_draft(session) or {}
    if src:
        block[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(src)
    for key in LIVE_DRAFT_SETTINGS_KEYS:
        if key in session:
            block[key] = session[key]


def write_canonical_live_draft_state(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    reason: str = "",
    local_edit: bool = False,
) -> dict[str, Any]:
    """Write JSON-safe canonical live_draft_state; mirror runtime room when provided."""
    if room is None:
        session.pop(LIVE_DRAFT_STATE_KEY, None)
        session[LIVE_DRAFT_ROOM_KEY] = None
        _sync_page_filter_live_draft_block(session, blob={})
        if local_edit:
            mark_live_draft_local_edit(session)
        return {}
    blob = room_to_persist_dict(room)
    blob["last_write_reason"] = reason or None
    session[LIVE_DRAFT_STATE_KEY] = blob
    session[LIVE_DRAFT_ROOM_KEY] = room
    _sync_page_filter_live_draft_block(session, blob=blob)
    session["_suite_last_cloud_payload_live_draft"] = {
        "draft_room_id": blob.get("draft_room_id"),
        "current_pick_index": blob.get("current_pick_index"),
        "status": blob.get("status"),
        "board_len": len(blob.get("draft_board") or []),
    }
    if local_edit:
        mark_live_draft_local_edit(session)
    return blob


def clear_live_draft_state(session: dict[str, Any], *, reason: str = "reset") -> None:
    write_canonical_live_draft_state(session, None, reason=reason, local_edit=True)


def prepare_live_draft_state(session: dict[str, Any]) -> dict[str, Any] | None:
    """Hydrate runtime room from canonical blob before Live Draft Room renders."""
    canonical = canonical_live_draft(session)
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if isinstance(canonical, dict) and canonical.get("draft_room_id"):
        restored = room_from_persist_dict(canonical)
        if restored:
            session[LIVE_DRAFT_ROOM_KEY] = restored
            return restored
    if is_runtime_room(room):
        write_canonical_live_draft_state(session, room, reason="session_hydrate", local_edit=False)
        return room
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
        if isinstance(block, dict):
            legacy = block.get(LIVE_DRAFT_ROOM_KEY)
            if is_persisted_room_blob(legacy):
                restored = room_from_persist_dict(legacy)
                if restored:
                    write_canonical_live_draft_state(session, restored, reason="page_filter_hydrate", local_edit=False)
                    return restored
    return room if isinstance(room, dict) else None


def _live_draft_from_blob(state: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    meta = state.get(LIVE_DRAFT_STATE_KEY)
    if isinstance(meta, dict) and meta.get("draft_room_id"):
        return copy.deepcopy(meta)
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
        if isinstance(block, dict):
            legacy = block.get(LIVE_DRAFT_ROOM_KEY)
            if is_persisted_room_blob(legacy):
                return copy.deepcopy(legacy)
    ws = state.get("baseball_workspace_state")
    if isinstance(ws, dict):
        ld = ws.get("live_draft")
        if isinstance(ld, dict) and ld.get("draft_room_id"):
            return copy.deepcopy(ld)
    return None


def apply_cloud_live_draft_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_live_draft_locally_dirty(session):
        return False
    blob = _live_draft_from_blob(state)
    if not blob or not blob.get("draft_room_id"):
        return False
    restored = room_from_persist_dict(blob)
    if not restored:
        return False
    write_canonical_live_draft_state(session, restored, reason="cloud_restore", local_edit=False)
    session["_live_draft_restore_source"] = "cloud_or_workspace"
    return True


def restore_live_draft_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    if is_live_draft_locally_dirty(session):
        return False
    snapshot = store.get(LIVE_DRAFT_PAGE_BLOCK) if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False
    blob = snapshot.get(LIVE_DRAFT_ROOM_KEY)
    if not is_persisted_room_blob(blob):
        return False
    restored = room_from_persist_dict(blob)
    if not restored:
        return False
    write_canonical_live_draft_state(session, restored, reason="page_filter_restore", local_edit=False)
    for key in LIVE_DRAFT_SETTINGS_KEYS:
        if key in snapshot:
            session[key] = snapshot[key]
    return True


def sync_live_draft_session_before_save(session: dict[str, Any]) -> None:
    """Ensure canonical live_draft_state matches runtime room before any persistence."""
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if is_runtime_room(room) and isinstance(room, dict) and room.get("draft_room_id"):
        write_canonical_live_draft_state(
            session,
            room,
            reason="pre_save_sync",
            local_edit=is_live_draft_locally_dirty(session),
        )
    elif is_persisted_room_blob(room) and isinstance(room, dict) and room.get("draft_room_id"):
        restored = room_from_persist_dict(room)
        if restored:
            write_canonical_live_draft_state(session, restored, reason="pre_save_sync", local_edit=False)


def enrich_save_payload_with_live_draft(
    session: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Inject JSON-safe live_draft_state into the workspace blob when session has a draft."""
    diag: dict[str, Any] = {
        "injected_from_session": False,
        "cloud_payload_has_live_draft_state": False,
        "cloud_payload_pick_count": 0,
        "cloud_payload_pool_count": 0,
    }
    sync_live_draft_session_before_save(session)
    blob = canonical_live_draft(session)
    if not blob or not blob.get("draft_room_id"):
        existing = _live_draft_from_blob(state)
        if existing and existing.get("draft_room_id"):
            blob = existing
        else:
            return state, diag

    if is_persisted_room_blob(blob):
        safe_blob = copy.deepcopy(blob)
    elif is_runtime_room(blob):
        safe_blob = room_to_persist_dict(blob)
    else:
        safe_blob = copy.deepcopy(blob)

    had_payload = bool(_live_draft_from_blob(state))
    out = copy.deepcopy(state)
    out[LIVE_DRAFT_STATE_KEY] = copy.deepcopy(safe_blob)
    out[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(safe_blob)
    pf = out.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        pf = {}
        out["page_filter_state"] = pf
    block = pf.setdefault(LIVE_DRAFT_PAGE_BLOCK, {})
    if isinstance(block, dict):
        block[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(safe_blob)
        for key in LIVE_DRAFT_SETTINGS_KEYS:
            if key in session:
                block[key] = session[key]

    board = safe_blob.get("draft_board") or []
    diag["injected_from_session"] = not had_payload
    diag["cloud_payload_has_live_draft_state"] = True
    diag["cloud_payload_pick_count"] = len(board) if isinstance(board, list) else 0
    diag["cloud_payload_pool_count"] = len(safe_blob.get("pool_records") or [])
    return out, diag


def live_draft_payload_diagnostics(state: dict[str, Any]) -> dict[str, Any]:
    blob = _live_draft_from_blob(state)
    board = (blob.get("draft_board") or []) if isinstance(blob, dict) else []
    return {
        "cloud_payload_has_live_draft_state": bool(isinstance(blob, dict) and blob.get("draft_room_id")),
        "cloud_payload_pick_count": len(board) if isinstance(board, list) else 0,
        "cloud_payload_pool_count": len(blob.get("pool_records") or []) if isinstance(blob, dict) else 0,
    }


def record_live_draft_cloud_save_diagnostics(
    session: dict[str, Any],
    *,
    payload: dict[str, Any],
    enrich_diag: dict[str, Any] | None = None,
    cloud_existing_before: bool = False,
    preserved_on_page_change: bool = False,
) -> None:
    payload_diag = live_draft_payload_diagnostics(payload)
    session["cloud_existing_has_live_draft_state_before_save"] = cloud_existing_before
    session["cloud_live_draft_preserved_on_page_change"] = preserved_on_page_change
    session["cloud_payload_has_live_draft_state"] = payload_diag["cloud_payload_has_live_draft_state"]
    session["cloud_payload_pick_count"] = payload_diag["cloud_payload_pick_count"]
    session["cloud_payload_pool_count"] = payload_diag["cloud_payload_pool_count"]
    if enrich_diag:
        session["live_draft_injected_from_session"] = enrich_diag.get("injected_from_session")


def sanitize_state_dict_for_json(state: dict[str, Any]) -> dict[str, Any]:
    """Ensure full_session blob is JSON-serializable (pool as records, not DataFrame)."""
    out = copy.deepcopy(state)
    pf = out.get("page_filter_state")
    block = pf.get(LIVE_DRAFT_PAGE_BLOCK) if isinstance(pf, dict) else None

    blob: dict[str, Any] | None = None
    room = out.get(LIVE_DRAFT_ROOM_KEY)
    if is_runtime_room(room):
        blob = room_to_persist_dict(room)
    elif is_persisted_room_blob(room):
        blob = copy.deepcopy(room)
    meta = out.get(LIVE_DRAFT_STATE_KEY)
    if blob is None and isinstance(meta, dict) and meta.get("draft_room_id"):
        blob = meta if is_persisted_room_blob(meta) else room_to_persist_dict(meta)
    if blob is None and isinstance(block, dict):
        pr = block.get(LIVE_DRAFT_ROOM_KEY)
        if is_runtime_room(pr):
            blob = room_to_persist_dict(pr)
        elif is_persisted_room_blob(pr):
            blob = copy.deepcopy(pr)

    if blob:
        out[LIVE_DRAFT_STATE_KEY] = copy.deepcopy(blob)
        out[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(blob)
        if isinstance(pf, dict):
            page_block = pf.setdefault(LIVE_DRAFT_PAGE_BLOCK, {})
            if isinstance(page_block, dict):
                page_block[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(blob)
    return out


def live_draft_envelope_summary(state: dict[str, Any]) -> dict[str, Any] | None:
    blob = _live_draft_from_blob(state)
    if not blob:
        return None
    board = blob.get("draft_board") or []
    return {
        "draft_room_id": blob.get("draft_room_id"),
        "status": blob.get("status"),
        "current_pick_index": blob.get("current_pick_index"),
        "board_len": len(board) if isinstance(board, list) else 0,
        "pool_len": len(blob.get("pool_records") or []),
    }


def commit_live_draft_room(st: Any, session: dict[str, Any], room: dict[str, Any] | None, *, reason: str) -> dict[str, Any]:
    """Canonical write + force-save after a live draft mutation."""
    trace: dict[str, Any] = {"reason": reason, "saved": False, "disk": False, "cloud": False, "error": ""}
    if room is None:
        clear_live_draft_state(session, reason=reason)
    else:
        write_canonical_live_draft_state(session, room, reason=reason, local_edit=True)
    blob = canonical_live_draft(session) or {}
    board = blob.get("draft_board") or []
    save_reason = "live_draft_manual_save" if reason == "manual_save" else "live_draft_pick"
    try:
        from baseball_persistent_state import force_save_baseball_state

        trace["saved"] = bool(force_save_baseball_state(st, reason=save_reason))
        trace["disk"] = bool(session.get("_suite_persist_last_save_disk"))
        trace["cloud"] = bool(session.get("_suite_persist_last_save_cloud"))
        trace["cloud_payload_has_live_draft_state"] = bool(session.get("cloud_payload_has_live_draft_state"))
        trace["cloud_payload_pick_count"] = session.get("cloud_payload_pick_count")
        trace["cloud_payload_pool_count"] = session.get("cloud_payload_pool_count")
        if session.get("_suite_persist_last_cloud_error"):
            trace["error"] = str(session.get("_suite_persist_last_cloud_error"))
        elif session.get("_suite_autosave_last_error"):
            trace["error"] = str(session.get("_suite_autosave_last_error"))
        elif session.get("_suite_autosave_cloud_blocked_reason"):
            trace["error"] = f"cloud_blocked:{session.get('_suite_autosave_cloud_blocked_reason')}"
        elif trace["cloud"] and not trace["cloud_payload_has_live_draft_state"]:
            trace["error"] = "cloud_saved_without_live_draft_state"
        if trace["saved"] and trace["cloud"] and trace["cloud_payload_has_live_draft_state"]:
            clear_live_draft_local_edit(session)
        elif trace["saved"] and not trace["cloud"]:
            trace["error"] = trace.get("error") or "cloud_write_failed"
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
    trace.update(
        {
            "last_live_draft_save_reason": save_reason,
            "last_live_draft_save_success": bool(
                trace["saved"] and trace["cloud"] and trace.get("cloud_payload_has_live_draft_state")
            ),
            "last_live_draft_save_error": trace.get("error") or "",
            "saved_live_draft_state_present": bool(blob.get("draft_room_id")),
            "saved_pick_count": len(board) if isinstance(board, list) else 0,
            "saved_current_pick_index": blob.get("current_pick_index"),
            "saved_pool_count": len(blob.get("pool_records") or []),
            "saved_cloud": trace["cloud"],
            "saved_disk": trace["disk"],
        }
    )
    session["_live_draft_last_save_trace"] = trace
    session["last_live_draft_save_reason"] = save_reason
    session["last_live_draft_save_success"] = trace["last_live_draft_save_success"]
    session["last_live_draft_save_error"] = trace["last_live_draft_save_error"]
    session["saved_live_draft_state_present"] = trace["saved_live_draft_state_present"]
    session["saved_pick_count"] = trace["saved_pick_count"]
    session["saved_current_pick_index"] = trace["saved_current_pick_index"]
    session["saved_pool_count"] = trace["saved_pool_count"]
    return trace


def verify_json_serializable(state: dict[str, Any]) -> tuple[bool, str]:
    try:
        json.dumps(sanitize_state_dict_for_json(state), ensure_ascii=False)
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def live_draft_restore_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Developer Mode fields for restore path."""
    blob = canonical_live_draft(session) or {}
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    pool_len = 0
    if isinstance(room, dict) and is_runtime_room(room):
        pool = room.get("pool")
        pool_len = len(pool) if hasattr(pool, "__len__") else 0
    elif blob:
        pool_len = len(blob.get("pool_records") or [])
    board = blob.get("draft_board") or []
    return {
        "live_draft_restore_source": session.get("_live_draft_restore_source"),
        "live_draft_state_present": bool(blob.get("draft_room_id")),
        "live_draft_room_hydrated": isinstance(room, dict) and is_runtime_room(room),
        "restored_pick_count": len(board) if isinstance(board, list) else 0,
        "restored_current_pick_index": blob.get("current_pick_index"),
        "restored_pool_count": pool_len,
        "restored_status": blob.get("status"),
        "live_draft_locally_dirty": is_live_draft_locally_dirty(session),
    }


def render_live_draft_save_diagnostics(st: Any) -> None:
    """Developer Mode panel for last live draft save and restore."""
    ss = st.session_state
    trace = ss.get("_live_draft_last_save_trace")
    restore = live_draft_restore_diagnostics(ss)
    with st.expander("Live draft save / restore trace", expanded=False):
        st.markdown("**Last save**")
        if isinstance(trace, dict):
            for key, val in trace.items():
                st.text(f"{key}: {val}")
        else:
            st.text("last_save_trace: (none)")
        st.markdown("**Restore (this session)**")
        for key, val in restore.items():
            st.text(f"{key}: {val}")
        st.text(f"cloud_autosave_blocked: {ss.get('_suite_autosave_cloud_blocked_reason')}")
        st.text(f"cloud_existing_has_live_draft_state_before_save: {ss.get('cloud_existing_has_live_draft_state_before_save')}")
        st.text(f"cloud_live_draft_preserved_on_page_change: {ss.get('cloud_live_draft_preserved_on_page_change')}")
        st.text(f"cloud_payload_has_live_draft_state: {ss.get('cloud_payload_has_live_draft_state')}")
        st.text(f"cloud_payload_pick_count: {ss.get('cloud_payload_pick_count')}")
        st.text(f"cloud_payload_pool_count: {ss.get('cloud_payload_pool_count')}")
        st.text(f"persist_restore_applied: {ss.get('_suite_persist_restore_applied')}")
        st.text(f"persist_restore_source: {ss.get('_suite_persist_last_restore_source')}")
        ok, err = verify_json_serializable(
            {"live_draft_state": ss.get(LIVE_DRAFT_STATE_KEY), "live_draft_room": ss.get(LIVE_DRAFT_ROOM_KEY)}
        )
        st.text(f"json_serializable: {ok}")
        if err:
            st.text(f"json_error: {err}")
