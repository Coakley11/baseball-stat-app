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

        pid = str(resolve_participant_id(session) or "").strip()
        if pid:
            return pid
    except ImportError:
        pass
    # Prefer durable auth uid even when Real Accounts is off (parked Continue Saved).
    try:
        from suite_auth import AUTH_USER_ID_KEY

        auth_id = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if auth_id:
            return auth_id
    except ImportError:
        pass
    return str(
        session.get("auth_user_id")
        or session.get("_suite_auth_user_id")
        or session.get("draft_room_participant_id")
        or ""
    ).strip()


def _participant_id_aliases(session: dict[str, Any]) -> set[str]:
    """Ids that may represent the same person across park / auth-off / workspace paths."""
    out: set[str] = set()
    for raw in (
        current_canonical_participant_id(session),
        session.get("draft_room_participant_id"),
        session.get("auth_user_id"),
        session.get("_suite_auth_user_id"),
    ):
        val = str(raw or "").strip()
        if val:
            out.add(val)
    try:
        from suite_auth import AUTH_USER_ID_KEY

        auth_id = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if auth_id:
            out.add(auth_id)
    except ImportError:
        pass
    return out


def is_canonical_commissioner(
    session: dict[str, Any],
    document: dict[str, Any] | None = None,
) -> bool:
    """True when current identity matches room.commissioner_participant_id.

    Never infer from Team A, workspace name alone, stale is_host flags, or guest aliases.
    Auth uid and parked draft_room_participant_id are accepted as the same person.
    """
    host = commissioner_participant_id(document)
    if not host:
        return False
    return host in _participant_id_aliases(session)


def session_may_use_commissioner_draft_controls(
    session: dict[str, Any],
    *,
    document: dict[str, Any] | None = None,
) -> bool:
    """Save/Continue Later, End/Delete, Continue Saved Draft, Resume Continue Draft.

    Shared Multiplayer: exact commissioner id on the authoritative room document.
    No shared room code: local session owns the draft (Solo / pre-create).
    """
    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code:
        try:
            from draft_room_context import resolve_shared_room_code

            code = str(resolve_shared_room_code(session) or "").strip().upper()
        except ImportError:
            pass
    if code:
        doc = document
        if not isinstance(doc, dict):
            try:
                from draft_room_shared_state import load_shared_room_document, load_shared_room

                doc = load_shared_room_document(session, code) or load_shared_room(code)
            except ImportError:
                doc = None
        return is_canonical_commissioner(session, doc if isinstance(doc, dict) else None)

    # No join code — local owner controls (Solo or orphan setup room).
    return True


def can_continue_saved_draft_slot(session: dict[str, Any]) -> bool:
    """Only the commissioner who owns the resumable Shared slot (or Solo owner)."""
    try:
        from live_draft_resumable_slot import get_resumable_live_draft_slot

        slot = get_resumable_live_draft_slot(session)
    except ImportError:
        slot = session.get("resumable_live_draft_slot")
        if not isinstance(slot, dict):
            slot = None
    if not isinstance(slot, dict):
        return False
    code = str(slot.get("room_code") or "").strip().upper()
    aliases = _participant_id_aliases(session)
    stamped = str(
        slot.get("commissioner_participant_id") or slot.get("participant_id") or ""
    ).strip()
    if stamped and stamped in aliases:
        return True
    if not code and not slot.get("is_shared"):
        return True
    if not code:
        return False
    try:
        from draft_room_shared_state import load_shared_room

        doc = load_shared_room(code)
    except ImportError:
        doc = None
    if not isinstance(doc, dict):
        return bool(stamped and stamped in aliases)
    return is_canonical_commissioner(session, doc)


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
    """Auto Pick Now: solo host always; commissioner always; guest only when their team is on clock."""
    try:
        from live_draft_solo_timer import is_solo_live_draft

        if is_solo_live_draft(session, room):
            return True
    except ImportError:
        pass
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
