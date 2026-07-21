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
            load_shared_room_document,
            publish_shared_room_runtime,
            shared_document_room_blob,
        )
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        if not is_multiplayer_draft_active(session):
            return None
        room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
        shared_doc = load_shared_room_document(session, room_code) if room_code else None
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
    fast_path: bool = False,
    allow_shared_failure: bool = False,
) -> PickCommitResult:
    """Persist a pick already applied to the in-memory room (make_pick already ran).

    fast_path=True (timer autopick): keep shared-room commit synchronous; defer board sync,
    activity, and local canonical cloud write to the next page flush.

    allow_shared_failure=True (Phase 2 deferred flush): shared write errors return ok=False
    without rolling back the caller's local room mutation.
    """
    import time

    persist_perf: dict[str, Any] = {}
    session["_live_draft_persist_perf"] = persist_perf
    try:
        from live_draft_perf import (
            PHASE_PICK_CANONICAL_FULL,
            PHASE_PICK_CANONICAL_PATCH,
            PHASE_PICK_DEFER_FLAGS,
            PHASE_PICK_PERSIST,
            PHASE_PICK_SHARED_COMMIT,
            live_draft_perf_action,
        )
    except ImportError:
        live_draft_perf_action = None  # type: ignore[assignment,misc]
        PHASE_PICK_PERSIST = "live_draft_pick_persist"  # type: ignore[misc]
        PHASE_PICK_SHARED_COMMIT = "live_draft_pick_shared_commit"  # type: ignore[misc]
        PHASE_PICK_DEFER_FLAGS = "live_draft_pick_defer_flags"  # type: ignore[misc]
        PHASE_PICK_CANONICAL_PATCH = "live_draft_pick_canonical_patch"  # type: ignore[misc]
        PHASE_PICK_CANONICAL_FULL = "live_draft_pick_canonical_full"  # type: ignore[misc]

    def _persist_body() -> PickCommitResult:
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
            t_shared = time.perf_counter()
            if live_draft_perf_action is not None:
                with live_draft_perf_action(session, "shared_commit", phase=PHASE_PICK_SHARED_COMMIT):
                    ok_commit, commit_msg, _saved = commit_shared_room_state(
                        session,
                        room,
                        pick_already_applied=True,
                        expected_revision=rev,
                    )
            else:
                ok_commit, commit_msg, _saved = commit_shared_room_state(
                    session,
                    room,
                    pick_already_applied=True,
                    expected_revision=rev,
                )
            persist_perf["shared_commit_ms"] = int((time.perf_counter() - t_shared) * 1000)
            if not ok_commit:
                return PickCommitResult(
                    ok=False,
                    message=commit_msg or "Could not sync pick to shared room.",
                    error="shared_commit_failed",
                    commit_path=commit_path,
                    board_size_before=board_before,
                    board_size_after=len((session.get(LIVE_DRAFT_ROOM_KEY) or {}).get("draft_board") or []),
                    current_pick_index_before=idx_b,
                    current_pick_index_after=int(
                        (session.get(LIVE_DRAFT_ROOM_KEY) or {}).get("current_pick_index") or idx_b
                    ),
                    expected_revision=rev,
                )
        else:
            pass

        _ = allow_shared_failure  # caller owns rollback policy (Phase 2 never rolls back local room)

        try:
            from live_draft_state import (
                defer_live_draft_canonical_write,
                defer_live_draft_pick_activity,
                invalidate_live_draft_prepare_cache,
                mark_live_draft_board_sync_pending,
            )

            invalidate_live_draft_prepare_cache(session, reason=f"pick:{source}")
            if mp and fast_path:
                # Shared room is authority; defer local board/activity/canonical cloud write.
                t_defer = time.perf_counter()
                mark_live_draft_board_sync_pending(session, reason=source)
                defer_live_draft_pick_activity(session, room, source=source)
                defer_live_draft_canonical_write(session, room, reason=source, local_edit=False)
                persist_perf["board_save_ms"] = 0
                persist_perf["activity_ms"] = 0
                persist_perf["cloud_write_ms"] = 0
                persist_perf["deferred_ms"] = int((time.perf_counter() - t_defer) * 1000)
            elif mp:
                t_board = time.perf_counter()
                try:
                    from draft_room_state import sync_live_draft_room_to_canonical_board

                    sync_live_draft_room_to_canonical_board(session, room)
                except ImportError:
                    pass
                persist_perf["board_save_ms"] = int((time.perf_counter() - t_board) * 1000)
                t_act = time.perf_counter()
                try:
                    from baseball_draft_activity import after_live_draft_pick_committed

                    after_live_draft_pick_committed(session, room)
                except Exception:
                    pass
                persist_perf["activity_ms"] = int((time.perf_counter() - t_act) * 1000)
            else:
                if live_draft_perf_action is not None:
                    with live_draft_perf_action(session, "defer_flags", phase=PHASE_PICK_DEFER_FLAGS):
                        mark_live_draft_board_sync_pending(session, reason=source)
                        defer_live_draft_pick_activity(session, room, source=source)
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

        if mp and not fast_path:
            t_cloud = time.perf_counter()
            if live_draft_perf_action is not None:
                with live_draft_perf_action(session, "canonical_full", phase=PHASE_PICK_CANONICAL_FULL):
                    write_canonical_live_draft_state(session, room, reason=source, local_edit=False)
            else:
                write_canonical_live_draft_state(session, room, reason=source, local_edit=False)
            persist_perf["cloud_write_ms"] = int((time.perf_counter() - t_cloud) * 1000)
        elif not mp:
            if fast_path:
                try:
                    from live_draft_state import defer_live_draft_canonical_write

                    defer_live_draft_canonical_write(session, room, reason=source, local_edit=True)
                    persist_perf["cloud_write_ms"] = 0
                except ImportError:
                    pass
            else:
                try:
                    from live_draft_state import patch_canonical_live_draft_pick_fields

                    t_cloud = time.perf_counter()
                    if live_draft_perf_action is not None:
                        with live_draft_perf_action(session, "canonical_patch", phase=PHASE_PICK_CANONICAL_PATCH):
                            patch_canonical_live_draft_pick_fields(session, room, reason=source, local_edit=True)
                    else:
                        patch_canonical_live_draft_pick_fields(session, room, reason=source, local_edit=True)
                    persist_perf["cloud_write_ms"] = int((time.perf_counter() - t_cloud) * 1000)
                except ImportError:
                    t_cloud = time.perf_counter()
                    if live_draft_perf_action is not None:
                        with live_draft_perf_action(session, "canonical_full", phase=PHASE_PICK_CANONICAL_FULL):
                            write_canonical_live_draft_state(session, room, reason=source, local_edit=True)
                    else:
                        write_canonical_live_draft_state(session, room, reason=source, local_edit=True)
                    persist_perf["cloud_write_ms"] = int((time.perf_counter() - t_cloud) * 1000)
        if mp:
            try:
                from live_draft_state import clear_live_draft_local_edit

                clear_live_draft_local_edit(session)
            except ImportError:
                pass
            if not fast_path:
                t_diag = time.perf_counter()
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
                persist_perf["poll_diag_ms"] = int((time.perf_counter() - t_diag) * 1000)
            else:
                # Lightweight mp diag update — no shared-store reload.
                diag = dict(session.get("_live_draft_mp_diag") or {})
                diag["last_pick_source"] = source
                diag["last_shared_write_ok"] = True
                session["_live_draft_mp_diag"] = diag
                persist_perf["poll_diag_ms"] = 0

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

    if live_draft_perf_action is not None:
        with live_draft_perf_action(session, "persist", phase=PHASE_PICK_PERSIST):
            return _persist_body()
    return _persist_body()


def commit_manual_live_pick(
    session: dict[str, Any],
    room: dict[str, Any],
    player_row: dict[str, Any],
    *,
    source: str,
    verdict: str | None = None,
    optimistic: bool = False,
) -> PickCommitResult:
    """Apply make_pick then persist — manual draft path.

    optimistic=True (Phase 2): mutate local board/roster/timer immediately, patch
    recommendation caches, defer durable/shared persistence. Never blocks paint on
    force_save or shared sync.
    """
    try:
        from live_draft_perf import (
            PHASE_PICK_CACHE_INVALIDATE,
            PHASE_PICK_COMMIT_DIAG,
            PHASE_PICK_MAKE_PICK,
            PHASE_PICK_SYNC_REVISION,
            PHASE_PICK_VERDICT_PREP,
            live_draft_perf_action,
        )
    except ImportError:
        live_draft_perf_action = None  # type: ignore[assignment,misc]
        PHASE_PICK_COMMIT_DIAG = "live_draft_pick_commit_diag"  # type: ignore[misc]
        PHASE_PICK_SYNC_REVISION = "live_draft_pick_sync_revision"  # type: ignore[misc]
        PHASE_PICK_VERDICT_PREP = "live_draft_pick_verdict_prep"  # type: ignore[misc]
        PHASE_PICK_MAKE_PICK = "live_draft_pick_make_pick"  # type: ignore[misc]
        PHASE_PICK_CACHE_INVALIDATE = "live_draft_pick_cache_invalidate"  # type: ignore[misc]

    def _diag(**fields: Any) -> None:
        try:
            from draft_commit_diagnostics import record_draft_commit_diagnostics

            if live_draft_perf_action is not None:
                with live_draft_perf_action(session, "commit_diag", phase=PHASE_PICK_COMMIT_DIAG):
                    record_draft_commit_diagnostics(session, **fields)
            else:
                record_draft_commit_diagnostics(session, **fields)
        except ImportError:
            pass

    _diag(
        commit_function_entered=True,
        manual_pick_commit_path="commit_manual_live_pick",
        optimistic_manual_pick=bool(optimistic),
    )
    board_before = len(room.get("draft_board") or [])
    idx_before = int(room.get("current_pick_index") or 0)
    player_id = str(player_row.get("playerID") or player_row.get("player_id") or "").strip()
    player_name = str(player_row.get("fullName") or player_row.get("Player") or "").strip()

    try:
        from live_draft_pick_persist import (
            already_applied_pick_guard,
            mark_applied_pick_guard,
            mark_pick_persist_dirty,
            pick_guard_token,
        )

        guard = pick_guard_token(room, player_id=player_id, player_name=player_name)
        if already_applied_pick_guard(session, guard):
            return PickCommitResult(
                ok=True,
                message="Pick already applied.",
                error="",
                commit_path="idempotent_guard",
                board_size_before=board_before,
                board_size_after=board_before,
                current_pick_index_before=idx_before,
                current_pick_index_after=idx_before,
            )
    except ImportError:
        guard = ""

    if live_draft_perf_action is not None:
        with live_draft_perf_action(session, "verdict_prep", phase=PHASE_PICK_VERDICT_PREP):
            try:
                from live_draft_pick_engine import build_structured_pick_verdict, normalize_pick_source_label

                source_label = normalize_pick_source_label(source)
                verdict_text = verdict or build_structured_pick_verdict(dict(player_row), pick_source=source_label)
            except ImportError:
                source_label = str(source or "Manual Pick")
                verdict_text = verdict or f"Draft ({source})"
    else:
        try:
            from live_draft_pick_engine import build_structured_pick_verdict, normalize_pick_source_label

            source_label = normalize_pick_source_label(source)
            verdict_text = verdict or build_structured_pick_verdict(dict(player_row), pick_source=source_label)
        except ImportError:
            source_label = str(source or "Manual Pick")
            verdict_text = verdict or f"Draft ({source})"

    expected_revision = None
    if not optimistic:
        if live_draft_perf_action is not None:
            with live_draft_perf_action(session, "sync_revision", phase=PHASE_PICK_SYNC_REVISION):
                expected_revision = sync_expected_revision(session)
        else:
            expected_revision = sync_expected_revision(session)

    if live_draft_perf_action is not None:
        with live_draft_perf_action(session, "make_pick", phase=PHASE_PICK_MAKE_PICK):
            ok, msg = live_draft_make_pick(
                room,
                player_row,
                verdict=verdict_text,
                pick_source=source_label,
                snapshot=dict(player_row),
                session=session,
                enrich_pick_context=False,
            )
    else:
        ok, msg = live_draft_make_pick(
            room,
            player_row,
            verdict=verdict_text,
            pick_source=source_label,
            snapshot=dict(player_row),
            session=session,
            enrich_pick_context=False,
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
        _diag(commit_function_returned=True, manual_pick_success=False, manual_pick_error=msg)
        return result

    try:
        from live_draft_pick_persist import mark_applied_pick_guard

        if guard:
            mark_applied_pick_guard(session, guard)
    except ImportError:
        pass

    # Shared side effects for every manual pick (queue, caches, snapshot, paint gate).
    if live_draft_perf_action is not None:
        with live_draft_perf_action(session, "cache_patch", phase=PHASE_PICK_CACHE_INVALIDATE):
            finalized = finalize_live_draft_pick_transition(
                session,
                room,
                source=source_label,
                player_id=player_id,
                player_name=player_name,
                board_size_before=board_before,
                idx_before=idx_before,
                persist=False,
                fast_path=bool(optimistic),
                request_immediate_paint=True,
            )
    else:
        finalized = finalize_live_draft_pick_transition(
            session,
            room,
            source=source_label,
            player_id=player_id,
            player_name=player_name,
            board_size_before=board_before,
            idx_before=idx_before,
            persist=False,
            fast_path=bool(optimistic),
            request_immediate_paint=True,
        )
    _diag(
        local_optimistic_update_applied=True,
        board_size_after=len(room.get("draft_board") or []),
        current_pick_index_after=int(room.get("current_pick_index") or 0),
    )
    if str(source).startswith("rec_card") or session.get("_rec_card_commit_in_flight"):
        _diag(rec_card_commit_started=True)

    if optimistic:
        try:
            from live_draft_pick_persist import mark_pick_persist_dirty

            mark_pick_persist_dirty(
                session,
                room,
                source=source,
                expected_revision=expected_revision,
            )
        except Exception:
            pass
        result = PickCommitResult(
            ok=True,
            message=msg or "Pick applied.",
            error="",
            commit_path="optimistic_local",
            board_size_before=board_before,
            board_size_after=len(room.get("draft_board") or []),
            current_pick_index_before=idx_before,
            current_pick_index_after=int(room.get("current_pick_index") or 0),
            expected_revision=expected_revision,
        )
        _diag(
            commit_function_returned=True,
            manual_pick_success=True,
            manual_pick_commit_path="optimistic_local",
        )
        return result

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
            from live_draft_state import LIVE_DRAFT_ROOM_KEY

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
            updates: dict[str, Any] = {}
            if session.pop("_rec_card_commit_in_flight", None):
                updates["rec_card_commit_success"] = True
            if updates:
                _diag(**updates)
            try:
                from live_draft_room_ui import record_rec_card_diagnostics

                if updates.get("rec_card_commit_success"):
                    record_rec_card_diagnostics(session, rec_card_commit_success=True)
            except ImportError:
                pass
        except ImportError:
            pass
    else:
        # Keep finalized local state even if durable persist failed.
        _ = finalized
    _diag(
        commit_function_returned=True,
        manual_pick_success=persisted.ok,
        manual_pick_error=None if persisted.ok else persisted.message,
        manual_pick_commit_path=persisted.commit_path,
    )
    return persisted


def finalize_live_draft_pick_transition(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    source: str,
    player_id: str = "",
    player_name: str = "",
    board_size_before: int | None = None,
    idx_before: int | None = None,
    persist: bool = True,
    fast_path: bool = False,
    request_immediate_paint: bool = True,
    zero_to_commit_ms: float | None = None,
) -> PickCommitResult:
    """Post-mutation side effects every pick path must run (manual, auto, expire).

    Assumes ``live_draft_make_pick`` already mutated the in-memory room.
    """
    import time

    t0 = time.perf_counter()
    board_before = int(board_size_before if board_size_before is not None else max(0, len(room.get("draft_board") or []) - 1))
    idx_b = int(idx_before if idx_before is not None else max(0, int(room.get("current_pick_index") or 0) - 1))
    pid = str(player_id or "").strip()
    pname = str(player_name or "").strip()
    if not pid or not pname:
        board = list(room.get("draft_board") or [])
        last = board[-1] if board and isinstance(board[-1], dict) else {}
        pid = pid or str(last.get("playerID") or last.get("player_id") or "").strip()
        pname = pname or str(last.get("fullName") or last.get("Player") or "").strip()

    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        session[LIVE_DRAFT_ROOM_KEY] = room
    except ImportError:
        session["live_draft_room"] = room

    # Queue prune — drafted players must leave every active queue surface immediately.
    try:
        from draft_state import remove_drafted_player_from_active_queues

        if pid:
            remove_drafted_player_from_active_queues(session, pid)
        if pname and pname != pid:
            remove_drafted_player_from_active_queues(session, pname)
    except Exception:
        pass

    # Align Solo expire guard with the pick that was just committed (pre-advance index).
    try:
        from live_draft_solo_timer import SOLO_EXPIRE_APPLIED_KEY

        room[SOLO_EXPIRE_APPLIED_KEY] = f"{_draft_id_safe(room)}|{idx_b}|{board_before}"
    except Exception:
        pass

    # Idempotency key: draft + pick index + revision (pre-commit board size as stand-in
    # when revision has not bumped yet). Fragments sharing this key must not re-pick.
    try:
        from live_draft_canonical_snapshot import auto_pick_idempotency_key, pick_commit_confirmed

        if pick_commit_confirmed(room, pick_index_before=idx_b, board_size_before=board_before):
            key = auto_pick_idempotency_key(room, pick_index=idx_b, board_size=board_before)
            session["_live_draft_last_auto_pick_idempotency_key"] = key
            room["_last_auto_pick_idempotency_key"] = key
        else:
            session.pop("_live_draft_last_auto_pick_idempotency_key", None)
            room.pop("_last_auto_pick_idempotency_key", None)
    except Exception:
        pass

    # Patch recommendation tables + invalidate Draft Assistant caches so drafted
    # players cannot reappear on the next paint.
    try:
        from live_draft_ui_cache import (
            invalidate_draft_assistant_scoring_cache,
            invalidate_draft_assistant_why_cache,
            patch_live_draft_caches_after_pick,
        )

        patch_live_draft_caches_after_pick(session, room, player_id=pid, player_name=pname)
        invalidate_draft_assistant_scoring_cache(session)
        invalidate_draft_assistant_why_cache(session)
    except Exception:
        session.pop("_live_draft_rec_cache", None)
        session.pop("_draft_assistant_scoring_cache", None)

    snap = {}
    try:
        from live_draft_canonical_snapshot import (
            install_canonical_live_draft_snapshot,
            note_pick_transition,
        )

        snap = install_canonical_live_draft_snapshot(session, room, state_source=f"pick:{source}")
        note_pick_transition(
            session,
            event="pick_committed",
            draft_id=str(snap.get("draft_id") or ""),
            pick_index=int(snap.get("current_pick_index") or 0),
            revision=int(snap.get("revision") or 0),
            team_on_clock=str(snap.get("team_on_clock") or ""),
            player_id=pid,
            player_name=pname,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            extra={
                "source": source,
                "zero_to_commit_ms": zero_to_commit_ms,
                "board_size": int(snap.get("board_size") or 0),
            },
        )
    except Exception:
        pass
    try:
        from live_draft_canonical_snapshot import invalidate_live_draft_paint

        invalidate_live_draft_paint(session)
    except ImportError:
        pass

    align_after = int(room.get("current_pick_index") or 0)
    board_after = len(room.get("draft_board") or [])
    if board_after != board_before + 1 and str(room.get("status") or "") != "complete":
        result = PickCommitResult(
            ok=False,
            message="Pick did not advance board by exactly one.",
            error="board_not_advanced",
            commit_path=f"finalize:{source}",
            board_size_before=board_before,
            board_size_after=board_after,
            current_pick_index_before=idx_b,
            current_pick_index_after=align_after,
        )
        session.pop("_live_draft_in_flight_auto_pick_key", None)
        return result

    if request_immediate_paint:
        try:
            from live_draft_canonical_snapshot import align_room_pick_index, begin_live_draft_paint

            align_room_pick_index(room)
            begin_live_draft_paint(session, room, state_source=f"pick:{source}")
        except ImportError:
            pass
        try:
            from live_draft_rerun_scope import mark_live_draft_optimistic_pick_tick

            mark_live_draft_optimistic_pick_tick(session)
        except ImportError:
            pass
        try:
            from live_draft_safe_mode import reset_poll_rerun_budget

            # Local pick commits must never be delayed by passive-poll rerun throttles.
            reset_poll_rerun_budget(session)
        except ImportError:
            session.pop("_live_draft_rerun_count", None)
        session["_live_draft_local_pick_paint_pending"] = True
        session["_live_draft_recs_pending_after_pick"] = True

    result = PickCommitResult(
        ok=True,
        message=f"Pick committed ({source}).",
        error="",
        commit_path=f"finalize:{source}",
        board_size_before=board_before,
        board_size_after=len(room.get("draft_board") or []),
        current_pick_index_before=idx_b,
        current_pick_index_after=int(room.get("current_pick_index") or 0),
    )
    if persist:
        persisted = persist_applied_pick(
            session,
            room,
            source=source,
            board_size_before=board_before,
            idx_before=idx_b,
            fast_path=fast_path,
        )
        if not persisted.ok:
            return persisted
        result = persisted
        result.commit_path = f"finalize+persist:{source}"
    return result


def _draft_id_safe(room: dict[str, Any]) -> str:
    return str(room.get("draft_room_id") or room.get("room_id") or room.get("draft_id") or "").strip()


def commit_live_draft_pick(
    session: dict[str, Any],
    room: dict[str, Any],
    player_row: dict[str, Any],
    *,
    source: str,
    verdict: str | None = None,
    optimistic: bool = False,
    persist: bool = True,
    fast_path: bool = False,
) -> PickCommitResult:
    """Authoritative pick transition: mutate → side effects → persist → snapshot."""
    board_before = len(room.get("draft_board") or [])
    idx_before = int(room.get("current_pick_index") or 0)
    player_id = str(player_row.get("playerID") or player_row.get("player_id") or "").strip()
    player_name = str(player_row.get("fullName") or player_row.get("Player") or "").strip()
    try:
        from live_draft_pick_engine import build_structured_pick_verdict, normalize_pick_source_label

        source_label = normalize_pick_source_label(source)
        verdict_text = verdict or build_structured_pick_verdict(dict(player_row), pick_source=source_label)
    except ImportError:
        source_label = str(source or "Manual Pick")
        verdict_text = verdict or f"Draft ({source})"

    ok, msg = live_draft_make_pick(
        room,
        player_row,
        verdict=verdict_text,
        pick_source=source_label,
        snapshot=dict(player_row),
        session=session,
        enrich_pick_context=False,
    )
    if not ok:
        return PickCommitResult(
            ok=False,
            message=msg,
            error="live_make_pick_failed",
            commit_path="commit_live_draft_pick",
            board_size_before=board_before,
            board_size_after=board_before,
            current_pick_index_before=idx_before,
            current_pick_index_after=idx_before,
        )
    result = finalize_live_draft_pick_transition(
        session,
        room,
        source=source_label,
        player_id=player_id,
        player_name=player_name,
        board_size_before=board_before,
        idx_before=idx_before,
        persist=persist and not optimistic,
        fast_path=fast_path or optimistic,
        request_immediate_paint=True,
    )
    if optimistic and result.ok:
        try:
            from live_draft_pick_persist import mark_pick_persist_dirty

            mark_pick_persist_dirty(session, room, source=source_label)
        except ImportError:
            pass
    if result.ok:
        result.message = msg
    return result


def run_autopick_selection(room: dict[str, Any], session: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Select and apply auto-pick to room (make_pick only — caller persists)."""
    from live_draft_autopick import live_draft_auto_pick

    return live_draft_auto_pick(room, session=session)

