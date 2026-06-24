"""Auth-based shared draft room membership (PR 5)."""

from __future__ import annotations

from typing import Any

ERR_LOGIN_REQUIRED = "Please log in to join this shared draft room."
ERR_LOGIN_REQUIRED_CREATE = "Please log in to create a shared draft room."
ERR_TEAM_ALREADY_ASSIGNED = "This team is already assigned."
ERR_HOST_ONLY_RESET = "Only the room host can reset this draft."
ERR_MEMBERSHIP_CHANGED = "Your room membership changed. Please refresh."
ERR_CANNOT_DRAFT_OTHER_TEAM = "You cannot draft for another team."


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


def document_host_id(document: dict[str, Any] | None) -> str:
    if not isinstance(document, dict):
        return ""
    return str(
        document.get("host_user_id")
        or document.get("host_participant_id")
        or ""
    ).strip()


def is_room_host(
    session: dict[str, Any],
    document: dict[str, Any] | None = None,
) -> bool:
    from draft_room_participant_state import resolve_participant_id

    host = document_host_id(document)
    if not host:
        return False
    return host == resolve_participant_id(session)


def resolve_join_team_assignment(
    document: dict[str, Any],
    participant_id: str,
    *,
    requested_team: str | None = None,
) -> tuple[str | None, str]:
    """Pick or restore team for join; return (team, error_message)."""
    from draft_room_participant_state import assign_team_for_join

    pid = str(participant_id or "").strip()
    participants = dict(document.get("participants") or {})
    existing = participants.get(pid)
    if isinstance(existing, dict) and existing.get("assigned_team"):
        return str(existing["assigned_team"]), ""

    room_blob = document.get("room")
    teams: list[str] = []
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
        if team:
            taken_by_other[team] = str(other_id)

    if requested_team:
        req = str(requested_team).strip()
        if req in taken_by_other and taken_by_other[req] != pid:
            return None, ERR_TEAM_ALREADY_ASSIGNED
        if req in teams and req not in taken_by_other:
            return req, ""

    assigned = assign_team_for_join(document, requested_team=requested_team)
    if not assigned:
        return None, "No open team slots in this room."
    return assigned, ""


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


def validate_participant_may_draft(
    session: dict[str, Any],
    live_room: dict[str, Any],
) -> tuple[bool, str]:
    """Ensure participant only drafts for their assigned team when on the clock."""
    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active
    except ImportError:
        return True, ""

    if not is_multiplayer_draft_active(session):
        return True, ""

    your_team = active_participant_team(session)
    if not your_team:
        return False, ERR_MEMBERSHIP_CHANGED

    try:
        from draft_actions import _import_baseball_app

        slot = _import_baseball_app().live_draft_current_slot(live_room)
    except Exception:
        slot = None
    if slot is None:
        return False, "Draft is complete."

    on_clock = str(slot.get("Team") or "").strip()
    if your_team != on_clock:
        pick_n = slot.get("Pick")
        if pick_n:
            return False, f"Not your pick (Pick {pick_n}: {on_clock})."
        return False, ERR_CANNOT_DRAFT_OTHER_TEAM
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
