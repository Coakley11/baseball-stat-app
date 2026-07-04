"""Fantasy League Context — full league state, ownership, and persistence."""

from __future__ import annotations

import copy
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from draft_archive_state import (
    ACTIVE_DRAFT_ARCHIVE_KEY,
    DRAFT_ARCHIVE_KEY,
    DRAFT_TYPE_LIVE,
    DRAFT_TYPE_SIMULATOR,
    get_draft_archive,
    set_active_draft_archive,
)

FANTASY_LEAGUE_CONTEXT_STATE_KEY = "fantasy_league_context_state"
SCHEMA_VERSION = 1

CONTEXT_TYPE_REAL_LEAGUE = "real_league"
CONTEXT_TYPE_LIVE_DRAFT_RESULT = "live_draft_result"
CONTEXT_TYPE_MOCK_DRAFT_SIMULATION = "mock_draft_simulation"

MIGRATION_STATUS_FULL_LEAGUE = "full_league"
MIGRATION_STATUS_SINGLE_TEAM_LEGACY = "single_team_legacy"

SOURCE_LIVE_DRAFT_ROOM = "live_draft_room"
SOURCE_DRAFT_SIMULATOR = "draft_simulator"
SOURCE_LEGACY_MIGRATION = "legacy_migration"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_player_key(name: Any) -> str:
    """Stable lowercase key for ownership map lookups."""
    return str(name or "").strip().lower()


def context_id_for_archive(draft_id: str) -> str:
    return f"archive:{str(draft_id or '').strip()}"


def _empty_store() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "active_league_context_id": "",
        "contexts": {},
        "legacy_migration": {
            "migrated_archive_ids": [],
            "archives_scanned_at": "",
        },
    }


def ensure_fantasy_league_context_state(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY)
    if not isinstance(raw, dict):
        store = _empty_store()
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = store
        return store
    if "contexts" not in raw or not isinstance(raw.get("contexts"), dict):
        raw["contexts"] = {}
    if "legacy_migration" not in raw or not isinstance(raw.get("legacy_migration"), dict):
        raw["legacy_migration"] = {"migrated_archive_ids": [], "archives_scanned_at": ""}
    raw.setdefault("schema_version", SCHEMA_VERSION)
    raw.setdefault("active_league_context_id", "")
    return raw


def _player_name_from_row(row: dict[str, Any]) -> str:
    for key in ("player_name", "fullName", "Player", "name", "player"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return ""


def _player_id_from_row(row: dict[str, Any]) -> str:
    for key in ("player_id", "playerID", "playerId", "mlbam_id", "ID"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return ""


def _normalize_player_entry(row: dict[str, Any], *, team_name: str) -> dict[str, Any]:
    source = dict(row)
    player_name = _player_name_from_row(source)
    player_id = _player_id_from_row(source)
    positions: list[str] = []
    for key in ("positions", "Primary Position", "position", "Pos"):
        raw = source.get(key)
        if isinstance(raw, list):
            positions = [str(p).strip() for p in raw if str(p).strip()]
            break
        if raw is not None and str(raw).strip():
            positions = [str(raw).strip()]
            break
    pick_val = source.get("pick") if source.get("pick") is not None else source.get("Pick")
    round_val = source.get("round") if source.get("round") is not None else source.get("Round")
    return {
        "player_name": player_name,
        "player_key": normalize_player_key(player_name),
        "player_id": player_id,
        "positions": positions,
        "pick": pick_val,
        "round": round_val,
        "source_row": source,
        "team_name": str(team_name or "").strip(),
    }


def _team_roster_entry(team_name: str, players: list[dict[str, Any]], *, is_user_team: bool) -> dict[str, Any]:
    return {
        "team_name": str(team_name or "").strip(),
        "is_user_team": bool(is_user_team),
        "players": copy.deepcopy(players),
    }


def build_league_rosters_from_live_room(
    room: dict[str, Any],
    my_team_name: str,
) -> dict[str, dict[str, Any]]:
    """Build all team rosters from a live draft room."""
    my_team = str(my_team_name or "").strip()
    rosters_raw = room.get("rosters") or {}
    if not isinstance(rosters_raw, dict):
        rosters_raw = {}
    league_rosters: dict[str, dict[str, Any]] = {}
    for team_name, rows in rosters_raw.items():
        team = str(team_name or "").strip()
        if not team:
            continue
        player_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        players = [_normalize_player_entry(row, team_name=team) for row in player_rows if _player_name_from_row(row)]
        league_rosters[team] = _team_roster_entry(team, players, is_user_team=(team == my_team))
    if not league_rosters and my_team:
        board = [dict(p) for p in (room.get("draft_board") or []) if isinstance(p, dict)]
        by_team: dict[str, list[dict[str, Any]]] = {}
        for pick in board:
            team = str(pick.get("Fantasy Team") or pick.get("Team") or "").strip()
            if not team:
                continue
            by_team.setdefault(team, []).append(pick)
        for team, rows in by_team.items():
            players = [_normalize_player_entry(row, team_name=team) for row in rows if _player_name_from_row(row)]
            league_rosters[team] = _team_roster_entry(team, players, is_user_team=(team == my_team))
    return league_rosters


def build_league_rosters_from_simulator_board(
    board_df: pd.DataFrame,
    my_team_name: str,
) -> dict[str, dict[str, Any]]:
    """Group simulator draft board rows by fantasy team."""
    my_team = str(my_team_name or "").strip()
    if board_df is None or getattr(board_df, "empty", True):
        return {}
    team_col = "Fantasy Team" if "Fantasy Team" in board_df.columns else "Team"
    if team_col not in board_df.columns:
        return {}
    league_rosters: dict[str, dict[str, Any]] = {}
    for team_name, subset in board_df.groupby(board_df[team_col].astype(str), sort=False):
        team = str(team_name or "").strip()
        if not team:
            continue
        rows = [dict(r) for r in subset.to_dict(orient="records")]
        players = [_normalize_player_entry(row, team_name=team) for row in rows if _player_name_from_row(row)]
        league_rosters[team] = _team_roster_entry(team, players, is_user_team=(team == my_team))
    return league_rosters


def build_ownership_map(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Derive player_key -> owner record from league_rosters."""
    ownership: dict[str, dict[str, Any]] = {}
    league_rosters = context.get("league_rosters") or {}
    if not isinstance(league_rosters, dict):
        return ownership
    for team_name, team_entry in league_rosters.items():
        if not isinstance(team_entry, dict):
            continue
        owner_team = str(team_entry.get("team_name") or team_name or "").strip()
        is_user_team = bool(team_entry.get("is_user_team"))
        for player in team_entry.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_name = str(player.get("player_name") or "").strip()
            player_key = str(player.get("player_key") or normalize_player_key(player_name)).strip()
            if not player_key:
                continue
            ownership[player_key] = {
                "player_key": player_key,
                "player_name": player_name,
                "player_id": str(player.get("player_id") or "").strip(),
                "owner_team": owner_team,
                "is_user_team": is_user_team,
            }
    return ownership


def league_context_roster_dataframe(context: dict[str, Any]) -> pd.DataFrame:
    """Normalize all league_rosters players into one DataFrame for Standings / cache."""
    league_rosters = context.get("league_rosters") or {}
    if not isinstance(league_rosters, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for team_name, team_entry in league_rosters.items():
        if not isinstance(team_entry, dict):
            continue
        fantasy_team = str(team_entry.get("team_name") or team_name or "").strip()
        for player in team_entry.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_name = str(player.get("player_name") or "").strip()
            if not player_name:
                continue
            source = dict(player.get("source_row") or {})
            row: dict[str, Any] = {
                "Player": player_name,
                "Team": fantasy_team,
            }
            positions = player.get("positions") or []
            if positions:
                row["Primary Position"] = str(positions[0])
            elif source.get("Primary Position"):
                row["Primary Position"] = str(source.get("Primary Position"))
            for src_key, dst_key in (("Pick", "Pick"), ("Round", "Round"), ("pick", "Pick"), ("round", "Round")):
                if src_key in source and dst_key not in row:
                    row[dst_key] = source[src_key]
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def build_roster_stats_from_league_context(
    context: dict[str, Any],
    current_stats: pd.DataFrame,
    *,
    normalize_name_fn,
) -> pd.DataFrame:
    """Merge every team's league_rosters players with current-season hitter stats."""
    if current_stats is None or getattr(current_stats, "empty", True):
        return pd.DataFrame()
    drafted = league_context_roster_dataframe(context)
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


def league_rosters_cache_sig(context: dict[str, Any] | None) -> str:
    """Stable signature for league_rosters used in standings cache keys."""
    if not context:
        return ""
    league_context_id = str(context.get("league_context_id") or "")
    rosters = context.get("league_rosters") or {}
    if not isinstance(rosters, dict):
        return league_context_id
    parts: list[str] = []
    for team_name in sorted(rosters.keys()):
        team_entry = rosters.get(team_name)
        if not isinstance(team_entry, dict):
            continue
        players = team_entry.get("players") or []
        parts.append(f"{team_name}:{len(players)}")
    raw = f"{league_context_id}|{'|'.join(parts)}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def has_full_league_rosters(context: dict[str, Any] | None) -> bool:
    if not context:
        return False
    meta = context.get("metadata") or {}
    if str(meta.get("migration_status") or "") == MIGRATION_STATUS_FULL_LEAGUE:
        return True
    rosters = context.get("league_rosters") or {}
    if isinstance(rosters, dict) and len(rosters) >= 2:
        return True
    return False


def _context_type_from_archive_draft_type(draft_type: str) -> str:
    if str(draft_type or "") == DRAFT_TYPE_LIVE:
        return CONTEXT_TYPE_LIVE_DRAFT_RESULT
    return CONTEXT_TYPE_MOCK_DRAFT_SIMULATION


def _players_from_archive_entry(archive_entry: dict[str, Any]) -> list[dict[str, Any]]:
    team_name = str(archive_entry.get("team_name") or "").strip()
    rows = [dict(r) for r in (archive_entry.get("players") or []) if isinstance(r, dict)]
    return [_normalize_player_entry(row, team_name=team_name) for row in rows if _player_name_from_row(row)]


def migrate_archive_to_league_context(archive_entry: dict[str, Any]) -> dict[str, Any]:
    """Convert one legacy saved draft archive into a Fantasy League Context."""
    draft_id = str(archive_entry.get("draft_id") or "").strip()
    team_name = str(archive_entry.get("team_name") or "").strip()
    draft_name = str(archive_entry.get("draft_name") or "").strip() or "Saved Draft"
    now = _utc_now_iso()
    created = str(archive_entry.get("created_at") or now)
    league_context_id = context_id_for_archive(draft_id)
    players = _players_from_archive_entry(archive_entry)
    league_rosters = {
        team_name: _team_roster_entry(team_name, players, is_user_team=True),
    } if team_name else {}
    context: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "league_context_id": league_context_id,
        "context_type": _context_type_from_archive_draft_type(str(archive_entry.get("draft_type") or "")),
        "league_name": draft_name,
        "display_name": draft_name,
        "my_team_name": team_name,
        "fantasy_format": str(archive_entry.get("fantasy_format") or "").strip(),
        "scoring_settings": copy.deepcopy(archive_entry.get("projection_settings") or {}),
        "roster_settings": {
            "roster_slots": dict(archive_entry.get("roster_slots") or {}),
            "slot_instances": list(archive_entry.get("slot_instances") or []),
        },
        "league_rosters": league_rosters,
        "ownership_map": {},
        "workflow": {
            "trade_candidates": [],
            "acquire_targets": [],
            "add_targets": [],
            "drop_candidates": [],
        },
        "metadata": {
            "created_at": created,
            "updated_at": str(archive_entry.get("updated_at") or now),
            "source_draft_id": draft_id,
            "source_workspace": "",
            "source": SOURCE_LEGACY_MIGRATION,
            "migration_status": MIGRATION_STATUS_SINGLE_TEAM_LEGACY,
        },
    }
    context["ownership_map"] = build_ownership_map(context)
    return context


def _empty_workflow() -> dict[str, list[Any]]:
    return {
        "trade_candidates": [],
        "acquire_targets": [],
        "add_targets": [],
        "drop_candidates": [],
        "league_activity": [],
    }


WORKFLOW_KEY_TRADE_CANDIDATES = "trade_candidates"
WORKFLOW_KEY_ACQUIRE_TARGETS = "acquire_targets"
TRADE_MODE_TRADE_AWAY = "trade_away"
TRADE_MODE_ACQUIRE = "acquire"
TRADE_HANDOFF_SESSION_KEY = "_fantasy_trade_handoff"
LINEUP_ASSISTANT_PAGE = "Fantasy Lineup Assistant"
PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY = "_pending_active_league_context_id"
PENDING_ARCHIVE_ACTIVATION_KEY = "_pending_active_archive_id"
LEAGUE_CONTEXT_SAVE_FLASH_KEY = "_league_context_save_flash"


def _workflow_key_for_mode(mode: str) -> str:
    mode_norm = str(mode or "").strip().lower()
    if mode_norm in (TRADE_MODE_TRADE_AWAY, "trade_away"):
        return WORKFLOW_KEY_TRADE_CANDIDATES
    if mode_norm == "add":
        return "add_targets"
    if mode_norm == "drop":
        return "drop_candidates"
    return WORKFLOW_KEY_ACQUIRE_TARGETS


def _normalize_workflow_target(player_name: str, *, owner_team: str = "") -> dict[str, Any]:
    name = str(player_name or "").strip()
    return {
        "player_name": name,
        "player_key": normalize_player_key(name),
        "owner_team": str(owner_team or "").strip(),
        "added_at": _utc_now_iso(),
    }


def _ensure_workflow(context: dict[str, Any]) -> dict[str, Any]:
    workflow = context.get("workflow")
    if not isinstance(workflow, dict):
        workflow = _empty_workflow()
        context["workflow"] = workflow
    for key in (
        WORKFLOW_KEY_TRADE_CANDIDATES,
        WORKFLOW_KEY_ACQUIRE_TARGETS,
        "add_targets",
        "drop_candidates",
        "league_activity",
    ):
        if not isinstance(workflow.get(key), list):
            workflow[key] = []
    return workflow


def get_workflow_targets(context: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    workflow = _ensure_workflow(context)
    key = _workflow_key_for_mode(mode)
    raw = workflow.get(key) or []
    return [dict(x) for x in raw if isinstance(x, dict)]


def workflow_target_player_names(context: dict[str, Any] | None, mode: str) -> list[str]:
    if not context:
        return []
    names: list[str] = []
    for target in get_workflow_targets(context, mode):
        name = str(target.get("player_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def get_active_workflow_targets(session: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    context = get_active_league_context(session)
    if not context:
        return []
    return get_workflow_targets(context, mode)


def add_workflow_target(
    session: dict[str, Any],
    league_context_id: str,
    mode: str,
    player_name: str,
    *,
    owner_team: str = "",
) -> dict[str, Any] | None:
    league_context_id = str(league_context_id or "").strip()
    if not league_context_id:
        return None
    context = get_league_context(session, league_context_id)
    if not context:
        return None
    workflow = _ensure_workflow(context)
    key = _workflow_key_for_mode(mode)
    target = _normalize_workflow_target(player_name, owner_team=owner_team)
    player_key = str(target.get("player_key") or "")
    existing = [dict(x) for x in (workflow.get(key) or []) if isinstance(x, dict)]
    if not any(str(x.get("player_key") or "") == player_key for x in existing):
        existing.append(target)
    workflow[key] = existing
    context["workflow"] = workflow
    return upsert_league_context(session, context)


def remove_workflow_target(
    session: dict[str, Any],
    league_context_id: str,
    mode: str,
    player_name: str,
) -> dict[str, Any] | None:
    league_context_id = str(league_context_id or "").strip()
    if not league_context_id:
        return None
    context = get_league_context(session, league_context_id)
    if not context:
        return None
    workflow = _ensure_workflow(context)
    key = _workflow_key_for_mode(mode)
    remove_key = normalize_player_key(player_name)
    existing = [dict(x) for x in (workflow.get(key) or []) if isinstance(x, dict)]
    workflow[key] = [x for x in existing if str(x.get("player_key") or "") != remove_key]
    context["workflow"] = workflow
    return upsert_league_context(session, context)


def migrate_global_pending_trade_targets(session: dict[str, Any]) -> bool:
    """One-time merge of legacy pending_trade_* lists into active context workflow."""
    store = ensure_fantasy_league_context_state(session)
    migration = store.setdefault("legacy_migration", {"migrated_archive_ids": [], "archives_scanned_at": ""})
    if not isinstance(migration, dict):
        migration = {"migrated_archive_ids": [], "archives_scanned_at": ""}
        store["legacy_migration"] = migration
    if migration.get("pending_trade_keys_migrated"):
        return False

    acquire_raw = session.get("pending_trade_acquire_players") or []
    away_raw = session.get("pending_trade_away_players") or []
    acquire_names = [str(x).strip() for x in acquire_raw if str(x).strip()] if isinstance(acquire_raw, list) else []
    away_names = [str(x).strip() for x in away_raw if str(x).strip()] if isinstance(away_raw, list) else []
    if not acquire_names and not away_names:
        migration["pending_trade_keys_migrated"] = True
        return False

    active_id = str(store.get("active_league_context_id") or "").strip()
    if not active_id:
        return False

    context = get_league_context(session, active_id)
    if not context:
        return False

    my_team = str(context.get("my_team_name") or "").strip()
    for name in away_names:
        add_workflow_target(session, active_id, TRADE_MODE_TRADE_AWAY, name, owner_team=my_team)
    for name in acquire_names:
        owner = ""
        owner_rec = (context.get("ownership_map") or {}).get(normalize_player_key(name)) or {}
        if isinstance(owner_rec, dict):
            owner = str(owner_rec.get("owner_team") or "")
        add_workflow_target(session, active_id, TRADE_MODE_ACQUIRE, name, owner_team=owner)

    session.pop("pending_trade_acquire_players", None)
    session.pop("pending_trade_away_players", None)
    migration["pending_trade_keys_migrated"] = True
    return True


def set_trade_acquire_handoff(
    session: dict[str, Any],
    *,
    league_context_id: str,
    mode: str,
    player_name: str,
    owner_team: str = "",
) -> None:
    league_context_id = str(league_context_id or "").strip()
    if league_context_id:
        schedule_league_context_activation(session, league_context_id)
    session[TRADE_HANDOFF_SESSION_KEY] = {
        "league_context_id": league_context_id,
        "mode": str(mode or "").strip(),
        "player_name": str(player_name or "").strip(),
        "owner_team": str(owner_team or "").strip(),
        "target_section": "trade_analyzer",
    }
    session["_navigate_to_page"] = LINEUP_ASSISTANT_PAGE
    session["_skip_page_restore_for"] = LINEUP_ASSISTANT_PAGE


def consume_trade_acquire_handoff(session: dict[str, Any]) -> dict[str, Any] | None:
    handoff = session.pop(TRADE_HANDOFF_SESSION_KEY, None)
    if not isinstance(handoff, dict):
        return None
    owner_team = str(handoff.get("owner_team") or "").strip()
    mode = str(handoff.get("mode") or "").strip()
    if owner_team and mode == TRADE_MODE_ACQUIRE:
        session["lineup_trade_other_team"] = owner_team
    player_name = str(handoff.get("player_name") or "").strip()
    if player_name:
        if mode == TRADE_MODE_TRADE_AWAY:
            session["lineup_trade_give_players"] = [player_name]
        elif mode == TRADE_MODE_ACQUIRE:
            session["lineup_trade_get_players"] = [player_name]
    session["_lineup_focus_trade_analyzer"] = True
    return handoff


def create_league_context(
    *,
    league_context_id: str,
    context_type: str,
    league_name: str,
    my_team_name: str,
    league_rosters: dict[str, dict[str, Any]],
    fantasy_format: str = "",
    scoring_settings: dict[str, Any] | None = None,
    roster_settings: dict[str, Any] | None = None,
    display_name: str = "",
    source: str = "",
    source_draft_id: str = "",
    migration_status: str = MIGRATION_STATUS_FULL_LEAGUE,
) -> dict[str, Any]:
    now = _utc_now_iso()
    my_team = str(my_team_name or "").strip()
    label = str(display_name or league_name or my_team or "Fantasy League").strip() or "Fantasy League"
    context: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "league_context_id": str(league_context_id or "").strip(),
        "context_type": str(context_type or CONTEXT_TYPE_MOCK_DRAFT_SIMULATION),
        "league_name": str(league_name or label).strip() or label,
        "display_name": label,
        "my_team_name": my_team,
        "fantasy_format": str(fantasy_format or "").strip(),
        "scoring_settings": copy.deepcopy(scoring_settings or {}),
        "roster_settings": copy.deepcopy(roster_settings or {"roster_slots": {}, "slot_instances": []}),
        "league_rosters": copy.deepcopy(league_rosters),
        "ownership_map": {},
        "workflow": _empty_workflow(),
        "metadata": {
            "created_at": now,
            "updated_at": now,
            "source_draft_id": str(source_draft_id or "").strip(),
            "source_workspace": "",
            "source": str(source or "").strip(),
            "migration_status": str(migration_status or MIGRATION_STATUS_FULL_LEAGUE),
        },
    }
    context["ownership_map"] = build_ownership_map(context)
    return context


def list_league_contexts(session: dict[str, Any]) -> list[dict[str, Any]]:
    store = ensure_fantasy_league_context_state(session)
    contexts = store.get("contexts") or {}
    entries = [copy.deepcopy(ctx) for ctx in contexts.values() if isinstance(ctx, dict)]
    return sorted(
        entries,
        key=lambda c: str((c.get("metadata") or {}).get("updated_at") or (c.get("metadata") or {}).get("created_at") or ""),
        reverse=True,
    )


def get_league_context(session: dict[str, Any], league_context_id: str) -> dict[str, Any] | None:
    league_context_id = str(league_context_id or "").strip()
    if not league_context_id:
        return None
    store = ensure_fantasy_league_context_state(session)
    ctx = (store.get("contexts") or {}).get(league_context_id)
    if not isinstance(ctx, dict):
        return None
    return copy.deepcopy(ctx)


def get_active_league_context(session: dict[str, Any]) -> dict[str, Any] | None:
    store = ensure_fantasy_league_context_state(session)
    active_id = str(store.get("active_league_context_id") or "").strip()
    if not active_id:
        return None
    return get_league_context(session, active_id)


def set_active_league_context(session: dict[str, Any], league_context_id: str | None) -> None:
    store = ensure_fantasy_league_context_state(session)
    if league_context_id:
        store["active_league_context_id"] = str(league_context_id).strip()
    else:
        store["active_league_context_id"] = ""


def clear_active_league_context(session: dict[str, Any]) -> None:
    set_active_league_context(session, None)


def schedule_league_context_activation(
    session: dict[str, Any],
    league_context_id: str,
    *,
    archive_id: str = "",
) -> None:
    """Defer room_your_team / archive alias sync until before widgets render."""
    league_context_id = str(league_context_id or "").strip()
    if league_context_id:
        session[PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY] = league_context_id
    archive_id = str(archive_id or "").strip()
    if archive_id:
        session[PENDING_ARCHIVE_ACTIVATION_KEY] = archive_id


def _clear_fantasy_context_caches(session: dict[str, Any]) -> None:
    try:
        from fantasy_perf_cache import LINEUP_SCORES_CACHE_KEY, STANDINGS_ROSTER_CACHE_KEY

        session.pop(STANDINGS_ROSTER_CACHE_KEY, None)
        session.pop(LINEUP_SCORES_CACHE_KEY, None)
    except ImportError:
        pass


def apply_pending_league_context_activation(session: dict[str, Any]) -> bool:
    """Apply deferred league-context activation before Streamlit widgets instantiate."""
    pending_ctx = str(session.pop(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, None) or "").strip()
    pending_archive = str(session.pop(PENDING_ARCHIVE_ACTIVATION_KEY, None) or "").strip()
    if not pending_ctx and not pending_archive:
        return False
    if pending_ctx:
        activate_league_context(session, pending_ctx)
    elif pending_archive:
        activate_archive_league_context(session, pending_archive)
    _clear_fantasy_context_caches(session)
    return True


def stash_league_context_save_flash(
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    league_save: bool = False,
) -> None:
    session[LEAGUE_CONTEXT_SAVE_FLASH_KEY] = {
        "draft_id": str(entry.get("draft_id") or ""),
        "draft_name": str(entry.get("draft_name") or ""),
        "team_count": league_team_count(context, entry),
        "player_count": len(entry.get("players") or []),
        "league_save": bool(league_save),
        "coverage": league_context_coverage_badge(context),
    }


def pop_league_context_save_flash(session: dict[str, Any]) -> dict[str, Any] | None:
    flash = session.pop(LEAGUE_CONTEXT_SAVE_FLASH_KEY, None)
    return dict(flash) if isinstance(flash, dict) else None


def schedule_active_context_resync(session: dict[str, Any]) -> bool:
    """Re-apply active league context aliases before fantasy page navigation."""
    context = get_active_league_context(session)
    if context:
        archive_id = str((context.get("metadata") or {}).get("source_draft_id") or "").strip()
        schedule_league_context_activation(
            session,
            str(context.get("league_context_id") or ""),
            archive_id=archive_id,
        )
        return True
    try:
        from draft_archive_state import get_active_draft_archive

        active = get_active_draft_archive(session)
    except ImportError:
        active = None
    if active:
        draft_id = str(active.get("draft_id") or "").strip()
        if draft_id:
            schedule_league_context_activation(session, context_id_for_archive(draft_id), archive_id=draft_id)
            return True
    return False


def _sync_legacy_archive_aliases(session: dict[str, Any], context: dict[str, Any] | None) -> None:
    if not context:
        session.pop(ACTIVE_DRAFT_ARCHIVE_KEY, None)
        return
    meta = context.get("metadata") or {}
    draft_id = str(meta.get("source_draft_id") or "").strip()
    if draft_id:
        set_active_draft_archive(session, draft_id)
    my_team = str(context.get("my_team_name") or "").strip()
    if my_team:
        session["room_your_team"] = my_team
    fmt = str(context.get("fantasy_format") or "").strip()
    if fmt:
        session["room_format"] = fmt
        session["standings_scoring_format"] = fmt


def activate_league_context(session: dict[str, Any], league_context_id: str) -> dict[str, Any] | None:
    context = get_league_context(session, league_context_id)
    if not context:
        return None
    set_active_league_context(session, league_context_id)
    _sync_legacy_archive_aliases(session, context)
    return context


def upsert_league_context(session: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Persist one league context; rebuild ownership_map before save."""
    store = ensure_fantasy_league_context_state(session)
    league_context_id = str(context.get("league_context_id") or "").strip()
    if not league_context_id:
        league_context_id = f"ctx:{uuid.uuid4().hex[:12]}"
        context["league_context_id"] = league_context_id
    now = _utc_now_iso()
    meta = dict(context.get("metadata") or {})
    meta.setdefault("created_at", now)
    meta["updated_at"] = now
    context["metadata"] = meta
    context["schema_version"] = SCHEMA_VERSION
    context["ownership_map"] = build_ownership_map(context)
    contexts = store.setdefault("contexts", {})
    if not isinstance(contexts, dict):
        contexts = {}
        store["contexts"] = contexts
    contexts[league_context_id] = copy.deepcopy(context)
    return copy.deepcopy(context)


def save_league_context(session: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return upsert_league_context(session, context)


def create_league_context_from_live_room(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    my_team_name: str,
    league_name: str = "",
    display_name: str = "",
    league_context_id: str | None = None,
    source_draft_id: str = "",
) -> dict[str, Any]:
    cfg = dict(room.get("config") or {})
    my_team = str(my_team_name or "").strip()
    league_rosters = build_league_rosters_from_live_room(room, my_team)
    label = str(display_name or "").strip() or f"{cfg.get('league_name', 'Live Draft')} — {my_team}"
    context_id = str(league_context_id or f"live:{uuid.uuid4().hex[:12]}")
    context = create_league_context(
        league_context_id=context_id,
        context_type=CONTEXT_TYPE_LIVE_DRAFT_RESULT,
        league_name=str(league_name or cfg.get("league_name") or "Live Draft").strip() or "Live Draft",
        my_team_name=my_team,
        league_rosters=league_rosters,
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or "").strip(),
        scoring_settings={
            "projection_window": cfg.get("projection_window"),
            "projection_style": cfg.get("projection_style"),
            "use_ml_blend": cfg.get("use_ml_blend"),
            "ml_blend_weight": cfg.get("ml_blend_weight"),
            "scoring_type": cfg.get("scoring_type"),
        },
        roster_settings={
            "roster_slots": dict(cfg.get("slots") or {}),
            "slot_instances": list(cfg.get("slot_instances") or []),
        },
        display_name=label,
        source=SOURCE_LIVE_DRAFT_ROOM,
        source_draft_id=str(source_draft_id or "").strip(),
        migration_status=MIGRATION_STATUS_FULL_LEAGUE,
    )
    return upsert_league_context(session, context)


def create_league_context_from_simulator_board(
    session: dict[str, Any],
    board_df: pd.DataFrame,
    *,
    my_team_name: str,
    config: dict[str, Any] | None = None,
    league_name: str = "",
    display_name: str = "",
    league_context_id: str | None = None,
    source_draft_id: str = "",
) -> dict[str, Any]:
    cfg = dict(config or session.get("draft_shared_settings") or {})
    my_team = str(my_team_name or "").strip()
    league_rosters = build_league_rosters_from_simulator_board(board_df, my_team)
    label = str(display_name or "").strip() or f"Simulator — {my_team}"
    context_id = str(league_context_id or f"sim:{uuid.uuid4().hex[:12]}")
    context = create_league_context(
        league_context_id=context_id,
        context_type=CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
        league_name=str(league_name or "Simulator").strip() or "Simulator",
        my_team_name=my_team,
        league_rosters=league_rosters,
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or "").strip(),
        scoring_settings={
            "projection_window": cfg.get("projection_window"),
            "projection_style": cfg.get("projection_style"),
            "use_ml_blend": cfg.get("use_ml_blend"),
            "ml_blend_weight": cfg.get("ml_blend_weight"),
            "scoring_type": cfg.get("scoring_type"),
        },
        roster_settings={
            "roster_slots": dict(cfg.get("slots") or {}),
            "slot_instances": list(cfg.get("slot_instances") or []),
        },
        display_name=label,
        source=SOURCE_DRAFT_SIMULATOR,
        source_draft_id=str(source_draft_id or "").strip(),
        migration_status=MIGRATION_STATUS_FULL_LEAGUE,
    )
    return upsert_league_context(session, context)


def get_league_context_for_archive(session: dict[str, Any], archive_entry: dict[str, Any]) -> dict[str, Any] | None:
    draft_id = str(archive_entry.get("draft_id") or "").strip()
    if not draft_id:
        return None
    linked_id = str(archive_entry.get("league_context_id") or "").strip()
    if linked_id:
        context = get_league_context(session, linked_id)
        if context:
            return context
    return get_league_context(session, context_id_for_archive(draft_id))


def league_context_coverage_badge(context: dict[str, Any] | None) -> str:
    if has_full_league_rosters(context):
        return "Full League Context"
    return "My Team Only / Legacy"


def league_context_type_badge(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    context_type = str(context.get("context_type") or "")
    if context_type == CONTEXT_TYPE_MOCK_DRAFT_SIMULATION:
        return "Mock Draft Simulation"
    if context_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT:
        return "Live Draft Result"
    if context_type == CONTEXT_TYPE_REAL_LEAGUE:
        return "Real League"
    return ""


def league_team_count(context: dict[str, Any] | None, archive_entry: dict[str, Any] | None = None) -> int:
    if context:
        rosters = context.get("league_rosters") or {}
        if isinstance(rosters, dict) and rosters:
            return len(rosters)
    if archive_entry:
        rosters = archive_entry.get("league_rosters") or {}
        if isinstance(rosters, dict) and rosters:
            return len(rosters)
    if archive_entry:
        return 1 if str(archive_entry.get("team_name") or "").strip() else 0
    return 0


def save_live_draft_league_context(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    my_team_name: str,
    draft_name: str = "",
    defer_activation: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Save full live-draft league context plus linked archive entry."""
    from draft_archive_state import save_live_draft_team_archive

    my_team = str(my_team_name or "").strip()
    league_rosters = build_league_rosters_from_live_room(room, my_team)
    cfg = dict(room.get("config") or {})
    label = str(draft_name or "").strip() or f"{cfg.get('league_name', 'Live Draft')} — {my_team}"
    entry = save_live_draft_team_archive(
        session,
        room,
        team_name=my_team,
        draft_name=label,
    )
    draft_id = str(entry.get("draft_id") or "")
    league_context_id = context_id_for_archive(draft_id)
    entry = save_draft_archive_with_league_context(
        session,
        draft_id=draft_id,
        league_rosters=league_rosters,
        league_context_id=league_context_id,
    )
    context = create_league_context_from_live_room(
        session,
        room,
        my_team_name=my_team,
        display_name=label,
        league_name=str(cfg.get("league_name") or "Live Draft"),
        league_context_id=league_context_id,
        source_draft_id=draft_id,
    )
    if defer_activation:
        schedule_league_context_activation(session, league_context_id, archive_id=draft_id)
    else:
        activate_league_context(session, league_context_id)
    return entry, context


def save_simulator_league_context(
    session: dict[str, Any],
    board_df: pd.DataFrame,
    *,
    my_team_name: str,
    draft_name: str = "",
    config: dict[str, Any] | None = None,
    defer_activation: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Save full mock-draft league context plus linked archive entry."""
    from draft_archive_state import save_simulator_team_archive

    my_team = str(my_team_name or "").strip()
    cfg = dict(config or session.get("draft_shared_settings") or {})
    league_rosters = build_league_rosters_from_simulator_board(board_df, my_team)
    label = str(draft_name or "").strip() or f"Simulator — {my_team}"
    entry = save_simulator_team_archive(
        session,
        board_df,
        team_name=my_team,
        draft_name=label,
        config=cfg,
    )
    draft_id = str(entry.get("draft_id") or "")
    league_context_id = context_id_for_archive(draft_id)
    entry = save_draft_archive_with_league_context(
        session,
        draft_id=draft_id,
        league_rosters=league_rosters,
        league_context_id=league_context_id,
    )
    context = create_league_context_from_simulator_board(
        session,
        board_df,
        my_team_name=my_team,
        display_name=label,
        config=cfg,
        league_context_id=league_context_id,
        source_draft_id=draft_id,
    )
    if defer_activation:
        schedule_league_context_activation(session, league_context_id, archive_id=draft_id)
    else:
        activate_league_context(session, league_context_id)
    return entry, context


def save_draft_archive_with_league_context(
    session: dict[str, Any],
    *,
    draft_id: str,
    league_rosters: dict[str, dict[str, Any]],
    league_context_id: str,
) -> dict[str, Any]:
    """Attach league_rosters and league_context_id to an existing archive entry."""
    from draft_archive_state import DRAFT_ARCHIVE_KEY, get_draft_archive

    draft_id = str(draft_id or "").strip()
    entry = get_draft_archive(session, draft_id)
    if not entry:
        return {}
    entry["league_rosters"] = copy.deepcopy(league_rosters)
    entry["league_context_id"] = str(league_context_id or "").strip()
    raw = session.get(DRAFT_ARCHIVE_KEY)
    entries = [dict(x) for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []
    for i, existing in enumerate(entries):
        if str(existing.get("draft_id") or "") == draft_id:
            entries[i] = copy.deepcopy(entry)
            break
    session[DRAFT_ARCHIVE_KEY] = entries
    return copy.deepcopy(entry)


def activate_archive_league_context(
    session: dict[str, Any],
    draft_id: str,
    *,
    defer_activation: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Activate saved draft archive and linked Fantasy League Context."""
    from draft_archive_state import activate_draft_archive, get_draft_archive

    draft_id = str(draft_id or "").strip()
    if defer_activation:
        entry = get_draft_archive(session, draft_id)
        if not entry:
            return None, None
        migrate_legacy_archives_to_contexts(session)
        league_context_id = str(entry.get("league_context_id") or context_id_for_archive(draft_id)).strip()
        schedule_league_context_activation(session, league_context_id, archive_id=draft_id)
        context = get_league_context(session, league_context_id)
        return entry, context
    entry = activate_draft_archive(session, draft_id)
    if not entry:
        return None, None
    migrate_legacy_archives_to_contexts(session)
    league_context_id = str(entry.get("league_context_id") or context_id_for_archive(draft_id)).strip()
    context = activate_league_context(session, league_context_id)
    return entry, context


def migrate_legacy_archives_to_contexts(session: dict[str, Any]) -> int:
    """Lazy-upgrade draft_archive_teams entries into fantasy league contexts."""
    store = ensure_fantasy_league_context_state(session)
    migration = store.setdefault("legacy_migration", {"migrated_archive_ids": [], "archives_scanned_at": ""})
    if not isinstance(migration, dict):
        migration = {"migrated_archive_ids": [], "archives_scanned_at": ""}
        store["legacy_migration"] = migration
    migrated_ids = {str(x).strip() for x in (migration.get("migrated_archive_ids") or []) if str(x).strip()}
    contexts = store.setdefault("contexts", {})
    if not isinstance(contexts, dict):
        contexts = {}
        store["contexts"] = contexts

    raw_archives = session.get(DRAFT_ARCHIVE_KEY)
    archives = [dict(x) for x in raw_archives if isinstance(x, dict)] if isinstance(raw_archives, list) else []
    created = 0
    for archive in archives:
        draft_id = str(archive.get("draft_id") or "").strip()
        if not draft_id:
            continue
        league_context_id = context_id_for_archive(draft_id)
        if league_context_id in contexts:
            migrated_ids.add(draft_id)
            continue
        if draft_id in migrated_ids and league_context_id in contexts:
            continue
        context = migrate_archive_to_league_context(archive)
        contexts[league_context_id] = context
        migrated_ids.add(draft_id)
        created += 1

    migration["migrated_archive_ids"] = sorted(migrated_ids)
    migration["archives_scanned_at"] = _utc_now_iso()

    active_archive_id = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    active_context_id = str(store.get("active_league_context_id") or "").strip()
    if active_archive_id and not active_context_id:
        archive_context_id = context_id_for_archive(active_archive_id)
        if archive_context_id in contexts:
            store["active_league_context_id"] = archive_context_id
    elif active_context_id and active_context_id in contexts and not active_archive_id:
        _sync_legacy_archive_aliases(session, contexts[active_context_id])

    return created


def apply_fantasy_league_context_disk_state(session: dict[str, Any], state: dict[str, Any]) -> None:
    """Restore league context store from disk/cloud and run legacy archive migration."""
    blob = state.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY)
    if isinstance(blob, dict):
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = copy.deepcopy(blob)
    else:
        ensure_fantasy_league_context_state(session)
    migrate_legacy_archives_to_contexts(session)
    migrate_global_pending_trade_targets(session)
