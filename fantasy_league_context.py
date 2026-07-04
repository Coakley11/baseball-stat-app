"""Fantasy League Context — full league state, ownership, and persistence."""

from __future__ import annotations

import copy
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
    }


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
        migration_status=MIGRATION_STATUS_FULL_LEAGUE,
    )
    return upsert_league_context(session, context)


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
