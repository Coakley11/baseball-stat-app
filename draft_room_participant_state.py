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


def _is_legacy_room_membership(room_mem: dict[str, Any]) -> bool:
    return bool(room_mem.get("assigned_team")) and bool(room_mem.get("participant_id"))


def _normalize_room_membership(room_mem: Any) -> dict[str, dict[str, Any]]:
    """Normalize room membership to ``{participant_id: {assigned_team, participant_id}}``."""
    if not isinstance(room_mem, dict):
        return {}
    if _is_legacy_room_membership(room_mem):
        pid = str(room_mem.get("participant_id") or "").strip()
        if not pid:
            return {}
        return {
            pid: {
                "participant_id": pid,
                "assigned_team": str(room_mem.get("assigned_team") or "").strip(),
            }
        }
    out: dict[str, dict[str, Any]] = {}
    for key, meta in room_mem.items():
        if not isinstance(meta, dict):
            continue
        pid = str(meta.get("participant_id") or key or "").strip()
        team = str(meta.get("assigned_team") or "").strip()
        if pid and team:
            out[pid] = {"participant_id": pid, "assigned_team": team}
    return out


def membership_team_for_participant(
    session: dict[str, Any],
    room_code: str,
    *,
    participant_id: str | None = None,
) -> str:
    """Assigned team for ``(room_code, participant_id)`` from persisted membership blobs."""
    code = str(room_code or "").strip().upper()
    pid = str(participant_id or resolve_participant_id(session)).strip()
    if not code or not pid:
        return ""

    membership = session.get(MEMBERSHIP_KEY)
    if isinstance(membership, dict):
        room_mem = _normalize_room_membership(membership.get(code))
        entry = room_mem.get(pid)
        if isinstance(entry, dict) and entry.get("assigned_team"):
            return str(entry["assigned_team"]).strip()

    room_state = participant_state_for_room(session, code)
    by_pid = room_state.get("by_participant")
    if isinstance(by_pid, dict):
        slot = by_pid.get(pid)
        if isinstance(slot, dict) and slot.get("assigned_team"):
            return str(slot["assigned_team"]).strip()

    legacy_pid = str(room_state.get("participant_id") or "").strip()
    if legacy_pid == pid and room_state.get("assigned_team"):
        return str(room_state["assigned_team"]).strip()
    return ""


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


def participant_workflow_slot(session: dict[str, Any], room_code: str) -> dict[str, Any]:
    """Private queue/watchlist slot keyed by auth user / participant id within a room."""
    code = str(room_code or "").strip().upper()
    room_state = participant_state_for_room(session, code)
    pid = resolve_participant_id(session)
    by_pid = room_state.get("by_participant")
    if not isinstance(by_pid, dict):
        by_pid = {}
        room_state["by_participant"] = by_pid
    if pid not in by_pid:
        slot: dict[str, Any] = {"participant_id": pid}
        legacy_workflow = room_state.get("workflow")
        legacy_pid = str(room_state.get("participant_id") or "").strip()
        if isinstance(legacy_workflow, dict) and (not legacy_pid or legacy_pid == pid):
            slot["workflow"] = copy.deepcopy(legacy_workflow)
            if isinstance(room_state.get("notes"), str):
                slot["notes"] = room_state["notes"]
        by_pid[pid] = slot
    slot = by_pid[pid]
    if not isinstance(slot, dict):
        slot = {"participant_id": pid}
        by_pid[pid] = slot
    slot.setdefault("participant_id", pid)
    return slot


def _persist_room_membership(
    session: dict[str, Any],
    *,
    room_code: str,
    participant_id: str,
    assigned_team: str,
) -> None:
    code = str(room_code or "").strip().upper()
    pid = str(participant_id or "").strip()
    team = str(assigned_team or "").strip()
    if not code or not pid or not team:
        return

    membership = session.setdefault(MEMBERSHIP_KEY, {})
    if not isinstance(membership, dict):
        membership = {}
        session[MEMBERSHIP_KEY] = membership

    existing = membership.get(code)
    room_mem = _normalize_room_membership(existing)
    room_mem[pid] = {"participant_id": pid, "assigned_team": team}
    membership[code] = room_mem

    slot = participant_workflow_slot(session, code)
    slot["assigned_team"] = team

    state = participant_state_for_room(session, code)
    state["participant_id"] = pid
    state["assigned_team"] = team


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
    state["joined_at"] = _utc_now_iso()
    _persist_room_membership(session, room_code=code, participant_id=pid, assigned_team=team)
    return state


def active_participant_team(session: dict[str, Any]) -> str:
    team = str(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or "").strip()
    if team:
        return team

    try:
        from draft_room_context import is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
            if code:
                scoped = membership_team_for_participant(session, code)
                if scoped:
                    session[ACTIVE_PARTICIPANT_TEAM_KEY] = scoped
                    return scoped
            return ""
    except ImportError:
        pass

    try:
        from global_fantasy_settings_state import GLOBAL_TEAM_KEY

        return str(session.get(GLOBAL_TEAM_KEY) or "").strip()
    except ImportError:
        return str(session.get("room_your_team") or "").strip()


def load_participant_workflow_into_session(session: dict[str, Any], room_code: str) -> dict[str, Any]:
    """Hydrate widget/canonical queue keys from participant-private storage."""
    slot = participant_workflow_slot(session, room_code)
    workflow = dict(slot.get("workflow") or {})
    if workflow.get("queue") is not None:
        session[DRAFT_QUEUE_KEY] = copy.deepcopy(workflow.get("queue") or [])
    if workflow.get("watchlist_focus") is not None:
        session[DRAFT_WATCHLIST_FOCUS_KEY] = copy.deepcopy(workflow.get("watchlist_focus") or [])
    if workflow.get("watchlist_favorites") is not None:
        session[DRAFT_WATCHLIST_FAVORITES_KEY] = copy.deepcopy(workflow.get("watchlist_favorites") or [])
    notes = slot.get("notes")
    if isinstance(notes, str):
        session[PARTICIPANT_NOTES_KEY] = notes
    team = str(slot.get("assigned_team") or "").strip()
    if team:
        session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
    return participant_state_for_room(session, room_code)


def save_participant_workflow_from_session(session: dict[str, Any], room_code: str) -> dict[str, Any]:
    """Persist queue/watchlist from session into participant-private storage."""
    prepare_draft_workflow(session)
    workflow = gather_draft_workflow(session)
    slot = participant_workflow_slot(session, room_code)
    slot["workflow"] = {
        "queue": copy.deepcopy(workflow.get("queue") or []),
        "watchlist_focus": copy.deepcopy(workflow.get("watchlist_focus") or []),
        "watchlist_favorites": copy.deepcopy(workflow.get("watchlist_favorites") or []),
        "updated_at": _utc_now_iso(),
    }
    notes = session.get(PARTICIPANT_NOTES_KEY)
    if isinstance(notes, str):
        slot["notes"] = notes
    pid = resolve_participant_id(session)
    team = str(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or slot.get("assigned_team") or "").strip()
    if team:
        _persist_room_membership(session, room_code=room_code, participant_id=pid, assigned_team=team)
    return participant_state_for_room(session, room_code)


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
    pid = resolve_participant_id(session)
    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if code:
        _hydrate_team_from_membership(session, code, participant_id=pid)
        return code

    membership = session.get(MEMBERSHIP_KEY)
    if isinstance(membership, dict):
        for raw_code, room_mem in membership.items():
            room_code = str(raw_code or "").strip().upper()
            if not room_code:
                continue
            team = membership_team_for_participant(session, room_code, participant_id=pid)
            if team:
                session[ACTIVE_SHARED_ROOM_CODE_KEY] = room_code
                session[ACTIVE_PARTICIPANT_ID_KEY] = pid
                session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
                return room_code

    bucket = session.get(PARTICIPANT_STATE_KEY)
    if isinstance(bucket, dict):
        for raw_code, state in bucket.items():
            room_code = str(raw_code or "").strip().upper()
            if not room_code or not isinstance(state, dict):
                continue
            legacy_pid = str(state.get("participant_id") or "").strip()
            team = membership_team_for_participant(session, room_code, participant_id=pid)
            if not team and legacy_pid == pid:
                team = str(state.get("assigned_team") or "").strip()
            if team:
                session[ACTIVE_SHARED_ROOM_CODE_KEY] = room_code
                session[ACTIVE_PARTICIPANT_ID_KEY] = pid
                session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
                return room_code
    return ""


def _hydrate_team_from_membership(
    session: dict[str, Any],
    room_code: str,
    *,
    participant_id: str | None = None,
) -> None:
    pid = str(participant_id or resolve_participant_id(session)).strip()
    code = str(room_code or "").strip().upper()
    team = membership_team_for_participant(session, code, participant_id=pid)
    if team:
        session[ACTIVE_PARTICIPANT_ID_KEY] = pid
        session[ACTIVE_PARTICIPANT_TEAM_KEY] = team


def get_participant_membership_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Auth + membership snapshot for dev acceptance (per device)."""
    pid = resolve_participant_id(session)
    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    auth_email = ""
    auth_user_id = ""
    try:
        from suite_auth import AUTH_USER_ID_KEY, current_auth_email, is_authenticated

        if is_authenticated(session):
            auth_email = str(current_auth_email(session) or "")
            auth_user_id = str(session.get(AUTH_USER_ID_KEY) or "")
    except ImportError:
        pass

    membership = session.get(MEMBERSHIP_KEY)
    room_registry: dict[str, Any] = {}
    if code:
        try:
            from draft_room_shared_state import load_shared_room

            doc = load_shared_room(code)
            if isinstance(doc, dict):
                room_registry = dict(doc.get("participants") or {})
        except ImportError:
            pass

    persisted_blob: dict[str, Any] = {}
    if isinstance(membership, dict) and code:
        persisted_blob = _normalize_room_membership(membership.get(code))

    return {
        "auth_email": auth_email,
        "auth_user_id": auth_user_id,
        "participant_id": pid,
        "room_code": code or None,
        "assigned_team": active_participant_team(session) or None,
        "membership_team": membership_team_for_participant(session, code) if code else None,
        "room_participant_registry": room_registry,
        "persisted_membership_blob": persisted_blob,
    }
