"""Authoritative roster transfer from completed Live Draft boards."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

COMPLETION_ROSTER_MISMATCH = "roster_transfer_mismatch"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _player_name(row: dict[str, Any]) -> str:
    for key in ("player_name", "fullName", "Player", "name", "player"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return ""


def _player_id(row: dict[str, Any]) -> str:
    for key in ("player_id", "playerID", "playerId", "mlbam_id", "ID"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return ""


def _position(row: dict[str, Any]) -> str:
    for key in ("position", "Primary Position", "Pos"):
        val = row.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _team_name(row: dict[str, Any]) -> str:
    for key in ("team", "Team", "Fantasy Team"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return ""


def get_roster_transfer_diagnostics(room: dict[str, Any]) -> dict[str, Any]:
    try:
        from live_draft_team_identity import build_board_team_resolution

        return build_board_team_resolution(room)
    except ImportError:
        teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
        return {
            "room_teams": teams,
            "room_roster_keys": sorted(str(k) for k in dict(room.get("rosters") or {}).keys()),
            "draft_board_row_count": len(room.get("draft_board") or []),
            "draft_board_distinct_team_values": [],
            "draft_results_count": 0,
            "draft_results_distinct_team_values": [],
            "configured_team_names": teams,
            "team_rename_map": {},
            "resolved_board_team_map": {},
            "unmapped_board_teams": [],
            "ambiguous_board_teams": [],
        }


def extract_draft_results_from_room(room: dict[str, Any]) -> list[dict[str, Any]]:
    """Build pick records from the live draft board with canonical team resolution."""
    try:
        from live_draft_team_identity import (
            build_board_team_resolution,
            build_team_rename_map,
            list_room_display_teams,
            resolve_board_team_label,
            _roster_player_indexes,
        )
    except ImportError:
        return _extract_draft_results_legacy(room)

    teams = list_room_display_teams(room)
    resolution = build_board_team_resolution(room)
    rename_map, _unmapped, ambiguous = build_team_rename_map(room)
    roster_by_id, roster_by_name = _roster_player_indexes(room)
    results: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for row in room.get("draft_board") or []:
        if not isinstance(row, dict):
            continue
        player_name = _player_name(row)
        if not player_name:
            continue
        resolved, raw, team_id, source = resolve_board_team_label(
            room,
            row,
            rename_map=rename_map,
            roster_by_id=roster_by_id,
            roster_by_name=roster_by_name,
            teams=teams,
        )
        if not resolved:
            pick_no = row.get("pick") or row.get("Pick") or "?"
            unresolved.append(
                f"Pick {pick_no} ({player_name!r}) uses unresolved team label {raw!r}."
            )
            continue
        pick_number = int(row.get("pick") or row.get("Pick") or len(results) + 1)
        round_number = int(row.get("round") or row.get("Round") or 1)
        source_row = dict(row)
        source_row["Team"] = resolved
        source_row["Fantasy Team"] = resolved
        if team_id:
            source_row["team_id"] = team_id
        results.append(
            {
                "pick_number": pick_number,
                "round": round_number,
                "team": resolved,
                "team_id": team_id,
                "raw_team": raw,
                "team_resolution_source": source,
                "player_id": _player_id(row),
                "player_name": player_name,
                "position": _position(row),
                "drafted_at": str(row.get("drafted_at") or row.get("timestamp") or "").strip() or None,
                "source_row": source_row,
            }
        )

    if ambiguous:
        room["_live_draft_roster_transfer_errors"] = [
            f"Ambiguous team label mapping for {label!r}." for label in ambiguous
        ] + unresolved
    elif unresolved:
        room["_live_draft_roster_transfer_errors"] = unresolved
    else:
        room.pop("_live_draft_roster_transfer_errors", None)

    room["_live_draft_roster_transfer_diag"] = resolution
    results.sort(key=lambda r: (int(r.get("pick_number") or 0), str(r.get("team") or "")))
    return results


def _extract_draft_results_legacy(room: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in room.get("draft_board") or []:
        if not isinstance(row, dict):
            continue
        team = _team_name(row)
        player_name = _player_name(row)
        if not team or not player_name:
            continue
        pick_number = int(row.get("pick") or row.get("Pick") or len(results) + 1)
        round_number = int(row.get("round") or row.get("Round") or 1)
        results.append(
            {
                "pick_number": pick_number,
                "round": round_number,
                "team": team,
                "raw_team": team,
                "player_id": _player_id(row),
                "player_name": player_name,
                "position": _position(row),
                "drafted_at": str(row.get("drafted_at") or row.get("timestamp") or "").strip() or None,
                "source_row": dict(row),
            }
        )
    results.sort(key=lambda r: (int(r.get("pick_number") or 0), str(r.get("team") or "")))
    return results


def build_league_rosters_from_draft_results(
    draft_results: list[dict[str, Any]],
    *,
    my_team_name: str,
    teams: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Derive final team rosters directly from draft results."""
    try:
        from fantasy_league_context import _normalize_player_entry, _team_roster_entry
    except ImportError:
        raise

    ordered_teams = [str(t).strip() for t in (teams or []) if str(t).strip()]
    my_team = str(my_team_name or "").strip()
    by_team: dict[str, list[dict[str, Any]]] = {team: [] for team in ordered_teams}
    for result in draft_results:
        team = str(result.get("team") or "").strip()
        if not team:
            continue
        by_team.setdefault(team, [])
        source = dict(result.get("source_row") or {})
        source.setdefault("fullName", result.get("player_name"))
        source.setdefault("playerID", result.get("player_id"))
        source.setdefault("Primary Position", result.get("position"))
        source.setdefault("Pick", result.get("pick_number"))
        source.setdefault("Round", result.get("round"))
        source.setdefault("Team", team)
        if result.get("team_id"):
            source.setdefault("team_id", result.get("team_id"))
        by_team[team].append(source)

    league_rosters: dict[str, dict[str, Any]] = {}
    for team, rows in by_team.items():
        players = [_normalize_player_entry(row, team_name=team) for row in rows if _player_name(row)]
        league_rosters[team] = _team_roster_entry(team, players, is_user_team=(team == my_team))
    return league_rosters


def validate_roster_transfer(
    room: dict[str, Any],
    draft_results: list[dict[str, Any]],
    league_rosters: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Validate draft board → league_rosters consistency."""
    errors: list[str] = []
    transfer_errors = room.get("_live_draft_roster_transfer_errors")
    if isinstance(transfer_errors, list):
        errors.extend(str(e) for e in transfer_errors if str(e).strip())

    if not draft_results:
        errors.append("No draft results found on the final board.")
        return False, errors

    teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
    result_teams = {str(r.get("team") or "").strip() for r in draft_results if str(r.get("team") or "").strip()}
    missing_team_labels = sorted(set(teams) - result_teams)
    extra_team_labels = sorted(result_teams - set(teams))
    if missing_team_labels:
        errors.append(
            "Draft results missing current room teams: " + ", ".join(missing_team_labels) + "."
        )
    if extra_team_labels:
        errors.append(
            "Draft results include teams not in the room: " + ", ".join(extra_team_labels) + "."
        )

    player_to_team: dict[str, str] = {}
    player_id_to_team: dict[str, str] = {}
    for result in draft_results:
        team = str(result.get("team") or "").strip()
        name = str(result.get("player_name") or "").strip()
        player_id = str(result.get("player_id") or "").strip()
        if not team:
            errors.append(f"Pick {result.get('pick_number')} is missing a drafting team.")
            continue
        if not name:
            errors.append(f"Pick {result.get('pick_number')} is missing a player name.")
            continue
        if name in player_to_team and player_to_team[name] != team:
            errors.append(f"Player {name!r} appears on multiple teams in draft results.")
        player_to_team[name] = team
        if player_id:
            if player_id in player_id_to_team and player_id_to_team[player_id] != team:
                errors.append(f"Player id {player_id!r} appears on multiple teams in draft results.")
            player_id_to_team[player_id] = team

    roster_names: dict[str, set[str]] = {}
    roster_count = 0
    for team_name, entry in (league_rosters or {}).items():
        team = str(team_name or "").strip()
        if not team:
            continue
        players = list((entry or {}).get("players") or [])
        names = {str(p.get("player_name") or "").strip() for p in players if str(p.get("player_name") or "").strip()}
        roster_names[team] = names
        roster_count += len(names)

    if roster_count != len(draft_results):
        errors.append(
            f"Roster player count ({roster_count}) does not equal completed picks ({len(draft_results)})."
        )

    for team in teams:
        expected = {r["player_name"] for r in draft_results if r.get("team") == team}
        actual = roster_names.get(team, set())
        if expected != actual:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            if missing:
                errors.append(f"Team {team!r} is missing drafted players: {', '.join(missing)}.")
            if extra:
                errors.append(f"Team {team!r} has extra players not from the draft board: {', '.join(extra)}.")

    room_rosters = room.get("rosters") or {}
    if isinstance(room_rosters, dict):
        for team, rows in room_rosters.items():
            team_name = str(team or "").strip()
            if not team_name:
                continue
            expected = roster_names.get(team_name, set())
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                name = _player_name(row)
                if name and name not in expected:
                    errors.append(
                        f"Room roster for {team_name!r} contains {name!r}, which is not in draft results."
                    )

    diag = room.get("_live_draft_roster_transfer_diag")
    if isinstance(diag, dict):
        for note in diag.get("resolution_notes") or []:
            if note and note not in errors:
                pass  # informational only; keep in diagnostics

    return not errors, errors


def build_authoritative_live_draft_rosters(
    room: dict[str, Any],
    *,
    my_team_name: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    """Extract draft results and validated league rosters from the live board."""
    try:
        from live_draft_team_identity import list_room_display_teams

        teams = list_room_display_teams(room)
    except ImportError:
        teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
    draft_results = extract_draft_results_from_room(room)
    league_rosters = build_league_rosters_from_draft_results(
        draft_results,
        my_team_name=my_team_name,
        teams=teams,
    )
    ok, errors = validate_roster_transfer(room, draft_results, league_rosters)
    if not ok:
        return draft_results, league_rosters, errors
    return draft_results, league_rosters, []
