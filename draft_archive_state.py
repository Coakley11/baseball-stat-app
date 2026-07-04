"""Saved draft teams — simulator and live draft archive with persistence."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd

DRAFT_ARCHIVE_KEY = "draft_archive_teams"
ACTIVE_DRAFT_ARCHIVE_KEY = "active_draft_archive_id"

DRAFT_TYPE_SIMULATOR = "simulator"
DRAFT_TYPE_LIVE = "live_draft_room"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _archive_list(session: dict[str, Any]) -> list[dict[str, Any]]:
    raw = session.get(DRAFT_ARCHIVE_KEY)
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, dict)]


def _set_archive_list(session: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    session[DRAFT_ARCHIVE_KEY] = entries


def list_draft_archives(session: dict[str, Any]) -> list[dict[str, Any]]:
    """All saved draft teams, newest first."""
    entries = _archive_list(session)
    return sorted(entries, key=lambda e: str(e.get("updated_at") or e.get("created_at") or ""), reverse=True)


def get_draft_archive(session: dict[str, Any], draft_id: str) -> dict[str, Any] | None:
    draft_id = str(draft_id or "").strip()
    if not draft_id:
        return None
    for entry in _archive_list(session):
        if str(entry.get("draft_id") or "") == draft_id:
            return copy.deepcopy(entry)
    return None


def set_active_draft_archive(session: dict[str, Any], draft_id: str | None) -> None:
    if draft_id:
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = str(draft_id)
    else:
        session.pop(ACTIVE_DRAFT_ARCHIVE_KEY, None)


def get_active_draft_archive(session: dict[str, Any]) -> dict[str, Any] | None:
    draft_id = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    if not draft_id:
        return None
    return get_draft_archive(session, draft_id)


def _roster_rows_from_live_room(room: dict[str, Any], team: str) -> list[dict[str, Any]]:
    rows = list((room.get("rosters") or {}).get(str(team), []) or [])
    return [dict(r) for r in rows if isinstance(r, dict)]


def _board_rows_for_team(board_df: pd.DataFrame, team: str) -> list[dict[str, Any]]:
    if board_df is None or board_df.empty:
        return []
    team_col = "Fantasy Team" if "Fantasy Team" in board_df.columns else "Team"
    if team_col not in board_df.columns:
        return []
    subset = board_df[board_df[team_col].astype(str) == str(team)].copy()
    if subset.empty:
        return []
    return subset.to_dict(orient="records")


def save_draft_archive(
    session: dict[str, Any],
    *,
    draft_type: str,
    draft_name: str,
    team_name: str,
    config: dict[str, Any] | None = None,
    roster_rows: list[dict[str, Any]] | None = None,
    pick_rows: list[dict[str, Any]] | None = None,
    draft_id: str | None = None,
    league_rosters: dict[str, dict[str, Any]] | None = None,
    league_context_id: str | None = None,
) -> dict[str, Any]:
    """Persist one saved draft team snapshot."""
    now = _utc_now_iso()
    entry_id = str(draft_id or uuid.uuid4().hex[:12])
    cfg = copy.deepcopy(config or {})
    entry: dict[str, Any] = {
        "draft_id": entry_id,
        "draft_type": str(draft_type or DRAFT_TYPE_SIMULATOR),
        "draft_name": str(draft_name or team_name or "Saved Draft").strip() or "Saved Draft",
        "team_name": str(team_name or "").strip(),
        "created_at": now,
        "updated_at": now,
        "fantasy_format": cfg.get("fantasy_format") or cfg.get("scoring_type") or "",
        "roster_slots": dict(cfg.get("slots") or {}),
        "slot_instances": list(cfg.get("slot_instances") or []),
        "projection_settings": {
            "projection_window": cfg.get("projection_window"),
            "projection_style": cfg.get("projection_style"),
            "use_ml_blend": cfg.get("use_ml_blend"),
            "ml_blend_weight": cfg.get("ml_blend_weight"),
            "scoring_type": cfg.get("scoring_type"),
        },
        "players": copy.deepcopy(roster_rows or []),
        "picks": copy.deepcopy(pick_rows or []),
    }
    if league_rosters is not None:
        entry["league_rosters"] = copy.deepcopy(league_rosters)
    if league_context_id:
        entry["league_context_id"] = str(league_context_id).strip()
    entries = _archive_list(session)
    replaced = False
    for i, existing in enumerate(entries):
        if str(existing.get("draft_id") or "") == entry_id:
            entry["created_at"] = existing.get("created_at") or now
            entries[i] = entry
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    _set_archive_list(session, entries)
    return entry


def save_live_draft_team_archive(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    team_name: str,
    draft_name: str = "",
) -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    roster = _roster_rows_from_live_room(room, team_name)
    picks = [
        dict(p)
        for p in (room.get("draft_board") or [])
        if isinstance(p, dict) and str(p.get("Fantasy Team") or p.get("Team") or "") == str(team_name)
    ]
    label = draft_name or f"{cfg.get('league_name', 'Live Draft')} — {team_name}"
    return save_draft_archive(
        session,
        draft_type=DRAFT_TYPE_LIVE,
        draft_name=label,
        team_name=team_name,
        config=cfg,
        roster_rows=roster,
        pick_rows=picks,
    )


def save_simulator_team_archive(
    session: dict[str, Any],
    board_df: pd.DataFrame,
    *,
    team_name: str,
    draft_name: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or session.get("draft_shared_settings") or {})
    picks = _board_rows_for_team(board_df, team_name)
    players = [dict(p) for p in picks if str(p.get("Player") or p.get("fullName") or "").strip()]
    label = draft_name or f"Simulator — {team_name}"
    return save_draft_archive(
        session,
        draft_type=DRAFT_TYPE_SIMULATOR,
        draft_name=label,
        team_name=team_name,
        config=cfg,
        roster_rows=players,
        pick_rows=picks,
    )


def archive_roster_dataframe(entry: dict[str, Any]) -> pd.DataFrame:
    """Normalize saved players for Standings / Lineup handoff."""
    rows = list(entry.get("players") or [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    rename = {"fullName": "Player", "Team": "MLB Team"}
    for old, new in rename.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})
    if "Player" not in df.columns:
        for col in ("name", "player"):
            if col in df.columns:
                df = df.rename(columns={col: "Player"})
                break
    team_name = str(entry.get("team_name") or "").strip()
    if team_name and "Team" not in df.columns:
        df["Team"] = team_name
    return df


def activate_draft_archive(session: dict[str, Any], draft_id: str) -> dict[str, Any] | None:
    """Mark one saved draft active without removing other archives."""
    entry = get_draft_archive(session, draft_id)
    if not entry:
        return None
    set_active_draft_archive(session, str(entry.get("draft_id") or ""))
    team = str(entry.get("team_name") or "").strip()
    if team:
        session["room_your_team"] = team
    fmt = str(entry.get("fantasy_format") or "").strip()
    if fmt:
        session["room_format"] = fmt
        session["standings_scoring_format"] = fmt
    return entry


def clear_active_draft_archive(session: dict[str, Any]) -> None:
    set_active_draft_archive(session, None)


def draft_type_display(entry: dict[str, Any] | None) -> str:
    if not entry:
        return ""
    draft_type = str(entry.get("draft_type") or DRAFT_TYPE_SIMULATOR)
    if draft_type == DRAFT_TYPE_LIVE:
        return "Live Draft"
    return "Simulator"


def format_archive_modified(entry: dict[str, Any] | None) -> str:
    if not entry:
        return "—"
    raw = str(entry.get("updated_at") or entry.get("created_at") or "").strip()
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except ValueError:
        return raw[:16]


def rename_draft_archive(session: dict[str, Any], draft_id: str, new_name: str) -> dict[str, Any] | None:
    draft_id = str(draft_id or "").strip()
    label = str(new_name or "").strip()
    if not draft_id or not label:
        return None
    entries = _archive_list(session)
    updated: dict[str, Any] | None = None
    for i, existing in enumerate(entries):
        if str(existing.get("draft_id") or "") != draft_id:
            continue
        row = dict(existing)
        row["draft_name"] = label
        row["updated_at"] = _utc_now_iso()
        entries[i] = row
        updated = row
        break
    if updated is None:
        return None
    _set_archive_list(session, entries)
    return copy.deepcopy(updated)


def duplicate_draft_archive(session: dict[str, Any], draft_id: str) -> dict[str, Any] | None:
    source = get_draft_archive(session, draft_id)
    if not source:
        return None
    now = _utc_now_iso()
    copy_entry = copy.deepcopy(source)
    copy_entry["draft_id"] = uuid.uuid4().hex[:12]
    base_name = str(source.get("draft_name") or "Saved Draft").strip()
    copy_entry["draft_name"] = f"{base_name} (copy)"
    copy_entry["created_at"] = now
    copy_entry["updated_at"] = now
    entries = _archive_list(session)
    entries.append(copy_entry)
    _set_archive_list(session, entries)
    return copy.deepcopy(copy_entry)


def delete_draft_archive(session: dict[str, Any], draft_id: str) -> bool:
    draft_id = str(draft_id or "").strip()
    if not draft_id:
        return False
    before = len(_archive_list(session))
    entries = [e for e in _archive_list(session) if str(e.get("draft_id") or "") != draft_id]
    if len(entries) == before:
        return False
    _set_archive_list(session, entries)
    if str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "") == draft_id:
        clear_active_draft_archive(session)
    return True


def active_archive_label(entry: dict[str, Any] | None) -> str:
    if not entry:
        return ""
    name = str(entry.get("draft_name") or "Saved Draft").strip()
    team = str(entry.get("team_name") or "").strip()
    draft_type = str(entry.get("draft_type") or "").replace("_", " ")
    parts = [p for p in (name, team, draft_type) if p]
    return " — ".join(parts[:2]) if parts else "Saved Draft"


def build_roster_stats_from_archive(
    entry: dict[str, Any],
    current_stats: pd.DataFrame,
    *,
    normalize_name_fn,
) -> pd.DataFrame:
    """Merge saved archive roster with current-season hitter stats."""
    if current_stats is None or getattr(current_stats, "empty", True):
        return pd.DataFrame()
    drafted = archive_roster_dataframe(entry)
    if drafted.empty or "Player" not in drafted.columns:
        return pd.DataFrame()
    work = drafted[drafted["Player"].astype(str).str.strip() != ""].copy()
    work["Player Key"] = work["Player"].apply(normalize_name_fn)
    stats = current_stats.copy()
    if "Player Key" not in stats.columns:
        name_col = "Player" if "Player" in stats.columns else stats.columns[0]
        stats["Player Key"] = stats[name_col].apply(normalize_name_fn)
    roster_stats = work.merge(stats, on="Player Key", how="left", suffixes=("", "_stats"))
    if "Player_stats" in roster_stats.columns:
        roster_stats["Player"] = roster_stats["Player"].fillna(roster_stats["Player_stats"])
    return roster_stats
