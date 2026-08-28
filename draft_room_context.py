"""Global draft context — shared room + participant team for every page and AMI send.

Call ``prepare_global_draft_context(session)`` during app bootstrap so Sleepers,
Comparison, AMI, and Live Draft all see the same active room while keeping private
queue/recommendation scope per participant.
"""

from __future__ import annotations

import time
from typing import Any

from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_ID_KEY,
    ACTIVE_PARTICIPANT_TEAM_KEY,
    active_participant_team,
    load_participant_workflow_into_session,
    resolve_participant_id,
    save_participant_workflow_from_session,
    set_active_participant,
)
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    SHARED_ROOM_META_KEY,
    SharedRoomStore,
    bump_revision,
    document_to_runtime_room,
    generate_room_code,
    get_shared_room_store,
    load_shared_room,
    publish_shared_room_runtime,
    shared_document_room_blob,
    shared_room_backend_name,
    shared_room_document,
)
from live_draft_state import LIVE_DRAFT_ROOM_KEY, has_active_live_draft, prepare_live_draft_state


def abort_shared_room_create(
    session: dict[str, Any],
    *,
    backup_room: dict[str, Any] | None,
    backup_room_code: str | None = None,
) -> None:
    """Rollback multiplayer session keys and restore the host's local draft room."""
    session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
    session.pop(SHARED_ROOM_META_KEY, None)
    session.pop("_shared_draft_sync_run", None)
    session.pop(ACTIVE_PARTICIPANT_TEAM_KEY, None)
    if backup_room_code and str(backup_room_code).strip():
        from draft_room_create_verify import is_plausible_share_code

        if is_plausible_share_code(backup_room_code):
            session[ACTIVE_SHARED_ROOM_CODE_KEY] = str(backup_room_code).strip().upper()
    if isinstance(backup_room, dict):
        session[LIVE_DRAFT_ROOM_KEY] = backup_room


def clear_stale_multiplayer_state(session: dict[str, Any], *, reason: str = "") -> None:
    """Drop invalid multiplayer flags and restore single-user live draft when possible."""
    backup = session.get(LIVE_DRAFT_ROOM_KEY)
    if not isinstance(backup, dict):
        try:
            from live_draft_state import canonical_live_draft, room_from_persist_dict

            blob = canonical_live_draft(session)
            if isinstance(blob, dict) and blob.get("draft_room_id"):
                restored = room_from_persist_dict(blob)
                if restored:
                    backup = restored
        except ImportError:
            pass
    session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
    session.pop(SHARED_ROOM_META_KEY, None)
    session.pop(ACTIVE_PARTICIPANT_TEAM_KEY, None)
    session.pop("_shared_draft_sync_run", None)
    if isinstance(backup, dict):
        session[LIVE_DRAFT_ROOM_KEY] = backup
    if reason:
        session["_draft_room_membership_notice"] = reason


def resolve_shared_room_code(session: dict[str, Any]) -> str:
    """Best-effort 6-character join code from session keys (survives refresh/poll)."""
    try:
        from draft_room_create_verify import is_plausible_share_code, normalize_room_code

        meta = session.get(SHARED_ROOM_META_KEY) or {}
        candidates = (
            session.get(ACTIVE_SHARED_ROOM_CODE_KEY),
            session.get("shared_room_code"),
            meta.get("room_code") if isinstance(meta, dict) else None,
        )
        for raw in candidates:
            code = normalize_room_code(raw)
            if code and is_plausible_share_code(code):
                if normalize_room_code(session.get(ACTIVE_SHARED_ROOM_CODE_KEY)) != code:
                    session[ACTIVE_SHARED_ROOM_CODE_KEY] = code
                return code
    except ImportError:
        code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
        if code:
            return code
    return ""


def is_multiplayer_draft_active(session: dict[str, Any]) -> bool:
    return bool(resolve_shared_room_code(session))


def get_global_draft_context(session: dict[str, Any]) -> dict[str, Any]:
    """Structured context for pages, AMI, and recommendation wrappers."""
    room_code = resolve_shared_room_code(session)
    participant_id = resolve_participant_id(session)
    participant_team = active_participant_team(session) if room_code else ""
    shared_meta = dict(session.get(SHARED_ROOM_META_KEY) or {})
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    runtime_active = has_active_live_draft(session)
    is_host = False
    shared_doc: dict[str, Any] | None = None
    if room_code:
        try:
            from draft_room_create_verify import load_shared_room_with_diagnostics
            from draft_room_membership import is_room_host

            load_result = load_shared_room_with_diagnostics(get_shared_room_store(), room_code)
            doc = load_result.get("document")
            shared_doc = doc if isinstance(doc, dict) else None
            is_host = is_room_host(session, shared_doc)
            session["_draft_room_sync_diag"] = {
                "room_code": room_code,
                "lookup_backend": load_result.get("backend"),
                "lookup_fallback_used": bool(load_result.get("lookup_fallback_used")),
                "matched_room_id": str((shared_doc or {}).get("draft_room_id") or ""),
                "room_revision": int((shared_doc or {}).get("revision") or 0),
                "host_participant_id": str((shared_doc or {}).get("host_participant_id") or ""),
                "host_user_id": str((shared_doc or {}).get("host_user_id") or ""),
                "is_room_host": is_host,
                "participant_id": participant_id,
                "session_teams": list((room or {}).get("teams") or []) if isinstance(room, dict) else [],
                "document_teams": list(((shared_doc or {}).get("room") or {}).get("teams") or [])
                if isinstance(shared_doc, dict)
                else [],
                "participants": {
                    str(k): str((v or {}).get("assigned_team") or "")
                    for k, v in dict((shared_doc or {}).get("participants") or {}).items()
                    if isinstance(v, dict)
                },
            }
        except ImportError:
            try:
                from draft_room_membership import is_room_host

                shared_doc = load_shared_room(room_code)
                is_host = is_room_host(session, shared_doc)
            except ImportError:
                pass
    return {
        "mode": "multiplayer" if room_code else ("single_user_live" if runtime_active else "none"),
        "room_code": room_code or None,
        "participant_id": participant_id,
        "participant_team": participant_team,
        "draft_room_id": str(room.get("draft_room_id") or "") if isinstance(room, dict) else "",
        "is_room_host": is_host,
        "shared_revision": shared_meta.get("revision")
        or (int((shared_doc or {}).get("revision") or 0) if shared_doc else None),
        "shared_updated_at": shared_meta.get("updated_at"),
        "shared_storage_backend": shared_meta.get("storage_backend"),
        "live_draft_active": runtime_active,
        "room_status": str(room.get("status") or "") if isinstance(room, dict) else "",
    }


def prepare_global_draft_context(session: dict[str, Any]) -> dict[str, Any]:
    """Bootstrap hook — hydrate runtime room and participant-private workflow."""
    from draft_room_participant_state import restore_persisted_shared_room_membership

    # Never rehydrate during active End/Delete. After delete completes, do not wipe a
    # brand-new protected create (stale deleting=done was killing Solo/Shared starts).
    deleting = str(session.get("_live_draft_deleting") or "").strip().lower()
    if deleting == "in_progress":
        session.pop("live_draft_room", None)
        session.pop("live_draft_state", None)
        session.pop("active_shared_draft_room_code", None)
        return get_global_draft_context(session)
    if deleting == "done":
        protected = False
        try:
            from live_draft_creation_trace import new_room_is_protected

            protected = bool(new_room_is_protected(session))
        except ImportError:
            protected = False
        room = session.get("live_draft_room")
        if protected and isinstance(room, dict):
            session.pop("_live_draft_deleting", None)
            session.pop("_live_draft_force_setup_after_delete", None)
        elif isinstance(room, dict):
            # Keep non-tombstoned rooms; only clear empty/stale pointers.
            session.pop("_live_draft_deleting", None)
            session.pop("_live_draft_force_setup_after_delete", None)
        else:
            session.pop("live_draft_room", None)
            session.pop("live_draft_state", None)
            session.pop("active_shared_draft_room_code", None)
            return get_global_draft_context(session)

    restored_code = restore_persisted_shared_room_membership(session)
    try:
        from draft_room_runtime_diagnostics import note_prepare_global_rehydrate

        if restored_code:
            note_prepare_global_rehydrate(session, room_code=str(restored_code), source="restore_persisted_membership")
    except ImportError:
        pass
    try:
        from draft_room_join_trace import trace_join_step

        if restored_code:
            trace_join_step(
                session,
                "membership_restored",
                room_code=restored_code,
                assigned_team=active_participant_team(session),
            )
    except ImportError:
        pass
    restored_team = active_participant_team(session)
    if restored_code and restored_team:
        _sync_participant_team_aliases(session, restored_team)
    ctx = get_global_draft_context(session)
    room_code = ctx.get("room_code")
    if room_code:
        backend_name = shared_room_backend_name()
        try:
            from draft_room_join_trace import trace_join_step

            trace_join_step(
                session,
                "prepare_global_context",
                room_code=room_code,
                backend=backend_name,
                multiplayer=True,
            )
        except ImportError:
            pass
        existing_room = session.get(LIVE_DRAFT_ROOM_KEY)
        shared_meta = session.get(SHARED_ROOM_META_KEY)
        try:
            from live_draft_state import is_runtime_room

            already_hydrated = (
                is_runtime_room(existing_room)
                and isinstance(shared_meta, dict)
                and str(shared_meta.get("room_code") or "").strip().upper() == str(room_code).strip().upper()
            )
        except ImportError:
            already_hydrated = isinstance(existing_room, dict) and bool(existing_room.get("draft_room_id"))

        if already_hydrated:
            load_participant_workflow_into_session(session, str(room_code))
            document = load_shared_room(str(room_code))
            if isinstance(document, dict):
                try:
                    from draft_room_membership import sync_membership_from_document

                    sync_membership_from_document(session, document)
                except ImportError:
                    pass
            try:
                from draft_room_participant_state import ensure_participant_team_assigned, record_join_assignment_diagnostics

                team, fail = ensure_participant_team_assigned(
                    session,
                    room_code=str(room_code),
                    document=document if isinstance(document, dict) else None,
                )
                record_join_assignment_diagnostics(session, source="prepare_global_hydrated", failure_reason=fail)
                if team:
                    _sync_participant_team_aliases(session, team)
            except ImportError:
                pass
        else:
            document = load_shared_room(str(room_code))
            if document:
                # Refuse to hydrate a shared room the current user never joined.
                try:
                    from shared_room_membership_gate import (
                        can_render_shared_live_draft,
                        clear_stale_shared_room_local_state,
                    )

                    ok_gate, gate_reason = can_render_shared_live_draft(
                        session, document=document, require_team_claim=False
                    )
                    if not ok_gate:
                        clear_stale_shared_room_local_state(
                            session, reason=f"prepare_global_gate:{gate_reason}"
                        )
                        return get_global_draft_context(session)
                except ImportError:
                    pass
                runtime = publish_shared_room_runtime(session, document, reason="global_context_prepare")
                if runtime is None:
                    clear_stale_multiplayer_state(
                        session,
                        reason=str(
                            session.get("_draft_room_publish_error") or "Shared room data is invalid or empty."
                        ),
                    )
                else:
                    load_participant_workflow_into_session(session, str(room_code))
                    try:
                        from draft_room_membership import sync_membership_from_document

                        ok, notice = sync_membership_from_document(session, document)
                        if notice:
                            session["_draft_room_membership_notice"] = notice
                    except ImportError:
                        membership = dict(document.get("participants") or {}).get(ctx["participant_id"])
                        if isinstance(membership, dict):
                            team = str(membership.get("assigned_team") or "").strip()
                            if team:
                                session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
                                _sync_participant_team_aliases(session, team)
            elif room_code:
                from draft_room_create_verify import is_plausible_share_code, looks_like_internal_draft_session_id, share_code_hint

                if not is_plausible_share_code(room_code):
                    clear_stale_multiplayer_state(
                        session,
                        reason=share_code_hint(room_code)
                        or f"Invalid share code **{room_code}** — cleared multiplayer mode.",
                    )
                else:
                    session["_draft_room_last_error"] = (
                        f"Shared room **{room_code}** could not be loaded from {shared_room_backend_name()}."
                    )
                    hint = ""
                    if looks_like_internal_draft_session_id(room_code):
                        hint = " Use the 6-character share code, not the internal session ID."
                    clear_stale_multiplayer_state(
                        session,
                        reason=(
                            f"Shared room **{room_code}** was not found in {shared_room_backend_name()}.{hint} "
                            "Your single-user draft is still available."
                        ),
                    )
    else:
        prepare_live_draft_state(session)
    if is_multiplayer_draft_active(session):
        session.pop("room_your_team", None)
    return get_global_draft_context(session)


_SHARED_DRAFT_SYNC_RUN_KEY = "_shared_draft_sync_run"


def reset_shared_draft_sync_gate(session: dict[str, Any]) -> None:
    """Allow another shared-room poll in the same Streamlit rerun (e.g. poll fragment)."""
    session.pop(_SHARED_DRAFT_SYNC_RUN_KEY, None)


def _shared_head_live_fields_diverge(head: dict[str, Any], local_room: dict[str, Any] | None) -> bool:
    """True when revision is unchanged but timer / pick / live status still drifted.

    Compare room-blob status, not the document wrapper (often ``waiting`` while
    the live room is ``in_progress``).
    """
    if not isinstance(head, dict) or not isinstance(local_room, dict):
        return False
    remote_status = str(head.get("room_status") or "").strip().lower()
    local_status = str(local_room.get("status") or "").strip().lower()
    if remote_status and local_status and remote_status != local_status:
        return True
    try:
        remote_idx = int(head.get("current_pick_index") or 0)
        local_idx = int(local_room.get("current_pick_index") or 0)
    except (TypeError, ValueError):
        remote_idx = head.get("current_pick_index")
        local_idx = local_room.get("current_pick_index")
    if remote_idx != local_idx:
        return True
    remote_dl = head.get("timer_deadline")
    local_dl = local_room.get("timer_deadline")
    if remote_dl is None and local_dl is None:
        return False
    if remote_dl is None or local_dl is None:
        return True
    try:
        return abs(float(remote_dl) - float(local_dl)) > 0.05
    except (TypeError, ValueError):
        return remote_dl != local_dl


def sync_shared_draft_room(
    session: dict[str, Any],
    *,
    force: bool = False,
    store: SharedRoomStore | None = None,
) -> bool:
    """Poll shared store; refresh session when revision advances.

    Returns True when the local runtime was updated from a newer remote revision.
    """
    try:
        from live_draft_mp_diagnostics import _last_pick_info, _on_clock_team, _pick_count, record_poll_sync_trace
    except ImportError:
        record_poll_sync_trace = None  # type: ignore[assignment,misc]

    def _trace(**fields: Any) -> None:
        if record_poll_sync_trace is not None:
            record_poll_sync_trace(session, **fields)

    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if not room_code:
        _trace(last_poll_result="skipped_no_room_code", poll_skipped_reason="no_room_code")
        return False
    if not force and session.get(_SHARED_DRAFT_SYNC_RUN_KEY):
        _trace(last_poll_result="skipped_sync_gate", poll_skipped_reason="sync_gate_already_ran")
        return False

    poll_started = time.time()
    _trace(last_poll_started_at=poll_started, room_code=room_code)

    backend = store if store is not None else get_shared_room_store()
    local_rev = int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        local_room = session.get(LIVE_DRAFT_ROOM_KEY)
    except ImportError:
        LIVE_DRAFT_ROOM_KEY = "live_draft_room"  # type: ignore[misc]
        local_room = session.get("live_draft_room")

    if isinstance(local_room, dict):
        _trace(
            local_revision=local_rev,
            local_current_pick_index=local_room.get("current_pick_index"),
            local_pick_count=_pick_count(local_room) if record_poll_sync_trace else len(local_room.get("draft_board") or []),
            local_on_clock_team=_on_clock_team(local_room) if record_poll_sync_trace else "",
            room_id=str(local_room.get("draft_room_id") or ""),
        )

    head_diverged = False
    if not force:
        load_head = getattr(backend, "load_head", None)
        if callable(load_head):
            head = load_head(room_code)
            if isinstance(head, dict):
                remote_rev = int(head.get("revision") or 0)
                _trace(remote_revision=remote_rev, last_seen_remote_revision=remote_rev)
                head_diverged = _shared_head_live_fields_diverge(
                    head, local_room if isinstance(local_room, dict) else None
                )
                if remote_rev <= local_rev and not head_diverged:
                    session[_SHARED_DRAFT_SYNC_RUN_KEY] = True
                    _trace(
                        last_poll_finished_at=time.time(),
                        last_poll_result="no_change_head",
                        poll_skipped_reason="remote_rev_not_newer",
                    )
                    return False

    document = backend.load(room_code)
    session[_SHARED_DRAFT_SYNC_RUN_KEY] = True
    if not isinstance(document, dict):
        _trace(
            last_poll_finished_at=time.time(),
            last_poll_result="load_failed",
            poll_skipped_reason="document_missing",
            last_apply_error="shared room document not found",
        )
        return False
    try:
        from live_draft_termination import handle_shared_document_terminal

        if handle_shared_document_terminal(session, document):
            _trace(
                last_poll_finished_at=time.time(),
                last_poll_result="room_terminated",
                poll_skipped_reason="document_terminal",
                remote_room_status=str(document.get("status") or ""),
            )
            return True
    except ImportError:
        pass
    remote_rev = int(document.get("revision") or 0)
    remote_blob = shared_document_room_blob(document)
    remote_player, remote_team, remote_pid = ("", "", "")
    if record_poll_sync_trace is not None:
        remote_player, remote_team, remote_pid = _last_pick_info(remote_blob if isinstance(remote_blob, dict) else None)
    _trace(
        remote_revision=remote_rev,
        last_seen_remote_revision=remote_rev,
        remote_room_status=str((remote_blob or {}).get("status") or document.get("status") or ""),
        remote_current_pick_index=(remote_blob or {}).get("current_pick_index") if isinstance(remote_blob, dict) else None,
        remote_pick_count=_pick_count(remote_blob) if isinstance(remote_blob, dict) and record_poll_sync_trace else None,
        remote_on_clock_team=_on_clock_team(remote_blob) if isinstance(remote_blob, dict) and record_poll_sync_trace else "",
        last_remote_pick_player=remote_player or None,
        last_remote_pick_team=remote_team or None,
        last_remote_pick_id=remote_pid or None,
    )

    if session.get("_live_draft_manual_pick_in_flight"):
        _trace(
            last_poll_finished_at=time.time(),
            last_poll_result="skipped_manual_pick_in_flight",
            poll_skipped_reason="manual_pick_in_flight",
        )
        return False

    remote_is_newer = remote_rev > local_rev
    if not remote_is_newer and not force and not head_diverged:
        _trace(
            last_poll_finished_at=time.time(),
            last_poll_result="no_change",
            poll_skipped_reason="remote_rev_not_newer",
            remote_revision_applied=False,
        )
        return False

    if not remote_is_newer:
        try:
            from live_draft_state import is_live_draft_locally_dirty, runtime_room_ahead_of_blob

            runtime = session.get(LIVE_DRAFT_ROOM_KEY)
            if (
                is_live_draft_locally_dirty(session)
                and isinstance(runtime, dict)
                and isinstance(remote_blob, dict)
                and runtime_room_ahead_of_blob(runtime, remote_blob)
            ):
                _trace(
                    last_poll_finished_at=time.time(),
                    last_poll_result="skipped_dirty_local_ahead",
                    poll_skipped_reason="dirty_local_ahead",
                    remote_revision_applied=False,
                )
                return False
        except ImportError:
            pass

    try:
        publish_shared_room_runtime(session, document, reason="shared_room_poll")
        try:
            from draft_room_shared_state import invalidate_shared_room_document_cache

            invalidate_shared_room_document_cache(session, room_code)
        except ImportError:
            pass
        try:
            from live_draft_state import clear_live_draft_local_edit

            clear_live_draft_local_edit(session)
        except ImportError:
            pass
        load_participant_workflow_into_session(session, room_code)
        runtime = session.get(LIVE_DRAFT_ROOM_KEY)
        try:
            from live_draft_safe_mode import reset_poll_rerun_budget

            reset_poll_rerun_budget(session)
        except ImportError:
            pass
        try:
            from live_draft_mp_diagnostics import record_multiplayer_sync_diagnostics

            record_multiplayer_sync_diagnostics(
                session,
                room=runtime if isinstance(runtime, dict) else None,
                local_revision=remote_rev,
                remote_revision=remote_rev,
                poll_applied=True,
            )
        except ImportError:
            pass
        try:
            from live_draft_state import check_manual_commit_overwrite

            check_manual_commit_overwrite(session, source="shared_room_poll")
        except ImportError:
            pass
        try:
            from draft_commit_diagnostics import record_draft_commit_diagnostics

            record_draft_commit_diagnostics(
                session,
                poll_refresh_detected=True,
                realtime_update_received=True,
                room_revision_after=remote_rev,
            )
        except ImportError:
            pass
        _trace(
            last_poll_finished_at=time.time(),
            last_poll_result="applied",
            poll_skipped_reason="",
            remote_revision_applied=True,
            local_revision=remote_rev,
            local_current_pick_index=runtime.get("current_pick_index") if isinstance(runtime, dict) else None,
            local_pick_count=_pick_count(runtime) if isinstance(runtime, dict) and record_poll_sync_trace else None,
            local_on_clock_team=_on_clock_team(runtime) if isinstance(runtime, dict) and record_poll_sync_trace else "",
        )
        return True
    except Exception as exc:
        _trace(
            last_poll_finished_at=time.time(),
            last_poll_result="apply_failed",
            poll_skipped_reason="apply_exception",
            remote_revision_applied=False,
            last_apply_error=str(exc),
        )
        return False


def poll_shared_draft_room(
    session: dict[str, Any],
    *,
    force: bool = False,
    store: SharedRoomStore | None = None,
) -> bool:
    """Poll shared draft room and defer cloud autosave churn. Returns True if revision changed."""
    try:
        from suite_egress_policy import block_cloud_autosave_for_poll_sync

        if not force:
            block_cloud_autosave_for_poll_sync(session)
    except ImportError:
        pass
    return sync_shared_draft_room(session, force=force, store=store)


def refresh_shared_lobby_authority(
    session: dict[str, Any],
    *,
    store: SharedRoomStore | None = None,
    force_poll: bool = True,
) -> dict[str, Any] | None:
    """Force-load the authoritative shared document for lobby claim/participant UI.

    Host screens must not keep rendering a stale session copy when a newer shared
    revision exists (e.g. Coakley11 claimed Team B).
    """
    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if not room_code:
        return None
    try:
        from draft_room_shared_state import invalidate_shared_room_document_cache

        invalidate_shared_room_document_cache(session, room_code)
    except ImportError:
        pass

    local_rev = int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)
    if force_poll:
        try:
            reset_shared_draft_sync_gate(session)
            poll_shared_draft_room(session, force=True, store=store)
        except Exception:
            pass

    backend = store if store is not None else get_shared_room_store()
    try:
        from draft_room_shared_state import invalidate_shared_room_document_cache

        invalidate_shared_room_document_cache(session, room_code)
    except ImportError:
        pass
    document = backend.load(room_code)
    if not isinstance(document, dict):
        return None

    remote_rev = int(document.get("revision") or 0)
    applied_newer = False
    if remote_rev > local_rev:
        try:
            publish_shared_room_runtime(session, document, reason="lobby_authority_refresh")
            applied_newer = True
        except Exception:
            pass
    # Always re-bind meta from the authoritative document so lobby rows / Start
    # Draft never keep a stale session revision when participants advanced.
    try:
        meta = dict(session.get(SHARED_ROOM_META_KEY) or {})
        meta["revision"] = remote_rev
        meta["room_code"] = room_code
        meta["updated_at"] = str(document.get("updated_at") or meta.get("updated_at") or "")
        meta["host_participant_id"] = str(
            document.get("host_participant_id") or meta.get("host_participant_id") or ""
        )
        session[SHARED_ROOM_META_KEY] = meta
    except Exception:
        pass

    session["_shared_lobby_authority_doc"] = document
    session["_shared_lobby_host_refresh_trace"] = {
        "room_code": room_code,
        "backend": shared_room_backend_name(),
        "storage_key": f"{shared_room_backend_name()}:{room_code}",
        "session_revision_before": local_rev,
        "backend_revision": remote_rev,
        "applied_newer_revision": applied_newer,
        "participant_ids": sorted(str(k) for k in dict(document.get("participants") or {})),
        "joined_participants": list(document.get("joined_participants") or []),
    }
    try:
        from live_draft_presence import build_lobby_sync_diagnostics

        live = session.get(LIVE_DRAFT_ROOM_KEY)
        session["_shared_lobby_sync_diag"] = build_lobby_sync_diagnostics(
            session,
            live if isinstance(live, dict) else {},
            document=document,
        )
    except ImportError:
        pass
    return document


def create_and_host_shared_room(
    session: dict[str, Any],
    live_room: dict[str, Any],
    *,
    host_team: str | None = None,
    store: SharedRoomStore | None = None,
) -> tuple[str, dict[str, Any]]:
    """Create a shared room, register host, and hydrate session."""
    from draft_room_membership import (
        auth_user_id,
        default_host_team,
        ensure_authenticated_for_shared_room,
        participant_display_name,
    )
    from draft_room_participant_state import register_participant_in_shared_document

    import copy

    from draft_room_create_verify import (
        merge_create_flow_diagnostics,
        normalize_room_code,
        verify_shared_room_persisted,
    )

    merge_create_flow_diagnostics(
        session,
        create_button_clicked=True,
        internal_draft_session_id=str(live_room.get("draft_room_id") or "").strip().upper(),
    )

    backup_room = copy.deepcopy(live_room) if isinstance(live_room, dict) else None
    backup_room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper() or None

    ok_auth, auth_msg = ensure_authenticated_for_shared_room(session, for_create=True)
    if not ok_auth:
        session["_draft_room_last_error"] = auth_msg
        return "", {}

    backend = store if store is not None else get_shared_room_store()
    participant_id = resolve_participant_id(session)
    assigned = str(host_team or "").strip() or default_host_team(live_room)
    try:
        from live_draft_state import repair_stale_live_draft_progress

        live_room = repair_stale_live_draft_progress(copy.deepcopy(live_room))
    except ImportError:
        live_room = copy.deepcopy(live_room)
    try:
        from draft_source_validation import ALLOW_FREE_POOL_KEY

        cfg = dict(live_room.get("config") or {})
        cfg.setdefault(ALLOW_FREE_POOL_KEY, True)
        live_room["config"] = cfg
    except ImportError:
        pass
    try:
        import pandas as pd

        from draft_scoring_pool import prepare_pool_for_compact_serialization

        pool = live_room.get("pool")
        if isinstance(pool, pd.DataFrame) and not pool.empty:
            try:
                from draft_room_runtime_diagnostics import record_scoring_pipeline_stage

                record_scoring_pipeline_stage(session, "original_source", pool)
            except ImportError:
                pass
            prepared, scoring_report = prepare_pool_for_compact_serialization(pool)
            live_room["pool"] = prepared
            live_room["_live_draft_pool_scoring_diag"] = scoring_report
    except ImportError:
        pass
    try:
        from draft_room_supabase_errors import SharedRoomSupabaseError, record_shared_room_supabase_error
    except ImportError:
        SharedRoomSupabaseError = RuntimeError  # type: ignore[misc, assignment]
        record_shared_room_supabase_error = None  # type: ignore[assignment]

    code = generate_room_code(exists=backend.exists)
    try:
        from shared_draft_local_pool import remember_local_shared_player_pool

        remember_local_shared_player_pool(
            session,
            live_room.get("pool"),
            room_code=str(code or ""),
        )
    except ImportError:
        pass
    merge_create_flow_diagnostics(session, generated_share_code=code)
    document = shared_room_document(
        room_code=code,
        host_participant_id=participant_id,
        live_room=live_room,
        revision=1,
    )
    document["created_at"] = document.get("updated_at") or document.get("created_at")
    document["host_user_id"] = str(auth_user_id(session) or participant_id)
    document["host_participant_id"] = participant_id
    try:
        from shared_draft_permissions import stamp_commissioner_on_document

        stamp_commissioner_on_document(
            document,
            participant_id=participant_id,
            auth_user_id=str(auth_user_id(session) or ""),
        )
    except ImportError:
        document["commissioner_participant_id"] = participant_id
    # Unique generation — guests must never inherit this via stale local pointers.
    import time as _time_mod
    import uuid as _uuid_mod

    document["room_generation"] = f"{code}-{int(_time_mod.time())}-{_uuid_mod.uuid4().hex[:8]}"
    document["participants"] = {}
    document["joined_participants"] = {}
    document["_storage_backend"] = shared_room_backend_name()
    document = register_participant_in_shared_document(
        document,
        participant_id=participant_id,
        assigned_team=assigned,
        display_name=participant_display_name(session),
        session=session,
    )
    try:
        from draft_room_runtime_diagnostics import record_scoring_pipeline_stage

        record_scoring_pipeline_stage(session, "compact_serialized", None, document=document)
    except ImportError:
        pass
    merge_create_flow_diagnostics(session, supabase_save_attempted=True)
    try:
        saved = backend.save(document)
    except SharedRoomSupabaseError as exc:
        merge_create_flow_diagnostics(session, supabase_save_success=False, cloud_write_ok=False, room_create_error=str(exc))
        if record_shared_room_supabase_error is not None:
            record_shared_room_supabase_error(session, exc)
        else:
            session["_draft_room_last_error"] = str(exc)
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}
    except ValueError as exc:
        merge_create_flow_diagnostics(session, supabase_save_success=False)
        session["_draft_room_last_error"] = str(exc)
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}
    except RuntimeError as exc:
        merge_create_flow_diagnostics(session, supabase_save_success=False)
        try:
            from draft_room_supabase_errors import (
                record_shared_room_supabase_error,
                shared_room_supabase_error_from_runtime,
            )

            parsed = shared_room_supabase_error_from_runtime(exc)
            record_shared_room_supabase_error(session, parsed)
        except ImportError:
            session["_draft_room_last_error"] = str(exc)
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}

    if not isinstance(saved, dict) or not saved.get("room_code"):
        merge_create_flow_diagnostics(session, supabase_save_success=False)
        session["_draft_room_last_error"] = "Could not create shared room."
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}

    # Mirror into the alternate global registry so guests can look up by code
    # even if their client resolves a different primary backend.
    try:
        from draft_room_shared_state import get_local_shared_room_store

        if shared_room_backend_name() == "supabase":
            get_local_shared_room_store().save(saved)
        else:
            try:
                from draft_room_supabase_store import (
                    get_supabase_shared_room_store,
                    supabase_shared_room_backend_available,
                )

                if supabase_shared_room_backend_available():
                    get_supabase_shared_room_store().save(saved)
            except Exception:
                pass
    except Exception:
        pass

    saved_code = normalize_room_code(saved.get("room_code"))
    merge_create_flow_diagnostics(session, supabase_save_success=True, cloud_write_ok=True)
    verified, verify_msg, verify_diag = verify_shared_room_persisted(
        backend,
        saved_code,
        saved_document=saved,
    )
    merge_create_flow_diagnostics(session, **verify_diag)
    if not verified:
        merge_create_flow_diagnostics(
            session,
            shared_room_code_displayed_to_user=False,
            cloud_readback_ok=False,
            room_create_ok=False,
            room_create_error=verify_msg,
        )
        session["_draft_room_last_error"] = verify_msg
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}

    runtime = publish_shared_room_runtime(session, saved, reason="shared_room_create")
    if runtime is None:
        merge_create_flow_diagnostics(session, shared_room_code_displayed_to_user=False)
        session["_draft_room_last_error"] = str(
            session.get("_draft_room_publish_error") or "Shared room saved but draft board could not be loaded."
        )
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}

    set_active_participant(
        session,
        room_code=saved_code,
        participant_id=participant_id,
        assigned_team=assigned,
    )
    try:
        from live_draft_presence import mark_participant_present

        mark_participant_present(session, force_save=True, store=backend)
    except ImportError:
        pass
    save_participant_workflow_from_session(session, saved_code)
    _sync_participant_team_aliases(session, assigned)
    try:
        from draft_room_join_trace import trace_join_step

        load_stats = dict(verify_diag.get("immediate_load") or {})
        load_stats.pop("room_code", None)
        trace_join_step(
            session,
            "shared_room_create_verified",
            room_code=saved_code,
            backend=shared_room_backend_name(),
            **load_stats,
        )
    except ImportError:
        pass
    merge_create_flow_diagnostics(
        session,
        shared_room_code_displayed_to_user=True,
        valid_runtime_room=True,
        cloud_readback_ok=True,
        room_create_ok=True,
        join_code=saved_code,
        join_code_present=True,
    )
    try:
        from baseball_draft_activity import log_live_draft_room_created

        live = session.get("live_draft_room")
        if not isinstance(live, dict):
            live = runtime if isinstance(runtime, dict) else live_room
        try:
            from live_draft_start_progress import is_live_draft_start_in_flight, queue_live_draft_created_activity

            if is_live_draft_start_in_flight(session):
                queue_live_draft_created_activity(session)
            else:
                log_live_draft_room_created(live, session=session)
        except ImportError:
            log_live_draft_room_created(live, session=session)
    except Exception:
        pass
    return saved_code, saved


def join_shared_draft_room(
    session: dict[str, Any],
    room_code: str,
    *,
    requested_team: str | None = None,
    display_name: str = "",
    store: SharedRoomStore | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Join an existing shared room; hydrate session context on success."""
    from draft_room_membership import (
        ensure_authenticated_for_shared_room,
        participant_display_name,
        resolve_join_team_assignment,
    )

    from draft_room_participant_state import register_participant_in_shared_document

    code = str(room_code or "").strip().upper()
    if not code:
        return False, "Enter a room code.", None
    try:
        from draft_room_create_verify import is_plausible_share_code, share_code_hint
        from draft_room_shared_state import ROOM_CODE_LEN

        if not is_plausible_share_code(code):
            hint = share_code_hint(code)
            return False, hint or f"Enter a valid {ROOM_CODE_LEN}-character share code from the host.", None
    except ImportError:
        pass
    backend = store if store is not None else get_shared_room_store()
    backend_name = shared_room_backend_name()
    try:
        from draft_room_join_trace import trace_join_step

        trace_join_step(
            session,
            "join_called",
            room_code_entered=code or None,
            backend=backend_name,
        )
    except ImportError:
        pass

    ok_auth, auth_msg = ensure_authenticated_for_shared_room(session)
    if not ok_auth:
        try:
            from draft_room_join_trace import get_shared_room_auth_diagnostics, trace_join_step

            trace_join_step(session, "join_auth_blocked", message=auth_msg, backend=backend_name)
            trace_join_step(session, "join_auth_diag", **get_shared_room_auth_diagnostics(session))
        except ImportError:
            pass
        return False, auth_msg, None

    from draft_room_create_verify import load_shared_room_with_diagnostics, validate_shared_room_document

    load_result = load_shared_room_with_diagnostics(backend, code)
    session["_draft_room_join_load_diag"] = {
        "room_code_queried": load_result.get("room_code_queried"),
        "backend": load_result.get("backend") or backend_name,
        "found": load_result.get("found"),
        "reason": load_result.get("reason"),
        "query_error": load_result.get("query_error"),
    }
    document = load_result.get("document")
    if not isinstance(document, dict):
        reason = str(load_result.get("reason") or "not_found")
        try:
            from draft_room_join_trace import trace_join_step

            trace_join_step(
                session,
                "join_room_not_found",
                room_code=code,
                backend=backend_name,
                reason=reason,
                query_error=load_result.get("query_error"),
            )
        except ImportError:
            pass
        if reason == "query_error":
            detail = str(load_result.get("query_error") or "Supabase query failed")
            return False, f"Could not look up room **{code}** ({backend_name}): {detail}", None
        return False, "Room code not found", None

    ok_doc, doc_err = validate_shared_room_document(document)
    if not ok_doc:
        return False, doc_err, document
    status = str(document.get("status") or "").strip().lower()
    # Guests may join waiting / ready / active / parked rooms. Completed/cancelled/expired are blocked.
    joinable = {
        "",
        "not_started",
        "waiting",
        "ready",
        "in_progress",
        "paused",
        "active",
        "saved_for_later",
        "parked",
    }
    blocked = {"closed", "complete", "completed", "cancelled", "canceled", "expired", "ended", "deleted"}
    if status in blocked or status not in joinable:
        try:
            from draft_room_join_trace import trace_join_step

            trace_join_step(
                session,
                "join_room_not_joinable",
                room_code=code,
                backend=backend_name,
                room_status=status or "unknown",
            )
        except ImportError:
            pass
        if status in ("closed", "cancelled", "canceled", "ended", "deleted"):
            try:
                from live_draft_termination import persist_durable_tombstones

                persist_durable_tombstones(session, room_code=code)
            except ImportError:
                pass
            return False, "This draft has ended.", document
        if status in ("complete", "completed", "expired"):
            return False, "Room is no longer joinable — the draft has already finished.", document
        return False, f"Room is no longer joinable (status: {status or 'unknown'}).", document

    # Capture identity for diagnostics — join must not switch guest workspace.
    owned_ws_before = str(
        session.get("_suite_owned_workspace_id") or session.get("_suite_active_workspace_id") or ""
    ).strip()
    try:
        from suite_auth import AUTH_USER_ID_KEY

        auth_uid = str(session.get(AUTH_USER_ID_KEY) or "").strip()
    except ImportError:
        auth_uid = str(session.get("auth_user_id") or "").strip()

    participant_id = resolve_participant_id(session)
    try:
        from live_draft_team_ownership import (
            list_available_shared_room_teams,
            repair_shared_document_claims,
            session_identity_aliases,
        )

        document = repair_shared_document_claims(document)
        aliases = session_identity_aliases(session)
        _open, claim_diag = list_available_shared_room_teams(
            document,
            participant_id,
            current_identity_aliases=aliases,
        )
        session["_draft_room_claim_diag"] = claim_diag
    except ImportError:
        aliases = {str(participant_id or "").strip()} if participant_id else set()
        claim_diag = {}

    participants = dict(document.get("participants") or {})
    existing = participants.get(participant_id)
    duplicate_rejoin = False
    already_team = str((claim_diag or {}).get("already_joined_team") or "").strip()
    # Resume lobby: reserved owners must reattach to their original team only.
    reserved = document.get("resume_reserved_teams") if isinstance(document, dict) else None
    if isinstance(reserved, dict) and participant_id:
        for team_name, meta in reserved.items():
            if not isinstance(meta, dict):
                continue
            if str(meta.get("participant_id") or "").strip() == participant_id:
                already_team = str(team_name).strip()
                break
    if already_team:
        # Only accept alias already_joined when the exact participant owns that seat.
        owner_ok = False
        if isinstance(existing, dict) and str(existing.get("assigned_team") or "").strip() == already_team:
            owner_ok = True
        elif isinstance(reserved, dict):
            rmeta = reserved.get(already_team) or {}
            if str((rmeta or {}).get("participant_id") or "").strip() == participant_id:
                owner_ok = True
        slot = ((claim_diag or {}).get("occupancy") or {}).get(already_team) or {}
        if str(slot.get("canonical_participant_id") or "").strip() == participant_id:
            owner_ok = True
        if owner_ok:
            assigned = already_team
            duplicate_rejoin = True
        else:
            already_team = ""
            assigned = None
    else:
        assigned = None
    if not assigned and isinstance(existing, dict) and existing.get("assigned_team"):
        assigned = str(existing["assigned_team"])
        duplicate_rejoin = True
    if not assigned:
        assigned, err = resolve_join_team_assignment(
            document,
            participant_id,
            requested_team=requested_team,
            current_identity_aliases=aliases,
        )
        if not assigned:
            friendly = err or "No teams are available"
            if "already assigned" in str(err or "").lower():
                friendly = "Team is already claimed"
            elif "not available" in str(err or "").lower():
                friendly = str(err)
            elif "choose a team" in str(err or "").lower():
                friendly = "Choose a team before joining"
            elif "no open" in str(err or "").lower():
                friendly = "No teams are available"
            return False, friendly, document
        # Atomic claim: reload latest → verify open → write claim + joined → bump revision → persist.
        try:
            from live_draft_team_ownership import repair_shared_document_claims as _repair_claims
        except ImportError:
            _repair_claims = None  # type: ignore[assignment,misc]
        try:
            fresh = backend.load(code)
            if isinstance(fresh, dict):
                document = fresh
                if callable(_repair_claims):
                    document = _repair_claims(document)
                assigned, err = resolve_join_team_assignment(
                    document,
                    participant_id,
                    requested_team=requested_team or assigned,
                    current_identity_aliases=aliases,
                )
                if not assigned:
                    friendly = err or "No teams are available"
                    if "already assigned" in str(err or "").lower():
                        friendly = "Team is already claimed"
                    return False, friendly, document
        except Exception:
            pass
        # CAS join: capture server revision before bump so a stale heartbeat cannot win.
        expected_rev = int(document.get("revision") or 0)
        document = register_participant_in_shared_document(
            document,
            participant_id=participant_id,
            assigned_team=assigned,
            display_name=display_name or participant_display_name(session),
            session=session,
        )
        try:
            from live_draft_presence import JOINED_PARTICIPANTS_KEY, reconcile_joined_from_participants

            document[JOINED_PARTICIPANTS_KEY] = reconcile_joined_from_participants(document)
            if callable(_repair_claims):
                document = _repair_claims(document)
        except ImportError:
            pass
        try:
            from draft_room_shared_state import invalidate_shared_room_document_cache

            saved_doc: dict[str, Any] | None = None
            cas_ok = False
            for _attempt in range(4):
                invalidate_shared_room_document_cache(session, code)
                if hasattr(backend, "save_if_revision"):
                    cas_ok, saved_doc = backend.save_if_revision(
                        document, expected_revision=expected_rev
                    )
                else:
                    saved_doc = backend.save(document)
                    cas_ok = True
                if cas_ok and isinstance(saved_doc, dict):
                    document = saved_doc
                    break
                # Reload authoritative doc and retry claim on the latest revision.
                fresh = backend.load(code)
                if not isinstance(fresh, dict):
                    break
                document = fresh
                if callable(_repair_claims):
                    document = _repair_claims(document)
                assigned, err = resolve_join_team_assignment(
                    document,
                    participant_id,
                    requested_team=requested_team or assigned,
                    current_identity_aliases=aliases,
                )
                if not assigned:
                    friendly = err or "No teams are available"
                    if "already assigned" in str(err or "").lower():
                        friendly = "Team is already claimed"
                    return False, friendly, document
                expected_rev = int(document.get("revision") or 0)
                document = register_participant_in_shared_document(
                    document,
                    participant_id=participant_id,
                    assigned_team=assigned,
                    display_name=display_name or participant_display_name(session),
                    session=session,
                )
                try:
                    from live_draft_presence import (
                        JOINED_PARTICIPANTS_KEY,
                        reconcile_joined_from_participants,
                    )

                    document[JOINED_PARTICIPANTS_KEY] = reconcile_joined_from_participants(document)
                    if callable(_repair_claims):
                        document = _repair_claims(document)
                except ImportError:
                    pass
            if not cas_ok or not isinstance(document, dict):
                return (
                    False,
                    f"Unable to save participant: concurrent update on room {code}. Retry join.",
                    document if isinstance(document, dict) else {},
                )
            # Mirror to the alternate registry so guests on either backend can re-load.
            try:
                from draft_room_shared_state import get_local_shared_room_store

                if shared_room_backend_name() == "supabase":
                    get_local_shared_room_store().save(document)
            except Exception:
                pass
            invalidate_shared_room_document_cache(session, code)
            # Read-back verification — claim must be visible on the global document.
            verified = backend.load(code)
            if isinstance(verified, dict):
                document = verified
                vparts = dict(verified.get("participants") or {})
                vmeta = vparts.get(participant_id) if isinstance(vparts.get(participant_id), dict) else {}
                if str((vmeta or {}).get("assigned_team") or "").strip() != str(assigned).strip():
                    return (
                        False,
                        f"Unable to save participant: Team {assigned} claim did not persist on room {code}.",
                        document,
                    )
            session["_shared_join_claim_trace"] = {
                "room_code": code,
                "backend": shared_room_backend_name(),
                "storage_key": f"{shared_room_backend_name()}:{code}",
                "participant_id": participant_id,
                "assigned_team": assigned,
                "expected_revision_before": expected_rev,
                "revision_after": int(document.get("revision") or 0),
                "cas_ok": cas_ok,
            }
        except Exception as exc:
            try:
                from draft_room_supabase_errors import (
                    SharedRoomSupabaseError,
                    record_shared_room_supabase_error,
                    shared_room_supabase_error_from_runtime,
                )

                if isinstance(exc, SharedRoomSupabaseError):
                    return False, record_shared_room_supabase_error(session, exc), document
                if isinstance(exc, RuntimeError):
                    parsed = shared_room_supabase_error_from_runtime(exc)
                    return False, record_shared_room_supabase_error(session, parsed), document
            except ImportError:
                pass
            if isinstance(exc, ValueError):
                return False, f"Unable to save participant: {exc}", document
            raise
    session[ACTIVE_SHARED_ROOM_CODE_KEY] = code
    # Explicit re-enter clears any stale local left_at from a soft disconnect.
    try:
        from draft_room_participant_state import clear_participant_left_room

        clear_participant_left_room(session, code)
    except ImportError:
        pass
    set_active_participant(session, room_code=code, participant_id=participant_id, assigned_team=assigned)
    # Resume lobby: mark this participant as explicitly rejoined.
    try:
        if isinstance(document, dict) and (
            document.get("resume_reserved_teams")
            or str(document.get("status") or "").lower() in ("saved_for_later", "parked")
        ):
            from live_draft_resume_lobby import mark_resume_rejoined

            # Use module-level get_shared_room_store / bump_revision — never re-import
            # get_shared_room_store here (UnboundLocalError on the earlier backend = … line).
            document = mark_resume_rejoined(document, participant_id=participant_id)
            updated = bump_revision(document)
            save_backend = store if store is not None else get_shared_room_store()
            save_backend.save(updated)
            document = updated
            session["_live_draft_resume_lobby"] = True
    except Exception:
        pass
    # Isolate Live Draft UI from leftover private simulator Pick N / source labels.
    try:
        from live_draft_navigation import clear_private_baseball_simulator_runtime

        clear_private_baseball_simulator_runtime(session, reason="shared_room_join")
        # Re-bind participant team aliases cleared with simulator runtime keys.
        _sync_participant_team_aliases(session, assigned)
    except ImportError:
        pass
    presence_ok = True
    try:
        from live_draft_presence import mark_participant_present

        mark_participant_present(session, force_save=True, store=backend)
        if session.get("_live_draft_presence_error"):
            presence_ok = False
        # Presence may bump revision after the claim save — return the latest document.
        refreshed = backend.load(code)
        if isinstance(refreshed, dict):
            document = refreshed
    except ImportError:
        pass
    from draft_state import DRAFT_QUEUE_KEY, DRAFT_WATCHLIST_FAVORITES_KEY, DRAFT_WATCHLIST_FOCUS_KEY
    from draft_room_participant_state import participant_workflow_slot

    slot = participant_workflow_slot(session, code)
    workflow = dict(slot.get("workflow") or {})
    if not any(workflow.get(k) for k in ("queue", "watchlist_focus", "watchlist_favorites")):
        session[DRAFT_QUEUE_KEY] = []
        session[DRAFT_WATCHLIST_FOCUS_KEY] = []
        session[DRAFT_WATCHLIST_FAVORITES_KEY] = []
    load_participant_workflow_into_session(session, code)
    save_participant_workflow_from_session(session, code)
    runtime = publish_shared_room_runtime(session, document, reason="shared_room_join")
    if runtime is None:
        session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
        session.pop(SHARED_ROOM_META_KEY, None)
        return (
            False,
            str(session.get("_draft_room_publish_error") or "Room data could not be loaded."),
            document,
        )
    load_participant_workflow_into_session(session, code)
    _sync_participant_team_aliases(session, assigned)
    try:
        from draft_room_participant_state import ensure_participant_team_assigned, record_join_assignment_diagnostics

        team, fail = ensure_participant_team_assigned(session, room_code=code, document=document)
        if team and team != assigned:
            assigned = team
            _sync_participant_team_aliases(session, assigned)
        record_join_assignment_diagnostics(session, source="join_success", failure_reason=fail)
    except ImportError:
        pass
    # Keep Draft Mode Shared for the guest after join (prefs only — no widget key write).
    try:
        from live_draft_setup_mode import SETUP_MODE_SHARED, persist_live_draft_setup_mode_preference

        persist_live_draft_setup_mode_preference(session, SETUP_MODE_SHARED, st=None)
    except ImportError:
        pass
    owned_ws_after = str(
        session.get("_suite_owned_workspace_id") or session.get("_suite_active_workspace_id") or ""
    ).strip()
    session["_draft_room_join_attempt_diag"] = {
        "entered_code": code,
        "normalized_code": code,
        "lookup_backend": str(load_result.get("backend") or backend_name),
        "lookup_fallback_used": bool(load_result.get("lookup_fallback_used")),
        "matched_room_id": str(document.get("draft_room_id") or ""),
        "room_owner": str(document.get("host_user_id") or document.get("host_participant_id") or ""),
        "room_status": status or str(document.get("status") or ""),
        "auth_user_id": auth_uid or participant_id,
        "owned_workspace_before": owned_ws_before,
        "owned_workspace_after": owned_ws_after,
        "workspace_unchanged": owned_ws_before == owned_ws_after or not owned_ws_before,
        "selected_team": assigned,
        "invitation_required": False,
        "duplicate_rejoin": duplicate_rejoin,
        "presence_write_ok": presence_ok,
        "participant_write_ok": True,
        "room_revision": int(document.get("revision") or 0),
        "navigation_target": "shared_lobby" if status in ("", "not_started", "waiting", "ready") else "active_room",
        "multiplayer_active": is_multiplayer_draft_active(session),
    }
    try:
        from draft_room_join_trace import trace_join_step

        trace_join_step(
            session,
            "join_success",
            room_code=code,
            assigned_team=assigned,
            backend=backend_name,
            multiplayer_active=is_multiplayer_draft_active(session),
            revision=document.get("revision"),
            duplicate_rejoin=duplicate_rejoin,
        )
    except ImportError:
        pass
    if duplicate_rejoin:
        return True, f"You already joined this room as {assigned}.", document
    return True, f"Joined room {code} as {assigned}.", document


def _on_clock_team_from_room(live_room: dict[str, Any] | None) -> str:
    if not isinstance(live_room, dict):
        return ""
    picks = list(live_room.get("pick_order") or [])
    idx = int(live_room.get("current_pick_index") or 0)
    if idx >= len(picks):
        return ""
    slot = picks[idx]
    if isinstance(slot, dict):
        return str(slot.get("Team") or "").strip()
    return ""


def commit_shared_room_state(
    session: dict[str, Any],
    live_room: dict[str, Any],
    *,
    expected_revision: int | None = None,
    player_name: str | None = None,
    pick_already_applied: bool = False,
    store: SharedRoomStore | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Validate (optional pick) and persist shared room document."""
    from draft_room_shared_state import commit_shared_room_pick

    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics
    except ImportError:
        record_draft_commit_diagnostics = None  # type: ignore[assignment,misc]

    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    backend = store if store is not None else get_shared_room_store()
    try:
        from draft_room_shared_state import load_shared_room_document

        shared_doc = (
            load_shared_room_document(session, room_code, store=backend) if room_code else None
        )
    except ImportError:
        shared_doc = backend.load(room_code) if room_code else None
    head_rev = int(shared_doc.get("revision") or 0) if isinstance(shared_doc, dict) else 0
    meta_rev = int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)
    if expected_revision is None:
        expected_revision = head_rev

    board_before = len(live_room.get("draft_board") or []) if isinstance(live_room, dict) else 0
    idx_before = int(live_room.get("current_pick_index") or 0) if isinstance(live_room, dict) else 0
    on_clock_before = _on_clock_team_from_room(live_room if isinstance(live_room, dict) else None)

    if record_draft_commit_diagnostics is not None:
        record_draft_commit_diagnostics(
            session,
            commit_path="shared_room",
            commit_shared_room_pick_called=False,
            supabase_revision_before=head_rev,
            board_size_before=board_before,
            current_pick_index_before=idx_before,
            on_clock_team_before=on_clock_before or None,
            room_revision_before=head_rev,
        )

    validate_result = None
    validate_msg = ""
    if player_name and not pick_already_applied:
        from draft_source_validation import validate_shared_pick_commit

        try:
            from draft_room_membership import validate_participant_may_draft

            ok_pick, pick_msg = validate_participant_may_draft(session, live_room)
            validate_result = ok_pick
            if record_draft_commit_diagnostics is not None:
                record_draft_commit_diagnostics(
                    session,
                    validate_participant_may_draft_result=ok_pick,
                    validate_participant_may_draft_message=pick_msg or None,
                )
            if not ok_pick:
                sync_shared_draft_room(session, force=True, store=store)
                if record_draft_commit_diagnostics is not None:
                    record_draft_commit_diagnostics(
                        session,
                        validate_shared_pick_commit_result=False,
                        supabase_commit_success=False,
                        supabase_commit_error=pick_msg,
                    )
                return False, pick_msg, None
        except ImportError:
            pass

        ok, msg = validate_shared_pick_commit(session, live_room, player_name)
        validate_result = ok
        validate_msg = msg
        if record_draft_commit_diagnostics is not None:
            record_draft_commit_diagnostics(
                session,
                validate_shared_pick_commit_result=ok,
                validate_shared_pick_commit_message=msg or None,
            )
        if not ok:
            sync_shared_draft_room(session, force=True, store=store)
            if record_draft_commit_diagnostics is not None:
                record_draft_commit_diagnostics(
                    session,
                    supabase_commit_success=False,
                    supabase_commit_error=msg,
                )
            return False, msg, None

    if record_draft_commit_diagnostics is not None:
        record_draft_commit_diagnostics(session, commit_shared_room_pick_called=True, shared_room_commit_called=True)

    ok, saved = commit_shared_room_pick(
        session,
        live_room,
        expected_revision=expected_revision,
        store=store,
    )
    board_after = len(live_room.get("draft_board") or []) if isinstance(live_room, dict) else 0
    idx_after = int(live_room.get("current_pick_index") or 0) if isinstance(live_room, dict) else 0
    on_clock_after = _on_clock_team_from_room(live_room if isinstance(live_room, dict) else None)
    rev_after = int(saved.get("revision") or 0) if isinstance(saved, dict) else None

    if record_draft_commit_diagnostics is not None:
        record_draft_commit_diagnostics(
            session,
            pick_saved_to_room=ok,
            supabase_commit_success=ok,
            supabase_commit_error=None if ok else "revision_conflict",
            board_size_after=board_after,
            current_pick_index_after=idx_after,
            on_clock_team_after=on_clock_after or None,
            room_revision_after=rev_after,
            current_pick_after=idx_after + 1 if idx_after > idx_before else live_room.get("current_pick"),
            next_team_resolved=on_clock_after or None,
            poll_refresh_detected=bool(ok),
            realtime_update_sent=bool(ok),
        )

    if not ok:
        sync_shared_draft_room(session, force=True, store=store)
        conflict_msg = "Another participant updated the room. Board refreshed — try your pick again."
        session["_draft_room_conflict_notice"] = conflict_msg
        if record_draft_commit_diagnostics is not None:
            record_draft_commit_diagnostics(
                session,
                supabase_commit_error=conflict_msg,
                realtime_update_received=True,
            )
        return False, conflict_msg, saved

    try:
        from live_draft_state import clear_live_draft_local_edit

        clear_live_draft_local_edit(session)
    except ImportError:
        pass
    try:
        from live_draft_mp_diagnostics import record_multiplayer_sync_diagnostics

        record_multiplayer_sync_diagnostics(
            session,
            room=live_room if isinstance(live_room, dict) else None,
            local_revision=rev_after,
            remote_revision=rev_after,
            last_shared_write_ok=True,
            last_pick_source="shared_room_commit",
        )
    except ImportError:
        pass

    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if room_code:
        save_participant_workflow_from_session(session, room_code)
    try:
        from draft_room_state import sync_live_draft_room_to_canonical_board

        sync_live_draft_room_to_canonical_board(session, live_room)
    except ImportError:
        pass
    return True, validate_msg if validate_result is False else "", saved


def leave_shared_draft_room(session: dict[str, Any]) -> None:
    """Leave multiplayer room and clear shared runtime keys (private workflow is saved).

    Guest action: removes only this participant from the authoritative document and
    releases their team. Does not delete the room or end the draft for others.
    """
    from draft_room_participant_state import (
        ACTIVE_PARTICIPANT_ID_KEY,
        PARTICIPANT_NOTES_KEY,
        mark_participant_left_room,
        save_participant_workflow_from_session,
    )
    from draft_state import DRAFT_QUEUE_KEY, DRAFT_WATCHLIST_FAVORITES_KEY, DRAFT_WATCHLIST_FOCUS_KEY
    from live_draft_state import LIVE_DRAFT_ROOM_KEY, clear_live_draft_state

    try:
        from draft_room_runtime_diagnostics import capture_leave_state_before

        capture_leave_state_before(session)
    except ImportError:
        pass

    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    leave_pid = str(session.get(ACTIVE_PARTICIPANT_ID_KEY) or resolve_participant_id(session)).strip()
    if room_code:
        save_participant_workflow_from_session(session, room_code)
        mark_participant_left_room(session, room_code, participant_id=leave_pid)
        # Release this participant from the authoritative shared document.
        try:
            doc = load_shared_room(room_code)
            if isinstance(doc, dict):
                parts = dict(doc.get("participants") or {})
                leave_meta = parts.get(leave_pid) if isinstance(parts.get(leave_pid), dict) else {}
                released_team = str((leave_meta or {}).get("assigned_team") or "").strip()
                aliases = {leave_pid}
                if isinstance(leave_meta, dict):
                    for key in ("user_id", "account_user_id", "participant_id"):
                        alias = str(leave_meta.get(key) or "").strip()
                        if alias:
                            aliases.add(alias)
                parts.pop(leave_pid, None)
                # Also drop case-insensitive aliases.
                for key in list(parts.keys()):
                    if str(key).strip().lower() == leave_pid.lower():
                        parts.pop(key, None)
                doc["participants"] = parts
                joined = doc.get("joined_participants")
                if isinstance(joined, dict):
                    for alias in aliases:
                        joined.pop(alias, None)
                        for key in list(joined.keys()):
                            if str(key).strip().lower() == str(alias).strip().lower():
                                joined.pop(key, None)
                    doc["joined_participants"] = joined
                claims = doc.get("team_claims")
                if isinstance(claims, dict) and released_team:
                    claims.pop(released_team, None)
                    doc["team_claims"] = claims
                try:
                    from draft_room_shared_state import record_shared_room_participant_left

                    record_shared_room_participant_left(
                        doc,
                        leave_pid,
                        aliases=aliases,
                        released_team=released_team,
                    )
                except ImportError:
                    pass
                updated = bump_revision(doc)
                get_shared_room_store().save(updated)
                try:
                    from draft_room_shared_state import invalidate_shared_room_document_cache

                    invalidate_shared_room_document_cache(session, room_code)
                except Exception:
                    pass
        except Exception:
            pass
    for key in (
        ACTIVE_SHARED_ROOM_CODE_KEY,
        SHARED_ROOM_META_KEY,
        ACTIVE_PARTICIPANT_TEAM_KEY,
        ACTIVE_PARTICIPANT_ID_KEY,
        LIVE_DRAFT_ROOM_KEY,
        PARTICIPANT_NOTES_KEY,
        "room_your_team",
        "_draft_room_publish_error",
        "_draft_room_conflict_notice",
        "_draft_room_membership_notice",
        "_shared_draft_poll_ts",
        _SHARED_DRAFT_SYNC_RUN_KEY,
        "_live_draft_queue_fragment_pick",
        "_live_draft_defer_full_rerun",
    ):
        session.pop(key, None)
    session[DRAFT_QUEUE_KEY] = []
    session[DRAFT_WATCHLIST_FOCUS_KEY] = []
    session[DRAFT_WATCHLIST_FAVORITES_KEY] = []
    try:
        clear_live_draft_state(session, reason="leave_shared_room")
    except Exception:
        pass
    session.pop(LIVE_DRAFT_ROOM_KEY, None)
    # Keep Solo/Shared preference for the next draft after leaving a room.
    try:
        from user_page_preferences import restore_live_draft_setup_mode_preference

        restore_live_draft_setup_mode_preference(session)
    except ImportError:
        pass
    try:
        from draft_room_runtime_diagnostics import capture_leave_state_after

        capture_leave_state_after(session, membership_marked_left=bool(room_code))
    except ImportError:
        pass
    try:
        from live_draft_termination import bump_live_draft_page_epoch

        bump_live_draft_page_epoch(session)
    except ImportError:
        pass

def recommendation_team(session: dict[str, Any], *, on_clock_team: str | None = None) -> str:
    """Team scope for recommendation engines — participant team in multiplayer."""
    if is_multiplayer_draft_active(session):
        team = active_participant_team(session)
        if team:
            return team
    if on_clock_team:
        return str(on_clock_team).strip()
    return active_participant_team(session)


def _sync_participant_team_aliases(session: dict[str, Any], team: str) -> None:
    if not team:
        return
    pid = resolve_participant_id(session)
    session[ACTIVE_PARTICIPANT_ID_KEY] = pid
    session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
    if is_multiplayer_draft_active(session):
        return
    session["room_your_team"] = team
    try:
        from global_fantasy_settings_state import write_canonical_global_fantasy_settings

        write_canonical_global_fantasy_settings(session, team=team, reason="draft_room_context")
    except ImportError:
        pass
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if isinstance(room, dict):
        cfg = dict(room.get("config") or {})
        cfg["your_team"] = team
        cfg["user_team"] = team
        room["config"] = cfg

