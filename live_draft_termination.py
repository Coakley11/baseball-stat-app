"""Canonical Live Draft End / Delete termination — permanent, exclusive lifecycle."""

from __future__ import annotations

import copy
import time
from datetime import datetime, timezone
from typing import Any

LAST_DRAFT_BOARD_SNAPSHOT_KEY = "last_draft_board_snapshot"
TERMINATION_TOMBSTONES_KEY = "live_draft_termination_tombstones"
PAGE_FRAGMENT_EPOCH_KEY = "_live_draft_page_fragment_epoch"
SUPPRESS_FRAGMENTS_KEY = "_live_draft_suppress_fragments"
DELETING_STATUS_KEY = "_live_draft_deleting"
REPAIR_DONE_KEY = "_live_draft_lifecycle_repair_v1_done"
ENDED_NOTICE_KEY = "_live_draft_session_ended_notice"
GUEST_ENDED_NOTICE_KEY = "_live_draft_guest_ended_notice"

# Session mirrors (also synced into durable tombstone blob).
ENDED_ROOM_CODES_KEY = "_live_draft_ended_room_codes"
ENDED_DRAFT_IDS_KEY = "_live_draft_ended_draft_ids"
ENDED_ROOM_IDS_KEY = "_live_draft_ended_room_ids"

# End/Delete (and similar) — permanently retired; never auto-restore.
DELETED_ROOM_STATUSES = frozenset({"ended", "closed", "deleted"})
# Natural draft completion — keep in session for Save to Draft Library / Analyze.
COMPLETED_ROOM_STATUSES = frozenset({"complete", "completed"})
# Broad terminal set for snapshots / shared-doc bookkeeping (not permanent retirement).
TERMINAL_ROOM_STATUSES = DELETED_ROOM_STATUSES | COMPLETED_ROOM_STATUSES

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
    # Fragments must stop painting the prior room after discard / epoch bump.
    session[SUPPRESS_FRAGMENTS_KEY] = nxt
    session.pop("_live_draft_poll_fragment_active", None)
    return nxt


def live_draft_fragments_suppressed(session: dict[str, Any]) -> bool:
    """True when poll/timer/queue fragments must not paint (delete in flight or setup-only)."""
    deleting = str(session.get(DELETING_STATUS_KEY) or "").strip().lower()
    if deleting == "in_progress":
        return True
    if bool(session.get(SUPPRESS_FRAGMENTS_KEY)):
        # Keep suppress until a non-setup lifecycle owns an active room again.
        room = session.get("live_draft_room")
        if not isinstance(room, dict):
            return True
        status = str(room.get("status") or "").strip().lower()
        if status in ("ended", "closed", "deleted", "complete", "completed"):
            return True
        if deleting == "done":
            return True
    return False


def clear_fragment_suppress_for_active_room(session: dict[str, Any]) -> None:
    """Allow fragments again for a live room — never clear a finished End/Delete flag.

    Popping ``_live_draft_deleting`` after a successful delete let prepare/restore
    rehydrate the room and the lifecycle fall through to ACTIVE. Only a brand-new
    draft create (``reset_context_for_new_live_draft``) may clear the done flag.
    """
    deleting = str(session.get(DELETING_STATUS_KEY) or "").strip().lower()
    if deleting in ("in_progress", "done"):
        return
    room = session.get("live_draft_room")
    if isinstance(room, dict) and str(room.get("status") or "").strip().lower() in (
        "in_progress",
        "paused",
        "waiting",
        "not_started",
    ):
        session.pop(SUPPRESS_FRAGMENTS_KEY, None)


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
    """True when this identity must never auto-restore as an active Live Draft.

    Natural ``complete`` status is NOT retirement — a stale complete flag on an
    unfinished board must not wipe the room, and a finished draft must stay
    available for Save to Draft Library / Analyze.
    """
    if isinstance(room, dict):
        status = str(room.get("status") or "").strip().lower()
        if status in DELETED_ROOM_STATUSES:
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


def session_may_close_backend_shared_room(
    session: dict[str, Any],
    room_code: str,
    *,
    document: dict[str, Any] | None = None,
) -> bool:
    """True when this session may tombstone the authoritative shared room.

    Commissioner-only once a host is stamped. Guests must leave locally without
    deleting the room for everyone. Sessions with no stamped commissioner
    (legacy/unit fixtures) keep the prior close behavior.
    """
    code = str(room_code or "").strip().upper()
    if not code:
        return True
    doc = document if isinstance(document, dict) else None
    if doc is None:
        try:
            from draft_room_shared_state import load_shared_room

            loaded = load_shared_room(code)
            doc = loaded if isinstance(loaded, dict) else None
        except Exception:
            doc = None
    if not isinstance(doc, dict):
        return True
    try:
        from shared_draft_permissions import commissioner_participant_id, is_canonical_commissioner

        if is_canonical_commissioner(session, doc):
            return True
        if commissioner_participant_id(doc):
            return False
    except ImportError:
        pass
    return True


def _close_backend_room(
    session: dict[str, Any],
    *,
    room_code: str,
    terminal_status: str,
) -> None:
    code = str(room_code or "").strip().upper()
    if not code:
        try:
            from draft_room_context import leave_shared_draft_room

            leave_shared_draft_room(session)
        except Exception:
            pass
        return
    try:
        from draft_room_shared_state import bump_revision, get_shared_room_store, load_shared_room

        document = load_shared_room(code)
        if isinstance(document, dict):
            if not session_may_close_backend_shared_room(session, code, document=document):
                # Guest/non-commissioner: release this seat only — never tombstone.
                try:
                    from draft_room_context import leave_shared_draft_room

                    leave_shared_draft_room(session)
                except Exception:
                    pass
                return
            updated = bump_revision(document)
            updated["status"] = terminal_status
            updated["terminated_at"] = _utc_now_iso()
            updated["termination"] = terminal_status
            if terminal_status in ("deleted", "ended", "closed"):
                updated["participants"] = {}
                updated["joined_participants"] = {}
                updated["team_claims"] = {}
                updated["resume_rejoined"] = {}
            room_blob = updated.get("room")
            if isinstance(room_blob, dict):
                room_blob["status"] = terminal_status
            try:
                get_shared_room_store().save(updated)
            except Exception:
                pass
            try:
                from draft_room_shared_state import invalidate_shared_room_document_cache

                invalidate_shared_room_document_cache(session, code)
            except Exception:
                pass
    except Exception:
        pass
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
        # Bust Streamlit sortable component state from the deleted draft.
        for k in list(session.keys()):
            if isinstance(k, str) and (
                k.startswith("sidebar_queue_sortable")
                or k.startswith("live_queue_sortable")
                or k.startswith("sim_queue_sortable")
            ):
                session.pop(k, None)
                cleared.append(k)
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
    """Remove every local membership / participant pointer for this room code."""
    code = str(room_code or "").strip().upper()
    if not code:
        return
    try:
        from draft_room_participant_state import (
            MEMBERSHIP_KEY,
            PARTICIPANT_STATE_KEY,
            mark_participant_left_room,
            resolve_participant_id,
        )

        mark_participant_left_room(
            session,
            code,
            participant_id=resolve_participant_id(session),
        )
        membership = session.get(MEMBERSHIP_KEY)
        if isinstance(membership, dict):
            membership.pop(code, None)
            # Also drop any case variants.
            for key in list(membership.keys()):
                if str(key).strip().upper() == code:
                    membership.pop(key, None)
        bucket = session.get(PARTICIPANT_STATE_KEY)
        if isinstance(bucket, dict):
            bucket.pop(code, None)
            for key in list(bucket.keys()):
                if str(key).strip().upper() == code:
                    bucket.pop(key, None)
    except Exception:
        pass
    try:
        from draft_room_participant_state import ACTIVE_SHARED_ROOM_CODE_KEY

        session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
    except Exception:
        session.pop("active_shared_draft_room_code", None)
    session.pop("draft_room_shared_meta", None)
    session.pop("draft_room_participant_team", None)
    session.pop("draft_room_participant_id", None)
    session.pop("room_your_team", None)
    session.pop("live_draft_my_team", None)


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
    # Idempotent: already deleted / no active room → stay on setup.
    if session.get(DELETING_STATUS_KEY) == "done" and not isinstance(session.get("live_draft_room"), dict):
        return {"ok": True, "operation": "delete", "idempotent": True}

    session[DELETING_STATUS_KEY] = "in_progress"
    session["_live_draft_delete_started_at"] = time.time()
    bump_live_draft_page_epoch(session)
    # Stop every interactive control immediately — fragments must no-op this run.
    session["_live_draft_controls_locked"] = True
    session.pop("_live_draft_timer_expired_pending", None)
    session.pop("_live_draft_page_owns_expired", None)
    session.pop("_live_draft_poll_fragment_active", None)

    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        room = {}
    d_id, r_id, code = _ids_from_room(session, room)
    draft_id = str(draft_id or d_id or "").strip()
    room_id = str(room_id or r_id or "").strip()
    room_code = str(room_code or code or "").strip().upper()

    # Guest End/Delete is leave-only. Never write a durable tombstone or
    # mark the authoritative shared document deleted — that would end the
    # draft for the commissioner and block later guest rejoin.
    if room_code and not session_may_close_backend_shared_room(session, room_code):
        try:
            from draft_room_context import leave_shared_draft_room

            leave_shared_draft_room(session)
        except Exception:
            pass
        _mark_membership_left(session, room_code)
        cleared = _clear_runtime_pointers(session, clear_queues=True)
        clear_last_draft_board_snapshot(session)
        session[DELETING_STATUS_KEY] = "done"
        session.pop("_live_draft_controls_locked", None)
        _clear_query_room_params(st)
        return {
            "ok": True,
            "operation": "leave",
            "backend_closed": False,
            "draft_id": draft_id or None,
            "room_id": room_id or None,
            "room_code": room_code or None,
            "cleared_keys": cleared,
        }

    # Snapshot sticky setup BEFORE clearing runtime so Shared/2/4 survive End/Delete.
    setup_snapshot: dict[str, Any] = {}
    try:
        from user_page_preferences import (
            PAGE_KEY_LIVE_DRAFT_SETUP,
            collect_live_draft_setup_settings,
            save_user_page_preferences,
        )

        setup_snapshot = collect_live_draft_setup_settings(session)
        # Prefer the just-active room's mode over a stale Solo preference.
        try:
            from live_draft_setup_mode import (
                LIVE_DRAFT_SETUP_MODE_KEY,
                PREFERRED_NEXT_DRAFT_MODE_KEY,
                SETUP_MODE_SHARED,
                normalize_setup_mode,
            )

            cfg = dict(room.get("config") or {}) if isinstance(room, dict) else {}
            room_mode = normalize_setup_mode(
                cfg.get("draft_setup_mode") or session.get(LIVE_DRAFT_SETUP_MODE_KEY)
            )
            if room_mode:
                setup_snapshot[LIVE_DRAFT_SETUP_MODE_KEY] = room_mode
                setup_snapshot[PREFERRED_NEXT_DRAFT_MODE_KEY] = room_mode
            # Prefer shared when an active shared room code existed.
            if room_code:
                setup_snapshot[LIVE_DRAFT_SETUP_MODE_KEY] = SETUP_MODE_SHARED
                setup_snapshot[PREFERRED_NEXT_DRAFT_MODE_KEY] = SETUP_MODE_SHARED
            # Prefer the just-deleted room's team/pick counts over stale durable 10/15.
            n_teams = cfg.get("num_teams") or len(room.get("teams") or [])
            if n_teams:
                setup_snapshot["live_draft_team_count"] = int(n_teams)
                setup_snapshot["live_draft_num_teams"] = int(n_teams)
            ppt = cfg.get("picks_per_team")
            if ppt:
                setup_snapshot["live_draft_picks_per_team"] = int(ppt)
        except ImportError:
            pass
        uid = str(session.get("auth_user_id") or "").strip()
        wid = str(
            session.get("_suite_active_workspace_id")
            or session.get("_suite_owned_workspace_id")
            or session.get("workspace_id")
            or ""
        ).strip()
        if setup_snapshot:
            save_user_page_preferences(
                uid,
                wid,
                PAGE_KEY_LIVE_DRAFT_SETUP,
                setup_snapshot,
                session=session,
                st=st,
                force_disk=True,
                merge=True,
            )
            session["_live_draft_setup_snapshot_after_delete"] = dict(setup_snapshot)
    except ImportError:
        setup_snapshot = {}

    # Also clear resumable slot when it points at this draft.
    try:
        from live_draft_resumable_slot import (
            clear_resumable_live_draft_slot,
            get_resumable_live_draft_slot,
            resumable_slot_matches_draft,
        )

        if resumable_slot_matches_draft(session, draft_id=draft_id, room_code=room_code):
            clear_resumable_live_draft_slot(session)
        elif get_resumable_live_draft_slot(session) and not draft_id and not room_code:
            clear_resumable_live_draft_slot(session)
    except ImportError:
        session.pop("resumable_live_draft_slot", None)

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

    # Mark locally dirty so enrich_save_payload cannot reinject the deleted room.
    session["_live_draft_locally_dirty"] = True
    session["_live_draft_termination_cleared"] = True

    # Epoch already bumped at start; keep suppress active for setup-only paint.
    session[SUPPRESS_FRAGMENTS_KEY] = int(session.get(PAGE_FRAGMENT_EPOCH_KEY) or 1)
    session[DELETING_STATUS_KEY] = "done"
    _clear_query_room_params(st)

    if delete_saved_library_copy and draft_id:
        try:
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
            apply_live_draft_setup_settings,
            ensure_live_draft_setup_preferences_loaded,
        )

        session.pop("_prefs_initialized:live_draft_setup", None)
        # Restore from the snapshot we just forced to disk — never stale Solo/10/15.
        restore_settings = setup_snapshot or session.get("_live_draft_setup_snapshot_after_delete")
        if isinstance(restore_settings, dict) and restore_settings:
            session["_live_draft_setup_force_mode_apply"] = True
            try:
                apply_live_draft_setup_settings(session, restore_settings)
            finally:
                session.pop("_live_draft_setup_force_mode_apply", None)
        ensure_live_draft_setup_preferences_loaded(session)
    except ImportError:
        pass

    try:
        from live_draft_state import commit_live_draft_room

        if st is not None:
            commit_live_draft_room(st, session, None, reason=reason)
    except Exception:
        pass

    # Bump global page generation so every fragment rejects the deleted instance.
    try:
        from app_page_generation import ACTIVE_PAGE_GENERATION_KEY, begin_page_run

        session[ACTIVE_PAGE_GENERATION_KEY] = int(session.get(ACTIVE_PAGE_GENERATION_KEY) or 0) + 1
        begin_page_run(session, "Live Draft Room")
    except ImportError:
        pass

    session[ENDED_NOTICE_KEY] = {
        "message": (
            "Deleted the draft permanently. The live room and temporary draft board were removed "
            "and cannot be restored. Choose Save & Continue Later next time if you want to finish later."
        ),
        "ended_at": _utc_now_iso(),
        "ended_room_code": room_code or None,
        "ended_draft_id": draft_id or None,
        "preserved_snapshot": False,
        "cleared_keys": list(cleared),
        "operation": "delete",
    }
    session["_live_draft_session_ended_notice"] = session[ENDED_NOTICE_KEY]
    session.pop("_live_draft_controls_locked", None)

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

    try:
        started = float(session.pop("_live_draft_delete_started_at", 0) or 0)
        if started:
            session["_live_draft_delete_elapsed_ms"] = int((time.time() - started) * 1000)
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
        "setup_snapshot": setup_snapshot or None,
        "delete_elapsed_ms": session.get("_live_draft_delete_elapsed_ms"),
    }


def discard_live_draft_and_start_over(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    reason: str = "discard_live_draft_and_start_over",
) -> dict[str, Any]:
    """Canonical End/Delete — permanently destroy the draft (no resume, no temp board)."""
    # Also discard resumable slot matching any parked copy of this draft.
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    d_id, _r_id, code = _ids_from_room(session, room)
    try:
        from live_draft_resumable_slot import (
            clear_resumable_live_draft_slot,
            get_resumable_live_draft_slot,
            resumable_slot_matches_draft,
        )

        slot = get_resumable_live_draft_slot(session)
        if slot and (
            not room
            or resumable_slot_matches_draft(session, draft_id=d_id, room_code=code)
        ):
            # When discarding from active room, only clear slot if it is this draft.
            if room and resumable_slot_matches_draft(session, draft_id=d_id, room_code=code):
                clear_resumable_live_draft_slot(session)
            elif not room:
                clear_resumable_live_draft_slot(session)
    except ImportError:
        pass
    result = permanently_delete_live_draft(session, st=st, reason=reason)
    if result.get("operation") != "leave":
        result["operation"] = "discard"
    return result


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
    """Deprecated alias — End now means discard (Save & Continue Later is the pause-for-later path)."""
    del canonical_user_id, draft_id, room_id, room_code
    return discard_live_draft_and_start_over(session, st=st, reason=reason)


def reset_context_for_new_live_draft(
    session: dict[str, Any],
    *,
    clear_resumable_slot: bool = True,
) -> dict[str, Any]:
    """On successful new Solo/Shared create — wipe prior temporary board and bind Pick 1."""
    clear_last_draft_board_snapshot(session)
    if clear_resumable_slot:
        try:
            from live_draft_resumable_slot import clear_resumable_live_draft_slot

            clear_resumable_live_draft_slot(session)
        except ImportError:
            session.pop("resumable_live_draft_slot", None)
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
    session.pop(DELETING_STATUS_KEY, None)
    # Must clear — lifecycle nukes every new room while this stays True after End/Delete.
    session.pop("_live_draft_force_setup_after_delete", None)
    session.pop("_live_draft_exit_deleted_room", None)
    session.pop(SUPPRESS_FRAGMENTS_KEY, None)
    session.pop("_live_draft_termination_cleared", None)
    session.pop("_live_draft_controls_locked", None)
    session.pop("_live_draft_locally_dirty", None)
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
    """If shared doc is ended/closed/deleted, clear local active runtime. Returns True if terminated.

    Natural ``complete`` is not treated as End/Delete — participants keep the
    finished room for library save / export.
    """
    if not isinstance(document, dict):
        return False
    status = str(document.get("status") or "").strip().lower()
    room_blob = document.get("room") if isinstance(document.get("room"), dict) else {}
    room_status = str(room_blob.get("status") or "").strip().lower()
    if status not in DELETED_ROOM_STATUSES and room_status not in DELETED_ROOM_STATUSES:
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
    session[DELETING_STATUS_KEY] = "done"
    session["_live_draft_force_setup_after_delete"] = True
    session[SUPPRESS_FRAGMENTS_KEY] = int(session.get(PAGE_FRAGMENT_EPOCH_KEY) or 1)
    session["_live_draft_exit_deleted_room"] = True
    try:
        from live_draft_delete_authority import note_delete_trace

        note_delete_trace(
            session,
            "poll_saw_deleted_room",
            room_code=code or None,
            draft_id=draft_id or None,
            status=status or room_status,
        )
    except ImportError:
        pass
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
        # Never clear a naturally completed draft (library / analyze still needed).
        # Never clear a stale ``complete`` flag on an unfinished board.
        deleted_like = status in DELETED_ROOM_STATUSES
        retired = is_live_draft_permanently_retired(
            session, draft_id=draft_id, room_id=room_id, room_code=code, room=room
        )
        if deleted_like or (retired and status not in COMPLETED_ROOM_STATUSES):
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
