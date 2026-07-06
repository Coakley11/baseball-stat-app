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
MANUAL_PICK_SNAPSHOT_KEY = "_manual_pick_commit_snapshot"
LIVE_DRAFT_PREPARE_FP_KEY = "_live_draft_prepare_fingerprint"
LIVE_DRAFT_FORCE_PREPARE_KEY = "_live_draft_force_prepare"
LIVE_DRAFT_BOARD_SYNC_PENDING_KEY = "_live_draft_board_sync_pending"
LIVE_DRAFT_DEFERRED_PICK_ACTIVITY_KEY = "_live_draft_deferred_pick_activity"
LIVE_DRAFT_PAGE_BLOCK = "Live Draft Room"
LIVE_DRAFT_OWNER_AUTH_KEY = "owner_auth_user_id"
LIVE_DRAFT_OWNER_EXTERNAL_KEY = "owner_external_id"
LIVE_DRAFT_OWNER_WORKSPACE_KEY = "owner_workspace_id"
from draft_scoring_pool import (
    LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS,
    prepare_pool_for_compact_serialization,
    select_live_draft_compact_columns,
)

LIVE_DRAFT_PERSIST_SCHEMA = 1


def _developer_ui_visible(st: Any) -> bool:
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        return developer_mode_checkbox_enabled(st=st)
    except ImportError:
        return False


def _current_auth_user_id(session: dict[str, Any]) -> str:
    try:
        from suite_auth import AUTH_USER_ID_KEY, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(session):
            return str(session.get(AUTH_USER_ID_KEY) or "").strip()
    except ImportError:
        pass
    return ""


def _current_auth_external_id(session: dict[str, Any]) -> str:
    try:
        from suite_auth import is_auth_enabled, is_authenticated, resolve_auth_external_id

        if is_auth_enabled() and is_authenticated(session):
            return str(resolve_auth_external_id(session) or "").strip()
    except ImportError:
        pass
    return ""


def _current_workspace_id(session: dict[str, Any]) -> str:
    try:
        from suite_workspace import get_active_workspace_id

        return str(get_active_workspace_id(st=type("S", (), {"session_state": session})()) or "")
    except ImportError:
        return ""


def _stamp_live_draft_owner(session: dict[str, Any], blob: dict[str, Any]) -> None:
    auth_uid = _current_auth_user_id(session)
    if auth_uid:
        blob[LIVE_DRAFT_OWNER_AUTH_KEY] = auth_uid
    ext = _current_auth_external_id(session)
    if ext:
        blob[LIVE_DRAFT_OWNER_EXTERNAL_KEY] = ext
    ws = _current_workspace_id(session)
    if ws:
        blob[LIVE_DRAFT_OWNER_WORKSPACE_KEY] = ws


def live_draft_blob_owner_auth_id(blob: dict[str, Any] | None) -> str:
    if not isinstance(blob, dict):
        return ""
    return str(blob.get(LIVE_DRAFT_OWNER_AUTH_KEY) or "").strip()


def live_draft_restore_allowed(
    session: dict[str, Any],
    blob: dict[str, Any] | None,
    *,
    source: str = "",
) -> tuple[bool, str]:
    """Return (allowed, reason) for applying a persisted live draft blob."""
    if not isinstance(blob, dict) or not blob.get("draft_room_id"):
        return False, "empty_blob"
    try:
        from suite_auth import is_auth_enabled, is_authenticated
    except ImportError:
        return True, "auth_module_missing"

    if not is_auth_enabled() or not is_authenticated(session):
        return True, "auth_disabled"

    current_auth = _current_auth_user_id(session)
    owner_auth = live_draft_blob_owner_auth_id(blob)
    if owner_auth:
        if not current_auth:
            return False, "auth_required_for_owned_blob"
        if owner_auth != current_auth:
            return False, "auth_user_mismatch"
        return True, "auth_owner_match"

    owner_ext = str(blob.get(LIVE_DRAFT_OWNER_EXTERNAL_KEY) or "").strip()
    current_ext = _current_auth_external_id(session)
    if owner_ext and current_ext and owner_ext != current_ext:
        return False, "external_id_mismatch"

    owner_ws = str(blob.get(LIVE_DRAFT_OWNER_WORKSPACE_KEY) or "").strip()
    current_ws = _current_workspace_id(session)
    if owner_ws and current_ws and owner_ws != current_ws:
        return False, "workspace_mismatch"

    # Legacy blob without owner stamp — only Daniel may load from shared daniel workspace.
    if current_ext and current_ext not in ("daniel", ""):
        return False, "legacy_unowned_foreign_blob"
    if current_ws and current_ws not in ("daniel", ""):
        return False, "legacy_unowned_foreign_workspace"
    return True, f"legacy_allowed:{source or 'unknown'}"


def clear_foreign_live_draft_state(session: dict[str, Any], *, reason: str) -> None:
    session.pop(LIVE_DRAFT_STATE_KEY, None)
    session.pop(LIVE_DRAFT_ROOM_KEY, None)
    session["_live_draft_restore_blocked_reason"] = reason
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
        if isinstance(block, dict):
            block.pop(LIVE_DRAFT_ROOM_KEY, None)


def workspace_blob_owned_by_session(session: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str]:
    """True when a full workspace restore blob belongs to the signed-in user."""
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        if not is_auth_enabled() or not is_authenticated(session):
            return True, "auth_disabled"
    except ImportError:
        return True, "auth_module_missing"

    current_ext = _current_auth_external_id(session)
    current_ws = _current_workspace_id(session)
    if current_ext and current_ext not in ("daniel", "") and current_ws == "daniel":
        return False, "foreign_daniel_workspace"

    blob = _live_draft_from_blob(state)
    if isinstance(blob, dict) and blob.get("draft_room_id"):
        allowed, reason = live_draft_restore_allowed(session, blob, source="workspace_blob")
        if not allowed:
            return False, reason

    if current_ext and current_ext not in ("daniel", ""):
        owner_ext = str((blob or {}).get(LIVE_DRAFT_OWNER_EXTERNAL_KEY) or "").strip()
        if owner_ext and owner_ext != current_ext:
            return False, "external_id_mismatch"
        try:
            from suite_user import get_external_user_id

            if get_external_user_id() == "daniel" and current_ws != current_ext:
                return False, "legacy_shared_cloud_blob"
        except ImportError:
            pass
    return True, "owned"


def live_draft_identity_diagnostics(session: dict[str, Any]) -> dict[str, str]:
    """Restore ownership trace for runtime acceptance."""
    diag: dict[str, str] = {}
    try:
        from suite_user import get_external_user_id

        diag["suite_external_user_id"] = str(get_external_user_id() or "")
    except ImportError:
        diag["suite_external_user_id"] = ""
    diag["auth_user_id"] = _current_auth_user_id(session)
    diag["auth_external_id"] = _current_auth_external_id(session)
    diag["workspace_owner"] = _current_workspace_id(session)
    diag["restoring_source"] = str(
        session.get("_live_draft_restore_source")
        or session.get("_suite_persist_debug_pick_source")
        or session.get("restore_source")
        or "—"
    )
    diag["restore_blocked_reason"] = str(session.get("_live_draft_restore_blocked_reason") or "—")
    diag["cloud_fetch_user_id"] = str(session.get("_suite_cloud_fetch_user_id") or "—")
    diag["cloud_fetch_app_key"] = str(session.get("_suite_cloud_fetch_app_key") or "—")
    blob = canonical_live_draft(session) or {}
    if isinstance(blob, dict):
        diag["live_draft_owner_auth_uuid"] = live_draft_blob_owner_auth_id(blob) or "—"
        diag["live_draft_owner_external_id"] = str(blob.get(LIVE_DRAFT_OWNER_EXTERNAL_KEY) or "—")
        diag["live_draft_owner_workspace"] = str(blob.get(LIVE_DRAFT_OWNER_WORKSPACE_KEY) or "—")
    else:
        diag["live_draft_owner_auth_uuid"] = "—"
        diag["live_draft_owner_external_id"] = "—"
        diag["live_draft_owner_workspace"] = "—"
    try:
        from draft_actions import draft_action_context

        ctx = draft_action_context(session)
        diag["assigned_team"] = str(ctx.get("your_team") or "—")
        diag["team_source"] = "live_draft_or_participant"
    except ImportError:
        diag["assigned_team"] = str(session.get("room_your_team") or "—")
        diag["team_source"] = "room_your_team"
    return diag


# Compact shared-room pools keep all live-draft scoring columns present in the source frame.
SHARED_DRAFT_POOL_COLUMNS = LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS

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


def room_to_persist_dict(room: dict[str, Any] | None, *, compact_pool: bool = False) -> dict[str, Any]:
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
                frame = pool
                if compact_pool:
                    frame, _compact_report = prepare_pool_for_compact_serialization(frame)
                    cols = select_live_draft_compact_columns(frame)
                    if cols:
                        frame = frame[cols]
                out["pool_records"] = _json_safe(frame.to_dict(orient="records"))
                out["pool_columns"] = [str(c) for c in frame.columns]
            elif isinstance(val, dict) and "pool_records" in val:
                records = val.get("pool_records") or []
                columns = [str(c) for c in (val.get("pool_columns") or [])]
                if compact_pool and records and columns:
                    frame = pd.DataFrame(records, columns=columns) if columns else pd.DataFrame(records)
                    frame, _compact_report = prepare_pool_for_compact_serialization(frame)
                    keep = select_live_draft_compact_columns(frame)
                    if not keep:
                        keep = [c for c in LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS if c in columns]
                    if keep:
                        idx = {c: columns.index(c) for c in keep}
                        slim_records = []
                        for row in records:
                            if isinstance(row, dict):
                                slim_records.append({c: row.get(c) for c in keep})
                            else:
                                slim_records.append({c: row[idx[c]] for c in keep if idx[c] < len(row)})
                        records = slim_records
                        columns = keep
                out["pool_records"] = _json_safe(records)
                out["pool_columns"] = columns
            else:
                out["pool_records"] = []
                out["pool_columns"] = []
        else:
            out[key] = _json_safe(val)
    out.pop("pool", None)
    out["timer_started_at"] = None
    out["timer_handled_index"] = int(room.get("timer_handled_index") or -1)
    status = str(room.get("status") or "")
    if status == "in_progress":
        deadline = room.get("timer_deadline")
        if deadline is None:
            started = room.get("timer_started_at")
            if started is not None:
                deadline = float(started) + int(room.get("config", {}).get("timer_seconds", 60))
        if deadline is not None:
            out["timer_deadline"] = float(deadline)
        else:
            out["_resume_timer_on_load"] = True
    else:
        out["timer_deadline"] = None
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
    persisted_deadline = out.pop("timer_deadline", None)
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
        try:
            from draft_scoring_pool import ensure_draft_scoring_pool_columns

            out["pool"] = ensure_draft_scoring_pool_columns(df)
        except ImportError:
            out["pool"] = df
    elif isinstance(data.get("pool"), str):
        out["pool"] = pd.DataFrame()
    if out.get("status") == "in_progress":
        if persisted_deadline is not None:
            deadline = float(persisted_deadline)
            out["timer_deadline"] = deadline
            timer_secs = int(out.get("config", {}).get("timer_seconds", 60))
            out["timer_started_at"] = deadline - timer_secs
        elif resume_timer:
            import time

            from live_draft_timer_logic import live_draft_reset_timer

            live_draft_reset_timer(out)
    try:
        from live_draft_roster_slots import ensure_room_slot_config

        ensure_room_slot_config(out)
    except ImportError:
        pass
    return out


def analyze_live_draft_progress(room: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize pick progress and why a draft may read as complete."""
    if not isinstance(room, dict):
        return {
            "draft_status": "",
            "shared_document_status": "",
            "current_pick_index": 0,
            "total_picks": 0,
            "drafted_player_count": 0,
            "draft_board_count": 0,
            "draft_complete": True,
            "draft_complete_reason": "no_room",
            "current_pick": None,
            "on_clock_team": None,
            "slot": None,
        }

    pick_order = list(room.get("pick_order") or [])
    idx = int(room.get("current_pick_index") or 0)
    board = room.get("draft_board") or []
    board_count = len(board) if isinstance(board, list) else 0
    drafted_ids = room.get("drafted_player_ids") or []
    drafted_count = len(drafted_ids) if isinstance(drafted_ids, list) else board_count
    total = len(pick_order)

    try:
        from live_draft_safe_mode import compute_draft_status, is_draft_truly_complete, total_expected_picks as _total_expected

        if not total:
            total = _total_expected(room)
        status, _completion_source = compute_draft_status(room)
        draft_complete = bool(total > 0 and is_draft_truly_complete(room))
    except ImportError:
        status = str(room.get("status") or "").strip()
        draft_complete = bool(total > 0 and board_count >= total)

    base: dict[str, Any] = {
        "draft_status": status,
        "shared_document_status": status,
        "current_pick_index": idx,
        "total_picks": total,
        "drafted_player_count": drafted_count,
        "draft_board_count": board_count,
        "draft_complete": draft_complete,
        "draft_complete_reason": "board_full" if draft_complete else "",
        "current_pick": None,
        "on_clock_team": None,
        "slot": None,
    }

    if not pick_order:
        base["draft_complete"] = False
        base["draft_complete_reason"] = "missing_pick_order"
        return base

    if draft_complete:
        return base

    if board_count < total:
        base["draft_complete"] = False
        if idx < board_count:
            idx = board_count
            base["current_pick_index"] = idx
        if idx < len(pick_order):
            slot = pick_order[idx]
            base["slot"] = slot
            try:
                base["current_pick"] = int(slot.get("Pick"))
            except (TypeError, ValueError):
                base["current_pick"] = None
            base["on_clock_team"] = str(slot.get("Team") or "").strip() or None
        if status == "not_started" and board_count == 0:
            base["draft_complete_reason"] = "not_started"
        return base

    slot = pick_order[min(idx, len(pick_order) - 1)] if pick_order else None
    if isinstance(slot, dict):
        base["slot"] = slot
        try:
            base["current_pick"] = int(slot.get("Pick"))
        except (TypeError, ValueError):
            base["current_pick"] = None
        base["on_clock_team"] = str(slot.get("Team") or "").strip() or None

    if status == "not_started" and board_count == 0:
        base["draft_complete_reason"] = "not_started"
    return base


def repair_stale_live_draft_progress(room: dict[str, Any]) -> dict[str, Any]:
    """Correct stale complete status or pick index when hydrating shared rooms."""
    if not isinstance(room, dict):
        return room
    pick_order = list(room.get("pick_order") or [])
    if not pick_order:
        return room

    total = len(pick_order)
    idx = int(room.get("current_pick_index") or 0)
    status = str(room.get("status") or "").strip()
    board = room.get("draft_board") or []
    board_count = len(board) if isinstance(board, list) else 0

    if board_count < total and idx != board_count:
        room["current_pick_index"] = board_count
        if status == "complete":
            room["status"] = "in_progress" if board_count > 0 else "not_started"

    if status == "complete" and board_count < total:
        room["status"] = "in_progress" if board_count > 0 else "not_started"
        room["current_pick_index"] = min(board_count, max(total - 1, 0))

    if int(room.get("current_pick_index") or 0) >= total and board_count < total:
        room["current_pick_index"] = min(board_count, max(total - 1, 0))
        room["status"] = "in_progress" if board_count > 0 else str(room.get("status") or "not_started")

    if status == "complete" and board_count >= total:
        room["current_pick_index"] = total

    return room


def live_draft_get_available(room: dict[str, Any] | None) -> pd.DataFrame:
    """Return undrafted pool rows for manual draft UI."""
    if not isinstance(room, dict):
        return pd.DataFrame()
    pool = room.get("pool")
    if pool is None or getattr(pool, "empty", True):
        records = room.get("pool_records") or []
        columns = room.get("pool_columns") or []
        if records:
            pool = pd.DataFrame(records)
            if columns:
                ordered = [c for c in columns if c in pool.columns]
                extras = [c for c in pool.columns if c not in ordered]
                pool = pool[ordered + extras]
        else:
            return pd.DataFrame()
    if isinstance(pool, pd.DataFrame) and pool.columns.duplicated().any():
        dupes = [str(c) for c in pool.columns[pool.columns.duplicated()].tolist()]
        room["_live_draft_pool_column_diag"] = {
            "duplicate_columns": dupes,
            "deduped": True,
        }
        pool = pool.loc[:, ~pool.columns.duplicated()].copy()
    drafted = set(room.get("drafted_player_ids", []) or [])
    if not drafted:
        out = pool.copy()
    elif "playerID" in pool.columns:
        out = pool[~pool["playerID"].astype(str).isin({str(x) for x in drafted})].copy()
    else:
        out = pool.copy()
    if isinstance(out, pd.DataFrame) and out.columns.duplicated().any():
        dupes = [str(c) for c in out.columns[out.columns.duplicated()].tolist()]
        room["_live_draft_pool_column_diag"] = {
            "duplicate_columns": dupes,
            "deduped": True,
        }
        out = out.loc[:, ~out.columns.duplicated()].copy()
    try:
        from draft_scoring_pool import ensure_draft_scoring_pool_columns_with_report

        out, report = ensure_draft_scoring_pool_columns_with_report(out)
        room["_live_draft_pool_scoring_diag"] = report
    except ImportError:
        pass
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
    return status in ("in_progress", "paused")


def is_live_draft_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(LIVE_DRAFT_DIRTY_KEY))


def live_draft_board_len(payload: dict[str, Any] | None) -> int:
    if not isinstance(payload, dict):
        return 0
    board = payload.get("draft_board") or []
    return len(board) if isinstance(board, list) else 0


def runtime_room_ahead_of_blob(runtime: dict[str, Any], blob: dict[str, Any]) -> bool:
    rb = live_draft_board_len(runtime)
    cb = live_draft_board_len(blob)
    if rb > cb:
        return True
    if rb < cb:
        return False
    return int(runtime.get("current_pick_index") or 0) > int(blob.get("current_pick_index") or 0)


def should_prefer_runtime_live_room(
    session: dict[str, Any],
    runtime: dict[str, Any] | None,
    canonical: dict[str, Any] | None,
) -> bool:
    if not is_runtime_room(runtime) or not isinstance(canonical, dict):
        return bool(is_runtime_room(runtime) and runtime_room_hydrated(runtime))
    if runtime_room_ahead_of_blob(runtime, canonical):
        return True
    if is_live_draft_locally_dirty(session):
        rb = live_draft_board_len(runtime)
        cb = live_draft_board_len(canonical)
        return rb >= cb
    if runtime_room_hydrated(runtime):
        rb = live_draft_board_len(runtime)
        cb = live_draft_board_len(canonical)
        ri = int(runtime.get("current_pick_index") or 0)
        ci = int(canonical.get("current_pick_index") or 0)
        if rb >= cb and ri >= ci and str(runtime.get("draft_room_id") or "") == str(canonical.get("draft_room_id") or ""):
            return True
    return False


def runtime_room_hydrated(room: dict[str, Any] | None) -> bool:
    """True when runtime room already has an in-memory pool — skip canonical rebuild."""
    if not is_runtime_room(room):
        return False
    pool = room.get("pool")
    if pool is None:
        return False
    if hasattr(pool, "empty"):
        return not pool.empty
    return bool(pool)


def live_draft_prepare_fingerprint(room: dict[str, Any] | None) -> tuple[Any, ...]:
    """Revision key for prepare short-circuit — pick/board/room identity + slot config."""
    if not isinstance(room, dict):
        return ("", 0, 0, 0, (), 0)
    cfg = dict(room.get("config") or {})
    slots = tuple(sorted((k, int(cfg.get(k) or 0)) for k in cfg if str(k).startswith("slot_")))
    pool = room.get("pool")
    pool_len = int(len(pool)) if hasattr(pool, "__len__") else 0
    rev = int(((room.get("meta") or {}).get("sync") or {}).get("revision") or 0)
    return (
        str(room.get("draft_room_id") or ""),
        int(room.get("current_pick_index") or 0),
        live_draft_board_len(room),
        pool_len,
        slots,
        rev,
    )


def invalidate_live_draft_prepare_cache(session: dict[str, Any], *, reason: str = "") -> None:
    session.pop(LIVE_DRAFT_PREPARE_FP_KEY, None)
    session[LIVE_DRAFT_FORCE_PREPARE_KEY] = str(reason or "invalidate")


def _store_live_draft_prepare_fingerprint(session: dict[str, Any], room: dict[str, Any] | None) -> None:
    if isinstance(room, dict):
        session[LIVE_DRAFT_PREPARE_FP_KEY] = live_draft_prepare_fingerprint(room)
    session.pop(LIVE_DRAFT_FORCE_PREPARE_KEY, None)


def _try_short_circuit_prepare(session: dict[str, Any]) -> dict[str, Any] | None:
    """Return hydrated runtime room when prepare would be a no-op."""
    if session.get(LIVE_DRAFT_FORCE_PREPARE_KEY):
        return None
    if session.get("_live_draft_force_sync_on_return"):
        return None
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if not is_runtime_room(room):
        return None
    fp = live_draft_prepare_fingerprint(room)
    if session.get(LIVE_DRAFT_PREPARE_FP_KEY) == fp and runtime_room_hydrated(room):
        return _finish_prepare(session, room)
    canonical = canonical_live_draft(session)
    if isinstance(canonical, dict) and canonical.get("draft_room_id"):
        if should_prefer_runtime_live_room(session, room, canonical):
            return _finish_prepare(session, room)
    return None


def mark_live_draft_board_sync_pending(session: dict[str, Any], *, reason: str = "") -> None:
    session[LIVE_DRAFT_BOARD_SYNC_PENDING_KEY] = str(reason or "pick")


def flush_deferred_live_draft_board_sync(session: dict[str, Any]) -> bool:
    """Push live draft picks to canonical draft_room_table when deferred after a pick."""
    if not session.get(LIVE_DRAFT_BOARD_SYNC_PENDING_KEY):
        return False
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if not isinstance(room, dict):
        session.pop(LIVE_DRAFT_BOARD_SYNC_PENDING_KEY, None)
        return False
    try:
        from draft_room_state import sync_live_draft_room_to_canonical_board

        sync_live_draft_room_to_canonical_board(session, room)
    except ImportError:
        pass
    session.pop(LIVE_DRAFT_BOARD_SYNC_PENDING_KEY, None)
    return True


def defer_live_draft_pick_activity(session: dict[str, Any], room: dict[str, Any], *, source: str = "") -> None:
    session[LIVE_DRAFT_DEFERRED_PICK_ACTIVITY_KEY] = {
        "room_id": str(room.get("draft_room_id") or ""),
        "pick_index": int(room.get("current_pick_index") or 0),
        "board_len": live_draft_board_len(room),
        "source": str(source or ""),
    }


def flush_deferred_live_draft_pick_activity(session: dict[str, Any]) -> bool:
    pending = session.get(LIVE_DRAFT_DEFERRED_PICK_ACTIVITY_KEY)
    if not isinstance(pending, dict):
        return False
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if not isinstance(room, dict):
        session.pop(LIVE_DRAFT_DEFERRED_PICK_ACTIVITY_KEY, None)
        return False
    try:
        from baseball_draft_activity import after_live_draft_pick_committed

        after_live_draft_pick_committed(session, room)
    except Exception:
        pass
    session.pop(LIVE_DRAFT_DEFERRED_PICK_ACTIVITY_KEY, None)
    return True


def flush_deferred_live_draft_pick_effects(session: dict[str, Any]) -> None:
    """Run board sync + activity logging deferred from the hot pick-commit path."""
    flush_deferred_live_draft_board_sync(session)
    flush_deferred_live_draft_pick_activity(session)


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
    if src and src.get("draft_room_id"):
        block[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(src)
    else:
        block.pop(LIVE_DRAFT_ROOM_KEY, None)
    for key in LIVE_DRAFT_SETTINGS_KEYS:
        if key in session:
            block[key] = session[key]


def patch_canonical_live_draft_pick_fields(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    reason: str = "",
    local_edit: bool = True,
) -> dict[str, Any]:
    """Fast pick persist — update board/index/rosters without re-serializing the pool."""
    blob = canonical_live_draft(session)
    if not isinstance(blob, dict) or not blob.get("draft_room_id"):
        return write_canonical_live_draft_state(session, room, reason=reason, local_edit=local_edit)
    if str(blob.get("draft_room_id") or "") != str(room.get("draft_room_id") or ""):
        return write_canonical_live_draft_state(session, room, reason=reason, local_edit=local_edit)
    for key in (
        "draft_board",
        "current_pick_index",
        "drafted_player_ids",
        "rosters",
        "status",
        "pick_order",
        "teams",
        "config",
        "meta",
        "paused_remaining_seconds",
        "timer_deadline",
        "timer_handled_index",
    ):
        if key in room:
            blob[key] = _json_safe(room[key])
    blob["last_write_reason"] = reason or None
    _stamp_live_draft_owner(session, blob)
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
    _stamp_live_draft_owner(session, blob)
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


def _apply_derived_draft_status(session: dict[str, Any], room: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(room, dict):
        return room
    room = repair_stale_live_draft_progress(dict(room))
    try:
        from live_draft_roster_slots import ensure_room_slot_config, sync_live_slot_widgets_from_config

        ensure_room_slot_config(room)
        sync_live_slot_widgets_from_config(session, room.get("config"))
    except ImportError:
        pass
    try:
        from live_draft_safe_mode import reconcile_live_draft_room

        room = reconcile_live_draft_room(session, room).room
    except ImportError:
        session[LIVE_DRAFT_ROOM_KEY] = room
    return room


def _finish_prepare(session: dict[str, Any], room: dict[str, Any] | None) -> dict[str, Any] | None:
    result = _apply_derived_draft_status(session, room)
    if is_runtime_room(result):
        _store_live_draft_prepare_fingerprint(session, result)
    return result


def record_manual_pick_snapshot(session: dict[str, Any], board_size: int, pick_index: int) -> None:
    session[MANUAL_PICK_SNAPSHOT_KEY] = {
        "board_size": int(board_size),
        "current_pick_index": int(pick_index),
    }


def check_manual_commit_overwrite(session: dict[str, Any], *, source: str = "") -> bool:
    """Detect when a successful manual pick was rolled back by restore/poll/reconcile."""
    snap = session.get(MANUAL_PICK_SNAPSHOT_KEY)
    if not isinstance(snap, dict):
        return False
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if not isinstance(room, dict):
        return False
    expected_board = int(snap.get("board_size") or 0)
    expected_idx = int(snap.get("current_pick_index") or 0)
    actual_board = live_draft_board_len(room)
    actual_idx = int(room.get("current_pick_index") or 0)
    if actual_board >= expected_board and actual_idx >= expected_idx:
        session.pop(MANUAL_PICK_SNAPSHOT_KEY, None)
        return False
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            manual_commit_overwritten_after_success=True,
            overwrite_source=str(source or "unknown"),
            board_size_after_manual_pick=actual_board,
            current_pick_index_after_manual_pick=actual_idx,
            board_size_before_manual_pick=expected_board,
            current_pick_index_before_manual_pick=expected_idx,
        )
    except ImportError:
        pass
    return True


def prepare_live_draft_state(session: dict[str, Any]) -> dict[str, Any] | None:
    """Hydrate runtime room from canonical blob before Live Draft Room renders."""
    try:
        from live_draft_perf import PHASE_PREPARE_STATE, live_draft_perf_action

        with live_draft_perf_action(session, "prepare_state", phase=PHASE_PREPARE_STATE):
            return _prepare_live_draft_state_body(session)
    except ImportError:
        return _prepare_live_draft_state_body(session)


def _prepare_live_draft_state_body(session: dict[str, Any]) -> dict[str, Any] | None:
    if session.get("_live_draft_manual_pick_in_flight"):
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if is_runtime_room(room):
            try:
                from draft_commit_diagnostics import record_draft_commit_diagnostics

                record_draft_commit_diagnostics(session, runtime_room_preferred=True, canonical_room_preferred=False)
            except ImportError:
                pass
            return _finish_prepare(session, room)
    try:
        from draft_ui import PENDING_MANUAL_PICK_KEY

        if session.get(PENDING_MANUAL_PICK_KEY):
            room = session.get(LIVE_DRAFT_ROOM_KEY)
            if is_runtime_room(room):
                return _finish_prepare(session, room)
    except ImportError:
        pass
    short = _try_short_circuit_prepare(session)
    if short is not None:
        return short
    try:
        from draft_room_context import clear_stale_multiplayer_state, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            room = session.get(LIVE_DRAFT_ROOM_KEY)
            if is_runtime_room(room):
                write_canonical_live_draft_state(session, room, reason="multiplayer_hydrate", local_edit=False)
                return _finish_prepare(session, room)
            clear_stale_multiplayer_state(
                session,
                reason="Shared room was not loaded — restored your single-user live draft.",
            )
    except ImportError:
        pass
    canonical = canonical_live_draft(session)
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if isinstance(canonical, dict) and canonical.get("draft_room_id"):
        allowed, block_reason = live_draft_restore_allowed(session, canonical, source="session_canonical")
        if not allowed:
            clear_foreign_live_draft_state(session, reason=block_reason)
            return None
        runtime = room if is_runtime_room(room) else None
        if should_prefer_runtime_live_room(session, runtime, canonical):
            try:
                from draft_commit_diagnostics import record_draft_commit_diagnostics

                record_draft_commit_diagnostics(session, runtime_room_preferred=True, canonical_room_preferred=False)
            except ImportError:
                pass
            write_canonical_live_draft_state(session, runtime, reason="session_hydrate_prefer_runtime", local_edit=True)
            check_manual_commit_overwrite(session, source="prepare_live_draft_state_prefer_runtime")
            return _finish_prepare(session, runtime)
        try:
            from draft_commit_diagnostics import record_draft_commit_diagnostics

            record_draft_commit_diagnostics(session, runtime_room_preferred=False, canonical_room_preferred=True)
        except ImportError:
            pass
        restored = room_from_persist_dict(canonical)
        if restored:
            session[LIVE_DRAFT_ROOM_KEY] = restored
            check_manual_commit_overwrite(session, source="prepare_live_draft_state_canonical_restore")
            return _finish_prepare(session, restored)
    if is_runtime_room(room):
        write_canonical_live_draft_state(session, room, reason="session_hydrate", local_edit=False)
        return _finish_prepare(session, room)
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
        if isinstance(block, dict):
            legacy = block.get(LIVE_DRAFT_ROOM_KEY)
            if is_persisted_room_blob(legacy):
                restored = room_from_persist_dict(legacy)
                if restored:
                    write_canonical_live_draft_state(session, restored, reason="page_filter_hydrate", local_edit=False)
                    return _finish_prepare(session, restored)
    final = room if isinstance(room, dict) else None
    return _finish_prepare(session, final)


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

def live_draft_restore_stats(state: dict[str, Any] | None) -> dict[str, Any]:
    """Summary stats for restore winner diagnostics."""
    blob = _live_draft_from_blob(state or {})
    board = (blob.get("draft_board") or []) if isinstance(blob, dict) else []
    return {
        "has_live_draft_state": bool(isinstance(blob, dict) and blob.get("draft_room_id")),
        "pick_count": len(board) if isinstance(board, list) else 0,
        "pool_count": len(blob.get("pool_records") or []) if isinstance(blob, dict) else 0,
    }


def apply_cloud_live_draft_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    try:
        from draft_room_context import is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            return False
        code = str(
            session.get("active_shared_draft_room_code")
            or state.get("active_shared_draft_room_code")
            or ""
        ).strip()
        if code:
            return False
        try:
            from draft_room_participant_state import participant_has_left_room

            for raw_code in (
                session.get("active_shared_draft_room_code"),
                state.get("active_shared_draft_room_code"),
            ):
                rc = str(raw_code or "").strip().upper()
                if rc and participant_has_left_room(session, rc):
                    return False
        except ImportError:
            pass
    except ImportError:
        pass
    if is_live_draft_locally_dirty(session):
        return False
    blob = _live_draft_from_blob(state)
    if not blob or not blob.get("draft_room_id"):
        return False
    allowed, block_reason = live_draft_restore_allowed(session, blob, source="cloud_or_workspace")
    if not allowed:
        clear_foreign_live_draft_state(session, reason=block_reason)
        return False
    restored = room_from_persist_dict(blob)
    if not restored:
        return False
    write_canonical_live_draft_state(session, restored, reason="cloud_restore", local_edit=False)
    session["_live_draft_restore_source"] = "cloud_or_workspace"
    return True


def restore_live_draft_page_filters(session: dict[str, Any], store: dict[str, Any]) -> bool:
    """Restore Live Draft Room settings and (when available) the active draft room state.

    Settings are always restored from the snapshot — they do NOT require an active draft
    blob to be present.  The room hydration (pick history, pool, etc.) is gated on a valid
    persisted blob as before.
    """
    if is_live_draft_locally_dirty(session):
        return False
    snapshot = store.get(LIVE_DRAFT_PAGE_BLOCK) if isinstance(store, dict) else None
    if not isinstance(snapshot, dict):
        return False

    # Always restore league/draft settings and slot sizes from the snapshot.
    # This is the fix for the refresh-revert bug: settings were saved to the snapshot
    # by _live_draft_setting_changed but only restored when an active draft blob existed.
    settings_restored = False
    for key in LIVE_DRAFT_SETTINGS_KEYS:
        if key in snapshot:
            session[key] = snapshot[key]
            settings_restored = True
    # Also restore roster slot and team name keys
    for key, val in snapshot.items():
        if key.startswith("live_slot_") or key.startswith("live_draft_team_name_"):
            session[key] = val
            settings_restored = True

    # Canonical league format wins over stale page snapshot for scoring label.
    try:
        from global_fantasy_settings_state import GLOBAL_FORMAT_KEY, to_live_draft_scoring

        fmt = session.get(GLOBAL_FORMAT_KEY)
        if fmt is not None:
            session["live_draft_scoring"] = to_live_draft_scoring(fmt)
            settings_restored = True
    except ImportError:
        pass

    # Room hydration is separate — only run when a full active draft blob is present.
    blob = snapshot.get(LIVE_DRAFT_ROOM_KEY)
    if not is_persisted_room_blob(blob):
        return settings_restored
    allowed, block_reason = live_draft_restore_allowed(session, blob if isinstance(blob, dict) else None, source="page_filter")
    if not allowed:
        clear_foreign_live_draft_state(session, reason=block_reason)
        return settings_restored
    restored = room_from_persist_dict(blob)
    if not restored:
        return settings_restored
    write_canonical_live_draft_state(session, restored, reason="page_filter_restore", local_edit=False)
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
        if is_live_draft_locally_dirty(session):
            out = copy.deepcopy(state)
            out.pop(LIVE_DRAFT_STATE_KEY, None)
            out.pop(LIVE_DRAFT_ROOM_KEY, None)
            pf = out.get("page_filter_state")
            if isinstance(pf, dict):
                block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
                if isinstance(block, dict):
                    block.pop(LIVE_DRAFT_ROOM_KEY, None)
            ws = out.get("baseball_workspace_state")
            if isinstance(ws, dict):
                ws.pop("live_draft", None)
            return out, diag
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
    try:
        from live_draft_perf import PHASE_PERSIST, live_draft_perf_action

        with live_draft_perf_action(session, f"persist:{reason}", phase=PHASE_PERSIST):
            return _commit_live_draft_room_body(st, session, room, reason=reason)
    except ImportError:
        return _commit_live_draft_room_body(st, session, room, reason=reason)


def _commit_live_draft_room_body(st: Any, session: dict[str, Any], room: dict[str, Any] | None, *, reason: str) -> dict[str, Any]:
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


def save_live_draft_direct_to_cloud(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Explicit Supabase full_session write for live draft — bypasses autosave triggers.
    Reports payload build, cloud enablement, timestamp before/after, and errors.
    """
    trace: dict[str, Any] = {
        "path": "direct_cloud_save",
        "saved_cloud": False,
        "cloud_timestamp_changed": False,
        "error": "",
    }
    try:
        from suite_storage_config import cloud_storage_enabled
        from suite_user import account_mode, get_account_user_id

        trace["cloud_storage_enabled"] = cloud_storage_enabled()
        trace["account_user_id"] = str(get_account_user_id() or "")[:40]
        trace["account_storage_mode"] = account_mode()
    except Exception as exc:
        trace["cloud_storage_enabled"] = False
        trace["error"] = f"config:{type(exc).__name__}:{exc}"
        session["_live_draft_direct_cloud_trace"] = trace
        return trace

    if not trace["cloud_storage_enabled"]:
        trace["error"] = "cloud_storage_disabled"
        session["_live_draft_direct_cloud_trace"] = trace
        return trace

    try:
        from suite_cloud_state import load_cloud_full_session, save_cloud_full_session_with_result, session_page_summary
        from baseball_persistent_state import build_baseball_disk_state

        cloud_before, ts_before = load_cloud_full_session("baseball")
        trace["cloud_updated_at_before"] = ts_before
        trace["cloud_existing_has_live_draft_state_before_save"] = bool(
            _live_draft_from_blob(cloud_before or {}) and _live_draft_from_blob(cloud_before or {}).get("draft_room_id")
        )

        if room is not None:
            write_canonical_live_draft_state(session, room, reason="direct_cloud_save", local_edit=True)
        elif session.get(LIVE_DRAFT_ROOM_KEY):
            sync_live_draft_session_before_save(session)

        session["_suite_pending_save_reason"] = "live_draft_direct_cloud"
        state = build_baseball_disk_state(st)
        state, enrich_diag = enrich_save_payload_with_live_draft(session, state)
        trace["live_draft_injected_from_session"] = enrich_diag.get("injected_from_session")
        record_live_draft_cloud_save_diagnostics(
            session,
            payload=state,
            enrich_diag=enrich_diag,
            cloud_existing_before=trace["cloud_existing_has_live_draft_state_before_save"],
            preserved_on_page_change=False,
        )
        trace.update(live_draft_payload_diagnostics(state))

        import json

        raw = json.dumps(state, default=str)
        trace["payload_json_ok"] = True
        trace["payload_bytes"] = len(raw)
    except Exception as exc:
        trace["payload_json_ok"] = False
        trace["error"] = f"payload_build:{type(exc).__name__}:{exc}"
        session["_live_draft_direct_cloud_trace"] = trace
        return trace

    if not trace.get("cloud_payload_has_live_draft_state"):
        trace["error"] = "payload_missing_live_draft_state"
        session["_live_draft_direct_cloud_trace"] = trace
        return trace

    page, summary = session_page_summary("baseball", state)
    ok, cloud_err = save_cloud_full_session_with_result("baseball", state, page=page, summary=summary)
    trace["saved_cloud"] = ok
    trace["cloud_write_error"] = cloud_err or ""
    if cloud_err:
        trace["error"] = cloud_err
        session["_suite_persist_last_cloud_error"] = cloud_err
        session["_suite_autosave_cloud_blocked_reason"] = None

    cloud_after, ts_after = load_cloud_full_session("baseball")
    trace["cloud_updated_at_after"] = ts_after
    trace["cloud_timestamp_changed"] = bool(ts_after and ts_after != ts_before)
    trace["cloud_has_live_draft_after_read"] = bool(
        _live_draft_from_blob(cloud_after or {}) and _live_draft_from_blob(cloud_after or {}).get("draft_room_id")
    )
    if ok:
        session["_suite_persist_last_save_cloud"] = True
        session["_suite_persist_last_save_reason"] = "live_draft_direct_cloud"
        session["_suite_cloud_fetch_updated_at"] = ts_after
        session.pop("_suite_persist_last_cloud_error", None)
        if trace["cloud_has_live_draft_after_read"]:
            clear_live_draft_local_edit(session)
    trace["last_live_draft_save_success"] = bool(
        ok and trace.get("cloud_payload_has_live_draft_state") and trace.get("cloud_has_live_draft_after_read")
    )
    session["_live_draft_direct_cloud_trace"] = trace
    session["_live_draft_last_save_trace"] = trace
    session["last_live_draft_save_success"] = trace["last_live_draft_save_success"]
    session["last_live_draft_save_error"] = trace.get("error") or ""
    return trace

def push_local_draft_to_cloud(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recovery: merge live draft from local disk, then push full_session to Supabase."""
    trace: dict[str, Any] = {"path": "push_local_to_cloud", "merged_from_disk": False}
    try:
        from suite_user_persistence import _load_raw

        disk_state, _, disk_ts = _load_raw("baseball")
        disk_stats = live_draft_restore_stats(disk_state)
        session_stats = live_draft_restore_stats(session)
        trace["local_disk_updated_at"] = disk_ts
        trace["local_disk_has_live_draft_state"] = disk_stats["has_live_draft_state"]
        trace["local_disk_pick_count"] = disk_stats["pick_count"]
        trace["session_has_live_draft_state"] = session_stats["has_live_draft_state"]
        if (
            not room
            and not session_stats["has_live_draft_state"]
            and disk_stats["has_live_draft_state"]
            and isinstance(disk_state, dict)
        ):
            apply_cloud_live_draft_state_if_allowed(session, disk_state)
            prepare_live_draft_state(session)
            room = session.get(LIVE_DRAFT_ROOM_KEY)
            trace["merged_from_disk"] = True
    except Exception as exc:
        trace["disk_merge_error"] = f"{type(exc).__name__}: {exc}"

    direct = save_live_draft_direct_to_cloud(st, session, room if isinstance(room, dict) else None)
    trace.update(direct)
    trace["path"] = "push_local_to_cloud"
    session["_live_draft_push_local_trace"] = trace
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
    if not _developer_ui_visible(st):
        return
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
        direct = ss.get("_live_draft_direct_cloud_trace")
        if isinstance(direct, dict):
            st.markdown("**Direct cloud save (last)**")
            for key, val in direct.items():
                st.text(f"{key}: {val}")
        st.text(f"_suite_persist_last_cloud_error: {ss.get('_suite_persist_last_cloud_error')}")
        st.text(f"_suite_force_autosave_last_error: {ss.get('_suite_force_autosave_last_error')}")
        st.text(f"_suite_last_save_payload_bytes: {ss.get('_suite_last_save_payload_bytes')}")
        st.text(f"cloud_fetch_updated_at: {ss.get('_suite_cloud_fetch_updated_at')}")
        try:
            from suite_deploy_marker import GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

            st.text(f"deploy_build: {SUITE_BUILD_LABEL}")
            st.text(f"deploy_commit: {GIT_COMMIT_SHORT}")
        except ImportError:
            pass
        st.text(f"persist_restore_applied: {ss.get('_suite_persist_restore_applied')}")
        st.text(f"persist_restore_source: {ss.get('_suite_persist_last_restore_source')}")
        ok, err = verify_json_serializable(
            {"live_draft_state": ss.get(LIVE_DRAFT_STATE_KEY), "live_draft_room": ss.get(LIVE_DRAFT_ROOM_KEY)}
        )
        st.text(f"json_serializable: {ok}")
        if err:
            st.text(f"json_error: {err}")
