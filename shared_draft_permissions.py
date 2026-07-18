"""Canonical Shared Multiplayer commissioner and role permissions."""

from __future__ import annotations

from typing import Any


def commissioner_participant_id(document: dict[str, Any] | None) -> str:
    """Single authoritative commissioner id for a shared room document."""
    if not isinstance(document, dict):
        return ""
    return str(
        document.get("commissioner_participant_id")
        or document.get("host_participant_id")
        or document.get("host_user_id")
        or ""
    ).strip()


def current_canonical_participant_id(session: dict[str, Any]) -> str:
    try:
        from draft_room_participant_state import resolve_participant_id

        return str(resolve_participant_id(session) or "").strip()
    except ImportError:
        return str(
            session.get("auth_user_id")
            or session.get("_suite_auth_user_id")
            or session.get("draft_room_participant_id")
            or ""
        ).strip()


def is_canonical_commissioner(
    session: dict[str, Any],
    document: dict[str, Any] | None = None,
) -> bool:
    """True only when the current participant is the room's commissioner.

    Never infer from Team A, workspace name, stale is_host flags, or generic aliases.
    """
    host = commissioner_participant_id(document)
    if not host:
        return False
    pid = current_canonical_participant_id(session)
    if not pid:
        return False
    if pid == host:
        return True
    # Allow exact auth-user match only when create stamped host_user_id separately.
    auth = str(session.get("auth_user_id") or session.get("_suite_auth_user_id") or "").strip()
    if auth and auth == host:
        return True
    try:
        from suite_auth import AUTH_USER_ID_KEY

        auth2 = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if auth2 and auth2 == host:
            return True
    except ImportError:
        pass
    return False


def stamp_commissioner_on_document(
    document: dict[str, Any],
    *,
    participant_id: str,
    auth_user_id: str = "",
) -> dict[str, Any]:
    pid = str(participant_id or "").strip()
    if not pid:
        return document
    document["commissioner_participant_id"] = pid
    document["host_participant_id"] = pid
    if auth_user_id:
        document["host_user_id"] = str(auth_user_id).strip()
    elif not document.get("host_user_id"):
        document["host_user_id"] = pid
    return document


def participant_may_auto_pick(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    document: dict[str, Any] | None = None,
    on_clock_team: str = "",
) -> bool:
    """Auto Pick Now: commissioner always; guest only when their claimed team is on clock."""
    if is_canonical_commissioner(session, document):
        return True
    team = ""
    try:
        from draft_room_participant_state import active_participant_team

        team = str(active_participant_team(session) or "").strip()
    except ImportError:
        team = str(session.get("draft_room_participant_team") or "").strip()
    clock = str(on_clock_team or "").strip()
    if not clock and isinstance(room, dict):
        try:
            from live_draft_timer_logic import live_draft_current_slot

            slot = live_draft_current_slot(room) or {}
            clock = str(slot.get("Team") or "").strip()
        except ImportError:
            pass
    return bool(team and clock and team == clock)
