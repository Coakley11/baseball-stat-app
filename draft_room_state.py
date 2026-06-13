"""Canonical Draft Room Simulator state — JSON-safe persistence for draft_room_table."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

DRAFT_ROOM_PAGE_BLOCK = "Draft Room Simulator"
DRAFT_ROOM_TABLE_KEY = "draft_room_table"
DRAFT_ROOM_EDITOR_KEY = "draft_room_board_editor"
DRAFT_ROOM_STATE_KEY = "draft_room_state"
DRAFT_ROOM_DIRTY_KEY = "draft_room_state_dirty"
DRAFT_ROOM_LOCAL_EDIT_TS_KEY = "draft_room_state_last_local_edit_ts"
DRAFT_ROOM_PERSIST_SCHEMA = 1

DRAFT_ROOM_SETTINGS_KEYS = (
    "room_your_team",
    "room_team_count",
    "room_rounds",
    "room_format",
    "room_window",
    "room_team_names",
    "fantasy_draft_projection_style",
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
    return str(value)


def is_runtime_table(table: Any) -> bool:
    return table is not None and hasattr(table, "to_dict")


def is_persisted_table_blob(data: Any) -> bool:
    return isinstance(data, dict) and (
        "table_records" in data or data.get("_persist_schema") == DRAFT_ROOM_PERSIST_SCHEMA
    )


def table_row_count(table: Any) -> int:
    if is_runtime_table(table):
        return len(table)
    if is_persisted_table_blob(table):
        return len(table.get("table_records") or [])
    return 0


def table_picks_fingerprint(table: Any) -> str:
    """Hash only filled pick rows — ignores empty grid structure changes."""
    import hashlib

    records: list[dict[str, Any]] = []
    if is_runtime_table(table) and "Player" in table.columns:
        picked = table[table["Player"].apply(_player_cell_filled)]
        records = _json_safe(picked.to_dict(orient="records"))  # type: ignore[assignment]
    elif is_persisted_table_blob(table):
        for row in table.get("table_records") or []:
            if isinstance(row, dict) and _player_cell_filled(row.get("Player")):
                records.append(_json_safe(row))  # type: ignore[arg-type]
    payload = json.dumps(records, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def table_pick_count(table: Any) -> int:
    if is_runtime_table(table):
        df = table
        if df.empty or "Player" not in df.columns:
            return 0
        return int(df["Player"].apply(_player_cell_filled).sum())
    if is_persisted_table_blob(table):
        records = table.get("table_records") or []
        if not isinstance(records, list):
            return 0
        return sum(
            1
            for row in records
            if isinstance(row, dict) and _player_cell_filled(row.get("Player"))
        )
    return 0


def _player_cell_filled(val: Any) -> bool:
    if val is None:
        return False
    try:
        if pd.isna(val):
            return False
    except (TypeError, ValueError):
        pass
    text = str(val).strip()
    return bool(text) and text.lower() not in {"none", "nan", "<na>"}


def table_to_persist_dict(table: Any, *, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"_persist_schema": DRAFT_ROOM_PERSIST_SCHEMA, "_persisted_at": _utc_now_iso()}
    if is_runtime_table(table):
        if table.empty:
            out["table_records"] = []
            out["table_columns"] = []
        else:
            out["table_records"] = _json_safe(table.to_dict(orient="records"))
            out["table_columns"] = [str(c) for c in table.columns]
    elif is_persisted_table_blob(table):
        out["table_records"] = _json_safe(table.get("table_records") or [])
        out["table_columns"] = [str(c) for c in (table.get("table_columns") or [])]
    else:
        out["table_records"] = []
        out["table_columns"] = []
    out["pick_count"] = table_pick_count(out)
    if settings:
        for key in DRAFT_ROOM_SETTINGS_KEYS:
            if key in settings:
                out[key] = _json_safe(settings[key])
    return out


def table_from_persist_dict(data: dict[str, Any] | None) -> pd.DataFrame | None:
    if not isinstance(data, dict):
        return None
    records = data.get("table_records")
    columns = data.get("table_columns")
    if records is None and not is_persisted_table_blob(data):
        return None
    if not records:
        return pd.DataFrame(columns=list(columns or []))
    df = pd.DataFrame(records)
    if columns:
        ordered = [c for c in columns if c in df.columns]
        extras = [c for c in df.columns if c not in ordered]
        df = df[ordered + extras]
    return df


def _draft_room_from_blob(state: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    meta = state.get(DRAFT_ROOM_STATE_KEY)
    if isinstance(meta, dict) and meta.get("_persist_schema") == DRAFT_ROOM_PERSIST_SCHEMA:
        return copy.deepcopy(meta)
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict):
            tbl = block.get(DRAFT_ROOM_TABLE_KEY)
            if is_persisted_table_blob(tbl):
                return copy.deepcopy(tbl)
            if is_runtime_table(tbl):
                return table_to_persist_dict(tbl)
    tbl = state.get(DRAFT_ROOM_TABLE_KEY)
    if is_persisted_table_blob(tbl):
        return copy.deepcopy(tbl)
    if is_runtime_table(tbl) and table_pick_count(tbl) > 0:
        return table_to_persist_dict(tbl)
    return None


def draft_room_restore_stats(state: dict[str, Any] | None) -> dict[str, Any]:
    blob = _draft_room_from_blob(state or {})
    pick_count = int(blob.get("pick_count") or 0) if isinstance(blob, dict) else 0
    if blob and not pick_count:
        pick_count = table_pick_count(blob)
    return {
        "has_draft_board": pick_count > 0,
        "pick_count": pick_count,
        "pool_count": len(blob.get("table_records") or []) if isinstance(blob, dict) else 0,
    }


def draft_board_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Unified diagnostics: Draft Room Simulator vs Live Draft Room."""
    from live_draft_state import LIVE_DRAFT_ROOM_KEY, live_draft_restore_stats

    room_stats = draft_room_restore_stats(session)
    live_stats = live_draft_restore_stats(session)
    active_page = str(session.get("active_page") or "")
    source_key = ""
    active_draft_page = ""
    runtime_picks = table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY))
    editor_picks = table_pick_count(session.get(DRAFT_ROOM_EDITOR_KEY))
    session_pick_count = max(room_stats["pick_count"], runtime_picks, editor_picks)
    session_has_board = session_pick_count > 0

    if session_has_board:
        source_key = DRAFT_ROOM_EDITOR_KEY if editor_picks >= runtime_picks else DRAFT_ROOM_TABLE_KEY
        active_draft_page = DRAFT_ROOM_PAGE_BLOCK
    elif live_stats["pick_count"] > 0 or live_stats["has_live_draft_state"]:
        source_key = LIVE_DRAFT_ROOM_KEY
        active_draft_page = "Live Draft Room"
        session_pick_count = live_stats["pick_count"]
        session_has_board = bool(live_stats["has_live_draft_state"])

    pf = session.get("page_filter_state")
    pf_pages = sorted(str(k) for k in pf.keys()) if isinstance(pf, dict) else []

    return {
        "active_draft_page": active_draft_page or active_page or None,
        "draft_board_source_key": source_key or None,
        "session_has_draft_board": session_has_board,
        "session_pick_count": session_pick_count,
        "draft_room_pick_count": room_stats["pick_count"],
        "live_draft_pick_count": live_stats["pick_count"],
        "page_filter_pages": pf_pages,
        "active_page": active_page or None,
    }


def is_draft_room_locally_dirty(session: dict[str, Any]) -> bool:
    return bool(session.get(DRAFT_ROOM_DIRTY_KEY))


def mark_draft_room_local_edit(session: dict[str, Any]) -> None:
    session[DRAFT_ROOM_DIRTY_KEY] = True
    session[DRAFT_ROOM_LOCAL_EDIT_TS_KEY] = _utc_now_iso()


def clear_draft_room_local_edit(session: dict[str, Any]) -> None:
    session.pop(DRAFT_ROOM_DIRTY_KEY, None)
    session.pop(DRAFT_ROOM_LOCAL_EDIT_TS_KEY, None)


def _room_settings_from_session(session: dict[str, Any]) -> dict[str, Any]:
    return {k: session[k] for k in DRAFT_ROOM_SETTINGS_KEYS if k in session}


def _sync_page_filter_draft_room_block(session: dict[str, Any], *, blob: dict[str, Any] | None = None) -> None:
    pf = session.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        return
    block = pf.setdefault(DRAFT_ROOM_PAGE_BLOCK, {})
    if not isinstance(block, dict):
        block = {}
        pf[DRAFT_ROOM_PAGE_BLOCK] = block
    src = blob if isinstance(blob, dict) else _draft_room_from_blob(session) or {}
    if src:
        block[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(src)
    for key in DRAFT_ROOM_SETTINGS_KEYS:
        if key in session:
            block[key] = session[key]


def write_canonical_draft_room_state(
    session: dict[str, Any],
    table: Any,
    *,
    reason: str = "",
    local_edit: bool = False,
) -> dict[str, Any]:
    settings = _room_settings_from_session(session)
    blob = table_to_persist_dict(table, settings=settings)
    blob["last_write_reason"] = reason or None
    session[DRAFT_ROOM_STATE_KEY] = blob
    if is_runtime_table(table):
        session[DRAFT_ROOM_TABLE_KEY] = table
    _sync_page_filter_draft_room_block(session, blob=blob)
    if local_edit:
        mark_draft_room_local_edit(session)
    return blob


def prepare_draft_room_state(session: dict[str, Any]) -> pd.DataFrame | None:
    """Hydrate runtime draft_room_table from canonical blob without clobbering in-memory picks."""
    runtime = session.get(DRAFT_ROOM_TABLE_KEY)
    runtime_picks = table_pick_count(runtime) if is_runtime_table(runtime) else 0
    editor = session.get(DRAFT_ROOM_EDITOR_KEY)
    editor_picks = table_pick_count(editor) if is_runtime_table(editor) else 0

    if is_draft_room_locally_dirty(session):
        best = editor if editor_picks >= runtime_picks and is_runtime_table(editor) else runtime
        if is_runtime_table(best) and table_pick_count(best) > 0:
            write_canonical_draft_room_state(session, best, reason="dirty_runtime_preserve", local_edit=True)
            if not is_runtime_table(editor) or editor_picks < runtime_picks:
                session[DRAFT_ROOM_EDITOR_KEY] = best.copy()
            return best

    blob = _draft_room_from_blob(session)
    blob_picks = table_pick_count(blob) if isinstance(blob, dict) else 0
    if runtime_picks > blob_picks and is_runtime_table(runtime):
        write_canonical_draft_room_state(session, runtime, reason="runtime_wins", local_edit=False)
        if editor_picks < runtime_picks or not is_runtime_table(editor):
            session[DRAFT_ROOM_EDITOR_KEY] = runtime.copy()
        return runtime
    if editor_picks > blob_picks and is_runtime_table(editor):
        write_canonical_draft_room_state(session, editor, reason="editor_wins", local_edit=False)
        session[DRAFT_ROOM_TABLE_KEY] = editor.copy()
        return editor

    table = runtime
    if isinstance(blob, dict) and blob.get("table_records") is not None:
        restored = table_from_persist_dict(blob)
        if restored is not None:
            session[DRAFT_ROOM_TABLE_KEY] = restored
            session[DRAFT_ROOM_STATE_KEY] = blob
            if DRAFT_ROOM_EDITOR_KEY not in session or table_pick_count(session.get(DRAFT_ROOM_EDITOR_KEY)) < table_pick_count(restored):
                session[DRAFT_ROOM_EDITOR_KEY] = restored.copy()
            for key in DRAFT_ROOM_SETTINGS_KEYS:
                if key in blob:
                    session[key] = blob[key]
            return restored
    if is_runtime_table(table):
        write_canonical_draft_room_state(session, table, reason="session_hydrate", local_edit=False)
        return table
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict):
            legacy = block.get(DRAFT_ROOM_TABLE_KEY)
            if is_persisted_table_blob(legacy) or is_runtime_table(legacy):
                restored = table_from_persist_dict(legacy) if is_persisted_table_blob(legacy) else legacy
                if restored is not None:
                    write_canonical_draft_room_state(session, restored, reason="page_filter_hydrate", local_edit=False)
                    for key in DRAFT_ROOM_SETTINGS_KEYS:
                        if key in block:
                            session[key] = block[key]
                    return restored
    return table if is_runtime_table(table) else None


def sync_draft_room_session_before_save(session: dict[str, Any]) -> None:
    table = session.get(DRAFT_ROOM_TABLE_KEY)
    if is_runtime_table(table):
        write_canonical_draft_room_state(
            session,
            table,
            reason="pre_save_sync",
            local_edit=is_draft_room_locally_dirty(session),
        )


def enrich_save_payload_with_draft_room(
    session: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    diag: dict[str, Any] = {
        "payload_has_draft_board": False,
        "cloud_payload_pick_count": 0,
    }
    sync_draft_room_session_before_save(session)
    blob = _draft_room_from_blob(session) or _draft_room_from_blob(state)
    if not blob or not blob.get("table_records"):
        existing = _draft_room_from_blob(state)
        if existing:
            blob = existing
        else:
            return state, diag

    safe_blob = copy.deepcopy(blob)
    out = copy.deepcopy(state)
    out[DRAFT_ROOM_STATE_KEY] = safe_blob
    out[DRAFT_ROOM_TABLE_KEY] = safe_blob
    pf = out.setdefault("page_filter_state", {})
    if not isinstance(pf, dict):
        pf = {}
        out["page_filter_state"] = pf
    block = pf.setdefault(DRAFT_ROOM_PAGE_BLOCK, {})
    if isinstance(block, dict):
        block[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(safe_blob)
        for key in DRAFT_ROOM_SETTINGS_KEYS:
            if key in session:
                block[key] = session[key]
    pick_count = int(safe_blob.get("pick_count") or table_pick_count(safe_blob))
    diag["payload_has_draft_board"] = pick_count > 0
    diag["cloud_payload_pick_count"] = pick_count
    session["cloud_payload_has_draft_board"] = diag["payload_has_draft_board"]
    session["cloud_payload_pick_count"] = pick_count
    board_diag = draft_board_diagnostics(session)
    session.update(
        {
            "active_draft_page": board_diag.get("active_draft_page"),
            "draft_board_source_key": board_diag.get("draft_board_source_key"),
            "session_has_draft_board": board_diag.get("session_has_draft_board"),
            "session_pick_count": board_diag.get("session_pick_count"),
            "payload_has_draft_board": diag["payload_has_draft_board"],
        }
    )
    return out, diag


def sanitize_state_dict_for_json(state: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(state)
    table = out.get(DRAFT_ROOM_TABLE_KEY)
    blob = out.get(DRAFT_ROOM_STATE_KEY)
    if is_runtime_table(table):
        blob = table_to_persist_dict(table)
    elif is_persisted_table_blob(table):
        blob = copy.deepcopy(table)
    elif isinstance(blob, dict) and blob.get("table_records") is not None:
        blob = copy.deepcopy(blob)
    elif isinstance(out.get("page_filter_state"), dict):
        block = out["page_filter_state"].get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict):
            pr = block.get(DRAFT_ROOM_TABLE_KEY)
            if is_runtime_table(pr):
                blob = table_to_persist_dict(pr)
            elif is_persisted_table_blob(pr):
                blob = copy.deepcopy(pr)
    if blob:
        out[DRAFT_ROOM_STATE_KEY] = copy.deepcopy(blob)
        out[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(blob)
        pf = out.get("page_filter_state")
        if isinstance(pf, dict):
            page_block = pf.setdefault(DRAFT_ROOM_PAGE_BLOCK, {})
            if isinstance(page_block, dict):
                page_block[DRAFT_ROOM_TABLE_KEY] = copy.deepcopy(blob)
    return out


def ensure_board_editor_seeded(session: dict[str, Any], canonical_table: Any) -> None:
    """Seed keyed data_editor only when the widget key is absent (never overwrite before render)."""
    if DRAFT_ROOM_EDITOR_KEY in session and is_runtime_table(session.get(DRAFT_ROOM_EDITOR_KEY)):
        return
    if is_runtime_table(canonical_table):
        session[DRAFT_ROOM_EDITOR_KEY] = canonical_table.copy()


def record_board_editor_diagnostics(
    session: dict[str, Any],
    edited_table: Any,
    *,
    editor_key: str = DRAFT_ROOM_EDITOR_KEY,
) -> dict[str, Any]:
    """Capture data_editor vs session_state wiring for Developer Mode."""
    session_table = session.get(DRAFT_ROOM_TABLE_KEY)
    blob = _draft_room_from_blob(session) or {}
    diag = {
        "data_editor_key": editor_key,
        "data_editor_returned_rows": table_row_count(edited_table),
        "data_editor_returned_pick_count": table_pick_count(edited_table),
        "session_draft_room_table_rows": table_row_count(session_table),
        "session_draft_room_table_pick_count": table_pick_count(session_table),
        "commit_input_pick_count": table_pick_count(edited_table),
        "persisted_pick_count": int(blob.get("pick_count") or table_pick_count(blob)),
        "persisted_rows": table_row_count(blob),
        "picks_fingerprint": table_picks_fingerprint(edited_table),
    }
    session["_draft_room_editor_diagnostics"] = diag
    return diag


def commit_draft_room_table_if_changed(
    st: Any,
    session: dict[str, Any],
    table: Any,
    *,
    reason: str = "board_edit",
    editor_key: str = DRAFT_ROOM_EDITOR_KEY,
) -> dict[str, Any]:
    """Force-save only when filled picks changed — avoids empty-grid autosaves."""
    editor_diag = record_board_editor_diagnostics(session, table, editor_key=editor_key)
    pick_count = table_pick_count(table)
    picks_fp = table_picks_fingerprint(table)
    prev_picks_fp = session.get("_draft_room_picks_fp")
    prev_pick_count = session.get("_draft_room_last_committed_pick_count")

    if (
        reason == "board_edit"
        and prev_picks_fp == picks_fp
        and prev_pick_count == pick_count
        and pick_count > 0
    ):
        trace = {
            "reason": reason,
            "skipped": "picks_unchanged",
            "saved": False,
            **editor_diag,
            **draft_board_diagnostics(session),
        }
        session["_draft_room_last_save_trace"] = trace
        return trace

    if reason == "board_edit" and pick_count == 0:
        if prev_picks_fp is None or prev_picks_fp == picks_fp:
            trace = {
                "reason": reason,
                "skipped": "no_picks_yet",
                "saved": False,
                **editor_diag,
                **draft_board_diagnostics(session),
            }
            session["_draft_room_last_save_trace"] = trace
            return trace

    session["_draft_room_picks_fp"] = picks_fp
    trace = commit_draft_room_table(st, session, table, reason=reason, editor_key=editor_key)
    session["_draft_room_last_committed_pick_count"] = pick_count
    return trace


def commit_draft_room_table(
    st: Any,
    session: dict[str, Any],
    table: Any,
    *,
    reason: str = "board_edit",
    editor_key: str = DRAFT_ROOM_EDITOR_KEY,
) -> dict[str, Any]:
    """Canonical write + force-save after Draft Room Simulator board change."""
    trace: dict[str, Any] = {"reason": reason, "saved": False, "disk": False, "cloud": False, "error": ""}
    import hashlib
    import json

    editor_diag = record_board_editor_diagnostics(session, table, editor_key=editor_key)
    trace.update(editor_diag)

    write_canonical_draft_room_state(session, table, reason=reason, local_edit=True)
    blob = _draft_room_from_blob(session) or {}
    trace["persisted_pick_count"] = int(blob.get("pick_count") or table_pick_count(blob))
    trace["persisted_rows"] = table_row_count(blob)
    fp = hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()[:16]
    if session.get("_draft_room_save_fp") == fp and reason == "board_edit":
        trace["skipped"] = "blob_unchanged"
        trace.update(draft_board_diagnostics(session))
        session["_draft_room_last_save_trace"] = trace
        return trace
    session["_draft_room_save_fp"] = fp
    board_diag = draft_board_diagnostics(session)
    trace.update(board_diag)
    try:
        from baseball_persistent_state import force_save_baseball_state

        trace["saved"] = bool(force_save_baseball_state(st, reason="draft_room_pick"))
        trace["disk"] = bool(session.get("_suite_persist_last_save_disk"))
        trace["cloud"] = bool(session.get("_suite_persist_last_save_cloud"))
        trace["saved_pick_count"] = table_pick_count(table)
        trace["payload_has_draft_board"] = bool(session.get("payload_has_draft_board"))
        trace["cloud_payload_pick_count"] = session.get("cloud_payload_pick_count")
        if session.get("_suite_persist_last_cloud_error"):
            trace["error"] = str(session.get("_suite_persist_last_cloud_error"))
        elif session.get("_suite_autosave_cloud_blocked_reason"):
            trace["error"] = f"cloud_blocked:{session.get('_suite_autosave_cloud_blocked_reason')}"
        if trace["saved"] and trace["cloud"] and trace.get("payload_has_draft_board"):
            clear_draft_room_local_edit(session)
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
    session["_draft_room_last_save_trace"] = trace
    return trace


def apply_cloud_draft_room_state_if_allowed(session: dict[str, Any], state: dict[str, Any]) -> bool:
    if is_draft_room_locally_dirty(session):
        return False
    blob = _draft_room_from_blob(state)
    if not blob or not blob.get("table_records"):
        return False
    restored = table_from_persist_dict(blob)
    if restored is None:
        return False
    write_canonical_draft_room_state(session, restored, reason="cloud_restore", local_edit=False)
    for key in DRAFT_ROOM_SETTINGS_KEYS:
        if key in blob:
            session[key] = blob[key]
    session["_draft_room_restore_source"] = "cloud_or_workspace"
    return True


def unified_draft_restore_stats(state: dict[str, Any] | None) -> dict[str, Any]:
    """Combined stats for restore winner (Draft Room Simulator + Live Draft Room)."""
    room = draft_room_restore_stats(state)
    try:
        from live_draft_state import live_draft_restore_stats

        live = live_draft_restore_stats(state)
    except ImportError:
        live = {"has_live_draft_state": False, "pick_count": 0, "pool_count": 0}
    return {
        "has_any_draft": bool(room["pick_count"] > 0 or live.get("pick_count", 0) > 0),
        "draft_room_pick_count": room["pick_count"],
        "live_draft_pick_count": live.get("pick_count", 0),
        "local_has_live_draft_state": live.get("has_live_draft_state", False),
        "local_has_draft_room_board": room["has_draft_board"],
    }


def read_board_from_editor(session: dict[str, Any]) -> pd.DataFrame | None:
    """Read the live keyed editor state — authoritative source for manual save."""
    editor = session.get(DRAFT_ROOM_EDITOR_KEY)
    if is_runtime_table(editor):
        return editor.copy()
    table = session.get(DRAFT_ROOM_TABLE_KEY)
    if is_runtime_table(table):
        return table.copy()
    return None


def save_draft_board_now(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    """Explicit Board-tab save: editor → draft_room_state → disk + cloud."""
    trace: dict[str, Any] = {
        "path": "save_draft_board_now",
        "saved": False,
        "disk": False,
        "cloud": False,
        "saved_pick_count": 0,
        "error": "",
    }
    cloud_ts_before = None
    try:
        from suite_cloud_state import load_cloud_full_session

        _, cloud_ts_before = load_cloud_full_session("baseball")
    except Exception as exc:
        trace["cloud_timestamp_before_error"] = f"{type(exc).__name__}: {exc}"
    trace["cloud_timestamp_before"] = cloud_ts_before

    board = read_board_from_editor(session)
    if board is None:
        trace["error"] = "editor_state_missing"
        session["_draft_room_manual_save_result"] = trace
        session["_draft_room_last_save_trace"] = trace
        return trace

    pick_count = table_pick_count(board)
    trace["saved_pick_count"] = pick_count
    record_board_editor_diagnostics(session, board)
    session[DRAFT_ROOM_TABLE_KEY] = board.copy()
    session["_draft_room_picks_fp"] = table_picks_fingerprint(board)
    session.pop("_draft_room_save_fp", None)

    save_trace = commit_draft_room_table(st, session, board, reason="manual_save")
    trace.update(save_trace)
    trace["saved_pick_count"] = pick_count
    trace["cloud_timestamp_before"] = cloud_ts_before

    cloud_ts_after = None
    try:
        from suite_cloud_state import load_cloud_full_session

        _, cloud_ts_after = load_cloud_full_session("baseball")
    except Exception as exc:
        trace["cloud_timestamp_after_error"] = f"{type(exc).__name__}: {exc}"
    trace["cloud_timestamp_after"] = cloud_ts_after

    session["_draft_room_manual_save_result"] = trace
    session["_draft_room_last_save_trace"] = trace
    return trace


def board_tab_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Live Board-tab fields shown directly under the editor."""
    editor = session.get(DRAFT_ROOM_EDITOR_KEY)
    editor_diag = session.get("_draft_room_editor_diagnostics")
    if not isinstance(editor_diag, dict) and is_runtime_table(editor):
        editor_diag = record_board_editor_diagnostics(session, editor)
    board = draft_board_diagnostics(session)
    trace = session.get("_draft_room_last_save_trace")
    out = {
        "data_editor_key": DRAFT_ROOM_EDITOR_KEY,
        "editor_state_exists": is_runtime_table(editor),
        "data_editor_returned_pick_count": table_pick_count(editor),
        "commit_input_pick_count": (
            editor_diag.get("commit_input_pick_count") if isinstance(editor_diag, dict) else table_pick_count(editor)
        ),
        "session_pick_count": board.get("session_pick_count"),
        "draft_room_pick_count": board.get("draft_room_pick_count"),
        "payload_has_draft_board": session.get("payload_has_draft_board"),
        "cloud_payload_pick_count": session.get("cloud_payload_pick_count"),
        "last_draft_room_save_trace": trace if isinstance(trace, dict) else None,
    }
    session["_draft_room_board_tab_diagnostics"] = out
    return out


def render_board_tab_diagnostics(st: Any) -> None:
    """Always-visible Board tab status panel (not dev-mode only)."""
    ss = st.session_state
    diag = board_tab_diagnostics(ss)
    manual = ss.get("_draft_room_manual_save_result")
    with st.container(border=True):
        st.markdown("**Board save status**")
        for key in (
            "data_editor_key",
            "editor_state_exists",
            "data_editor_returned_pick_count",
            "commit_input_pick_count",
            "session_pick_count",
            "draft_room_pick_count",
            "payload_has_draft_board",
            "cloud_payload_pick_count",
        ):
            st.text(f"{key}: {diag.get(key)}")
        trace = diag.get("last_draft_room_save_trace")
        if isinstance(trace, dict):
            st.text(f"last_draft_room_save_trace.reason: {trace.get('reason')}")
            st.text(f"last_draft_room_save_trace.saved: {trace.get('saved')}")
            st.text(f"last_draft_room_save_trace.saved_pick_count: {trace.get('saved_pick_count')}")
            st.text(f"last_draft_room_save_trace.error: {trace.get('error') or ''}")
        if isinstance(manual, dict) and manual.get("path") == "save_draft_board_now":
            st.text(f"manual_save.cloud_timestamp_before: {manual.get('cloud_timestamp_before')}")
            st.text(f"manual_save.cloud_timestamp_after: {manual.get('cloud_timestamp_after')}")


def render_draft_board_diagnostics(st: Any) -> None:
    ss = st.session_state
    board = draft_board_diagnostics(ss)
    trace = ss.get("_draft_room_last_save_trace")
    with st.expander("Draft board save / restore trace", expanded=False):
        st.markdown("**Active draft board**")
        for key, val in board.items():
            st.text(f"{key}: {val}")
        st.text(f"payload_has_draft_board: {ss.get('payload_has_draft_board')}")
        st.text(f"cloud_payload_pick_count: {ss.get('cloud_payload_pick_count')}")
        if isinstance(trace, dict):
            st.markdown("**Last Draft Room save**")
            for key, val in trace.items():
                st.text(f"{key}: {val}")
        editor_diag = ss.get("_draft_room_editor_diagnostics")
        if isinstance(editor_diag, dict):
            st.markdown("**Board editor wiring**")
            for key, val in editor_diag.items():
                st.text(f"{key}: {val}")
        st.text(f"local_has_draft_room_board: {draft_room_restore_stats(ss).get('has_draft_board')}")
        st.text(f"cloud_has_draft_room: {ss.get('cloud_has_draft_room_board')}")


def push_local_draft_room_to_cloud(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    """Recovery: push Draft Room Simulator board from disk/session to Supabase."""
    trace: dict[str, Any] = {"path": "push_draft_room_to_cloud", "merged_from_disk": False}
    try:
        from suite_user_persistence import _load_raw

        disk_state, _, disk_ts = _load_raw("baseball")
        disk_stats = draft_room_restore_stats(disk_state)
        session_stats = draft_room_restore_stats(session)
        trace["local_disk_updated_at"] = disk_ts
        trace["local_disk_pick_count"] = disk_stats.get("pick_count")
        trace["session_pick_count"] = session_stats.get("pick_count")
        if (
            session_stats.get("pick_count", 0) <= 0
            and disk_stats.get("pick_count", 0) > 0
            and isinstance(disk_state, dict)
        ):
            apply_cloud_draft_room_state_if_allowed(session, disk_state)
            prepare_draft_room_state(session)
            trace["merged_from_disk"] = True
    except Exception as exc:
        trace["disk_merge_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from baseball_persistent_state import force_save_baseball_state

        sync_draft_room_session_before_save(session)
        trace["saved"] = bool(force_save_baseball_state(st, reason="draft_room_pick"))
        trace["disk"] = bool(session.get("_suite_persist_last_save_disk"))
        trace["cloud"] = bool(session.get("_suite_persist_last_save_cloud"))
        trace["payload_has_draft_board"] = bool(session.get("payload_has_draft_board"))
        trace["cloud_payload_pick_count"] = session.get("cloud_payload_pick_count")
        if session.get("_suite_persist_last_cloud_error"):
            trace["error"] = str(session.get("_suite_persist_last_cloud_error"))
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
    session["_draft_room_push_local_trace"] = trace
    return trace
