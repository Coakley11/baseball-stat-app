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
SOLO_WORKFLOW_ROOM_KEY = "_solo"
AUTH_WORKFLOW_USER_KEY = "_draft_workflow_auth_user_id"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_participant_id(session: dict[str, Any]) -> str:
    """Stable participant key — auth user id when Real Accounts is on, else workspace (dev)."""
    try:
        from suite_auth import AUTH_USER_ID_KEY, is_auth_enabled

        if is_auth_enabled():
            auth_id = str(session.get(AUTH_USER_ID_KEY) or "").strip()
            if auth_id:
                stale = str(session.get(ACTIVE_PARTICIPANT_ID_KEY) or "").strip()
                if stale and stale != auth_id:
                    session.pop(ACTIVE_PARTICIPANT_ID_KEY, None)
                    session.pop(ACTIVE_PARTICIPANT_TEAM_KEY, None)
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
        if isinstance(legacy_workflow, dict) and legacy_pid == pid:
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


def _by_participant_slot(session: dict[str, Any], room_code: str, participant_id: str) -> dict[str, Any]:
    code = str(room_code or "").strip().upper()
    pid = str(participant_id or "").strip()
    room_state = participant_state_for_room(session, code)
    by_pid = room_state.get("by_participant")
    if not isinstance(by_pid, dict):
        by_pid = {}
        room_state["by_participant"] = by_pid
    if pid not in by_pid:
        by_pid[pid] = {"participant_id": pid}
    slot = by_pid[pid]
    if not isinstance(slot, dict):
        slot = {"participant_id": pid}
        by_pid[pid] = slot
    slot.setdefault("participant_id", pid)
    return slot


def _solo_slot_for_pid(session: dict[str, Any], participant_id: str) -> dict[str, Any]:
    pid = str(participant_id or "").strip()
    bucket = _participant_bucket(session)
    solo = bucket.get(SOLO_WORKFLOW_ROOM_KEY)
    if not isinstance(solo, dict):
        solo = {}
        bucket[SOLO_WORKFLOW_ROOM_KEY] = solo
    by_pid = solo.get("by_participant")
    if not isinstance(by_pid, dict):
        by_pid = {}
        solo["by_participant"] = by_pid
    if pid not in by_pid:
        by_pid[pid] = {"participant_id": pid}
    slot = by_pid[pid]
    if not isinstance(slot, dict):
        slot = {"participant_id": pid}
        by_pid[pid] = slot
    slot.setdefault("participant_id", pid)
    return slot


def _workflow_payload_from_dict(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue": copy.deepcopy(workflow.get("queue") or []),
        "watchlist_focus": copy.deepcopy(workflow.get("watchlist_focus") or []),
        "watchlist_favorites": copy.deepcopy(workflow.get("watchlist_favorites") or []),
        "updated_at": _utc_now_iso(),
    }


def save_workflow_for_participant_id(
    session: dict[str, Any],
    participant_id: str,
    workflow: dict[str, Any],
    *,
    room_code: str | None = None,
) -> None:
    """Persist queue/watchlist for one auth user — room slot when in multiplayer, always solo mirror."""
    pid = str(participant_id or "").strip()
    if not pid:
        return
    payload = _workflow_payload_from_dict(workflow)
    code = str(
        room_code
        or session.get(ACTIVE_SHARED_ROOM_CODE_KEY)
        or ""
    ).strip().upper()
    if code:
        slot = _by_participant_slot(session, code, pid)
        slot["workflow"] = copy.deepcopy(payload)
    solo = _solo_slot_for_pid(session, pid)
    solo["workflow"] = copy.deepcopy(payload)


def load_workflow_for_participant_id(
    session: dict[str, Any],
    participant_id: str,
    *,
    room_code: str | None = None,
) -> dict[str, list[str]]:
    """Load saved queue/watchlist for one auth user."""
    empty: dict[str, list[str]] = {
        "queue": [],
        "watchlist_focus": [],
        "watchlist_favorites": [],
    }
    pid = str(participant_id or "").strip()
    if not pid:
        return empty
    code = str(
        room_code
        or session.get(ACTIVE_SHARED_ROOM_CODE_KEY)
        or ""
    ).strip().upper()
    if code:
        slot = _by_participant_slot(session, code, pid)
        wf = slot.get("workflow")
        if isinstance(wf, dict) and any(wf.get(k) for k in ("queue", "watchlist_focus", "watchlist_favorites")):
            return {
                "queue": list(wf.get("queue") or []),
                "watchlist_focus": list(wf.get("watchlist_focus") or []),
                "watchlist_favorites": list(wf.get("watchlist_favorites") or []),
            }
    solo = _solo_slot_for_pid(session, pid)
    wf = solo.get("workflow")
    if isinstance(wf, dict):
        return {
            "queue": list(wf.get("queue") or []),
            "watchlist_focus": list(wf.get("watchlist_focus") or []),
            "watchlist_favorites": list(wf.get("watchlist_favorites") or []),
        }
    return empty


def _clear_session_draft_workflow_widgets(session: dict[str, Any]) -> None:
    try:
        from draft_state import write_canonical_draft_state

        write_canonical_draft_state(
            session,
            queue=[],
            watchlist_focus=[],
            watchlist_favorites=[],
            reason="auth_user_switch",
            local_edit=False,
            sync_widget_keys=True,
            sync_participant=False,
        )
    except ImportError:
        session[DRAFT_QUEUE_KEY] = []
        session[DRAFT_WATCHLIST_FOCUS_KEY] = []
        session[DRAFT_WATCHLIST_FAVORITES_KEY] = []


def apply_workflow_to_session(session: dict[str, Any], workflow: dict[str, Any]) -> None:
    try:
        from draft_state import write_canonical_draft_state

        write_canonical_draft_state(
            session,
            queue=list(workflow.get("queue") or []),
            watchlist_focus=list(workflow.get("watchlist_focus") or []),
            watchlist_favorites=list(workflow.get("watchlist_favorites") or []),
            reason="auth_user_restore",
            local_edit=False,
            sync_widget_keys=True,
            sync_participant=False,
        )
    except ImportError:
        session[DRAFT_QUEUE_KEY] = list(workflow.get("queue") or [])
        session[DRAFT_WATCHLIST_FOCUS_KEY] = list(workflow.get("watchlist_focus") or [])
        session[DRAFT_WATCHLIST_FAVORITES_KEY] = list(workflow.get("watchlist_favorites") or [])


def on_auth_user_switch(
    session: dict[str, Any],
    *,
    from_user_id: str,
    to_user_id: str,
) -> None:
    """Save outgoing account queue, clear session widgets, load incoming account queue."""
    old_id = str(from_user_id or "").strip()
    new_id = str(to_user_id or "").strip()
    if old_id and new_id and old_id != new_id:
        from draft_state import gather_draft_workflow

        save_workflow_for_participant_id(session, old_id, gather_draft_workflow(session))
    if old_id == new_id and new_id:
        session[AUTH_WORKFLOW_USER_KEY] = new_id
        return
    session[AUTH_WORKFLOW_USER_KEY] = new_id
    _clear_session_draft_workflow_widgets(session)
    if new_id:
        apply_workflow_to_session(session, load_workflow_for_participant_id(session, new_id))
        try:
            from draft_room_context import is_multiplayer_draft_active

            if is_multiplayer_draft_active(session):
                code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
                if code:
                    load_participant_workflow_into_session(session, code)
        except ImportError:
            pass


def on_auth_logout_save_workflow(session: dict[str, Any]) -> None:
    """Persist queue for the signing-out account and clear session widgets."""
    pid = str(session.get(AUTH_WORKFLOW_USER_KEY) or resolve_participant_id(session)).strip()
    if pid:
        from draft_state import gather_draft_workflow

        save_workflow_for_participant_id(session, pid, gather_draft_workflow(session))
    session.pop(AUTH_WORKFLOW_USER_KEY, None)
    _clear_session_draft_workflow_widgets(session)


def reconcile_auth_scoped_draft_workflow(session: dict[str, Any]) -> bool:
    """Safety net when auth participant id changes without an explicit login hook."""
    current = str(resolve_participant_id(session) or "").strip()
    tracked = str(session.get(AUTH_WORKFLOW_USER_KEY) or "").strip()
    if not current:
        session.pop(AUTH_WORKFLOW_USER_KEY, None)
        return False
    if tracked == current:
        return False
    on_auth_user_switch(session, from_user_id=tracked, to_user_id=current)
    return True


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

    # Room-level legacy fields are host-only; per-participant data lives in by_participant.


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
    clear_participant_left_room(session, code)
    _persist_room_membership(session, room_code=code, participant_id=pid, assigned_team=team)
    return state


def active_participant_team(session: dict[str, Any]) -> str:
    pid = resolve_participant_id(session)
    try:
        from draft_room_context import is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
            if code:
                scoped = membership_team_for_participant(session, code, participant_id=pid)
                if scoped:
                    session[ACTIVE_PARTICIPANT_ID_KEY] = pid
                    session[ACTIVE_PARTICIPANT_TEAM_KEY] = scoped
                    return scoped
                try:
                    from draft_room_shared_state import load_shared_room

                    doc = load_shared_room(code)
                    participants = dict((doc or {}).get("participants") or {})
                    meta = participants.get(pid)
                    if isinstance(meta, dict) and meta.get("assigned_team"):
                        team = str(meta["assigned_team"]).strip()
                        session[ACTIVE_PARTICIPANT_ID_KEY] = pid
                        session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
                        _persist_room_membership(
                            session,
                            room_code=code,
                            participant_id=pid,
                            assigned_team=team,
                        )
                        return team
                except ImportError:
                    pass
            team, fail = ensure_participant_team_assigned(session, room_code=code)
            if fail:
                session[ASSIGNMENT_FAILURE_KEY] = fail
            if team:
                return team
            return ""
    except ImportError:
        pass

    team = str(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or "").strip()
    if team:
        stored_pid = str(session.get(ACTIVE_PARTICIPANT_ID_KEY) or "").strip()
        if not stored_pid or stored_pid != pid:
            return ""
        return team

    try:
        from draft_room_context import is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            return ""
    except ImportError:
        pass

    try:
        from global_fantasy_settings_state import GLOBAL_TEAM_KEY

        return str(session.get(GLOBAL_TEAM_KEY) or "").strip()
    except ImportError:
        return ""


def load_participant_workflow_into_session(session: dict[str, Any], room_code: str) -> dict[str, Any]:
    """Hydrate widget/canonical queue keys from participant-private storage."""
    slot = participant_workflow_slot(session, room_code)
    workflow = dict(slot.get("workflow") or {})
    # Always scope session widgets to this participant — never leave a prior user's queue visible.
    session[DRAFT_QUEUE_KEY] = copy.deepcopy(workflow.get("queue") or [])
    session[DRAFT_WATCHLIST_FOCUS_KEY] = copy.deepcopy(workflow.get("watchlist_focus") or [])
    session[DRAFT_WATCHLIST_FAVORITES_KEY] = copy.deepcopy(workflow.get("watchlist_favorites") or [])
    notes = slot.get("notes")
    if isinstance(notes, str):
        session[PARTICIPANT_NOTES_KEY] = notes
    else:
        session.pop(PARTICIPANT_NOTES_KEY, None)
    pid = resolve_participant_id(session)
    team = membership_team_for_participant(session, room_code, participant_id=pid)
    if not team:
        team = str(slot.get("assigned_team") or "").strip()
    if team:
        session[ACTIVE_PARTICIPANT_ID_KEY] = pid
        session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
    return participant_state_for_room(session, room_code)


def save_participant_workflow_from_session(session: dict[str, Any], room_code: str) -> dict[str, Any]:
    """Persist queue/watchlist from session into participant-private storage."""
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
    if pid:
        solo = _solo_slot_for_pid(session, pid)
        solo["workflow"] = copy.deepcopy(slot["workflow"])
        session[AUTH_WORKFLOW_USER_KEY] = pid
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


JOIN_ASSIGNMENT_DIAG_KEY = "_draft_room_join_assignment_diag"
ASSIGNMENT_FAILURE_KEY = "_draft_room_assignment_failure_reason"


def ensure_participant_team_assigned(
    session: dict[str, Any],
    *,
    room_code: str | None = None,
    document: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Reconcile assigned team from local membership or shared participant registry."""
    code = str(room_code or session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    if not code:
        return "", "no_room_code"
    pid = resolve_participant_id(session)
    if not pid:
        return "", "no_participant_id"

    team = membership_team_for_participant(session, code, participant_id=pid)
    if team:
        set_active_participant(session, room_code=code, participant_id=pid, assigned_team=team)
        return team, ""

    slot = participant_workflow_slot(session, code)
    slot_team = str(slot.get("assigned_team") or "").strip()
    if slot_team:
        set_active_participant(session, room_code=code, participant_id=pid, assigned_team=slot_team)
        return slot_team, ""

    doc = document
    if doc is None:
        try:
            from draft_room_shared_state import load_shared_room

            doc = load_shared_room(code)
        except ImportError:
            doc = None

    if not isinstance(doc, dict):
        return "", "registry_load_failed"

    participants = dict(doc.get("participants") or {})
    if pid not in participants:
        return "", "participant_not_in_registry"

    meta = participants.get(pid)
    if not isinstance(meta, dict) or not meta.get("assigned_team"):
        return "", "registry_missing_assigned_team"

    team = str(meta["assigned_team"]).strip()
    set_active_participant(session, room_code=code, participant_id=pid, assigned_team=team)
    save_participant_workflow_from_session(session, code)
    return team, ""


def build_participant_assignment_diagnostics(
    session: dict[str, Any],
    *,
    failure_reason: str = "",
    source: str = "",
) -> dict[str, Any]:
    """Snapshot for join/restore team assignment acceptance."""
    pid = resolve_participant_id(session)
    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    auth_user_id = ""
    try:
        from suite_auth import AUTH_USER_ID_KEY, is_authenticated

        if is_authenticated(session):
            auth_user_id = str(session.get(AUTH_USER_ID_KEY) or "").strip()
    except ImportError:
        pass

    membership_blob_team = membership_team_for_participant(session, code, participant_id=pid) if code else ""
    registry_team = ""
    registry_found = False
    if code and pid:
        try:
            from draft_room_shared_state import load_shared_room

            doc = load_shared_room(code)
            if isinstance(doc, dict):
                participants = dict(doc.get("participants") or {})
                if pid in participants:
                    registry_found = True
                    meta = participants.get(pid)
                    if isinstance(meta, dict):
                        registry_team = str(meta.get("assigned_team") or "").strip()
        except ImportError:
            pass

    displayed_team = ""
    displayed_source = ""
    try:
        from draft_room_runtime_diagnostics import resolve_displayed_team_label

        displayed_team, displayed_source = resolve_displayed_team_label(session)
    except ImportError:
        displayed_team = active_participant_team(session)
        displayed_source = "active_participant_team" if displayed_team else "none"

    session_team = str(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or "").strip()
    reason = str(failure_reason or session.get(ASSIGNMENT_FAILURE_KEY) or "").strip()
    if not reason and code and not session_team and not registry_team and not membership_blob_team:
        reason = "team_unassigned"

    return {
        "room_code": code or None,
        "auth_user_id": auth_user_id or None,
        "participant_id": pid or None,
        "participant_registry_found": registry_found,
        "registry_assigned_team": registry_team or None,
        "membership_assigned_team": membership_blob_team or None,
        "displayed_team": displayed_team or None,
        "displayed_team_source": displayed_source or None,
        "assignment_failure_reason": reason or None,
        "assignment_source": source or None,
    }


def record_join_assignment_diagnostics(
    session: dict[str, Any],
    *,
    source: str = "join",
    failure_reason: str = "",
) -> dict[str, Any]:
    diag = build_participant_assignment_diagnostics(session, failure_reason=failure_reason, source=source)
    session[JOIN_ASSIGNMENT_DIAG_KEY] = diag
    if failure_reason:
        session[ASSIGNMENT_FAILURE_KEY] = failure_reason
    else:
        session.pop(ASSIGNMENT_FAILURE_KEY, None)
    return diag


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
        team_val = str(assigned_team or "").strip()
        if team_val:
            entry["assigned_team"] = team_val
        else:
            entry.setdefault("assigned_team", "")
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


def participant_has_left_room(session: dict[str, Any], room_code: str) -> bool:
    code = str(room_code or "").strip().upper()
    if not code:
        return False
    room_state = participant_state_for_room(session, code)
    by_pid = room_state.get("by_participant")
    if isinstance(by_pid, dict):
        pid = str(resolve_participant_id(session)).strip()
        slot = by_pid.get(pid)
        if isinstance(slot, dict) and str(slot.get("left_at") or "").strip():
            return True
        for slot in by_pid.values():
            if isinstance(slot, dict) and str(slot.get("left_at") or "").strip():
                return True
    return False


def mark_participant_left_room(
    session: dict[str, Any],
    room_code: str,
    *,
    participant_id: str | None = None,
) -> None:
    code = str(room_code or "").strip().upper()
    if not code:
        return
    pid = str(participant_id or session.get(ACTIVE_PARTICIPANT_ID_KEY) or resolve_participant_id(session)).strip()
    room_state = participant_state_for_room(session, code)
    by_pid = room_state.get("by_participant")
    if not isinstance(by_pid, dict):
        by_pid = {}
        room_state["by_participant"] = by_pid
    slot = by_pid.get(pid)
    if not isinstance(slot, dict):
        slot = {"participant_id": pid}
        by_pid[pid] = slot
    slot["left_at"] = _utc_now_iso()
    slot.pop("joined_at", None)


def clear_participant_left_room(session: dict[str, Any], room_code: str) -> None:
    code = str(room_code or "").strip().upper()
    if not code:
        return
    slot = participant_workflow_slot(session, code)
    slot.pop("left_at", None)
    slot["joined_at"] = _utc_now_iso()


def restore_persisted_shared_room_membership(session: dict[str, Any]) -> str:
    """Rehydrate active room code + team from persisted workspace blob after refresh."""
    try:
        from draft_room_create_verify import is_plausible_share_code
    except ImportError:
        is_plausible_share_code = None  # type: ignore[assignment,misc]

    def _valid_code(raw: str) -> str:
        code = str(raw or "").strip().upper()
        if not code:
            return ""
        if is_plausible_share_code is not None and not is_plausible_share_code(code):
            return ""
        return code

    pid = resolve_participant_id(session)
    code = _valid_code(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "")
    if code:
        if participant_has_left_room(session, code):
            session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
            code = ""
        else:
            _hydrate_team_from_membership(session, code, participant_id=pid)
            if not str(session.get(ACTIVE_PARTICIPANT_TEAM_KEY) or "").strip():
                team, _fail = ensure_participant_team_assigned(session, room_code=code)
                if team:
                    session[ACTIVE_PARTICIPANT_ID_KEY] = pid
                    session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
            return code

    membership = session.get(MEMBERSHIP_KEY)
    if isinstance(membership, dict):
        for raw_code, room_mem in membership.items():
            room_code = _valid_code(raw_code)
            if not room_code or participant_has_left_room(session, room_code):
                continue
            team = membership_team_for_participant(session, room_code, participant_id=pid)
            if team:
                session[ACTIVE_SHARED_ROOM_CODE_KEY] = room_code
                session[ACTIVE_PARTICIPANT_ID_KEY] = pid
                session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
                try:
                    from draft_room_runtime_diagnostics import note_prepare_global_rehydrate

                    note_prepare_global_rehydrate(session, room_code=room_code, source="membership_blob")
                except ImportError:
                    pass
                return room_code

    bucket = session.get(PARTICIPANT_STATE_KEY)
    if isinstance(bucket, dict):
        for raw_code, state in bucket.items():
            room_code = _valid_code(raw_code)
            if not room_code or not isinstance(state, dict) or participant_has_left_room(session, room_code):
                continue
            legacy_pid = str(state.get("participant_id") or "").strip()
            team = membership_team_for_participant(session, room_code, participant_id=pid)
            if not team and legacy_pid == pid:
                team = str(state.get("assigned_team") or "").strip()
            if team:
                session[ACTIVE_SHARED_ROOM_CODE_KEY] = room_code
                session[ACTIVE_PARTICIPANT_ID_KEY] = pid
                session[ACTIVE_PARTICIPANT_TEAM_KEY] = team
                try:
                    from draft_room_runtime_diagnostics import note_prepare_global_rehydrate

                    note_prepare_global_rehydrate(session, room_code=room_code, source="participant_state_blob")
                except ImportError:
                    pass
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


def clear_multiplayer_membership_for_account(session: dict[str, Any]) -> str:
    """Dev helper — clear stale multiplayer membership/team globals for the current auth user."""
    pid = resolve_participant_id(session)
    code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    session.pop(ACTIVE_PARTICIPANT_TEAM_KEY, None)
    session.pop(ACTIVE_PARTICIPANT_ID_KEY, None)
    session.pop("room_your_team", None)
    session.pop(PARTICIPANT_NOTES_KEY, None)
    session[DRAFT_QUEUE_KEY] = []
    session[DRAFT_WATCHLIST_FOCUS_KEY] = []
    session[DRAFT_WATCHLIST_FAVORITES_KEY] = []
    if code:
        membership = session.get(MEMBERSHIP_KEY)
        if isinstance(membership, dict) and isinstance(membership.get(code), dict):
            room_mem = _normalize_room_membership(membership.get(code))
            room_mem.pop(pid, None)
            if room_mem:
                membership[code] = room_mem
            else:
                membership.pop(code, None)
        room_state = participant_state_for_room(session, code)
        by_pid = room_state.get("by_participant")
        if isinstance(by_pid, dict):
            by_pid.pop(pid, None)
        if str(room_state.get("participant_id") or "") == pid:
            room_state.pop("participant_id", None)
            room_state.pop("assigned_team", None)
    return pid


def get_participant_membership_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Auth + membership snapshot for dev acceptance (per device)."""
    assignment = build_participant_assignment_diagnostics(session)
    pid = str(assignment.get("participant_id") or resolve_participant_id(session))
    code = str(assignment.get("room_code") or session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    auth_email = ""
    try:
        from suite_auth import current_auth_email, is_authenticated

        if is_authenticated(session):
            auth_email = str(current_auth_email(session) or "")
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
        "auth_user_id": assignment.get("auth_user_id"),
        "participant_id": pid or None,
        "room_code": code or None,
        "assigned_team": active_participant_team(session) or None,
        "registry_assigned_team": assignment.get("registry_assigned_team"),
        "membership_team": assignment.get("membership_assigned_team"),
        "membership_blob_team": assignment.get("membership_assigned_team"),
        "membership_assigned_team": assignment.get("membership_assigned_team"),
        "participant_registry_found": assignment.get("participant_registry_found"),
        "displayed_team": assignment.get("displayed_team"),
        "displayed_team_source": assignment.get("displayed_team_source"),
        "assignment_failure_reason": assignment.get("assignment_failure_reason"),
        "active_queue_key": "draft_queue",
        "active_watchlist_focus_key": "draft_assistant_focus_players",
        "active_watchlist_favorites_key": "workflow_favorite_targets",
        "room_participant_registry": room_registry,
        "persisted_membership_blob": persisted_blob,
    }
