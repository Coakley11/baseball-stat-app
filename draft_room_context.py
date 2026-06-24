"""Global draft context — shared room + participant team for every page and AMI send.

Call ``prepare_global_draft_context(session)`` during app bootstrap so Sleepers,
Comparison, AMI, and Live Draft all see the same active room while keeping private
queue/recommendation scope per participant.
"""

from __future__ import annotations

from typing import Any

from draft_room_participant_state import (
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
    document_to_runtime_room,
    generate_room_code,
    get_shared_room_store,
    load_shared_room,
    publish_shared_room_runtime,
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
    if backup_room_code:
        session[ACTIVE_SHARED_ROOM_CODE_KEY] = str(backup_room_code).strip().upper()
    if isinstance(backup_room, dict):
        session[LIVE_DRAFT_ROOM_KEY] = backup_room
    session.pop(ACTIVE_PARTICIPANT_TEAM_KEY, None)


def is_multiplayer_draft_active(session: dict[str, Any]) -> bool:
    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip()
    return bool(code)


def get_global_draft_context(session: dict[str, Any]) -> dict[str, Any]:
    """Structured context for pages, AMI, and recommendation wrappers."""
    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    participant_id = resolve_participant_id(session)
    participant_team = active_participant_team(session)
    shared_meta = dict(session.get(SHARED_ROOM_META_KEY) or {})
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    runtime_active = has_active_live_draft(session)
    is_host = False
    if room_code:
        try:
            from draft_room_membership import is_room_host

            doc = load_shared_room(room_code)
            is_host = is_room_host(session, doc)
        except ImportError:
            pass
    return {
        "mode": "multiplayer" if room_code else ("single_user_live" if runtime_active else "none"),
        "room_code": room_code or None,
        "participant_id": participant_id,
        "participant_team": participant_team,
        "is_room_host": is_host,
        "shared_revision": shared_meta.get("revision"),
        "shared_updated_at": shared_meta.get("updated_at"),
        "shared_storage_backend": shared_meta.get("storage_backend"),
        "live_draft_active": runtime_active,
        "room_status": str(room.get("status") or "") if isinstance(room, dict) else "",
        "draft_room_id": str(room.get("draft_room_id") or "") if isinstance(room, dict) else "",
    }


def prepare_global_draft_context(session: dict[str, Any]) -> dict[str, Any]:
    """Bootstrap hook — hydrate runtime room and participant-private workflow."""
    from draft_room_participant_state import restore_persisted_shared_room_membership

    restored_code = restore_persisted_shared_room_membership(session)
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
        document = load_shared_room(str(room_code))
        if document:
            runtime = publish_shared_room_runtime(session, document, reason="global_context_prepare")
            if runtime is None:
                session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
                session.pop(SHARED_ROOM_META_KEY, None)
                session["_draft_room_last_error"] = str(
                    session.get("_draft_room_publish_error") or "Shared room data is invalid or empty."
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
            session["_draft_room_last_error"] = (
                f"Shared room **{room_code}** could not be loaded from {shared_room_backend_name()}."
            )
    else:
        prepare_live_draft_state(session)
    return get_global_draft_context(session)


_SHARED_DRAFT_SYNC_RUN_KEY = "_shared_draft_sync_run"


def sync_shared_draft_room(
    session: dict[str, Any],
    *,
    force: bool = False,
    store: SharedRoomStore | None = None,
) -> bool:
    """Poll shared store; refresh session when revision advances.

    Returns True when the local runtime was updated from a newer remote revision.
    """
    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if not room_code:
        return False
    if not force and session.get(_SHARED_DRAFT_SYNC_RUN_KEY):
        return False

    backend = store or get_shared_room_store()
    local_rev = int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)

    if not force:
        load_head = getattr(backend, "load_head", None)
        if callable(load_head):
            head = load_head(room_code)
            if isinstance(head, dict):
                remote_rev = int(head.get("revision") or 0)
                if remote_rev <= local_rev:
                    session[_SHARED_DRAFT_SYNC_RUN_KEY] = True
                    return False

    document = backend.load(room_code)
    session[_SHARED_DRAFT_SYNC_RUN_KEY] = True
    if not isinstance(document, dict):
        return False
    remote_rev = int(document.get("revision") or 0)
    if force or remote_rev > local_rev:
        publish_shared_room_runtime(session, document, reason="shared_room_poll")
        load_participant_workflow_into_session(session, room_code)
        return True
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

    from draft_room_create_verify import normalize_room_code, verify_shared_room_persisted

    backup_room = copy.deepcopy(live_room) if isinstance(live_room, dict) else None
    backup_room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper() or None

    ok_auth, auth_msg = ensure_authenticated_for_shared_room(session, for_create=True)
    if not ok_auth:
        session["_draft_room_last_error"] = auth_msg
        return "", {}

    backend = store or get_shared_room_store()
    participant_id = resolve_participant_id(session)
    assigned = str(host_team or "").strip() or default_host_team(live_room)
    try:
        from draft_room_supabase_errors import SharedRoomSupabaseError, record_shared_room_supabase_error
    except ImportError:
        SharedRoomSupabaseError = RuntimeError  # type: ignore[misc, assignment]
        record_shared_room_supabase_error = None  # type: ignore[assignment]

    code = generate_room_code(exists=backend.exists)
    document = shared_room_document(
        room_code=code,
        host_participant_id=participant_id,
        live_room=live_room,
        revision=1,
    )
    document["created_at"] = document.get("updated_at") or document.get("created_at")
    document["host_user_id"] = str(auth_user_id(session) or participant_id)
    document["host_participant_id"] = participant_id
    document["_storage_backend"] = shared_room_backend_name()
    document = register_participant_in_shared_document(
        document,
        participant_id=participant_id,
        assigned_team=assigned,
        display_name=participant_display_name(session),
    )
    try:
        saved = backend.save(document)
    except SharedRoomSupabaseError as exc:
        if record_shared_room_supabase_error is not None:
            record_shared_room_supabase_error(session, exc)
        else:
            session["_draft_room_last_error"] = str(exc)
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}
    except ValueError as exc:
        session["_draft_room_last_error"] = str(exc)
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}
    except RuntimeError as exc:
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
        session["_draft_room_last_error"] = "Could not create shared room."
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}

    saved_code = normalize_room_code(saved.get("room_code"))
    verified, verify_msg, verify_diag = verify_shared_room_persisted(
        backend,
        saved_code,
        saved_document=saved,
    )
    session["_draft_room_create_diag"] = verify_diag
    if not verified:
        session["_draft_room_last_error"] = verify_msg
        abort_shared_room_create(session, backup_room=backup_room, backup_room_code=backup_room_code)
        return "", {}

    runtime = publish_shared_room_runtime(session, saved, reason="shared_room_create")
    if runtime is None:
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
    backend = store or get_shared_room_store()
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
        return False, f"Room **{code}** not found in {backend_name}. Check the code and try again.", None

    ok_doc, doc_err = validate_shared_room_document(document)
    if not ok_doc:
        return False, doc_err, document
    if str(document.get("status") or "").lower() == "closed":
        try:
            from draft_room_join_trace import trace_join_step

            trace_join_step(session, "join_room_closed", room_code=code, backend=backend_name)
        except ImportError:
            pass
        return False, "This draft room has been closed by the host.", None

    participant_id = resolve_participant_id(session)
    participants = dict(document.get("participants") or {})
    existing = participants.get(participant_id)
    if isinstance(existing, dict) and existing.get("assigned_team"):
        assigned = str(existing["assigned_team"])
    else:
        assigned, err = resolve_join_team_assignment(
            document,
            participant_id,
            requested_team=requested_team,
        )
        if not assigned:
            return False, err or "No open team slots in this room.", document
        document = register_participant_in_shared_document(
            document,
            participant_id=participant_id,
            assigned_team=assigned,
            display_name=display_name or participant_display_name(session),
        )
        try:
            backend.save(document)
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
                return False, str(exc), document
            raise
    session[ACTIVE_SHARED_ROOM_CODE_KEY] = code
    set_active_participant(session, room_code=code, participant_id=participant_id, assigned_team=assigned)
    save_participant_workflow_from_session(session, code)
    runtime = publish_shared_room_runtime(session, document, reason="shared_room_join")
    if runtime is None:
        session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
        session.pop(SHARED_ROOM_META_KEY, None)
        return False, str(session.get("_draft_room_publish_error") or "Shared room data is invalid."), document
    load_participant_workflow_into_session(session, code)
    _sync_participant_team_aliases(session, assigned)
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
        )
    except ImportError:
        pass
    return True, f"Joined room {code} as {assigned}.", document


def commit_shared_room_state(
    session: dict[str, Any],
    live_room: dict[str, Any],
    *,
    expected_revision: int | None = None,
    player_name: str | None = None,
    store: SharedRoomStore | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Validate (optional pick) and persist shared room document."""
    from draft_room_shared_state import commit_shared_room_pick

    if player_name:
        from draft_source_validation import validate_shared_pick_commit

        room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
        shared_doc = None
        if room_code:
            from draft_room_shared_state import document_to_runtime_room, load_shared_room

            shared_doc = load_shared_room(room_code, store=store)
        remote_rev = int(shared_doc.get("revision") or 0) if isinstance(shared_doc, dict) else 0
        exp_rev = int(expected_revision or 0)
        if isinstance(shared_doc, dict) and remote_rev == exp_rev:
            validation_room = document_to_runtime_room(shared_doc) or live_room
            ok, msg = validate_shared_pick_commit(session, validation_room, player_name)
            if not ok:
                sync_shared_draft_room(session, force=True, store=store)
                return False, msg, None

    if expected_revision is None:
        expected_revision = int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)

    ok, saved = commit_shared_room_pick(
        session,
        live_room,
        expected_revision=expected_revision,
        store=store,
    )
    if not ok:
        sync_shared_draft_room(session, force=True, store=store)
        conflict_msg = "Another participant updated the room. Board refreshed."
        session["_draft_room_conflict_notice"] = conflict_msg
        return False, conflict_msg, saved

    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if room_code:
        save_participant_workflow_from_session(session, room_code)
    try:
        from draft_room_state import sync_live_draft_room_to_canonical_board

        sync_live_draft_room_to_canonical_board(session, live_room)
    except ImportError:
        pass
    return True, "", saved


def leave_shared_draft_room(session: dict[str, Any]) -> None:
    room_code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if room_code:
        save_participant_workflow_from_session(session, room_code)
    session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
    session.pop(SHARED_ROOM_META_KEY, None)
    session.pop(ACTIVE_PARTICIPANT_TEAM_KEY, None)


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

