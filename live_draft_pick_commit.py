"""Unified live draft pick persistence — shared by manual pick and timer auto-pick."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from live_draft_pick_engine import live_draft_make_pick
from live_draft_timer_logic import live_draft_current_slot


@dataclass
class PickCommitResult:
    ok: bool
    message: str
    error: str
    commit_path: str
    board_size_before: int
    board_size_after: int
    current_pick_index_before: int
    current_pick_index_after: int
    expected_revision: int | None = None


def resolve_live_room(session: dict[str, Any], room: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if isinstance(room, dict):
        return room
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        live = session.get(LIVE_DRAFT_ROOM_KEY)
        if isinstance(live, dict):
            return live
    except ImportError:
        pass
    return None


def sync_expected_revision(session: dict[str, Any]) -> int | None:
    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_shared_state import (
            ACTIVE_SHARED_ROOM_CODE_KEY,
            SHARED_ROOM_META_KEY,
            get_shared_room_store,
            publish_shared_room_runtime,
            shared_document_room_blob,
        )
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        if not is_multiplayer_draft_active(session):
            return None
        room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
        backend = get_shared_room_store()
        shared_doc = backend.load(room_code) if room_code else None
        head_rev = int(shared_doc.get("revision") or 0) if isinstance(shared_doc, dict) else 0
        meta_rev = int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)
        if head_rev > meta_rev and isinstance(shared_doc, dict):
            runtime = session.get(LIVE_DRAFT_ROOM_KEY)
            remote_room = shared_document_room_blob(shared_doc)
            if not isinstance(remote_room, dict):
                remote_room = shared_doc.get("live_room") if isinstance(shared_doc.get("live_room"), dict) else shared_doc
            local_picks = len((runtime or {}).get("draft_board") or []) if isinstance(runtime, dict) else 0
            remote_picks = len((remote_room or {}).get("draft_board") or []) if isinstance(remote_room, dict) else 0
            if local_picks < remote_picks:
                return meta_rev
            try:
                from live_draft_state import should_prefer_runtime_live_room

                if isinstance(runtime, dict) and isinstance(remote_room, dict) and should_prefer_runtime_live_room(
                    session, runtime, remote_room
                ):
                    return head_rev
            except ImportError:
                pass
            publish_shared_room_runtime(session, shared_doc, reason="shared_room_pre_pick_sync")
        return head_rev
    except ImportError:
        return None


def persist_applied_pick(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    source: str,
    expected_revision: int | None = None,
    board_size_before: int | None = None,
    idx_before: int | None = None,
) -> PickCommitResult:
    """Persist a pick already applied to the in-memory room (make_pick already ran)."""
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, write_canonical_live_draft_state
    except ImportError as exc:
        return PickCommitResult(
            ok=False,
            message=str(exc),
            error="import_failed",
            commit_path="unknown",
            board_size_before=board_size_before or 0,
            board_size_after=len(room.get("draft_board") or []),
            current_pick_index_before=idx_before or 0,
            current_pick_index_after=int(room.get("current_pick_index") or 0),
        )

    board_before = board_size_before if board_size_before is not None else len(room.get("draft_board") or [])
    idx_b = idx_before if idx_before is not None else int(room.get("current_pick_index") or 0) - 1
    idx_a = int(room.get("current_pick_index") or 0)
    board_after = len(room.get("draft_board") or [])

    try:
        from draft_room_context import commit_shared_room_state, is_multiplayer_draft_active

        mp = is_multiplayer_draft_active(session)
    except ImportError:
        mp = False

    commit_path = "shared_room" if mp else "single_user"
    session[LIVE_DRAFT_ROOM_KEY] = room

    if mp:
        rev = expected_revision if expected_revision is not None else sync_expected_revision(session)
        ok_commit, commit_msg, _saved = commit_shared_room_state(
            session,
            room,
            pick_already_applied=True,
            expected_revision=rev,
        )
        if not ok_commit:
            return PickCommitResult(
                ok=False,
                message=commit_msg or "Could not sync pick to shared room.",
                error="shared_commit_failed",
                commit_path=commit_path,
                board_size_before=board_before,
                board_size_after=len((session.get(LIVE_DRAFT_ROOM_KEY) or {}).get("draft_board") or []),
                current_pick_index_before=idx_b,
                current_pick_index_after=int((session.get(LIVE_DRAFT_ROOM_KEY) or {}).get("current_pick_index") or idx_b),
                expected_revision=rev,
            )
    else:
        pass

    try:
        from live_draft_state import (
            defer_live_draft_pick_activity,
            invalidate_live_draft_prepare_cache,
            mark_live_draft_board_sync_pending,
        )

        invalidate_live_draft_prepare_cache(session, reason=f"pick:{source}")
        if mp:
            try:
                from draft_room_state import sync_live_draft_room_to_canonical_board

                sync_live_draft_room_to_canonical_board(session, room)
            except ImportError:
                pass
            try:
                from baseball_draft_activity import after_live_draft_pick_committed

                after_live_draft_pick_committed(session, room)
            except Exception:
                pass
        else:
            mark_live_draft_board_sync_pending(session, reason=source)
            defer_live_draft_pick_activity(session, room, source=source)
    except ImportError:
        try:
            from draft_room_state import sync_live_draft_room_to_canonical_board

            sync_live_draft_room_to_canonical_board(session, room)
        except ImportError:
            pass
        try:
            from baseball_draft_activity import after_live_draft_pick_committed

            after_live_draft_pick_committed(session, room)
        except Exception:
            pass

    if mp:
        write_canonical_live_draft_state(session, room, reason=source, local_edit=False)
    else:
        try:
            from live_draft_state import patch_canonical_live_draft_pick_fields

            patch_canonical_live_draft_pick_fields(session, room, reason=source, local_edit=True)
        except ImportError:
            write_canonical_live_draft_state(session, room, reason=source, local_edit=True)
    if mp:
        try:
            from live_draft_state import clear_live_draft_local_edit

            clear_live_draft_local_edit(session)
        except ImportError:
            pass
        try:
            from live_draft_mp_diagnostics import record_multiplayer_sync_diagnostics

            record_multiplayer_sync_diagnostics(
                session,
                room=room,
                last_pick_source=source,
                last_shared_write_ok=True,
            )
        except ImportError:
            pass

    return PickCommitResult(
        ok=True,
        message="Pick saved.",
        error="",
        commit_path=commit_path,
        board_size_before=board_before,
        board_size_after=board_after,
        current_pick_index_before=idx_b,
        current_pick_index_after=idx_a,
        expected_revision=expected_revision,
    )


def commit_manual_live_pick(
    session: dict[str, Any],
    room: dict[str, Any],
    player_row: dict[str, Any],
    *,
    source: str,
    verdict: str | None = None,
) -> PickCommitResult:
    """Apply make_pick then persist — manual draft path."""
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            commit_function_entered=True,
            manual_pick_commit_path="commit_manual_live_pick",
        )
    except ImportError:
        pass
    board_before = len(room.get("draft_board") or [])
    idx_before = int(room.get("current_pick_index") or 0)
    try:
        from live_draft_pick_engine import build_structured_pick_verdict, normalize_pick_source_label

        source_label = normalize_pick_source_label(source)
        verdict_text = verdict or build_structured_pick_verdict(dict(player_row), pick_source=source_label)
    except ImportError:
        source_label = str(source or "Manual Pick")
        verdict_text = verdict or f"Draft ({source})"
    expected_revision = sync_expected_revision(session)

    ok, msg = live_draft_make_pick(
        room,
        player_row,
        verdict=verdict_text,
        pick_source=source_label,
        snapshot=dict(player_row),
    )
    if not ok:
        result = PickCommitResult(
            ok=False,
            message=msg,
            error="live_make_pick_failed",
            commit_path="not_reached",
            board_size_before=board_before,
            board_size_after=board_before,
            current_pick_index_before=idx_before,
            current_pick_index_after=idx_before,
        )
        try:
            from draft_commit_diagnostics import record_draft_commit_diagnostics

            record_draft_commit_diagnostics(session, commit_function_returned=True, manual_pick_success=False, manual_pick_error=msg)
        except ImportError:
            pass
        return result

    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        session[LIVE_DRAFT_ROOM_KEY] = room
        try:
            from live_draft_ui_cache import invalidate_draft_assistant_scoring_cache, invalidate_live_draft_ui_caches

            invalidate_live_draft_ui_caches(session)
            invalidate_draft_assistant_scoring_cache(session)
        except ImportError:
            session.pop("_live_draft_rec_cache", None)
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            local_optimistic_update_applied=True,
            board_size_after=len(room.get("draft_board") or []),
            current_pick_index_after=int(room.get("current_pick_index") or 0),
        )
        if str(source).startswith("rec_card") or session.get("_rec_card_commit_in_flight"):
            record_draft_commit_diagnostics(session, rec_card_commit_started=True)
    except ImportError:
        pass

    persisted = persist_applied_pick(
        session,
        room,
        source=source,
        expected_revision=expected_revision,
        board_size_before=board_before,
        idx_before=idx_before,
    )
    if not persisted.ok:
        try:
            from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, get_shared_room_store, publish_shared_room_runtime

            code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
            if code:
                head = get_shared_room_store().load(code)
                if isinstance(head, dict):
                    publish_shared_room_runtime(session, head, reason="rollback_failed_pick")
                    room = session.get(LIVE_DRAFT_ROOM_KEY) or room
        except ImportError:
            pass
    if persisted.ok:
        persisted.message = msg
        try:
            from draft_commit_diagnostics import record_draft_commit_diagnostics

            updates: dict[str, Any] = {}
            if session.pop("_rec_card_commit_in_flight", None):
                updates["rec_card_commit_success"] = True
            if updates:
                record_draft_commit_diagnostics(session, **updates)
            try:
                from live_draft_room_ui import record_rec_card_diagnostics

                if updates.get("rec_card_commit_success"):
                    record_rec_card_diagnostics(session, rec_card_commit_success=True)
            except ImportError:
                pass
        except ImportError:
            pass
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(
            session,
            commit_function_returned=True,
            manual_pick_success=persisted.ok,
            manual_pick_error=None if persisted.ok else persisted.message,
            manual_pick_commit_path=persisted.commit_path,
        )
    except ImportError:
        pass
    return persisted


def run_autopick_selection(room: dict[str, Any], session: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Select and apply auto-pick to room (make_pick only — caller persists)."""
    from live_draft_autopick import live_draft_auto_pick

    return live_draft_auto_pick(room, session=session)
