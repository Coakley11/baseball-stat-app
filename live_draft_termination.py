"""Canonical Live Draft End / Delete termination — permanent, exclusive lifecycle."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

LAST_DRAFT_BOARD_SNAPSHOT_KEY = "last_draft_board_snapshot"
TERMINATION_TOMBSTONES_KEY = "live_draft_termination_tombstones"
PAGE_FRAGMENT_EPOCH_KEY = "_live_draft_page_fragment_epoch"
REPAIR_DONE_KEY = "_live_draft_lifecycle_repair_v1_done"
ENDED_NOTICE_KEY = "_live_draft_session_ended_notice"
GUEST_ENDED_NOTICE_KEY = "_live_draft_guest_ended_notice"

# Session mirrors (also synced into durable tombstone blob).
ENDED_ROOM_CODES_KEY = "_live_draft_ended_room_codes"
ENDED_DRAFT_IDS_KEY = "_live_draft_ended_draft_ids"
ENDED_ROOM_IDS_KEY = "_live_draft_ended_room_ids"

TERMINAL_ROOM_STATUSES = frozenset({"ended", "closed", "deleted", "completed", "complete"})

# Everything that can resurrect or paint an active live room after End/Delete.
TERMINATION_CLEAR_KEYS = (
    "active_shared_draft_room_code",
    "draft_room_shared_meta",
    "draft_room_participant_team",
    "draft_room_participant_id",
    "draft_room_participant_notes",
    "room_your_team",
    "live_draft_my_team",
    "live_draft_room",
    "live_draft_state",
    "_live_draft_shared_league_confirm_open",
    "_live_draft_browsing_away",
    "_live_draft_force_sync_on_return",
    "_shared_draft_poll_ts",
    "_draft_room_publish_error",
    "_draft_room_conflict_notice",
    "_draft_room_membership_notice",
    "_start_live_draft_pending",
    "live_draft_join_code_input",
    "live_draft_join_team_pick",
    "_draft_join_flash",
    "_draft_join_error",
    "_draft_room_claim_diag",
    "_draft_room_sync_diag",
    "_draft_room_join_attempt_diag",
    "_live_draft_resume_last_room",
    "_live_draft_force_resume",
    "active_draft_source",
    "_active_draft_source",
    "_shared_lobby_authority_doc",
    "_shared_lobby_sync_diag",
    "_shared_lobby_host_refresh_trace",
    "_shared_room_doc_soft_cache",
    "_live_draft_rec_cache",
    "_live_draft_joined_participants_cache",
    "_live_draft_timer_expired_pending",
    "_live_draft_page_owns_expired",
    "_live_draft_poll_diag",
    "_live_draft_poll_apply_pending",
    "_active_live_draft_mode_resolve",
    "_live_draft_queue_last_good",
    "show_live_draft",
    "draft_started",
    "live_draft_active",
    "_live_draft_start_feedback",
    "_shared_draft_room_created_flash",
    "_draft_room_create_flash",
    "_live_draft_delete_confirm",
    "_live_draft_end_confirm",
    "_simulator_to_live_show_confirm",
    "_live_draft_history_view",
    "source_room_code",
    "_source_room_code",
    "_suite_resume_draft_room",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def bump_live_draft_page_epoch(session: dict[str, Any]) -> int:
    nxt = int(session.get(PAGE_FRAGMENT_EPOCH_KEY) or 0) + 1
    session[PAGE_FRAGMENT_EPOCH_KEY] = nxt
    session["_draft_queue_widget_epoch"] = int(session.get("_draft_queue_widget_epoch") or 0) + 1
    return nxt


def _ids_from_room(session: dict[str, Any], room: dict[str, Any] | None) -> tuple[str, str, str]:
    live = room if isinstance(room, dict) else {}
    draft_id = str(
        live.get("draft_room_id")
        or live.get("draft_id")
        or (live.get("config") or {}).get("draft_id")
        or ""
    ).strip()
    room_id = str(live.get("room_id") or draft_id or "").strip()
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code:
        try:
            from draft_room_context import resolve_shared_room_code

            code = str(resolve_shared_room_code(session) or "").strip().upper()
        except ImportError:
            pass
    if not code and isinstance(live, dict):
        cfg = dict(live.get("config") or {})
        code = str(live.get("room_code") or cfg.get("room_code") or "").strip().upper()
    return draft_id, room_id, code


def _empty_tombstone_blob() -> dict[str, Any]:
    return {
        "room_codes": [],
        "draft_ids": [],
        "room_ids": [],
        "updated_at": None,
    }


def load_durable_tombstones(session: dict[str, Any]) -> dict[str, Any]:
    blob = session.get(TERMINATION_TOMBSTONES_KEY)
    if isinstance(blob, dict):
        out = _empty_tombstone_blob()
        for key in ("room_codes", "draft_ids", "room_ids"):
            raw = blob.get(key)
            out[key] = [str(x).strip() for x in (raw or []) if str(x).strip()] if isinstance(raw, list) else []
        out["updated_at"] = blob.get("updated_at")
        return out
    return _empty_tombstone_blob()


def _mirror_session_tombstone_lists(session: dict[str, Any], blob: dict[str, Any]) -> None:
    session[ENDED_ROOM_CODES_KEY] = list(blob.get("room_codes") or [])
    session[ENDED_DRAFT_IDS_KEY] = list(blob.get("draft_ids") or [])
    session[ENDED_ROOM_IDS_KEY] = list(blob.get("room_ids") or [])
    # Keep legacy completion module keys in sync.
    try:
        from live_draft_completion import ENDED_DRAFT_IDS_KEY as C_IDS
        from live_draft_completion import ENDED_ROOM_CODES_KEY as C_CODES

        session[C_CODES] = list(blob.get("room_codes") or [])
        session[C_IDS] = list(blob.get("draft_ids") or [])
    except ImportError:
        pass


def persist_durable_tombstones(
    session: dict[str, Any],
    *,
    draft_id: str = "",
    room_id: str = "",
    room_code: str = "",
) -> dict[str, Any]:
    """Authoritative retirement markers — survive refresh / reboot / sign-in."""
    blob = load_durable_tombstones(session)
    code = str(room_code or "").strip().upper()
    did = str(draft_id or "").strip()
    rid = str(room_id or "").strip()
    if code and code not in blob["room_codes"]:
        blob["room_codes"].append(code)
    if did and did not in blob["draft_ids"]:
        blob["draft_ids"].append(did)
    if rid and rid not in blob["room_ids"]:
        blob["room_ids"].append(rid)
    blob["updated_at"] = _utc_now_iso()
    session[TERMINATION_TOMBSTONES_KEY] = blob
    _mirror_session_tombstone_lists(session, blob)
    return blob


def is_live_draft_permanently_retired(
    session: dict[str, Any],
    *,
    draft_id: str = "",
    room_id: str = "",
    room_code: str = "",
    room: dict[str, Any] | None = None,
) -> bool:
    """True when this identity must never auto-restore as an active Live Draft."""
    if isinstance(room, dict):
        status = str(room.get("status") or "").strip().lower()
        if status in TERMINAL_ROOM_STATUSES:
            return True
        d, r, c = _ids_from_room(session, room)
        draft_id = draft_id or d
        room_id = room_id or r
        room_code = room_code or c

    blob = load_durable_tombstones(session)
    code = str(room_code or "").strip().upper()
    did = str(draft_id or "").strip()
    rid = str(room_id or "").strip()
    if code and code in (blob.get("room_codes") or []):
        return True
    if did and did in (blob.get("draft_ids") or []):
        return True
    if rid and rid in (blob.get("room_ids") or []):
        return True

    # Legacy session-only lists (pre-durable builds) — do not call back into
    # live_draft_completion.is_live_draft_ended_tombstoned (recursion).
    codes = session.get(ENDED_ROOM_CODES_KEY)
    if code and isinstance(codes, list) and code in codes:
        return True
    ids = session.get(ENDED_DRAFT_IDS_KEY)
    if did and isinstance(ids, list) and did in ids:
        return True
    try:
        from live_draft_completion import ENDED_DRAFT_IDS_KEY as C_IDS
        from live_draft_completion import ENDED_ROOM_CODES_KEY as C_CODES

        codes2 = session.get(C_CODES)
        if code and isinstance(codes2, list) and code in codes2:
            return True
        ids2 = session.get(C_IDS)
        if did and isinstance(ids2, list) and did in ids2:
            return True
    except ImportError:
        pass
    return False


def capture_last_draft_board_snapshot(
    session: dict[str, Any],
    room: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Isolate ended picks as a temporary Simulator/sidebar snapshot (not a live room)."""
    if not isinstance(room, dict):
        return None
    board = room.get("draft_board")
    if not isinstance(board, list) or not board:
        # Fall back to canonical simulator table if live board empty.
        try:
            from draft_room_state import DRAFT_ROOM_TABLE_KEY, table_pick_count

            table = session.get(DRAFT_ROOM_TABLE_KEY)
            if table_pick_count(table) <= 0:
                return None
        except ImportError:
            return None

    draft_id, room_id, code = _ids_from_room(session, room)
    cfg = dict(room.get("config") or {})
    picks = []
    if isinstance(board, list):
        for row in board:
            if not isinstance(row, dict):
                continue
            picks.append(
                {
                    "pick": row.get("Pick") or row.get("pick"),
                    "round": row.get("Round") or row.get("round"),
                    "team": row.get("Team") or row.get("team"),
                    "fullName": row.get("fullName") or row.get("player") or row.get("Player"),
                    "playerID": row.get("playerID") or row.get("player_id"),
                    "position": row.get("Primary Position") or row.get("position"),
                }
            )
    total = int(cfg.get("total_picks") or cfg.get("num_rounds", 0) * cfg.get("num_teams", 0) or 0)
    if not total:
        try:
            from live_draft_safe_mode import total_expected_picks

            total = int(total_expected_picks(room) or 0)
        except ImportError:
            total = len(picks)

    snap = {
        "kind": "last_draft_board_snapshot",
        "not_a_live_room": True,
        "draft_id": draft_id,
        "room_id": room_id,
        "ended_room_code": code or None,
        "league_name": str(cfg.get("league_name") or room.get("league_name") or "Previous Draft").strip(),
        "pick_count": len(picks),
        "total_picks": total or len(picks),
        "picks": picks,
        "teams": list(room.get("teams") or cfg.get("teams") or []),
        "captured_at": _utc_now_iso(),
        "label": f"Last Draft Board: {len(picks)} of {total or len(picks)} picks",
    }
    session[LAST_DRAFT_BOARD_SNAPSHOT_KEY] = snap
    return snap


def clear_last_draft_board_snapshot(session: dict[str, Any]) -> None:
    session.pop(LAST_DRAFT_BOARD_SNAPSHOT_KEY, None)


def get_last_draft_board_snapshot(session: dict[str, Any]) -> dict[str, Any] | None:
    snap = session.get(LAST_DRAFT_BOARD_SNAPSHOT_KEY)
    if isinstance(snap, dict) and snap.get("not_a_live_room"):
        return snap
    return None


def _clear_query_room_params(st: Any | None) -> None:
    if st is None:
        return
    try:
        qp = dict(st.query_params) if hasattr(st, "query_params") else {}
        for key in ("room_code", "draft_room_code", "live_draft_room_code", "code"):
            if key in qp:
                try:
                    del st.query_params[key]
                except Exception:
                    pass
    except Exception:
        pass


def _close_backend_room(
    session: dict[str, Any],
    *,
    room_code: str,
    terminal_status: str,
) -> None:
    code = str(room_code or "").strip().upper()
    if not code:
        return
    try:
        from draft_room_membership import is_room_host
        from draft_room_shared_state import bump_revision, get_shared_room_store, load_shared_room

        document = load_shared_room(code)
        if not isinstance(document, dict):
            return
        if is_room_host(session, document):
            updated = bump_revision(document)
            updated["status"] = terminal_status
            updated["terminated_at"] = _utc_now_iso()
            updated["termination"] = terminal_status
            room_blob = updated.get("room")
            if isinstance(room_blob, dict):
                room_blob["status"] = terminal_status
            get_shared_room_store().save(updated)
        try:
            from draft_room_context import leave_shared_draft_room

            leave_shared_draft_room(session)
        except ImportError:
            pass
    except Exception:
        try:
            from draft_room_context import leave_shared_draft_room

            leave_shared_draft_room(session)
        except Exception:
            pass


def _clear_runtime_pointers(session: dict[str, Any], *, clear_queues: bool) -> list[str]:
    cleared: list[str] = []
    for key in TERMINATION_CLEAR_KEYS:
        if key in session:
            session.pop(key, None)
            cleared.append(key)
    try:
        from live_draft_state import clear_live_draft_state

        clear_live_draft_state(session, reason="live_draft_termination")
        cleared.append("clear_live_draft_state")
    except Exception:
        session.pop("live_draft_room", None)
        session.pop("live_draft_state", None)
    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Live Draft Room")
        if isinstance(block, dict):
            block.pop("live_draft_room", None)
            cleared.append("page_filter_live_draft_room")
    if clear_queues:
        try:
            from draft_state import DRAFT_QUEUE_KEY, DRAFT_WATCHLIST_FAVORITES_KEY, DRAFT_WATCHLIST_FOCUS_KEY

            session[DRAFT_QUEUE_KEY] = []
            session[DRAFT_WATCHLIST_FOCUS_KEY] = []
            session[DRAFT_WATCHLIST_FAVORITES_KEY] = []
            cleared.extend([DRAFT_QUEUE_KEY, DRAFT_WATCHLIST_FOCUS_KEY, DRAFT_WATCHLIST_FAVORITES_KEY])
        except ImportError:
            pass
    try:
        from draft_room_shared_state import invalidate_shared_room_document_cache

        invalidate_shared_room_document_cache(session, "")
    except Exception:
        pass
    try:
        from suite_storage_supabase import invalidate_shared_draft_room_read_cache

        invalidate_shared_draft_room_read_cache()
    except Exception:
        pass
    return cleared


def _mark_membership_left(session: dict[str, Any], room_code: str) -> None:
    code = str(room_code or "").strip().upper()
    if not code:
        return
    try:
        from draft_room_participant_state import mark_participant_left_room, resolve_participant_id

        mark_participant_left_room(
            session,
            code,
            participant_id=resolve_participant_id(session),
        )
    except Exception:
        pass


def permanently_end_live_draft(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    canonical_user_id: str = "",
    draft_id: str = "",
    room_id: str = "",
    room_code: str = "",
    reason: str = "permanently_end_live_draft",
) -> dict[str, Any]:
    """End the active Live Draft permanently; keep temporary last-board snapshot."""
    del canonical_user_id  # reserved for future auth-scoped tombstone rows
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        room = {}
    d_id, r_id, code = _ids_from_room(session, room)
    draft_id = str(draft_id or d_id or "").strip()
    room_id = str(room_id or r_id or "").strip()
    room_code = str(room_code or code or "").strip().upper()

    snapshot = capture_last_draft_board_snapshot(session, room if room else None)

    # Sync picks into simulator table so sidebar/Simulator can show the snapshot board.
    if room:
        try:
            from draft_room_state import sync_live_draft_room_to_canonical_board

            sync_live_draft_room_to_canonical_board(session, room)
        except Exception:
            pass

    persist_durable_tombstones(
        session, draft_id=draft_id, room_id=room_id, room_code=room_code
    )
    _close_backend_room(session, room_code=room_code, terminal_status="ended")
    _mark_membership_left(session, room_code)
    cleared = _clear_runtime_pointers(session, clear_queues=True)
    bump_live_draft_page_epoch(session)
    _clear_query_room_params(st)

    # Re-seed setup preferences (mode preserved via preferred_next_draft_mode).
    try:
        from user_page_preferences import (
            ensure_live_draft_setup_preferences_loaded,
            restore_live_draft_setup_mode_preference,
        )

        session.pop("_prefs_initialized:live_draft_setup", None)
        restore_live_draft_setup_mode_preference(session)
        ensure_live_draft_setup_preferences_loaded(session)
    except ImportError:
        pass

    try:
        from live_draft_state import commit_live_draft_room

        if st is not None:
            commit_live_draft_room(st, session, None, reason=reason)
    except Exception:
        pass

    session[ENDED_NOTICE_KEY] = {
        "message": (
            "Ended the Live Draft session permanently. The live room cannot be resumed. "
            "Previous picks may remain temporarily in the Draft Simulator until you start another live draft."
        ),
        "ended_at": _utc_now_iso(),
        "ended_room_code": room_code or None,
        "ended_draft_id": draft_id or None,
        "preserved_snapshot": bool(snapshot),
        "cleared_keys": list(cleared),
        "operation": "end",
    }
    # Alias for existing setup notice reader.
    session["_live_draft_session_ended_notice"] = session[ENDED_NOTICE_KEY]

    try:
        from baseball_persistent_state import force_save_baseball_state

        if st is not None:
            force_save_baseball_state(st, reason=reason)
        else:
            force_save_baseball_state(
                type("S", (), {"session_state": session})(),
                reason=reason,
            )
    except Exception:
        pass

    return {
        "ok": True,
        "operation": "end",
        "draft_id": draft_id or None,
        "room_id": room_id or None,
        "room_code": room_code or None,
        "snapshot": snapshot,
        "cleared_keys": cleared,
    }


def permanently_delete_live_draft(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    canonical_user_id: str = "",
    draft_id: str = "",
    room_id: str = "",
    room_code: str = "",
    delete_saved_library_copy: bool = False,
    reason: str = "permanently_delete_live_draft",
) -> dict[str, Any]:
    """Delete live room + temporary board snapshot. Saved library only if explicitly requested."""
    del canonical_user_id
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        room = {}
    d_id, r_id, code = _ids_from_room(session, room)
    draft_id = str(draft_id or d_id or "").strip()
    room_id = str(room_id or r_id or "").strip()
    room_code = str(room_code or code or "").strip().upper()

    persist_durable_tombstones(
        session, draft_id=draft_id, room_id=room_id, room_code=room_code
    )
    _close_backend_room(session, room_code=room_code, terminal_status="deleted")
    _mark_membership_left(session, room_code)
    cleared = _clear_runtime_pointers(session, clear_queues=True)
    clear_last_draft_board_snapshot(session)

    try:
        from draft_room_state import delete_active_draft

        delete_active_draft(session, clear_queue=True)
        cleared.append("delete_active_draft")
    except Exception:
        try:
            from draft_room_state import reset_canonical_draft_board

            reset_canonical_draft_board(session)
            cleared.append("reset_canonical_draft_board")
        except Exception:
            pass

    bump_live_draft_page_epoch(session)
    _clear_query_room_params(st)

    if delete_saved_library_copy and draft_id:
        try:
            # Explicit only — never silent.
            from draft_library_manifest import mark_draft_deleted_from_library

            mark_draft_deleted_from_library(session, draft_id)
            cleared.append("saved_library_copy")
        except Exception:
            try:
                from draft_archive_state import delete_draft_archive

                delete_draft_archive(session, draft_id)
                cleared.append("saved_library_copy")
            except Exception:
                pass

    try:
        from user_page_preferences import (
            ensure_live_draft_setup_preferences_loaded,
            restore_live_draft_setup_mode_preference,
        )

        session.pop("_prefs_initialized:live_draft_setup", None)
        restore_live_draft_setup_mode_preference(session)
        ensure_live_draft_setup_preferences_loaded(session)
    except ImportError:
        pass

    try:
        from live_draft_state import commit_live_draft_room

        if st is not None:
            commit_live_draft_room(st, session, None, reason=reason)
    except Exception:
        pass

    session[ENDED_NOTICE_KEY] = {
        "message": (
            "Deleted the draft permanently. The live room and temporary draft board were removed "
            "and cannot be restored."
        ),
        "ended_at": _utc_now_iso(),
        "ended_room_code": room_code or None,
        "ended_draft_id": draft_id or None,
        "preserved_snapshot": False,
        "cleared_keys": list(cleared),
        "operation": "delete",
    }
    session["_live_draft_session_ended_notice"] = session[ENDED_NOTICE_KEY]

    try:
        from baseball_persistent_state import force_save_baseball_state

        if st is not None:
            force_save_baseball_state(st, reason=reason)
        else:
            force_save_baseball_state(
                type("S", (), {"session_state": session})(),
                reason=reason,
            )
    except Exception:
        pass

    return {
        "ok": True,
        "operation": "delete",
        "draft_id": draft_id or None,
        "room_id": room_id or None,
        "room_code": room_code or None,
        "snapshot": None,
        "cleared_keys": cleared,
    }


def reset_context_for_new_live_draft(session: dict[str, Any]) -> dict[str, Any]:
    """On successful new Solo/Shared create — wipe prior temporary board and bind Pick 1."""
    clear_last_draft_board_snapshot(session)
    try:
        from draft_room_state import delete_active_draft

        # Keep live room that was just created — only wipe simulator leftovers first.
        # Caller sets the new live room after this; wipe board/queue then let start seed Pick 1.
        session.pop("draft_room_table", None)
        session.pop("draft_room_state", None)
        session.pop("simulated_draft_room_table", None)
    except Exception:
        pass
    try:
        from draft_room_state import reset_canonical_draft_board

        reset_canonical_draft_board(session)
    except Exception:
        pass
    try:
        from draft_state import clear_draft_queue

        clear_draft_queue(session, reason="new_live_draft_reset")
    except Exception:
        session["draft_queue"] = []
    session["draft_queue"] = []
    for key in (
        "_live_draft_rec_cache",
        "_live_draft_joined_participants_cache",
        "_live_draft_start_feedback",
        "_shared_draft_room_created_flash",
        "_draft_join_flash",
        "show_live_draft",
        "draft_started",
        "live_draft_active",
    ):
        session.pop(key, None)
    bump_live_draft_page_epoch(session)
    return {"ok": True, "pick_index": 0}


def apply_guest_ended_room_notice(session: dict[str, Any], *, room_code: str = "") -> None:
    session[GUEST_ENDED_NOTICE_KEY] = {
        "message": "This draft has ended.",
        "room_code": str(room_code or "").strip().upper() or None,
        "at": _utc_now_iso(),
    }


def handle_shared_document_terminal(
    session: dict[str, Any],
    document: dict[str, Any] | None,
) -> bool:
    """If shared doc is ended/closed/deleted, clear local active runtime. Returns True if terminated."""
    if not isinstance(document, dict):
        return False
    status = str(document.get("status") or "").strip().lower()
    room_blob = document.get("room") if isinstance(document.get("room"), dict) else {}
    room_status = str(room_blob.get("status") or "").strip().lower()
    if status not in TERMINAL_ROOM_STATUSES and room_status not in TERMINAL_ROOM_STATUSES:
        return False
    code = str(document.get("room_code") or "").strip().upper()
    draft_id = str(
        document.get("draft_room_id")
        or room_blob.get("draft_room_id")
        or ""
    ).strip()
    persist_durable_tombstones(session, draft_id=draft_id, room_id=draft_id, room_code=code)
    apply_guest_ended_room_notice(session, room_code=code)
    _mark_membership_left(session, code)
    _clear_runtime_pointers(session, clear_queues=True)
    bump_live_draft_page_epoch(session)
    return True


def repair_corrupted_live_draft_lifecycle(session: dict[str, Any]) -> dict[str, Any]:
    """One-time / each-boot repair for accounts that still hold ended rooms as active."""
    actions: list[str] = []
    # Hydrate durable tombstones from any legacy session lists.
    legacy_codes = session.get(ENDED_ROOM_CODES_KEY)
    legacy_ids = session.get(ENDED_DRAFT_IDS_KEY)
    if isinstance(legacy_codes, list) or isinstance(legacy_ids, list):
        for code in legacy_codes or []:
            persist_durable_tombstones(session, room_code=str(code))
            actions.append(f"mirror_code:{code}")
        for did in legacy_ids or []:
            persist_durable_tombstones(session, draft_id=str(did))
            actions.append(f"mirror_id:{did}")

    room = session.get("live_draft_room")
    if isinstance(room, dict):
        draft_id, room_id, code = _ids_from_room(session, room)
        status = str(room.get("status") or "").strip().lower()
        if (
            status in TERMINAL_ROOM_STATUSES
            or is_live_draft_permanently_retired(
                session, draft_id=draft_id, room_id=room_id, room_code=code, room=room
            )
        ):
            if status not in ("ended", "deleted") and room.get("draft_board"):
                capture_last_draft_board_snapshot(session, room)
                actions.append("preserve_snapshot")
            persist_durable_tombstones(
                session, draft_id=draft_id, room_id=room_id, room_code=code
            )
            _clear_runtime_pointers(session, clear_queues=True)
            actions.append("cleared_terminal_runtime")

    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if code and is_live_draft_permanently_retired(session, room_code=code):
        _mark_membership_left(session, code)
        session.pop("active_shared_draft_room_code", None)
        actions.append(f"cleared_tombstoned_code:{code}")
        try:
            from draft_room_shared_state import load_shared_room

            doc = load_shared_room(code)
            handle_shared_document_terminal(session, doc if isinstance(doc, dict) else None)
        except Exception:
            pass

    # Conflicting flags: setup chrome + live room.
    if session.get("live_draft_room") is None:
        for flag in ("show_live_draft", "draft_started", "live_draft_active"):
            if session.pop(flag, None) is not None:
                actions.append(f"cleared_flag:{flag}")
        session.pop("_live_draft_start_feedback", None)
        session.pop("_shared_draft_room_created_flash", None)
        session.pop("_draft_join_flash", None)

    # Snapshot must never be treated as live room.
    snap = get_last_draft_board_snapshot(session)
    if snap and isinstance(session.get("live_draft_room"), dict):
        live = session["live_draft_room"]
        if str(live.get("draft_room_id") or "") == str(snap.get("draft_id") or "") and str(
            live.get("status") or ""
        ).lower() in TERMINAL_ROOM_STATUSES:
            session.pop("live_draft_room", None)
            actions.append("detached_snapshot_from_live")

    session[REPAIR_DONE_KEY] = _utc_now_iso()
    session["_live_draft_lifecycle_repair_actions"] = actions
    return {"ok": True, "actions": actions}


def on_permanently_end_live_draft() -> None:
    try:
        import streamlit as st_mod
    except Exception:
        return
    permanently_end_live_draft(st_mod.session_state, st=st_mod)
    try:
        st_mod.rerun()
    except Exception:
        pass


def on_permanently_delete_live_draft() -> None:
    try:
        import streamlit as st_mod
    except Exception:
        return
    permanently_delete_live_draft(st_mod.session_state, st=st_mod)
    try:
        st_mod.rerun()
    except Exception:
        pass
