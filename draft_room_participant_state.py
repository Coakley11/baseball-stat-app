"""Private per-participant draft room state — queue, watchlist, notes, AMI context.

Each connected user in a shared room keeps their own strategy layer. Shared board
state lives in ``draft_room_shared_state``; this module owns participant-private data.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY
from draft_state import (
    DRAFT_QUEUE_KEY,
    DRAFT_WATCHLIST_FAVORITES_KEY,
    DRAFT_WATCHLIST_FOCUS_KEY,
    gather_draft_workflow,
    prepare_draft_workflow,
)

PARTICIPANT_STATE_KEY = "draft_room_participant_state"
ACTIVE_PARTICIPANT_ID_KEY = "draft_room_participant_id"
ACTIVE_PARTICIPANT_TEAM_KEY = "draft_room_participant_team"
PARTICIPANT_NOTES_KEY = "draft_room_participant_notes"
MEMBERSHIP_KEY = "draft_room_participant_membership"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_participant_id(session: dict[str, Any]) -> str:
    """Stable participant key — auth user id when logged in, else workspace (dev)."""
    try:
        from suite_auth import AUTH_USER_ID_KEY, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(session):
            auth_id = str(session.get(AUTH_USER_ID_KEY) or "").strip()
            if auth_id:
                return auth_id
    except ImportError:
        pass
    explicit = str(session.get(ACTIVE_PARTICIPANT_ID_KEY) or "").strip()
    if explicit:
        return explicit
    try:
        from suite_workspace import resolve_workspace_id

        return f"workspace:{resolve_workspace_id(st=type('S', (), {'session_state': session})())}"
    except ImportError:
        pass
    try:
        from suite_user import get_external_user_id

        return f"user:{get_external_user_id()}"
    except ImportError:
        return "anonymous"


def _participant_bucket(session: dict[str, Any]) -> dict[str, Any]:
    root = session.setdefault(PARTICIPANT_STATE_KEY, {})
    if not isinstance(root, dict):
        root = {}
        session[PARTICIPANT_STATE_KEY] = root
    return root


def participant_state_for_room(session: dict[str, Any], room_code: str) -> dict[str, Any]:
    code = str(room_code or "").strip().upper()
    bucket = _participant_bucket(session)
    state = bucket.get(code)
    if not isinstance(state, dict):
        state = {}
        bucket[code] = state
    return state


def set_active_participant(
    session: dict[str, Any],
    *,
    room_code: str,
    participant_id: str,
    assigned_team: str,
) -> dict[str, Any]:
    """Record membership after create/join."""
    code = str(room_code or "").strip().upper()
    pid = str(participant_id or "").strip()
    team = str(assigned_team or "").strip()
    session[ACTIVE_PARTICIPANT_ID_KEY] = pid
    session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
    state = participant_state_for_room(session, code)
    state["participant_id"] = pid
    state["assigned_team"] = team
    state["joined_at"] = _utc_now_iso()
    membership = session.setdefault(MEMBERSHIP_KEY, {})
    if isinstance(membership, dict):
        membership[code] = {"participant_id": pid, "assigned_team": team}
    return state


def active_participant_team(session: dict[str, Any]) -> str:
    team = str(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or "").strip()
    if team:
        return team
    try:
        from global_fantasy_settings_state import GLOBAL_TEAM_KEY

        return str(session.get(GLOBAL_TEAM_KEY) or "").strip()
    except ImportError:
        return str(session.get("room_your_team") or "").strip()


def load_participant_workflow_into_session(session: dict[str, Any], room_code: str) -> dict[str, Any]:
    """Hydrate widget/canonical queue keys from participant-private storage."""
    state = participant_state_for_room(session, room_code)
    workflow = dict(state.get("workflow") or {})
    if workflow.get("queue") is not None:
        session[DRAFT_QUEUE_KEY] = copy.deepcopy(workflow.get("queue") or [])
    if workflow.get("watchlist_focus") is not None:
        session[DRAFT_WATCHLIST_FOCUS_KEY] = copy.deepcopy(workflow.get("watchlist_focus") or [])
    if workflow.get("watchlist_favorites") is not None:
        session[DRAFT_WATCHLIST_FAVORITES_KEY] = copy.deepcopy(workflow.get("watchlist_favorites") or [])
    notes = state.get("notes")
    if isinstance(notes, str):
        session[PARTICIPANT_NOTES_KEY] = notes
    return state


def save_participant_workflow_from_session(session: dict[str, Any], room_code: str) -> dict[str, Any]:
    """Persist queue/watchlist from session into participant-private storage."""
    prepare_draft_workflow(session)
    workflow = gather_draft_workflow(session)
    state = participant_state_for_room(session, room_code)
    state["workflow"] = {
        "queue": copy.deepcopy(workflow.get("queue") or []),
        "watchlist_focus": copy.deepcopy(workflow.get("watchlist_focus") or []),
        "watchlist_favorites": copy.deepcopy(workflow.get("watchlist_favorites") or []),
        "updated_at": _utc_now_iso(),
    }
    notes = session.get(PARTICIPANT_NOTES_KEY)
    if isinstance(notes, str):
        state["notes"] = notes
    return state


def assign_team_for_join(
    shared_document: dict[str, Any],
    *,
    requested_team: str | None = None,
) -> str | None:
    """Pick the next open fantasy team slot when a user joins."""
    room_blob = shared_document.get("room")
    if not isinstance(room_blob, dict):
        return None
    teams = [str(t).strip() for t in (room_blob.get("teams") or []) if str(t).strip()]
    if not teams:
        cfg = dict(room_blob.get("config") or {})
        n = int(cfg.get("num_teams") or 0)
        teams = [f"Team {i + 1}" for i in range(n)] if n else []
    membership = dict(shared_document.get("participants") or {})
    taken = {str(v.get("assigned_team") or "").strip() for v in membership.values() if isinstance(v, dict)}
    if requested_team:
        req = str(requested_team).strip()
        if req in teams and req not in taken:
            return req
    for team in teams:
        if team not in taken:
            return team
    return None


def register_participant_in_shared_document(
    shared_document: dict[str, Any],
    *,
    participant_id: str,
    assigned_team: str,
    display_name: str = "",
) -> dict[str, Any]:
    out = copy.deepcopy(shared_document)
    participants = dict(out.get("participants") or {})
    pid = str(participant_id)
    if pid in participants and isinstance(participants[pid], dict):
        entry = dict(participants[pid])
        if display_name:
            entry["display_name"] = str(display_name)
        entry.setdefault("assigned_team", str(assigned_team))
        entry.setdefault("joined_at", _utc_now_iso())
        participants[pid] = entry
    else:
        participants[pid] = {
            "assigned_team": str(assigned_team),
            "display_name": str(display_name or participant_id),
            "joined_at": _utc_now_iso(),
        }
    out["participants"] = participants
    out["revision"] = int(out.get("revision") or 0) + 1
    out["updated_at"] = _utc_now_iso()
    return out


def restore_persisted_shared_room_membership(session: dict[str, Any]) -> str:
    """Rehydrate active room code + team from persisted workspace blob after refresh."""
    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if code:
        _hydrate_team_from_membership(session, code)
        return code

    bucket = session.get(PARTICIPANT_STATE_KEY)
    if isinstance(bucket, dict):
        for raw_code, state in bucket.items():
            room_code = str(raw_code or "").strip().upper()
            if not room_code or not isinstance(state, dict):
                continue
            session[ACTIVE_SHARED_ROOM_CODE_KEY] = room_code
            pid = str(state.get("participant_id") or resolve_participant_id(session))
            team = str(state.get("assigned_team") or "").strip()
            if pid:
                session[ACTIVE_PARTICIPANT_ID_KEY] = pid
            if team:
                session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
            return room_code

    membership = session.get(MEMBERSHIP_KEY)
    if isinstance(membership, dict):
        for raw_code, meta in membership.items():
            room_code = str(raw_code or "").strip().upper()
            if not room_code or not isinstance(meta, dict):
                continue
            session[ACTIVE_SHARED_ROOM_CODE_KEY] = room_code
            if meta.get("participant_id"):
                session[ACTIVE_PARTICIPANT_ID_KEY] = str(meta["participant_id"])
            if meta.get("assigned_team"):
                session[ACTIVE_PARTICIPANT_TEAM_KEY] = str(meta["assigned_team"])
            return room_code
    return ""


def _hydrate_team_from_membership(session: dict[str, Any], room_code: str) -> None:
    code = str(room_code or "").strip().upper()
    membership = session.get(MEMBERSHIP_KEY)
    if isinstance(membership, dict):
        meta = membership.get(code)
        if isinstance(meta, dict) and meta.get("assigned_team"):
            session[ACTIVE_PARTICIPANT_TEAM_KEY] = str(meta["assigned_team"])
            return
    state = participant_state_for_room(session, code)
    if state.get("assigned_team"):
        session[ACTIVE_PARTICIPANT_TEAM_KEY] = str(state["assigned_team"])
