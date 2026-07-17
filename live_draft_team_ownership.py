"""Shared draft room — explicit team ownership and claim helpers."""

from __future__ import annotations

from typing import Any


def list_room_teams(room: dict[str, Any]) -> list[str]:
    teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
    if teams:
        return teams
    cfg = dict(room.get("config") or {})
    named = [str(t).strip() for t in (cfg.get("teams") or []) if str(t).strip()]
    if named:
        return named
    n = int(cfg.get("num_teams") or 0)
    return [f"Team {i + 1}" for i in range(n)] if n else []


def load_shared_participants(session: dict[str, Any], *, room_code: str | None = None) -> dict[str, dict[str, Any]]:
    code = str(room_code or session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code:
        return {}
    try:
        from draft_room_shared_state import load_shared_room

        doc = load_shared_room(code)
        if isinstance(doc, dict):
            raw = doc.get("participants") or {}
            if isinstance(raw, dict):
                return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
    except ImportError:
        pass
    return {}


def _host_participant_id(session: dict[str, Any], document: dict[str, Any] | None = None) -> str:
    doc = document
    if doc is None:
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
        if code:
            try:
                from draft_room_shared_state import load_shared_room

                doc = load_shared_room(code)
            except ImportError:
                doc = None
    if isinstance(doc, dict):
        return str(doc.get("host_user_id") or doc.get("host_participant_id") or "").strip()
    return ""


def team_claim_rows(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One row per fantasy team: team name, claim status, owner label, host flag."""
    teams = list_room_teams(room)
    participants = dict((document or {}).get("participants") or {})
    if not participants:
        participants = load_shared_participants(session)
    host_pid = _host_participant_id(session, document)

    by_team: dict[str, dict[str, Any]] = {}
    for pid, meta in participants.items():
        if not isinstance(meta, dict):
            continue
        team = str(meta.get("assigned_team") or "").strip()
        if not team:
            continue
        display = str(meta.get("display_name") or "").strip() or "Guest"
        is_host = pid == host_pid
        by_team[team] = {
            "team": team,
            "claimed": True,
            "owner_label": "Host" if is_host else display,
            "is_host": is_host,
            "participant_id": pid,
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
    room_blob = document.get("room")
    teams: list[str] = []
    if isinstance(room_blob, dict):
        teams = list_room_teams(room_blob)
    participants = dict(document.get("participants") or {})
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
        open_teams = open_teams_for_join(document)
        if not open_teams:
            return [], "No teams are available"
        return open_teams, ""
    except ImportError:
        return [], "Join lookup is unavailable."
