"""Auth-based shared draft room membership (PR 5)."""

from __future__ import annotations

from typing import Any

ERR_LOGIN_REQUIRED = "Please log in to join this shared draft room."
ERR_LOGIN_REQUIRED_CREATE = "Please log in to create a shared draft room."
ERR_TEAM_ALREADY_ASSIGNED = "This team is already assigned."
ERR_HOST_ONLY_RESET = "Only the room host can reset this draft."
ERR_MEMBERSHIP_CHANGED = "Your room membership changed. Please refresh."
ERR_CANNOT_DRAFT_OTHER_TEAM = "You cannot draft for another team."


def _normalize_team_label(team: str) -> str:
    return str(team or "").strip().casefold()


def _teams_match(participant_team: str, on_clock_team: str) -> bool:
    a = _normalize_team_label(participant_team)
    b = _normalize_team_label(on_clock_team)
    return bool(a and b and a == b)


def _record_validate_participant_diag(session: dict[str, Any], **fields: Any) -> None:
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(session, validate_participant_may_draft_entered=True, **fields)
    except ImportError:
        pass


def _resolve_on_clock_slot_for_validation(live_room: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve on-clock pick slot without importing streamlit_app."""
    if not isinstance(live_room, dict):
        return None
    try:
        from live_draft_timer_logic import live_draft_current_slot
    except ImportError:
        live_draft_current_slot = None  # type: ignore[assignment,misc]

    room = live_room
    if live_draft_current_slot is not None:
        slot = live_draft_current_slot(room)
        if isinstance(slot, dict):
            return slot

    try:
        from live_draft_state import analyze_live_draft_progress, repair_stale_live_draft_progress

        room = repair_stale_live_draft_progress(dict(live_room))
        if live_draft_current_slot is not None:
            slot = live_draft_current_slot(room)
            if isinstance(slot, dict):
                return slot
        progress = analyze_live_draft_progress(room)
        slot = progress.get("slot")
        if isinstance(slot, dict):
            return slot
    except ImportError:
        room = live_room

    pick_order = list(room.get("pick_order") or [])
    if not pick_order:
        return None
    board = len(room.get("draft_board") or [])
    idx = int(room.get("current_pick_index") or 0)
    if idx >= len(pick_order) and board < len(pick_order):
        idx = board
    if 0 <= idx < len(pick_order):
        slot = pick_order[idx]
        if isinstance(slot, dict):
            return slot
    if 0 <= board < len(pick_order):
        slot = pick_order[board]
        if isinstance(slot, dict):
            return slot
    return None


def _validation_context(session: dict[str, Any], live_room: dict[str, Any]) -> dict[str, Any]:
    board_size = len(live_room.get("draft_board") or []) if isinstance(live_room, dict) else 0
    total_picks = 0
    draft_complete = False
    computed_status = ""
    completion_source = ""
    saved_status = str(live_room.get("status") or "").strip() if isinstance(live_room, dict) else ""
    current_pick_index = int(live_room.get("current_pick_index") or 0) if isinstance(live_room, dict) else 0
    manual_recovery = False
    safe_mode_active = False
    draft_state_error = False
    is_my_turn = False
    on_clock_team = ""
    participant_team = ""

    if isinstance(live_room, dict):
        try:
            from live_draft_safe_mode import compute_draft_status, is_draft_truly_complete, total_expected_picks

            total_picks = total_expected_picks(live_room)
            draft_complete = bool(total_picks > 0 and is_draft_truly_complete(live_room))
            computed_status, completion_source = compute_draft_status(live_room)
        except ImportError:
            total_picks = len(live_room.get("pick_order") or [])
            draft_complete = total_picks > 0 and board_size >= total_picks

    try:
        from live_draft_safe_mode import draft_state_error_reason, is_safe_mode_active

        safe_mode_active = is_safe_mode_active(session)
        draft_state_error = bool(draft_state_error_reason(session))
        manual_recovery = bool((session.get("_live_draft_safe_mode_diag") or {}).get("manual_recovery_available"))
    except ImportError:
        pass

    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            participant_team = str(active_participant_team(session) or "").strip()
    except ImportError:
        participant_team = str(session.get("room_your_team") or "").strip()

    slot = _resolve_on_clock_slot_for_validation(live_room) if isinstance(live_room, dict) else None
    if isinstance(slot, dict):
        on_clock_team = str(slot.get("Team") or "").strip()
    is_my_turn = _teams_match(participant_team, on_clock_team)

    return {
        "validation_board_size": board_size,
        "validation_total_picks": total_picks,
        "validation_current_pick_index": current_pick_index,
        "validation_saved_status": saved_status,
        "validation_computed_status": computed_status,
        "validation_completion_source": completion_source,
        "validation_draft_complete": draft_complete,
        "validation_participant_team": participant_team or None,
        "validation_on_clock_team": on_clock_team or None,
        "validation_is_my_turn": is_my_turn,
        "validation_manual_recovery_available": manual_recovery,
        "validation_safe_mode_active": safe_mode_active,
        "validation_draft_state_error": draft_state_error,
    }


def _player_available_for_manual_pick(session: dict[str, Any], player_name: str) -> bool | None:
    name = str(player_name or "").strip()
    if not name:
        return None
    try:
        from draft_actions import _live_player_available

        ok, _ = _live_player_available(session, name)
        return bool(ok)
    except Exception:
        return None


def validate_participant_may_draft(
    session: dict[str, Any],
    live_room: dict[str, Any],
    *,
    player_name: str = "",
) -> tuple[bool, str]:
    """Ensure participant only drafts for their assigned team when on the clock."""
    ctx = _validation_context(session, live_room)
    player_available = _player_available_for_manual_pick(session, player_name) if player_name else None

    def _fail(reason: str) -> tuple[bool, str]:
        _record_validate_participant_diag(
            session,
            **ctx,
            validation_player_available=player_available,
            validate_participant_may_draft_result=False,
            validate_participant_may_draft_reason=reason,
            validate_participant_may_draft_message=reason,
        )
        return False, reason

    def _ok() -> tuple[bool, str]:
        _record_validate_participant_diag(
            session,
            **ctx,
            validation_player_available=player_available,
            validate_participant_may_draft_result=True,
            validate_participant_may_draft_reason="ok",
            validate_participant_may_draft_message=None,
        )
        return True, ""

    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active
    except ImportError:
        return _ok()

    if not is_multiplayer_draft_active(session):
        _record_validate_participant_diag(
            session,
            **ctx,
            validation_player_available=player_available,
            validate_participant_may_draft_reason="not_multiplayer",
            validate_participant_may_draft_result=True,
        )
        return True, ""

    your_team = str(active_participant_team(session) or ctx.get("validation_participant_team") or "").strip()
    ctx["validation_participant_team"] = your_team or None
    if not your_team:
        return _fail(ERR_MEMBERSHIP_CHANGED)

    slot = _resolve_on_clock_slot_for_validation(live_room)
    if isinstance(slot, dict):
        on_clock = str(slot.get("Team") or "").strip()
        ctx["validation_on_clock_team"] = on_clock or None
        ctx["validation_is_my_turn"] = _teams_match(your_team, on_clock)
        if on_clock and not _teams_match(your_team, on_clock):
            pick_n = slot.get("Pick")
            if pick_n:
                return _fail(f"Not your pick (Pick {pick_n}: {on_clock}).")
            return _fail(ERR_CANNOT_DRAFT_OTHER_TEAM)

    draft_complete = bool(ctx.get("validation_draft_complete"))
    board_size = int(ctx.get("validation_board_size") or 0)
    total_picks = int(ctx.get("validation_total_picks") or 0)
    computed_status = str(ctx.get("validation_computed_status") or "").strip()
    saved_status = str(ctx.get("validation_saved_status") or "").strip()

    if draft_complete and total_picks > 0 and board_size >= total_picks:
        return _fail("Draft is complete.")

    # Derived in-progress overrides stale saved complete for validation.
    if computed_status == "in_progress" or (total_picks > 0 and board_size < total_picks):
        pass
    elif saved_status == "complete":
        return _fail("Draft is complete.")

    if slot is None:
        if total_picks > 0 and board_size < total_picks:
            return _fail(
                f"Pick slot unavailable but draft in progress "
                f"(board={board_size}, total={total_picks}, idx={ctx.get('validation_current_pick_index')})."
            )
        return _fail("Draft is complete.")

    return _ok()


def shared_room_requires_auth() -> bool:
    """True when shared rooms use Supabase (cross-account multiplayer)."""
    try:
        from draft_room_supabase_store import supabase_shared_room_backend_available

        return bool(supabase_shared_room_backend_available())
    except ImportError:
        return False


def is_auth_session(session: dict[str, Any]) -> bool:
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        return bool(is_auth_enabled() and is_authenticated(session))
    except ImportError:
        return False


def auth_user_id(session: dict[str, Any]) -> str:
    """Supabase Auth user UUID when logged in."""
    try:
        from suite_auth import AUTH_USER_ID_KEY

        return str(session.get(AUTH_USER_ID_KEY) or "").strip()
    except ImportError:
        return ""


def participant_display_name(session: dict[str, Any]) -> str:
    try:
        from suite_auth import current_auth_email, is_authenticated

        if is_authenticated(session):
            email = str(current_auth_email(session) or "").strip()
            if email:
                return email
    except ImportError:
        pass
    from draft_room_participant_state import resolve_participant_id

    return resolve_participant_id(session)


def ensure_authenticated_for_shared_room(
    session: dict[str, Any],
    *,
    for_create: bool = False,
) -> tuple[bool, str]:
    if not shared_room_requires_auth():
        return True, ""
    if is_auth_session(session) and auth_user_id(session):
        return True, ""
    return False, ERR_LOGIN_REQUIRED_CREATE if for_create else ERR_LOGIN_REQUIRED


def default_host_team(live_room: dict[str, Any]) -> str:
    teams = live_room.get("teams") or []
    if teams:
        return str(teams[0]).strip()
    cfg = dict(live_room.get("config") or {})
    n = int(cfg.get("num_teams") or 0)
    if n:
        return "Team 1"
    return "Team 1"


def document_host_ids(document: dict[str, Any] | None) -> set[str]:
    """All host identity aliases on a shared room document."""
    if not isinstance(document, dict):
        return set()
    out: set[str] = set()
    for key in ("commissioner_participant_id", "host_participant_id", "host_user_id"):
        val = str(document.get(key) or "").strip()
        if val:
            out.add(val)
    return out


def document_host_id(document: dict[str, Any] | None) -> str:
    """Primary host id — prefer commissioner / participant map key over auth alias."""
    if not isinstance(document, dict):
        return ""
    return str(
        document.get("commissioner_participant_id")
        or document.get("host_participant_id")
        or document.get("host_user_id")
        or ""
    ).strip()


def is_room_host(
    session: dict[str, Any],
    document: dict[str, Any] | None = None,
) -> bool:
    """True only when the current participant is the authoritative room commissioner.

    Never infer from Team A, workspace name, stale is_host flags, or sibling
    membership pids. Matching rule:

        canonical_current_participant_id == authoritative_room.commissioner_participant_id
    """
    try:
        from shared_draft_permissions import is_canonical_commissioner

        return bool(is_canonical_commissioner(session, document))
    except ImportError:
        pass
    from draft_room_participant_state import resolve_participant_id

    host = document_host_id(document)
    if not host:
        return False
    pid = str(resolve_participant_id(session) or "").strip()
    if pid and pid == host:
        return True
    try:
        from suite_auth import AUTH_USER_ID_KEY

        auth = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if auth and auth == host:
            return True
    except ImportError:
        pass
    return False


def resolve_join_team_assignment(
    document: dict[str, Any],
    participant_id: str,
    *,
    requested_team: str | None = None,
    current_identity_aliases: set[str] | None = None,
) -> tuple[str | None, str]:
    """Pick or restore team for join; return (team, error_message).

    Occupancy uses the same authoritative calculator as the guest join screen so
    host alias duplicates cannot invent a second claimed seat.

    Auto-assigns when exactly one human team is open. Requires explicit selection
    when multiple teams remain open. Never assigns the commissioner seat to a guest.
    """
    pid = str(participant_id or "").strip()
    # Exact document reattach — current participant already owns a team in this room.
    participants = dict(document.get("participants") or {}) if isinstance(document, dict) else {}
    existing = participants.get(pid)
    if isinstance(existing, dict) and existing.get("assigned_team"):
        return str(existing["assigned_team"]).strip(), ""

    try:
        from live_draft_team_ownership import (
            list_available_shared_room_teams,
            repair_shared_document_claims,
        )

        doc = repair_shared_document_claims(document)
        open_teams, diag = list_available_shared_room_teams(
            doc,
            pid,
            current_identity_aliases=current_identity_aliases,
        )
        already = str(diag.get("already_joined_team") or "").strip()
        if already:
            # Guard: never treat commissioner Team A as "already joined" for a guest
            # whose exact participant row is missing from the document.
            owner_pid = str(
                ((diag.get("occupancy") or {}).get(already) or {}).get("canonical_participant_id")
                or ""
            ).strip()
            if owner_pid and owner_pid == pid:
                return already, ""
            if pid in participants and str(
                (participants.get(pid) or {}).get("assigned_team") or ""
            ).strip() == already:
                return already, ""
            # Stale alias match — ignore and continue with open-team assignment.
            already = ""

        if requested_team:
            req = str(requested_team).strip()
            if req in open_teams:
                return req, ""
            slot = (diag.get("occupancy") or {}).get(req) or {}
            owner = str(slot.get("canonical_claimant") or "").strip()
            if owner or slot.get("canonical_participant_id"):
                return None, ERR_TEAM_ALREADY_ASSIGNED
            return None, f"Team **{req}** is not available in this room."

        if not open_teams:
            return None, "No open team slots in this room."
        if len(open_teams) == 1:
            return open_teams[0], ""
        return None, "Choose a team before joining — select one of the open teams."
    except ImportError:
        pass

    participants = dict(document.get("participants") or {})
    existing = participants.get(pid)
    if isinstance(existing, dict) and existing.get("assigned_team"):
        return str(existing["assigned_team"]), ""

    room_blob = document.get("room")
    teams = []
    if isinstance(room_blob, dict):
        teams = [str(t).strip() for t in (room_blob.get("teams") or []) if str(t).strip()]
        if not teams:
            cfg = dict(room_blob.get("config") or {})
            n = int(cfg.get("num_teams") or 0)
            teams = [f"Team {i + 1}" for i in range(n)] if n else []

    taken_by_other: dict[str, str] = {}
    for other_id, meta in participants.items():
        if not isinstance(meta, dict):
            continue
        team = str(meta.get("assigned_team") or "").strip()
        if not team:
            continue
        taken_by_other[team] = str(other_id)

    if requested_team:
        req = str(requested_team).strip()
        if req in taken_by_other and taken_by_other[req] != pid:
            return None, ERR_TEAM_ALREADY_ASSIGNED
        if req in teams and req not in taken_by_other:
            return req, ""
        return None, f"Team **{req}** is not available in this room."

    open_teams = [t for t in teams if t not in taken_by_other]
    if not open_teams:
        return None, "No open team slots in this room."
    if len(open_teams) == 1:
        return open_teams[0], ""
    return None, "Choose a team before joining — select one of the open teams."


def sync_membership_from_document(
    session: dict[str, Any],
    document: dict[str, Any],
) -> tuple[bool, str]:
    """Align session team with shared participant registry."""
    from draft_room_participant_state import (
        ACTIVE_PARTICIPANT_TEAM_KEY,
        resolve_participant_id,
        set_active_participant,
    )

    code = str(document.get("room_code") or session.get("active_shared_draft_room_code") or "").upper()
    pid = resolve_participant_id(session)
    participants = dict(document.get("participants") or {})
    meta = participants.get(pid)
    if not isinstance(meta, dict) or not meta.get("assigned_team"):
        if shared_room_requires_auth() and is_auth_session(session):
            return False, ERR_MEMBERSHIP_CHANGED
        return True, ""

    team = str(meta.get("assigned_team") or "").strip()
    session_team = str(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or "").strip()
    changed = bool(session_team and team and session_team != team)
    needs_sync = bool(team and (changed or not session_team))
    if needs_sync:
        set_active_participant(session, room_code=code, participant_id=pid, assigned_team=team)
        try:
            from draft_room_context import _sync_participant_team_aliases

            _sync_participant_team_aliases(session, team)
        except ImportError:
            pass
    if changed:
        return False, ERR_MEMBERSHIP_CHANGED
    return True, ""


def close_shared_draft_room(
    session: dict[str, Any],
    *,
    store: Any | None = None,
) -> tuple[bool, str]:
    """Host closes shared room document (status=closed)."""
    from draft_room_context import is_multiplayer_draft_active, leave_shared_draft_room
    from draft_room_shared_state import bump_revision, get_shared_room_store, load_shared_room

    if not is_multiplayer_draft_active(session):
        return True, ""

    document = load_shared_room(str(session.get("active_shared_draft_room_code") or ""), store=store)
    if not is_room_host(session, document):
        return False, ERR_HOST_ONLY_RESET

    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code or not isinstance(document, dict):
        leave_shared_draft_room(session)
        return True, ""

    backend = store or get_shared_room_store()
    updated = bump_revision(document)
    updated["status"] = "closed"
    room_blob = updated.get("room")
    if isinstance(room_blob, dict):
        room_blob["status"] = "closed"
    backend.save(updated)
    leave_shared_draft_room(session)
    return True, ""


def reset_live_draft_with_membership_guard(
    session: dict[str, Any],
    *,
    st_obj: Any = None,
    reason: str = "reset",
) -> tuple[bool, str]:
    """Delete live draft locally; host-only when in shared multiplayer room."""
    from draft_room_context import is_multiplayer_draft_active

    if is_multiplayer_draft_active(session):
        ok, msg = close_shared_draft_room(session)
        if not ok:
            return False, msg

    try:
        from draft_room_state import delete_live_draft_only
        from live_draft_state import commit_live_draft_room

        delete_live_draft_only(session)
        if st_obj is not None:
            commit_live_draft_room(st_obj, session, None, reason=reason)
    except ImportError:
        pass
    return True, ""
