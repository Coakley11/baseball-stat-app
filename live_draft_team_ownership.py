"""Shared draft room — explicit team ownership and claim helpers."""

from __future__ import annotations

from typing import Any


def list_room_teams(room: dict[str, Any] | None) -> list[str]:
    if not isinstance(room, dict):
        return []
    teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
    if teams:
        return teams
    cfg = dict(room.get("config") or {})
    named = [str(t).strip() for t in (cfg.get("teams") or []) if str(t).strip()]
    if named:
        return named
    # Derive from pick order when persist stripped top-level teams.
    order_teams: list[str] = []
    seen: set[str] = set()
    for slot in room.get("pick_order") or []:
        if not isinstance(slot, dict):
            continue
        name = str(slot.get("Team") or "").strip()
        if name and name not in seen:
            seen.add(name)
            order_teams.append(name)
    if order_teams:
        return order_teams
    n = int(cfg.get("num_teams") or 0)
    return [f"Team {i + 1}" for i in range(n)] if n else []


def list_document_teams(document: dict[str, Any] | None, *, session_room: dict[str, Any] | None = None) -> list[str]:
    """Canonical team list for host lobby and guest join — same source of truth.

    Prefer shared ``document.room``; union session runtime teams so a thin/stale
    document cannot hide Team B while the host lobby still shows it.
    """
    doc_teams: list[str] = []
    if isinstance(document, dict):
        room_blob = document.get("room")
        if isinstance(room_blob, dict):
            doc_teams = list_room_teams(room_blob)
    session_teams = list_room_teams(session_room) if isinstance(session_room, dict) else []
    if not doc_teams:
        return session_teams
    if not session_teams:
        return doc_teams
    # Preserve document order; append any session-only teams.
    seen = {t.lower() for t in doc_teams}
    merged = list(doc_teams)
    for team in session_teams:
        if team.lower() not in seen:
            merged.append(team)
            seen.add(team.lower())
    return merged


def load_shared_room_document(session: dict[str, Any], *, room_code: str | None = None) -> dict[str, Any] | None:
    """Load shared room with the same global lookup + fallback guests use."""
    code = str(room_code or session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code:
        return None
    try:
        from draft_room_context import get_shared_room_store
        from draft_room_create_verify import load_shared_room_with_diagnostics

        result = load_shared_room_with_diagnostics(get_shared_room_store(), code)
        doc = result.get("document")
        return doc if isinstance(doc, dict) else None
    except ImportError:
        pass
    try:
        from draft_room_shared_state import load_shared_room

        doc = load_shared_room(code)
        return doc if isinstance(doc, dict) else None
    except ImportError:
        return None


def load_shared_participants(session: dict[str, Any], *, room_code: str | None = None) -> dict[str, dict[str, Any]]:
    doc = load_shared_room_document(session, room_code=room_code)
    if not isinstance(doc, dict):
        return {}
    raw = doc.get("participants") or {}
    if isinstance(raw, dict):
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    return {}


def _host_id_aliases(session: dict[str, Any], document: dict[str, Any] | None = None) -> set[str]:
    doc = document
    if doc is None:
        doc = load_shared_room_document(session)
    try:
        from draft_room_membership import document_host_ids

        return document_host_ids(doc)
    except ImportError:
        pass
    if isinstance(doc, dict):
        return {
            str(x).strip()
            for x in (doc.get("host_participant_id"), doc.get("host_user_id"))
            if str(x or "").strip()
        }
    return set()


def _host_participant_id(session: dict[str, Any], document: dict[str, Any] | None = None) -> str:
    aliases = _host_id_aliases(session, document)
    if not aliases:
        return ""
    # Prefer host_participant_id (map key) when present on the document.
    if isinstance(document, dict):
        primary = str(document.get("host_participant_id") or "").strip()
        if primary:
            return primary
    return next(iter(aliases))


def _participant_is_host(pid: str, host_aliases: set[str], meta: dict[str, Any] | None = None) -> bool:
    key = str(pid or "").strip()
    if key and key in host_aliases:
        return True
    if isinstance(meta, dict):
        for field in ("user_id", "account_user_id", "participant_id"):
            alias = str(meta.get(field) or "").strip()
            if alias and alias in host_aliases:
                return True
    return False


def _dedupe_participants_by_team(participants: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One claim per team — prefer earlier / host map keys when aliases collide."""
    by_team: dict[str, tuple[str, dict[str, Any]]] = {}
    for pid, meta in participants.items():
        if not isinstance(meta, dict):
            continue
        team = str(meta.get("assigned_team") or "").strip()
        if not team:
            continue
        prev = by_team.get(team)
        if prev is None:
            by_team[team] = (str(pid), meta)
            continue
        # Keep existing unless the new entry carries richer identity for same user.
        prev_meta = prev[1]
        prev_uids = {
            str(prev_meta.get("user_id") or "").strip(),
            str(prev_meta.get("account_user_id") or "").strip(),
            str(prev[0]).strip(),
        }
        new_uids = {
            str(meta.get("user_id") or "").strip(),
            str(meta.get("account_user_id") or "").strip(),
            str(pid).strip(),
        }
        if prev_uids & new_uids - {""}:
            # Same person double-registered — keep the first (usually create-time) key.
            continue
        # Distinct owners claiming same team — keep first for display; join gate blocks later.
        continue
    return {pid: meta for pid, meta in by_team.values()}


def team_claim_rows(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One row per fantasy team: team name, claim status, owner label, host flag."""
    doc = document
    if doc is None:
        doc = load_shared_room_document(session)
    teams = list_document_teams(doc, session_room=room if isinstance(room, dict) else None)
    participants = dict((doc or {}).get("participants") or {}) if isinstance(doc, dict) else {}
    if not participants:
        participants = load_shared_participants(session)
    participants = _dedupe_participants_by_team(participants)
    host_aliases = _host_id_aliases(session, doc)

    by_team: dict[str, dict[str, Any]] = {}
    for pid, meta in participants.items():
        if not isinstance(meta, dict):
            continue
        team = str(meta.get("assigned_team") or "").strip()
        if not team:
            continue
        display = str(meta.get("display_name") or "").strip() or "Guest"
        is_host = _participant_is_host(str(pid), host_aliases, meta)
        by_team[team] = {
            "team": team,
            "claimed": True,
            "owner_label": "Host" if is_host else display,
            "is_host": is_host,
            "participant_id": str(pid),
        }

    rows: list[dict[str, Any]] = []
    for team in teams:
        if team in by_team:
            rows.append(by_team[team])
        else:
            rows.append(
                {
                    "team": team,
                    "claimed": False,
                    "owner_label": "",
                    "is_host": False,
                    "participant_id": "",
                }
            )
    return rows


def _is_cpu_or_placeholder_team(name: str) -> bool:
    raw = str(name or "").strip().lower()
    if not raw:
        return True
    tokens = ("cpu", "bot", "ai team", "placeholder", "computer", "auto-draft")
    return any(tok in raw for tok in tokens) or raw.startswith("cpu ")


def open_teams_for_join(
    document: dict[str, Any],
) -> list[str]:
    """Human teams not yet claimed in a shared room document."""
    teams = list_document_teams(document)
    participants = _dedupe_participants_by_team(dict(document.get("participants") or {}))
    taken = {
        str(v.get("assigned_team") or "").strip()
        for v in participants.values()
        if isinstance(v, dict) and v.get("assigned_team")
    }
    return [t for t in teams if t not in taken and not _is_cpu_or_placeholder_team(t)]


def count_joined_teams(session: dict[str, Any], room: dict[str, Any]) -> tuple[int, int]:
    rows = team_claim_rows(session, room)
    total = len(rows)
    joined = sum(1 for r in rows if r.get("claimed"))
    return joined, total


def claimed_team_count(session: dict[str, Any], room: dict[str, Any]) -> int:
    joined, _total = count_joined_teams(session, room)
    return joined


def distinct_claimed_owner_count(session: dict[str, Any], room: dict[str, Any] | None = None) -> int:
    """Distinct participant IDs with a claimed team (Phase 1 anti-solo-both-teams gate)."""
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        return 0
    owners: set[str] = set()
    for row in team_claim_rows(session, live):
        if not row.get("claimed"):
            continue
        pid = str(row.get("participant_id") or "").strip()
        if pid:
            owners.add(pid)
    return len(owners)


def waiting_participant_count(session: dict[str, Any], room: dict[str, Any]) -> int:
    joined, total = count_joined_teams(session, room)
    return max(0, int(total) - int(joined))


def format_team_claim_status(session: dict[str, Any], row: dict[str, Any]) -> str:
    """User-facing team line using canonical participant identity."""
    team = str(row.get("team") or "").strip()
    if not row.get("claimed"):
        return f"{team} — open"
    try:
        from live_draft_ux import format_participant_identity
    except ImportError:
        format_participant_identity = None  # type: ignore[assignment,misc]
    try:
        from draft_room_participant_state import resolve_participant_id

        my_pid = str(resolve_participant_id(session) or "").strip()
        owner_pid = str(row.get("participant_id") or "").strip()
        if my_pid and owner_pid and my_pid == owner_pid:
            if format_participant_identity:
                return format_participant_identity("You", role="Guest" if not row.get("is_host") else "Commissioner", team=team)
            return f"{team} — claimed by you"
    except ImportError:
        pass
    owner = str(row.get("owner_label") or "Guest").strip()
    role = "Commissioner" if row.get("is_host") else "Guest"
    if format_participant_identity:
        return format_participant_identity(owner, role=role, team=team)
    if row.get("is_host"):
        return f"{team} — claimed by {owner} (commissioner)"
    return f"{team} — claimed by {owner}"


ROOM_NOT_FOUND_MSG = "Room code not found"


def format_team_ownership_line(row: dict[str, Any]) -> str:
    team = str(row.get("team") or "")
    if row.get("claimed"):
        owner = str(row.get("owner_label") or "Guest")
        if row.get("is_host"):
            return f"**{team}** (Host) · ✓ Claimed"
        return f"**{team}** · ✓ Claimed by {owner}"
    return f"**{team}** · Available"


def format_team_ownership_html(row: dict[str, Any]) -> str:
    team = str(row.get("team") or "")
    try:
        from live_draft_ux import format_participant_identity
    except ImportError:
        format_participant_identity = None  # type: ignore[assignment,misc]
    if row.get("claimed"):
        owner = str(row.get("owner_label") or "Guest")
        role = "Commissioner" if row.get("is_host") else "Guest"
        if format_participant_identity:
            return format_participant_identity(owner, role=role, team=team) + " · ✓ Claimed"
        if row.get("is_host"):
            return f"<strong>{team}</strong> (Host) · ✓ Claimed"
        return f"<strong>{team}</strong> · ✓ Claimed by {owner}"
    return f"<strong>{team}</strong> · Available"


def lookup_open_teams_for_code(room_code: str, *, store: Any = None) -> tuple[list[str], str]:
    """Read-only lookup of open teams for join UI. Returns (teams, error)."""
    code = str(room_code or "").strip().upper()
    if not code:
        return [], ""
    try:
        from draft_room_create_verify import is_plausible_share_code, load_shared_room_with_diagnostics

        if not is_plausible_share_code(code):
            return [], "Enter a valid 6-character room code."
    except ImportError:
        pass
    try:
        from draft_room_context import get_shared_room_store

        backend = store or get_shared_room_store()
        from draft_room_create_verify import load_shared_room_with_diagnostics

        load_result = load_shared_room_with_diagnostics(backend, code)
        document = load_result.get("document")
        if not isinstance(document, dict):
            reason = str(load_result.get("reason") or "not_found")
            if reason == "query_error":
                return [], str(load_result.get("query_error") or "Could not look up room.")
            return [], "Room code not found"
        status = str(document.get("status") or "").lower()
        if status in ("closed", "complete", "completed", "cancelled", "canceled", "expired"):
            return [], "Room is no longer joinable"
        teams = list_document_teams(document)
        if not teams:
            return [], "Room data could not be loaded — team list missing from shared room."
        open_teams = open_teams_for_join(document)
        if not open_teams:
            return [], "No teams are available"
        return open_teams, ""
    except ImportError:
        return [], "Join lookup is unavailable."
