"""Stable team slot identity + display-name resolution for Live Draft rooms."""

from __future__ import annotations

import re
from typing import Any

TEAM_SLOTS_CONFIG_KEY = "team_slots"
TEAM_RENAME_MAP_CONFIG_KEY = "team_rename_map"


def team_slot_id(index: int) -> str:
    return f"team_{int(index) + 1}"


def legacy_generated_team_label(index: int) -> str:
    """Default numbered label (Team 1, Team 2, ...)."""
    return f"Team {int(index) + 1}"


def legacy_alpha_team_label(index: int) -> str:
    i = int(index)
    if 0 <= i < 26:
        return f"Team {chr(65 + i)}"
    return legacy_generated_team_label(i)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def list_room_display_teams(room: dict[str, Any]) -> list[str]:
    try:
        from live_draft_team_ownership import list_room_teams

        teams = list_room_teams(room)
        if teams:
            return teams
    except ImportError:
        pass
    cfg = dict(room.get("config") or {})
    named = [str(t).strip() for t in (cfg.get("teams") or room.get("teams") or []) if str(t).strip()]
    return named


def ensure_room_team_slots(room: dict[str, Any], *, persist: bool = True) -> list[dict[str, Any]]:
    """Ensure config.team_slots aligns with current display team order."""
    teams = list_room_display_teams(room)
    cfg = dict(room.get("config") or {})
    raw = cfg.get(TEAM_SLOTS_CONFIG_KEY)
    slots: list[dict[str, Any]] = []
    if isinstance(raw, list) and len(raw) == len(teams):
        for i, display in enumerate(teams):
            entry = dict(raw[i]) if isinstance(raw[i], dict) else {}
            slot_id = str(entry.get("team_id") or team_slot_id(i)).strip() or team_slot_id(i)
            slots.append(
                {
                    "team_id": slot_id,
                    "display_name": display,
                    "slot_index": int(entry.get("slot_index") if entry.get("slot_index") is not None else i),
                }
            )
    else:
        slots = [
            {"team_id": team_slot_id(i), "display_name": teams[i], "slot_index": i}
            for i in range(len(teams))
        ]
    if persist:
        cfg[TEAM_SLOTS_CONFIG_KEY] = slots
        cfg["teams"] = list(teams)
        room["config"] = cfg
        if teams:
            room["teams"] = list(teams)
    return slots


def display_name_for_team_id(room: dict[str, Any], team_id: str) -> str:
    tid = str(team_id or "").strip()
    if not tid:
        return ""
    slots = ensure_room_team_slots(room, persist=False)
    for entry in slots:
        if str(entry.get("team_id") or "").strip() == tid:
            return str(entry.get("display_name") or "").strip()
    return ""


def sync_room_team_display_names(room: dict[str, Any], new_team_names: list[str]) -> dict[str, str]:
    """Apply lobby/setup renames to pick_order and team slot metadata (pre-first-pick)."""
    updated = [str(t).strip() for t in new_team_names if str(t).strip()]
    if not updated:
        return {}
    old_teams = list_room_display_teams(room)
    slots = ensure_room_team_slots(room, persist=True)
    rename_map: dict[str, str] = dict((room.get("config") or {}).get(TEAM_RENAME_MAP_CONFIG_KEY) or {})
    for i, display in enumerate(updated):
        if i < len(old_teams):
            old = str(old_teams[i] or "").strip()
            if old and old != display:
                rename_map[old] = display
        if i < len(slots):
            slots[i]["display_name"] = display
    cfg = dict(room.get("config") or {})
    cfg[TEAM_RENAME_MAP_CONFIG_KEY] = rename_map
    cfg[TEAM_SLOTS_CONFIG_KEY] = slots
    cfg["teams"] = updated
    room["config"] = cfg
    room["teams"] = updated

    old_rosters = dict(room.get("rosters") or {})
    new_rosters: dict[str, list[Any]] = {}
    for i, display in enumerate(updated):
        source_key = old_teams[i] if i < len(old_teams) else display
        rows = list(old_rosters.get(source_key) or [])
        new_rosters[display] = rows
    room["rosters"] = new_rosters

    for slot in room.get("pick_order") or []:
        if not isinstance(slot, dict):
            continue
        raw = str(slot.get("Team") or "").strip()
        if raw in rename_map:
            slot["Team"] = rename_map[raw]
        elif raw in old_teams:
            idx = old_teams.index(raw)
            if idx < len(updated):
                slot["Team"] = updated[idx]
                if raw != updated[idx]:
                    rename_map[raw] = updated[idx]
    cfg[TEAM_RENAME_MAP_CONFIG_KEY] = rename_map
    room["config"] = cfg
    return rename_map


def _first_round_team_order(pick_order: list[Any]) -> list[str]:
    ordered: list[str] = []
    for slot in pick_order:
        if not isinstance(slot, dict):
            continue
        if int(slot.get("Round") or 1) != 1:
            continue
        team = str(slot.get("Team") or "").strip()
        if team and team not in ordered:
            ordered.append(team)
    if ordered:
        return ordered
    seen: list[str] = []
    for slot in pick_order:
        if not isinstance(slot, dict):
            continue
        team = str(slot.get("Team") or "").strip()
        if team and team not in seen:
            seen.append(team)
    return seen


def build_team_rename_map(room: dict[str, Any]) -> tuple[dict[str, str], list[str], list[str]]:
    """Return (rename_map, unmapped_board_teams, ambiguous_labels)."""
    teams = list_room_display_teams(room)
    cfg = dict(room.get("config") or {})
    rename_map: dict[str, str] = {}
    ambiguous: list[str] = []
    explicit = cfg.get(TEAM_RENAME_MAP_CONFIG_KEY)
    if isinstance(explicit, dict):
        for raw, display in explicit.items():
            key = str(raw or "").strip()
            val = str(display or "").strip()
            if key and val:
                rename_map[key] = val

    slots = ensure_room_team_slots(room, persist=False)
    for i, display in enumerate(teams):
        for legacy in (legacy_generated_team_label(i), legacy_alpha_team_label(i)):
            if not legacy or legacy == display:
                continue
            if legacy in rename_map and rename_map[legacy] != display:
                ambiguous.append(legacy)
            elif legacy not in rename_map:
                rename_map[legacy] = display

    pick_labels = _first_round_team_order(list(room.get("pick_order") or []))
    if len(pick_labels) == len(teams):
        for i, legacy in enumerate(pick_labels):
            display = teams[i]
            if legacy == display:
                continue
            if legacy in rename_map and rename_map[legacy] != display:
                if legacy not in ambiguous:
                    ambiguous.append(legacy)
            elif legacy not in rename_map:
                rename_map[legacy] = display

    board_labels = _distinct_board_team_values(room)
    unmapped = [label for label in board_labels if label not in teams and label not in rename_map]
    return rename_map, unmapped, ambiguous


def _distinct_board_team_values(room: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for row in room.get("draft_board") or []:
        if not isinstance(row, dict):
            continue
        for key in ("team", "Team", "Fantasy Team"):
            val = str(row.get(key) or "").strip()
            if val and val not in seen:
                seen.append(val)
    return seen


def _roster_player_indexes(room: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    by_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for team, rows in dict(room.get("rosters") or {}).items():
        team_name = str(team or "").strip()
        if not team_name:
            continue
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            pid = ""
            for key in ("player_id", "playerID", "playerId", "mlbam_id", "ID"):
                pid = str(row.get(key) or "").strip()
                if pid:
                    break
            name = ""
            for key in ("player_name", "fullName", "Player", "name", "player"):
                name = str(row.get(key) or "").strip()
                if name:
                    break
            if pid:
                prev = by_id.get(pid)
                if prev and prev != team_name:
                    by_id[pid] = ""
                else:
                    by_id[pid] = team_name
            if name:
                norm = _normalize_name(name)
                prev = by_name.get(norm)
                if prev and prev != team_name:
                    by_name[norm] = ""
                else:
                    by_name[norm] = team_name
    by_id = {k: v for k, v in by_id.items() if v}
    by_name = {k: v for k, v in by_name.items() if v}
    return by_id, by_name


def resolve_board_team_label(
    room: dict[str, Any],
    row: dict[str, Any],
    *,
    rename_map: dict[str, str],
    roster_by_id: dict[str, str],
    roster_by_name: dict[str, str],
    teams: list[str],
) -> tuple[str, str, str, str]:
    """Return (resolved_team, raw_team, team_id, resolution_source)."""
    raw = ""
    for key in ("team", "Team", "Fantasy Team"):
        val = str(row.get(key) or "").strip()
        if val:
            raw = val
            break
    team_id = str(row.get("team_id") or row.get("TeamId") or row.get("teamId") or "").strip()
    if team_id:
        display = display_name_for_team_id(room, team_id)
        if display:
            return display, raw or display, team_id, f"team_id:{team_id}"

    if raw in teams:
        return raw, raw, team_id, "current_display_name"

    if raw in rename_map:
        mapped = rename_map[raw]
        return mapped, raw, team_id, f"rename_map:{raw}"

    pid = ""
    for key in ("player_id", "playerID", "playerId", "mlbam_id", "ID"):
        pid = str(row.get(key) or "").strip()
        if pid:
            break
    name = ""
    for key in ("player_name", "fullName", "Player", "name", "player"):
        name = str(row.get(key) or "").strip()
        if name:
            break

    candidates: set[str] = set()
    if pid and pid in roster_by_id:
        candidates.add(roster_by_id[pid])
    if name:
        norm = _normalize_name(name)
        if norm in roster_by_name:
            candidates.add(roster_by_name[norm])
    candidates = {c for c in candidates if c}
    if len(candidates) == 1:
        resolved = next(iter(candidates))
        return resolved, raw, team_id, "roster_membership"
    return "", raw, team_id, "unresolved"


def build_board_team_resolution(room: dict[str, Any]) -> dict[str, Any]:
    """Diagnostics + per-row resolution for legacy/stale board team labels."""
    teams = list_room_display_teams(room)
    slots = ensure_room_team_slots(room, persist=False)
    rename_map, unmapped, ambiguous = build_team_rename_map(room)
    roster_by_id, roster_by_name = _roster_player_indexes(room)
    board_rows: list[dict[str, Any]] = []
    resolved_map: dict[str, str] = {}
    resolution_notes: list[str] = []

    for row in room.get("draft_board") or []:
        if not isinstance(row, dict):
            continue
        resolved, raw, tid, source = resolve_board_team_label(
            room,
            row,
            rename_map=rename_map,
            roster_by_id=roster_by_id,
            roster_by_name=roster_by_name,
            teams=teams,
        )
        if raw and resolved and raw != resolved and raw not in resolved_map:
            resolved_map[raw] = resolved
            slot_note = ""
            for i, display in enumerate(teams):
                if display == resolved:
                    for legacy in (legacy_generated_team_label(i), legacy_alpha_team_label(i)):
                        if legacy == raw:
                            slot_note = f" using team slot {team_slot_id(i)}"
                            break
                    break
            if source.startswith("rename_map:"):
                resolution_notes.append(
                    f"Resolved {raw!r} → {resolved!r}{slot_note or ' using team rename map'}."
                )
            elif source.startswith("team_id:"):
                resolution_notes.append(f"Resolved {raw!r} → {resolved!r} using {tid}.")
            elif source == "roster_membership":
                resolution_notes.append(
                    f"Resolved {raw!r} → {resolved!r} using unique roster membership for pick {row.get('Pick')}."
                )
        board_rows.append(
            {
                "pick_number": row.get("Pick") or row.get("pick"),
                "player_name": row.get("fullName") or row.get("Player") or row.get("player_name"),
                "player_id": row.get("playerID") or row.get("player_id"),
                "raw_board_team": raw,
                "team_id": tid or None,
                "resolved_display_team": resolved,
                "resolution_source": source,
            }
        )

    if unmapped:
        for label in unmapped:
            if label not in resolved_map:
                resolution_notes.append(f"Final board uses unresolved team label {label!r}.")

    draft_results_preview: list[str] = []
    for entry in board_rows:
        team = str(entry.get("resolved_display_team") or "").strip()
        if team and team not in draft_results_preview:
            draft_results_preview.append(team)

    configured = [str(s.get("display_name") or "") for s in slots]
    resolved_count = sum(1 for e in board_rows if str(e.get("resolved_display_team") or "").strip())
    return {
        "room_teams": teams,
        "room_roster_keys": sorted(str(k) for k in dict(room.get("rosters") or {}).keys()),
        "draft_board_row_count": len(board_rows),
        "draft_board_distinct_team_values": _distinct_board_team_values(room),
        "draft_results_count": resolved_count,
        "draft_results_distinct_team_values": draft_results_preview,
        "configured_team_names": configured,
        "team_rename_map": rename_map,
        "resolved_board_team_map": resolved_map,
        "unmapped_board_teams": [t for t in unmapped if t not in resolved_map],
        "ambiguous_board_teams": ambiguous,
        "board_row_details": board_rows,
        "resolution_notes": resolution_notes,
    }


def team_id_for_display_name(room: dict[str, Any], display_name: str) -> str:
    target = str(display_name or "").strip()
    if not target:
        return ""
    for entry in ensure_room_team_slots(room, persist=False):
        if str(entry.get("display_name") or "").strip() == target:
            return str(entry.get("team_id") or "").strip()
    return ""

def stamp_team_id_on_pick_record(room: dict[str, Any], pick_record: dict[str, Any], display_team: str) -> None:
    tid = team_id_for_display_name(room, display_team)
    if tid:
        pick_record["team_id"] = tid
    pick_record["Team"] = display_team
    if "Fantasy Team" in pick_record or display_team:
        pick_record["Fantasy Team"] = display_team
