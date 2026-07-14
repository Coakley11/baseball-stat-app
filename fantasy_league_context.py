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
    DRAFT_TYPE_IMPORTED,
    DRAFT_TYPE_LIVE,
    DRAFT_TYPE_SIMULATOR,
    get_draft_archive,
    set_active_draft_archive,
)

FANTASY_LEAGUE_CONTEXT_STATE_KEY = "fantasy_league_context_state"
SIMULATOR_SESSION_LIBRARY_DRAFT_KEY = "_simulator_session_library_draft_id"
SCHEMA_VERSION = 1

CONTEXT_TYPE_REAL_LEAGUE = "real_league"
CONTEXT_TYPE_LIVE_DRAFT_RESULT = "live_draft_result"
CONTEXT_TYPE_MOCK_DRAFT_SIMULATION = "mock_draft_simulation"

EPHEMERAL_CONTEXT_PREFIX = "__ephemeral_"


def is_ephemeral_league_context_id(league_context_id: str) -> bool:
    """True for temporary workspace board ids that must never link saved library rows."""
    return str(league_context_id or "").strip().startswith(EPHEMERAL_CONTEXT_PREFIX)

MIGRATION_STATUS_FULL_LEAGUE = "full_league"
MIGRATION_STATUS_SINGLE_TEAM_LEGACY = "single_team_legacy"

SOURCE_LIVE_DRAFT_ROOM = "live_draft_room"
SOURCE_DRAFT_SIMULATOR = "draft_simulator"
SOURCE_IMPORTED_DRAFT = "imported_draft"
SOURCE_LEGACY_MIGRATION = "legacy_migration"

CREATION_ORIGIN_VALIDATED_IMPORT = "validated_import"
CREATION_ORIGIN_LIVE_DRAFT_ROOM = "live_draft_room"
CREATION_ORIGIN_DRAFT_SIMULATOR = "draft_simulator"


def stamp_immutable_creation_origin(metadata: dict[str, Any] | None, origin: str) -> dict[str, Any]:
    """Set creation_origin only when absent — never overwrite on sync/repair."""
    meta = dict(metadata or {})
    if not str(meta.get("creation_origin") or "").strip():
        stamped = str(origin or "").strip()
        if stamped:
            meta["creation_origin"] = stamped
    return meta


def read_immutable_creation_origin(
    *,
    context: dict[str, Any] | None = None,
    shared_doc: dict[str, Any] | None = None,
    archive_entry: dict[str, Any] | None = None,
) -> str:
    shared_meta = dict((shared_doc or {}).get("metadata") or {}) if isinstance(shared_doc, dict) else {}
    for source in (
        dict((context or {}).get("metadata") or {}),
        shared_meta,
        shared_doc if isinstance(shared_doc, dict) else {},
        archive_entry if isinstance(archive_entry, dict) else {},
    ):
        origin = str(source.get("creation_origin") or "").strip()
        if origin:
            return origin
    return ""


def _infer_creation_origin_for_backfill(
    *,
    context: dict[str, Any] | None = None,
    shared_doc: dict[str, Any] | None = None,
    archive_entry: dict[str, Any] | None = None,
) -> str:
    """Infer immutable creation provenance for legacy rows missing creation_origin."""
    existing = read_immutable_creation_origin(
        context=context,
        shared_doc=shared_doc,
        archive_entry=archive_entry,
    )
    if existing:
        return existing

    evidence = collect_origin_evidence(
        context=context,
        shared_doc=shared_doc,
        archive_entry=archive_entry,
    )
    import_creation = _verified_import_creation_event(evidence, context=context, shared_doc=shared_doc)
    live_creation = _verified_live_creation_event(evidence, context=context, shared_doc=shared_doc)

    if import_creation and not live_creation:
        return CREATION_ORIGIN_VALIDATED_IMPORT
    if live_creation and not import_creation:
        return CREATION_ORIGIN_LIVE_DRAFT_ROOM
    if evidence.get("live_evidence_found") and evidence.get("import_evidence_found"):
        return ""

    if evidence.get("import_evidence_found") and not evidence.get("live_evidence_found"):
        return CREATION_ORIGIN_VALIDATED_IMPORT
    if evidence.get("live_evidence_found") and not evidence.get("import_evidence_found"):
        return CREATION_ORIGIN_LIVE_DRAFT_ROOM

    if isinstance(context, dict) and str(context.get("source") or "") == SOURCE_IMPORTED_DRAFT:
        return CREATION_ORIGIN_VALIDATED_IMPORT
    if isinstance(context, dict) and str(context.get("source") or "") == SOURCE_LIVE_DRAFT_ROOM:
        return CREATION_ORIGIN_LIVE_DRAFT_ROOM
    if isinstance(archive_entry, dict) and str(archive_entry.get("draft_type") or "") == DRAFT_TYPE_IMPORTED:
        return CREATION_ORIGIN_VALIDATED_IMPORT
    if isinstance(archive_entry, dict) and str(archive_entry.get("draft_type") or "") == DRAFT_TYPE_LIVE:
        return CREATION_ORIGIN_LIVE_DRAFT_ROOM
    return ""


def _verified_import_creation_event(
    evidence: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    shared_doc: dict[str, Any] | None = None,
) -> bool:
    if evidence.get("explicit_import_origin"):
        return True
    for blob in (shared_doc, context, dict((context or {}).get("metadata") or {})):
        if not isinstance(blob, dict):
            continue
        for key in ("created_from", "source_draft_type", "source"):
            val = str(blob.get(key) or "").strip().lower()
            if val in {"validated_import", "imported_draft", "uploaded_draft", "draft_import"}:
                return True
    return False


def _verified_live_creation_event(
    evidence: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    shared_doc: dict[str, Any] | None = None,
) -> bool:
    if str(evidence.get("context_type") or "") == CONTEXT_TYPE_LIVE_DRAFT_RESULT:
        return True
    if evidence.get("explicit_live_origin"):
        return True
    for blob in (shared_doc, context, dict((context or {}).get("metadata") or {})):
        if not isinstance(blob, dict):
            continue
        for key in ("created_from", "source_draft_type", "source"):
            val = str(blob.get(key) or "").strip().lower()
            if val in {SOURCE_LIVE_DRAFT_ROOM, DRAFT_TYPE_LIVE, "live_draft"}:
                return True
    return False


def backfill_immutable_creation_origins(session: dict[str, Any]) -> int:
    """Backfill creation_origin on contexts and shared docs without changing active selection."""
    try:
        from fantasy_creation_origin_repair import repair_known_canonical_creation_origins

        repair_known_canonical_creation_origins(session)
    except ImportError:
        pass
    updated = 0
    for ctx in list_league_contexts(session):
        if not isinstance(ctx, dict):
            continue
        ctx_id = str(ctx.get("league_context_id") or "").strip()
        meta = dict(ctx.get("metadata") or {})
        if str(meta.get("creation_origin") or "").strip():
            continue
        shared_doc = None
        try:
            from fantasy_league_identity import resolve_canonical_league_id
            from fantasy_shared_league_store import load_shared_league

            league_id = str(resolve_canonical_league_id(ctx) or "").strip()
            if league_id:
                shared_doc = load_shared_league(league_id)
        except ImportError:
            shared_doc = None
        draft_id = str(meta.get("source_draft_id") or "").strip()
        archive_entry = get_draft_archive(session, draft_id) if draft_id else None
        origin = _infer_creation_origin_for_backfill(
            context=ctx,
            shared_doc=shared_doc if isinstance(shared_doc, dict) else None,
            archive_entry=archive_entry if isinstance(archive_entry, dict) else None,
        )
        if not origin:
            continue
        meta = stamp_immutable_creation_origin(meta, origin)
        ctx = dict(ctx)
        ctx["metadata"] = meta
        upsert_league_context(session, ctx, mark_persist_authoritative=False)
        updated += 1
        if isinstance(shared_doc, dict):
            try:
                from fantasy_shared_league_store import save_shared_league

                shared_copy = dict(shared_doc)
                if not str(shared_copy.get("creation_origin") or "").strip():
                    shared_copy["creation_origin"] = origin
                    save_shared_league(shared_copy)
            except ImportError:
                pass
    return updated


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
    if str(draft_type or "") == DRAFT_TYPE_IMPORTED:
        return CONTEXT_TYPE_REAL_LEAGUE
    return CONTEXT_TYPE_MOCK_DRAFT_SIMULATION


def _players_from_archive_entry(archive_entry: dict[str, Any]) -> list[dict[str, Any]]:
    team_name = str(archive_entry.get("team_name") or "").strip()
    rows = [dict(r) for r in (archive_entry.get("players") or []) if isinstance(r, dict)]
    return [_normalize_player_entry(row, team_name=team_name) for row in rows if _player_name_from_row(row)]


def _league_rosters_from_archive_entry(
    archive_entry: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], str, str]:
    """Build league_rosters plus migration_status and metadata source from a saved archive."""
    team_name = str(archive_entry.get("team_name") or "").strip()
    draft_type = str(archive_entry.get("draft_type") or "").strip()
    raw_rosters = archive_entry.get("league_rosters")
    if isinstance(raw_rosters, dict) and raw_rosters:
        league_rosters: dict[str, dict[str, Any]] = {}
        for roster_team, team_entry in raw_rosters.items():
            if not isinstance(team_entry, dict):
                continue
            team = str(roster_team or team_entry.get("team_name") or "").strip()
            if not team:
                continue
            players = [
                _normalize_player_entry(dict(row), team_name=team)
                for row in (team_entry.get("players") or [])
                if isinstance(row, dict) and _player_name_from_row(row)
            ]
            is_user_team = bool(team_entry.get("is_user_team")) or (team == team_name)
            league_rosters[team] = _team_roster_entry(team, players, is_user_team=is_user_team)
        if league_rosters:
            if len(league_rosters) >= 2 or draft_type == DRAFT_TYPE_IMPORTED:
                source = SOURCE_IMPORTED_DRAFT if draft_type == DRAFT_TYPE_IMPORTED else SOURCE_LEGACY_MIGRATION
                return league_rosters, MIGRATION_STATUS_FULL_LEAGUE, source
            return league_rosters, MIGRATION_STATUS_SINGLE_TEAM_LEGACY, SOURCE_LEGACY_MIGRATION

    players = _players_from_archive_entry(archive_entry)
    league_rosters = {
        team_name: _team_roster_entry(team_name, players, is_user_team=True),
    } if team_name else {}
    return league_rosters, MIGRATION_STATUS_SINGLE_TEAM_LEGACY, SOURCE_LEGACY_MIGRATION


def migrate_archive_to_league_context(archive_entry: dict[str, Any]) -> dict[str, Any]:
    """Convert one legacy saved draft archive into a Fantasy League Context."""
    draft_id = str(archive_entry.get("draft_id") or "").strip()
    team_name = str(archive_entry.get("team_name") or "").strip()
    draft_name = str(archive_entry.get("draft_name") or "").strip() or "Saved Draft"
    now = _utc_now_iso()
    created = str(archive_entry.get("created_at") or now)
    league_context_id = context_id_for_archive(draft_id)
    league_rosters, migration_status, source = _league_rosters_from_archive_entry(archive_entry)
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
            "source": source,
            "migration_status": migration_status,
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
        "trade_proposals": [],
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
        "trade_proposals",
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
    player_name = str(handoff.get("player_name") or "").strip()
    league_context_id = str(handoff.get("league_context_id") or "").strip()
    my_team = ""
    try:
        from fantasy_league_context import get_active_league_context
        from fantasy_league_team_ownership import owned_team_for_user

        active = get_active_league_context(session) or {}
        my_team = owned_team_for_user(active) or str(active.get("my_team_name") or "").strip()
        if not league_context_id:
            league_context_id = str(active.get("league_context_id") or "").strip()
    except ImportError:
        active = {}

    try:
        from player_trade_handoff import TRADE_CENTER_HANDOFF_KEY, build_trade_center_handoff_payload

        payload = build_trade_center_handoff_payload(
            mode=mode,
            player_name=player_name,
            league_context_id=league_context_id,
            my_team=my_team,
            owner_team=owner_team,
        )
        if payload.get("give_players") or payload.get("receive_players"):
            session["_lineup_focus_trade_center"] = True
            session[TRADE_CENTER_HANDOFF_KEY] = payload
    except ImportError:
        give_players: list[str] = []
        receive_players: list[str] = []
        other_team = ""
        if mode == TRADE_MODE_TRADE_AWAY and player_name:
            give_players = [player_name]
        elif mode == TRADE_MODE_ACQUIRE and player_name:
            receive_players = [player_name]
            other_team = owner_team
        if give_players or receive_players:
            session["_lineup_focus_trade_center"] = True
            session["_trade_center_handoff"] = {
                "action": "use",
                "give_players": give_players,
                "receive_players": receive_players,
                "other_team": other_team,
                "trade_partner": other_team or "Any team",
                "auto_analyze": False,
            }
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
    try:
        from fantasy_workspace_team_identity import overlay_workspace_team_on_context

        overlaid = overlay_workspace_team_on_context(
            session,
            ctx,
            trace_phase="get_league_context",
            record_trace=False,
        )
        return overlaid if isinstance(overlaid, dict) else copy.deepcopy(ctx)
    except ImportError:
        return copy.deepcopy(ctx)


def get_active_league_context(
    session: dict[str, Any],
    *,
    respect_source_priority: bool = True,
) -> dict[str, Any] | None:
    """Return the league context feeding fantasy pages.

    When ``respect_source_priority`` is True (default), delegates to
    ``fantasy_context_source.get_effective_fantasy_context`` so live/simulator
    overrides can win over the Saved Draft Library Active Draft. Pass False to
    read only the persisted Active Draft (library UI, activation flows).
    """
    if respect_source_priority:
        try:
            from fantasy_context_source import get_effective_fantasy_context

            effective = get_effective_fantasy_context(session)
            if effective is not None:
                return effective
        except ImportError:
            pass
    store = ensure_fantasy_league_context_state(session)
    active_id = str(store.get("active_league_context_id") or "").strip()
    if not active_id:
        return None
    return get_league_context(session, active_id)


def fingerprint_payload_for_archive_save(
    *,
    league_rosters: dict[str, dict[str, Any]],
    config: dict[str, Any] | None = None,
    fantasy_format: str = "",
) -> dict[str, Any]:
    """Build a content-only payload for canonical draft fingerprinting."""
    cfg = dict(config or {})
    return {
        "league_rosters": league_rosters,
        "fantasy_format": str(
            fantasy_format or cfg.get("fantasy_format") or cfg.get("scoring_type") or ""
        ).strip(),
        "scoring_settings": {
            "projection_window": cfg.get("projection_window"),
            "projection_style": cfg.get("projection_style"),
            "use_ml_blend": cfg.get("use_ml_blend"),
            "ml_blend_weight": cfg.get("ml_blend_weight"),
            "scoring_type": cfg.get("scoring_type"),
        },
        "roster_settings": {
            "roster_slots": dict(cfg.get("slots") or {}),
            "slot_instances": list(cfg.get("slot_instances") or []),
        },
    }


def compute_save_draft_fingerprint(
    *,
    league_rosters: dict[str, dict[str, Any]],
    config: dict[str, Any] | None = None,
    fantasy_format: str = "",
) -> str:
    try:
        from fantasy_league_identity import compute_draft_fingerprint

        payload = fingerprint_payload_for_archive_save(
            league_rosters=league_rosters,
            config=config,
            fantasy_format=fantasy_format,
        )
        return compute_draft_fingerprint(payload)
    except ImportError:
        return ""


def find_archive_by_draft_fingerprint(session: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    """Return the first saved archive matching a canonical draft fingerprint."""
    fingerprint = str(fingerprint or "").strip()
    if not fingerprint:
        return None
    try:
        from draft_archive_state import get_draft_archive, list_draft_archives
    except ImportError:
        return None
    for entry in list_draft_archives(session):
        stored = str(entry.get("draft_fingerprint") or "").strip()
        if stored and stored == fingerprint:
            return get_draft_archive(session, str(entry.get("draft_id") or ""))
        rosters = entry.get("league_rosters")
        if isinstance(rosters, dict) and rosters:
            fp = compute_save_draft_fingerprint(
                league_rosters=rosters,
                config={
                    "fantasy_format": entry.get("fantasy_format"),
                    "slots": entry.get("roster_slots"),
                    "slot_instances": entry.get("slot_instances"),
                    **(entry.get("projection_settings") or {}),
                },
                fantasy_format=str(entry.get("fantasy_format") or ""),
            )
            if fp and fp == fingerprint:
                return get_draft_archive(session, str(entry.get("draft_id") or ""))
    return None


def find_league_context_by_draft_fingerprint(
    session: dict[str, Any],
    fingerprint: str,
) -> dict[str, Any] | None:
    """Return a saved league context with the same canonical draft fingerprint."""
    fingerprint = str(fingerprint or "").strip()
    if not fingerprint:
        return None
    store = ensure_fantasy_league_context_state(session)
    contexts = store.get("contexts") or {}
    if not isinstance(contexts, dict):
        return None
    for ctx in contexts.values():
        if not isinstance(ctx, dict):
            continue
        ctx_id = str(ctx.get("league_context_id") or "").strip()
        if is_ephemeral_league_context_id(ctx_id):
            continue
        meta = ctx.get("metadata") or {}
        stored = str(meta.get("draft_fingerprint") or "").strip()
        if stored and stored == fingerprint:
            return copy.deepcopy(ctx)
        fp = compute_save_draft_fingerprint(
            league_rosters=dict(ctx.get("league_rosters") or {}),
            config={
                "fantasy_format": ctx.get("fantasy_format"),
                "slots": (ctx.get("roster_settings") or {}).get("roster_slots"),
                "slot_instances": (ctx.get("roster_settings") or {}).get("slot_instances"),
                **(ctx.get("scoring_settings") or {}),
            },
            fantasy_format=str(ctx.get("fantasy_format") or ""),
        )
        if fp and fp == fingerprint:
            return copy.deepcopy(ctx)
    return None


def resolve_canonical_save_ids(
    session: dict[str, Any],
    *,
    league_rosters: dict[str, dict[str, Any]],
    config: dict[str, Any] | None = None,
    fantasy_format: str = "",
    draft_id: str | None = None,
    league_context_id: str | None = None,
) -> tuple[str | None, str | None, str]:
    """Resolve stable archive/context ids for duplicate saves of the same draft content."""
    fingerprint = compute_save_draft_fingerprint(
        league_rosters=league_rosters,
        config=config,
        fantasy_format=fantasy_format,
    )
    if not fingerprint:
        return (str(draft_id).strip() or None, str(league_context_id).strip() or None, "")

    existing_archive = find_archive_by_draft_fingerprint(session, fingerprint)
    if existing_archive:
        draft_id = str(existing_archive.get("draft_id") or draft_id or "").strip() or None
        linked = str(existing_archive.get("league_context_id") or league_context_id or "").strip()
        if linked and not is_ephemeral_league_context_id(linked):
            league_context_id = linked or None
    existing_context = find_league_context_by_draft_fingerprint(session, fingerprint)
    if existing_context and not league_context_id:
        candidate = str(existing_context.get("league_context_id") or "").strip()
        if candidate and not is_ephemeral_league_context_id(candidate):
            league_context_id = candidate or None
    if draft_id and not league_context_id:
        league_context_id = context_id_for_archive(str(draft_id))
    return draft_id, league_context_id, fingerprint


def context_has_roster_slots(context: dict[str, Any] | None) -> bool:
    """True when a saved context carries explicit roster-slot rules.

    Live drafts and custom-slot drafts store roster_slots / slot_instances.
    Mock-draft simulations saved without slot settings return False so callers
    can skip positional completion checks instead of inventing a default format.
    """
    if not isinstance(context, dict):
        return False
    roster_settings = context.get("roster_settings")
    if not isinstance(roster_settings, dict):
        return False
    roster_slots = roster_settings.get("roster_slots") or {}
    if isinstance(roster_slots, dict) and any(
        int(v or 0) > 0 for v in roster_slots.values()
    ):
        return True
    slot_instances = roster_settings.get("slot_instances") or []
    return bool(isinstance(slot_instances, list) and slot_instances)


def resolve_context_draft_slot_config(context: dict[str, Any] | None) -> dict[str, Any]:
    """Normalized draft slot config from an active league context."""
    if not context_has_roster_slots(context):
        return {}
    roster_settings = context.get("roster_settings") or {}
    roster_slots = dict(roster_settings.get("roster_slots") or {})
    slot_instances = list(roster_settings.get("slot_instances") or [])
    raw = {"slots": roster_slots, "slot_instances": slot_instances}
    try:
        from live_draft_roster_slots import normalize_draft_slot_config

        return normalize_draft_slot_config(raw)
    except ImportError:
        return raw


def resolve_context_lineup_slots(context: dict[str, Any] | None) -> list[str] | None:
    """Starter slot tokens for Lineup Assistant from active context roster settings."""
    config = resolve_context_draft_slot_config(context)
    if not config.get("slots") and not config.get("slot_instances"):
        return None
    try:
        from live_draft_roster_slots import get_active_draft_roster_slots

        instances = get_active_draft_roster_slots(config)
    except ImportError:
        return None
    if not instances:
        return None
    lineup_slots: list[str] = []
    for inst in instances:
        pos = str(inst.get("position") or "").strip().upper()
        if pos in ("BN", "P", "SP", "RP"):
            continue
        if pos == "DH":
            pos = "UTIL"
        lineup_slots.append(pos)
    return lineup_slots or None


def resolve_context_bench_slot_count(context: dict[str, Any] | None) -> int | None:
    """BN slot count from active context, or None when context has no roster settings."""
    config = resolve_context_draft_slot_config(context)
    slots = config.get("slots")
    if not isinstance(slots, dict) or not slots:
        return None
    return int(slots.get("BN", 0) or 0)


def resolve_context_open_position_needs(
    context: dict[str, Any] | None,
    roster_df: Any,
) -> list[str]:
    """Open roster slot codes from active context (e.g. ['OF', 'SS'])."""
    config = resolve_context_draft_slot_config(context)
    if not config.get("slots") and not config.get("slot_instances"):
        return []
    try:
        from live_draft_roster_slots import get_remaining_position_needs

        return list(get_remaining_position_needs(roster_df, config) or [])
    except ImportError:
        return []


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
    try:
        from fantasy_trade_roster_sync import invalidate_fantasy_roster_view_caches

        invalidate_fantasy_roster_view_caches(session)
    except ImportError:
        session.pop("fantasy_current_roster_stats", None)
        session.pop("fantasy_current_standings", None)
    try:
        from resolved_fantasy_context import invalidate_resolved_fantasy_context

        invalidate_resolved_fantasy_context(session)
    except ImportError:
        pass
    try:
        from fantasy_context_source import invalidate_fantasy_workflow_descriptor_cache

        invalidate_fantasy_workflow_descriptor_cache(session)
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
        "player_count": archive_my_team_player_count(entry, context=context),
        "league_save": bool(league_save),
        "coverage": league_context_coverage_badge(context),
        "offer_set_active": True,
    }


def pop_league_context_save_flash(session: dict[str, Any]) -> dict[str, Any] | None:
    flash = session.pop(LEAGUE_CONTEXT_SAVE_FLASH_KEY, None)
    return dict(flash) if isinstance(flash, dict) else None


def schedule_active_context_resync(session: dict[str, Any]) -> bool:
    """Re-apply active league context aliases before fantasy page navigation."""
    migrate_legacy_archives_to_contexts(session)
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
    try:
        from fantasy_league_team_ownership import get_team_ownership
        from fantasy_shared_league_store import (
            build_team_ownership_sync_diagnostics,
            sync_context_with_shared_store,
        )

        ownership_before = copy.deepcopy(get_team_ownership(context))
        local_revision = int((context.get("metadata") or {}).get("shared_revision") or 0)
        context = sync_context_with_shared_store(session, context)
        ownership_after = copy.deepcopy(get_team_ownership(context))
        shared_revision = int((context.get("metadata") or {}).get("shared_revision") or 0)
        if ownership_before != ownership_after or shared_revision > local_revision:
            session["_suite_last_set_active_sync_trace"] = {
                "trigger": "activate_league_context",
                "league_context_id": league_context_id,
                "ownership_sync": build_team_ownership_sync_diagnostics(context),
                "synced": ownership_before != ownership_after,
                "shared_revision_before": local_revision,
                "shared_revision_after": shared_revision,
                "ownership_before": ownership_before,
                "ownership_after": ownership_after,
                "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
    except ImportError:
        pass
    _clear_fantasy_context_caches(session)
    return context


def delete_league_context_for_archive(session: dict[str, Any], draft_id: str) -> bool:
    """Remove the league context linked to a saved draft archive entry."""
    draft_id = str(draft_id or "").strip()
    if not draft_id:
        return False
    league_context_id = context_id_for_archive(draft_id)
    store = ensure_fantasy_league_context_state(session)
    contexts = store.get("contexts")
    if not isinstance(contexts, dict) or league_context_id not in contexts:
        return False
    del contexts[league_context_id]
    if str(store.get("active_league_context_id") or "").strip() == league_context_id:
        store["active_league_context_id"] = ""
        clear_active_league_context(session)
    tombstones = store.setdefault("deleted_context_ids", [])
    if isinstance(tombstones, list) and league_context_id not in tombstones:
        tombstones.append(league_context_id)
    try:
        from workflow_persist_guard import mark_workflow_persist_authoritative

        mark_workflow_persist_authoritative(session)
    except ImportError:
        pass
    return True


def upsert_league_context(
    session: dict[str, Any],
    context: dict[str, Any],
    *,
    mark_persist_authoritative: bool = True,
) -> dict[str, Any]:
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
    try:
        from fantasy_league_identity import ensure_league_identity

        context = ensure_league_identity(context)
    except ImportError:
        pass
    context["schema_version"] = SCHEMA_VERSION
    context["ownership_map"] = build_ownership_map(context)
    contexts = store.setdefault("contexts", {})
    if not isinstance(contexts, dict):
        contexts = {}
        store["contexts"] = contexts
    contexts[league_context_id] = copy.deepcopy(context)
    if mark_persist_authoritative:
        try:
            from workflow_persist_guard import mark_workflow_persist_authoritative

            mark_workflow_persist_authoritative(session)
        except ImportError:
            pass
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
    persist: bool = True,
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
    try:
        from live_draft_lineup_config import build_live_draft_slot_config, persist_live_draft_lineup_metadata

        slot_cfg = build_live_draft_slot_config(
            roster_size=int(cfg.get("rounds") or cfg.get("roster_size") or 0) or 0,
            slots=dict(cfg.get("slots") or {}),
        )
        if not slot_cfg.get("slots"):
            slot_cfg = {"slots": dict(cfg.get("slots") or {}), "slot_instances": list(cfg.get("slot_instances") or [])}
        context = persist_live_draft_lineup_metadata(
            context,
            slot_cfg,
            roster_size=int(cfg.get("rounds") or cfg.get("roster_size") or 0),
            draft_rounds=int(cfg.get("rounds") or 0),
            team_count=int(cfg.get("team_count") or len(league_rosters)),
        )
    except ImportError:
        pass
    meta = stamp_immutable_creation_origin(dict(context.get("metadata") or {}), CREATION_ORIGIN_LIVE_DRAFT_ROOM)
    context["metadata"] = meta
    if persist:
        return upsert_league_context(session, context)
    return context


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
    persist: bool = True,
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
    if persist:
        return upsert_league_context(session, context)
    return context


def create_league_context_from_imported_board(
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
    """Build a real_league Fantasy League Context from a validated imported board."""
    cfg = dict(config or session.get("draft_shared_settings") or {})
    my_team = str(my_team_name or "").strip()
    league_rosters = build_league_rosters_from_simulator_board(board_df, my_team)
    label = str(display_name or league_name or "").strip() or f"Imported League — {my_team}"
    context_id = str(league_context_id or f"import:{uuid.uuid4().hex[:12]}")
    context = create_league_context(
        league_context_id=context_id,
        context_type=CONTEXT_TYPE_REAL_LEAGUE,
        league_name=str(league_name or label).strip() or label,
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
        source=SOURCE_IMPORTED_DRAFT,
        source_draft_id=str(source_draft_id or "").strip(),
        migration_status=MIGRATION_STATUS_FULL_LEAGUE,
    )
    meta = stamp_immutable_creation_origin(dict(context.get("metadata") or {}), CREATION_ORIGIN_VALIDATED_IMPORT)
    meta["created_from"] = str(meta.get("created_from") or "validated_import").strip() or "validated_import"
    context["metadata"] = meta
    return upsert_league_context(session, context)


def save_imported_league_context(
    session: dict[str, Any],
    board_df: pd.DataFrame,
    *,
    my_team_name: str,
    draft_name: str = "",
    league_name: str = "",
    config: dict[str, Any] | None = None,
    defer_activation: bool = False,
    save_only: bool = False,
    assign_team: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Save validated imported draft as real_league context + archive.

    save_only=True: persist to library without activating (user must Set Active separately).
    """
    from draft_archive_state import save_imported_draft_archive

    my_team = str(my_team_name or "").strip()
    if not my_team:
        raise ValueError("my_team_name is required to save an imported league.")
    cfg = dict(config or session.get("draft_shared_settings") or {})
    league_rosters = build_league_rosters_from_simulator_board(board_df, my_team)
    if not league_rosters:
        raise ValueError("Imported board has no team rosters.")
    label = str(draft_name or league_name or "").strip() or f"Imported League — {my_team}"
    draft_id, league_context_id, _fp = resolve_canonical_save_ids(
        session,
        league_rosters=league_rosters,
        config=cfg,
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or ""),
    )
    entry = save_imported_draft_archive(
        session,
        board_df,
        team_name=my_team,
        draft_name=label,
        config=cfg,
        draft_id=draft_id,
        league_rosters=league_rosters,
        league_context_id=league_context_id,
    )
    draft_id = str(entry.get("draft_id") or "")
    league_context_id = str(
        entry.get("league_context_id") or league_context_id or context_id_for_archive(draft_id)
    ).strip()
    entry = save_draft_archive_with_league_context(
        session,
        draft_id=draft_id,
        league_rosters=league_rosters,
        league_context_id=league_context_id,
    )
    context = create_league_context_from_imported_board(
        session,
        board_df,
        my_team_name=my_team,
        display_name=label,
        league_name=str(league_name or label).strip() or label,
        config=cfg,
        league_context_id=league_context_id,
        source_draft_id=draft_id,
    )
    if save_only:
        if assign_team:
            try:
                from fantasy_league_team_ownership import assign_team_owner_to_context

                context = assign_team_owner_to_context(context, my_team)
                context["my_team_name"] = my_team
                context = upsert_league_context(session, context)
            except ImportError:
                pass
    elif defer_activation:
        schedule_league_context_activation(session, league_context_id, archive_id=draft_id)
    else:
        activate_league_context(session, league_context_id)
        if assign_team:
            try:
                from fantasy_league_team_ownership import assign_my_team

                context, err = assign_my_team(session, my_team)
                if err:
                    raise ValueError(err)
            except ImportError:
                pass
    context = get_league_context(session, league_context_id) or context
    meta = dict(context.get("metadata") or {})
    if not str(meta.get("commissioner_user_id") or "").strip() and assign_team:
        try:
            from fantasy_league_team_ownership import _resolve_user_id

            commissioner = str(_resolve_user_id() or "").strip()
            if commissioner:
                meta["commissioner_user_id"] = commissioner
                context["metadata"] = meta
                context = upsert_league_context(session, context)
        except ImportError:
            pass
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        push_league_context_to_shared(session, context)
    except (ImportError, RuntimeError, OSError):
        pass
    context = get_league_context(session, league_context_id) or context
    return entry, context


def get_league_context_for_archive(session: dict[str, Any], archive_entry: dict[str, Any]) -> dict[str, Any] | None:
    draft_id = str(archive_entry.get("draft_id") or "").strip()
    if not draft_id:
        return None
    linked_id = str(archive_entry.get("league_context_id") or "").strip()
    if linked_id and not is_ephemeral_league_context_id(linked_id):
        context = get_league_context(session, linked_id)
        if context:
            return context
    return get_league_context(session, context_id_for_archive(draft_id))


def league_context_coverage_badge(context: dict[str, Any] | None) -> str:
    if has_full_league_rosters(context):
        return "Full League Draft"
    return "Incomplete — re-save draft"


def league_context_type_badge(
    context: dict[str, Any] | None,
    archive_entry: dict[str, Any] | None = None,
) -> str:
    if not context and not archive_entry:
        return ""
    try:
        from fantasy_context_terminology import league_context_type_badge as _terminology_badge

        return _terminology_badge(context, archive_entry)
    except ImportError:
        if not context:
            return ""
        context_type = str(context.get("context_type") or "")
        if context_type == CONTEXT_TYPE_MOCK_DRAFT_SIMULATION:
            return "Mock Draft"
        if context_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT:
            return "Live Draft"
        if context_type == CONTEXT_TYPE_REAL_LEAGUE:
            return "Uploaded League"
        return ""


def league_team_names(context: dict[str, Any] | None, archive_entry: dict[str, Any] | None = None) -> list[str]:
    """Fantasy team names from league context or archive rosters."""
    rosters: dict[str, Any] = {}
    if context:
        rosters = dict(context.get("league_rosters") or {})
    if not rosters and archive_entry:
        rosters = dict(archive_entry.get("league_rosters") or {})
    if rosters:
        return sorted(str(name).strip() for name in rosters.keys() if str(name).strip())
    if archive_entry:
        team = str(archive_entry.get("team_name") or "").strip()
        return [team] if team else []
    return []


def filter_roster_stats_to_league_teams(
    roster_df: pd.DataFrame,
    context: dict[str, Any] | None,
    *,
    archive_entry: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Keep only rows for teams in the active league context."""
    if roster_df is None or getattr(roster_df, "empty", True) or "Team" not in roster_df.columns:
        return roster_df
    teams = set(league_team_names(context, archive_entry))
    if not teams:
        return roster_df
    filtered = roster_df[roster_df["Team"].astype(str).isin(teams)].copy()
    return filtered if not filtered.empty else roster_df


def league_team_count(context: dict[str, Any] | None, archive_entry: dict[str, Any] | None = None) -> int:
    names = league_team_names(context, archive_entry)
    if names:
        return len(names)
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


def archive_card_team_count(archive_entry: dict[str, Any] | None) -> int:
    """Immutable team count for Saved Draft Library cards (snapshot only)."""
    entry = dict(archive_entry or {})
    snap = entry.get("snapshot")
    if isinstance(snap, dict) and snap.get("team_count") is not None:
        return int(snap.get("team_count") or 0)
    rosters = dict(entry.get("league_rosters") or {})
    if rosters:
        return len([str(k).strip() for k in rosters.keys() if str(k).strip()])
    return 1 if str(entry.get("team_name") or "").strip() else 0


def archive_card_player_count(archive_entry: dict[str, Any] | None) -> int:
    """Immutable roster count for Saved Draft Library cards (snapshot only)."""
    entry = dict(archive_entry or {})
    snap = entry.get("snapshot")
    if isinstance(snap, dict) and snap.get("my_team_player_count") is not None:
        return int(snap.get("my_team_player_count") or 0)
    return archive_my_team_player_count(entry, context=None)


def archive_my_team_player_count(
    archive_entry: dict[str, Any] | None,
    *,
    context: dict[str, Any] | None = None,
) -> int:
    """Count players on the saved user's fantasy team (matches library card logic)."""
    entry = dict(archive_entry or {})
    ctx = context if isinstance(context, dict) else None
    team = str(entry.get("team_name") or (ctx or {}).get("my_team_name") or "").strip()
    direct = [p for p in (entry.get("players") or []) if isinstance(p, dict)]
    if direct:
        return len(direct)
    rosters: dict[str, Any] = {}
    if ctx:
        rosters = dict(ctx.get("league_rosters") or {})
    if not rosters:
        rosters = dict(entry.get("league_rosters") or {})
    if team and isinstance(rosters.get(team), dict):
        team_players = rosters[team].get("players") or []
        return len([p for p in team_players if isinstance(p, dict)])
    for roster in rosters.values():
        if isinstance(roster, dict) and roster.get("is_user_team"):
            team_players = roster.get("players") or []
            return len([p for p in team_players if isinstance(p, dict)])
    return 0


def save_live_draft_league_context(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    my_team_name: str,
    draft_name: str = "",
    defer_activation: bool = False,
    save_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Save full live-draft league context plus linked archive entry."""
    from draft_archive_state import save_live_draft_team_archive

    my_team = str(my_team_name or "").strip()
    league_rosters = build_league_rosters_from_live_room(room, my_team)
    cfg = dict(room.get("config") or {})
    label = str(draft_name or "").strip() or f"{cfg.get('league_name', 'Live Draft')} — {my_team}"
    draft_id, league_context_id, _fp = resolve_canonical_save_ids(
        session,
        league_rosters=league_rosters,
        config=cfg,
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or ""),
    )
    entry = save_live_draft_team_archive(
        session,
        room,
        team_name=my_team,
        draft_name=label,
        league_rosters=league_rosters,
        draft_id=draft_id,
    )
    draft_id = str(entry.get("draft_id") or "")
    league_context_id = str(
        entry.get("league_context_id") or league_context_id or context_id_for_archive(draft_id)
    ).strip()
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
    context = upsert_league_context(session, context)
    if save_only:
        session.pop(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, None)
        session.pop(PENDING_ARCHIVE_ACTIVATION_KEY, None)
    elif defer_activation:
        schedule_league_context_activation(session, league_context_id, archive_id=draft_id)
    else:
        activate_league_context(session, league_context_id)
    return entry, context


def resolve_simulator_library_draft_id(session: dict[str, Any]) -> str | None:
    """Reuse the in-session simulator library draft when updating after board save."""
    draft_id = str(session.get(SIMULATOR_SESSION_LIBRARY_DRAFT_KEY) or "").strip()
    if draft_id and get_draft_archive(session, draft_id):
        return draft_id
    active_id = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    if active_id:
        entry = get_draft_archive(session, active_id)
        if entry and str(entry.get("draft_type") or "") == DRAFT_TYPE_SIMULATOR:
            return active_id
    return None


def save_simulator_league_context(
    session: dict[str, Any],
    board_df: pd.DataFrame,
    *,
    my_team_name: str,
    draft_name: str = "",
    config: dict[str, Any] | None = None,
    defer_activation: bool = False,
    draft_id: str | None = None,
    reuse_session_draft_id: bool = True,
    save_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Save full mock-draft league context plus linked archive entry."""
    from draft_archive_state import save_simulator_team_archive

    my_team = str(my_team_name or "").strip()
    cfg = dict(config or session.get("draft_shared_settings") or {})
    league_rosters = build_league_rosters_from_simulator_board(board_df, my_team)
    label = str(draft_name or "").strip() or f"Simulator — {my_team}"
    if reuse_session_draft_id and not draft_id:
        if save_only:
            # Save Draft must not mutate the currently active simulator league.
            session_library_id = str(session.get(SIMULATOR_SESSION_LIBRARY_DRAFT_KEY) or "").strip()
            active_draft_id = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
            resolved_draft_id = session_library_id if session_library_id and session_library_id != active_draft_id else None
        else:
            resolved_draft_id = str(resolve_simulator_library_draft_id(session) or "").strip() or None
    else:
        resolved_draft_id = str(draft_id or "").strip() or None
    resolved_draft_id, league_context_id, _fp = resolve_canonical_save_ids(
        session,
        league_rosters=league_rosters,
        config=cfg,
        fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or ""),
        draft_id=resolved_draft_id,
    )
    entry = save_simulator_team_archive(
        session,
        board_df,
        team_name=my_team,
        draft_name=label,
        config=cfg,
        draft_id=resolved_draft_id,
        league_rosters=league_rosters,
    )
    draft_id = str(entry.get("draft_id") or "")
    session[SIMULATOR_SESSION_LIBRARY_DRAFT_KEY] = draft_id
    league_context_id = str(
        entry.get("league_context_id") or league_context_id or context_id_for_archive(draft_id)
    ).strip()
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
    context = upsert_league_context(session, context)
    if save_only:
        session.pop(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, None)
        session.pop(PENDING_ARCHIVE_ACTIVATION_KEY, None)
    elif defer_activation:
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
    from draft_archive_state import _archive_list, _set_archive_list, get_draft_archive

    draft_id = str(draft_id or "").strip()
    entry = get_draft_archive(session, draft_id)
    if not entry:
        return {}
    league_rosters = copy.deepcopy(league_rosters)
    entry["league_rosters"] = league_rosters
    entry["league_context_id"] = str(league_context_id or "").strip()
    team_name = str(entry.get("team_name") or "").strip()
    team_entry = league_rosters.get(team_name) if team_name and isinstance(league_rosters, dict) else None
    if isinstance(team_entry, dict):
        entry["players"] = copy.deepcopy(team_entry.get("players") or [])
    try:
        from draft_archive_state import _build_archive_snapshot

        entry["snapshot"] = _build_archive_snapshot(entry, league_rosters=league_rosters)
    except ImportError:
        pass
    entries = _archive_list(session)
    for i, existing in enumerate(entries):
        if str(existing.get("draft_id") or "") == draft_id:
            entries[i] = copy.deepcopy(entry)
            break
    _set_archive_list(session, entries)
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


def _archive_team_count_for_repair(archive: dict[str, Any]) -> int:
    snap = archive.get("snapshot")
    if isinstance(snap, dict) and snap.get("team_count") is not None:
        return int(snap.get("team_count") or 0)
    rosters = archive.get("league_rosters") or {}
    if isinstance(rosters, dict) and rosters:
        return len([name for name in rosters.keys() if str(name).strip()])
    return 0


def _board_source_is_validated_import(session: dict[str, Any]) -> bool:
    try:
        from draft_room_state import get_canonical_draft_meta

        meta = get_canonical_draft_meta(session)
        return str(meta.get("source") or "").strip() == "validated_import"
    except ImportError:
        return False


def purge_ephemeral_league_contexts(session: dict[str, Any]) -> int:
    """Remove persisted temporary workspace contexts from the league context store."""
    store = ensure_fantasy_league_context_state(session)
    contexts = store.get("contexts") or {}
    if not isinstance(contexts, dict):
        return 0
    removed = 0
    for ctx_id in list(contexts.keys()):
        if is_ephemeral_league_context_id(str(ctx_id)):
            contexts.pop(ctx_id, None)
            removed += 1
    active_id = str(store.get("active_league_context_id") or "").strip()
    if is_ephemeral_league_context_id(active_id):
        store["active_league_context_id"] = ""
    return removed


def repair_misclassified_imported_league_archives(session: dict[str, Any]) -> int:
    """Upgrade uploaded/shared leagues that were saved as simulator + ephemeral context."""
    from draft_archive_state import _archive_list, _set_archive_list

    purge_ephemeral_league_contexts(session)
    store = ensure_fantasy_league_context_state(session)
    contexts = store.setdefault("contexts", {})
    if not isinstance(contexts, dict):
        contexts = {}
        store["contexts"] = contexts

    repaired = 0
    entries = _archive_list(session)
    changed = False
    validated_import_board = _board_source_is_validated_import(session)
    for i, raw in enumerate(entries):
        archive = copy.deepcopy(raw)
        draft_id = str(archive.get("draft_id") or "").strip()
        if not draft_id:
            continue
        team_count = _archive_team_count_for_repair(archive)
        if team_count < 2:
            continue
        linked_id = str(archive.get("league_context_id") or "").strip()
        draft_type = str(archive.get("draft_type") or "").strip()
        ctx = get_league_context(session, linked_id) if linked_id else None
        if not ctx and not is_ephemeral_league_context_id(linked_id):
            ctx = get_league_context(session, context_id_for_archive(draft_id))
        ctx_type = str((ctx or {}).get("context_type") or "").strip()
        meta = (ctx or {}).get("metadata") or {}
        meta_source = str(meta.get("source") or "").strip()
        needs_repair = is_ephemeral_league_context_id(linked_id)
        if not needs_repair and draft_type == DRAFT_TYPE_SIMULATOR:
            needs_repair = validated_import_board or (
                ctx_type == CONTEXT_TYPE_MOCK_DRAFT_SIMULATION
                and meta_source == SOURCE_DRAFT_SIMULATOR
            )
        if not needs_repair:
            continue

        archive["draft_type"] = DRAFT_TYPE_IMPORTED
        archive["league_context_id"] = context_id_for_archive(draft_id)
        entries[i] = archive
        changed = True
        context = migrate_archive_to_league_context(archive)
        context["context_type"] = CONTEXT_TYPE_REAL_LEAGUE
        context_meta = dict(context.get("metadata") or {})
        context_meta["source"] = SOURCE_IMPORTED_DRAFT
        context["metadata"] = context_meta
        my_team = str(context.get("my_team_name") or archive.get("team_name") or "").strip()
        try:
            from fantasy_league_team_ownership import assign_team_owner_to_context

            if my_team:
                context = assign_team_owner_to_context(context, my_team)
        except ImportError:
            pass
        context = upsert_league_context(session, context)
        try:
            from fantasy_league_invites import repair_commissioner_identity

            context, _ = repair_commissioner_identity(context, session)
        except ImportError:
            pass
        repaired += 1

    if changed:
        _set_archive_list(session, entries)
    return repaired


def classify_origin_token(token: str) -> str | None:
    """Map a single origin hint to draft_type, or None if inconclusive."""
    return _classify_origin_token(token)


def _classify_origin_token(token: str) -> str | None:
    """Map a single origin hint to draft_type, or None if inconclusive."""
    value = str(token or "").strip().lower()
    if not value:
        return None
    try:
        from live_draft_shared_league import CREATED_FROM_LIVE_DRAFT
    except ImportError:
        CREATED_FROM_LIVE_DRAFT = "live_draft"
    live_markers = {
        CREATED_FROM_LIVE_DRAFT,
        "live_draft",
        DRAFT_TYPE_LIVE,
        SOURCE_LIVE_DRAFT_ROOM,
    }
    import_markers = {
        DRAFT_TYPE_IMPORTED,
        SOURCE_IMPORTED_DRAFT,
        "imported_draft",
        "uploaded_draft",
        "draft_import",
    }
    sim_markers = {
        DRAFT_TYPE_SIMULATOR,
        SOURCE_DRAFT_SIMULATOR,
        "simulator",
        "mock_draft",
    }
    if value in live_markers or "live_draft" in value:
        return DRAFT_TYPE_LIVE
    if value in import_markers or "import" in value:
        return DRAFT_TYPE_IMPORTED
    if value in sim_markers:
        return DRAFT_TYPE_SIMULATOR
    return None


def _ordered_origin_tokens(
    *,
    shared_doc: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    archive_entry: dict[str, Any] | None = None,
) -> list[str]:
    """Collect origin hints in canonical priority order."""
    tokens: list[str] = []

    def _push(value: Any) -> None:
        text = str(value or "").strip()
        if text:
            tokens.append(text)

    if isinstance(shared_doc, dict):
        shared_meta = dict(shared_doc.get("metadata") or {})
        _push(shared_doc.get("created_from"))
        _push(shared_meta.get("created_from"))
        _push(shared_doc.get("source_draft_type"))
        _push(shared_meta.get("source_draft_type"))
        _push(shared_doc.get("source"))
    if isinstance(context, dict):
        context_meta = dict(context.get("metadata") or {})
        _push(context_meta.get("created_from"))
        _push(context_meta.get("source_draft_type"))
        _push(context.get("source"))
        _push(context_meta.get("source"))
    if isinstance(archive_entry, dict):
        _push(archive_entry.get("draft_type"))
    return tokens


def _canonical_origin_tokens(shared_doc: dict[str, Any] | None) -> list[str]:
    """Origin hints from the canonical shared league document only."""
    tokens: list[str] = []
    if not isinstance(shared_doc, dict):
        return tokens

    def _push(value: Any) -> None:
        text = str(value or "").strip()
        if text:
            tokens.append(text)

    shared_meta = dict(shared_doc.get("metadata") or {})
    _push(shared_doc.get("created_from"))
    _push(shared_meta.get("created_from"))
    _push(shared_doc.get("source_draft_type"))
    _push(shared_meta.get("source_draft_type"))
    _push(shared_doc.get("source"))
    _push(shared_meta.get("source"))
    return tokens


def _context_explicit_live_origin(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    meta = dict(context.get("metadata") or {})
    for value in (context.get("source"), meta.get("created_from"), meta.get("source_draft_type"), meta.get("source")):
        if _classify_origin_token(str(value or "")) == DRAFT_TYPE_LIVE:
            return True
    return False


def _session_user_id(session: dict[str, Any] | None) -> str:
    if not isinstance(session, dict):
        return ""
    return str(
        session.get("_suite_auth_user_id")
        or session.get("_suite_cloud_user_id")
        or session.get("user_id")
        or ""
    ).strip()


def _accepted_invite_claims_team(
    shared_doc: dict[str, Any] | None,
    team_name: str,
    *,
    session: dict[str, Any] | None = None,
) -> bool:
    if not isinstance(shared_doc, dict):
        return False
    team = str(team_name or "").strip()
    if not team:
        return False
    uid = _session_user_id(session)
    external = str((session or {}).get("_suite_auth_external_id") or "").strip().lower()
    workspace = str((session or {}).get("_suite_active_workspace_id") or "").strip().lower()
    invites = shared_doc.get("league_invites") or []
    if not isinstance(invites, list):
        return False
    for invite in invites:
        if not isinstance(invite, dict):
            continue
        if str(invite.get("status") or "").strip() != "accepted":
            continue
        claimed = str(invite.get("claimed_team") or "").strip()
        if claimed and claimed != team:
            continue
        if session is None:
            if claimed == team:
                return True
            continue
        invite_uid = str(invite.get("user_id") or invite.get("claimed_by_user_id") or "").strip()
        invite_external = str(invite.get("external_id") or invite.get("claimed_by_external_id") or "").strip().lower()
        invite_workspace = str(invite.get("workspace_id") or "").strip().lower()
        if uid and invite_uid and uid == invite_uid:
            return True
        if external and invite_external and external == invite_external:
            return True
        if workspace and invite_workspace and workspace == invite_workspace:
            return True
        if claimed == team and (invite_uid or invite_external or invite_workspace):
            return True
    return False


def _account_owns_team_in_shared(
    shared_doc: dict[str, Any] | None,
    context: dict[str, Any] | None,
    *,
    session: dict[str, Any] | None = None,
) -> bool:
    if not isinstance(shared_doc, dict) or not isinstance(context, dict):
        return False
    my_team = str(context.get("my_team_name") or "").strip()
    if not my_team:
        return False
    ownership = shared_doc.get("team_ownership") or {}
    if not isinstance(ownership, dict):
        return False
    record = ownership.get(my_team)
    if not isinstance(record, dict):
        return False
    owner_uid = str(record.get("user_id") or "").strip()
    if not owner_uid:
        return False
    uid = _session_user_id(session)
    if uid:
        try:
            from fantasy_league_team_ownership import account_user_ids_match

            if account_user_ids_match(uid, owner_uid):
                return True
        except ImportError:
            if uid == owner_uid:
                return True
    return bool(owner_uid)


def collect_origin_evidence(
    *,
    context: dict[str, Any] | None = None,
    shared_doc: dict[str, Any] | None = None,
    archive_entry: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect draft-origin evidence without first-token-wins resolution."""
    evidence: dict[str, Any] = {
        "origin_tokens_found": _ordered_origin_tokens(
            shared_doc=shared_doc,
            context=context,
            archive_entry=archive_entry,
        ),
        "live_evidence_found": False,
        "import_evidence_found": False,
        "joined_via_live_draft": False,
        "preassigned_live_draft_owner": False,
        "accepted_invite_found": False,
        "canonical_team_ownership": False,
        "existing_archive_type": "",
        "explicit_live_origin": False,
        "explicit_import_origin": False,
        "context_type": "",
        "creation_origin": "",
    }
    evidence["creation_origin"] = read_immutable_creation_origin(
        context=context,
        shared_doc=shared_doc,
        archive_entry=archive_entry,
    )
    for token in _canonical_origin_tokens(shared_doc):
        classified = _classify_origin_token(token)
        if classified == DRAFT_TYPE_LIVE:
            evidence["explicit_live_origin"] = True
            evidence["live_evidence_found"] = True
        elif classified == DRAFT_TYPE_IMPORTED:
            evidence["explicit_import_origin"] = True
            evidence["import_evidence_found"] = True

    if isinstance(context, dict):
        meta = dict(context.get("metadata") or {})
        evidence["context_type"] = str(context.get("context_type") or "").strip()
        evidence["joined_via_live_draft"] = bool(meta.get("joined_via_live_draft"))
        evidence["preassigned_live_draft_owner"] = bool(meta.get("preassigned_live_draft_owner"))
        my_team = str(context.get("my_team_name") or "").strip()
        evidence["canonical_team_ownership"] = _account_owns_team_in_shared(
            shared_doc,
            context,
            session=session,
        )
        evidence["accepted_invite_found"] = _accepted_invite_claims_team(
            shared_doc,
            my_team,
            session=session,
        )
        for token in (
            context.get("source"),
            meta.get("created_from"),
            meta.get("source_draft_type"),
            meta.get("source"),
        ):
            classified = _classify_origin_token(str(token or ""))
            if classified == DRAFT_TYPE_LIVE:
                evidence["live_evidence_found"] = True
            elif classified == DRAFT_TYPE_IMPORTED:
                evidence["import_evidence_found"] = True

    if isinstance(archive_entry, dict):
        evidence["existing_archive_type"] = str(archive_entry.get("draft_type") or "").strip()
        classified = _classify_origin_token(evidence["existing_archive_type"])
        if classified == DRAFT_TYPE_LIVE:
            evidence["live_evidence_found"] = True
        elif classified == DRAFT_TYPE_IMPORTED:
            evidence["import_evidence_found"] = True
    return evidence


def _strong_live_draft_membership(evidence: dict[str, Any]) -> bool:
    return (
        evidence.get("context_type") == CONTEXT_TYPE_REAL_LEAGUE
        and bool(evidence.get("joined_via_live_draft"))
        and bool(evidence.get("preassigned_live_draft_owner"))
        and bool(evidence.get("canonical_team_ownership"))
        and not bool(evidence.get("accepted_invite_found"))
    )


def resolve_archive_draft_type_with_reason(
    *,
    context: dict[str, Any] | None = None,
    shared_doc: dict[str, Any] | None = None,
    archive_entry: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Resolve draft_type plus human-readable reason and evidence diagnostics."""
    evidence = collect_origin_evidence(
        context=context,
        shared_doc=shared_doc,
        archive_entry=archive_entry,
        session=session,
    )
    context_type = str(evidence.get("context_type") or "").strip()
    if context_type == CONTEXT_TYPE_MOCK_DRAFT_SIMULATION:
        return DRAFT_TYPE_SIMULATOR, "mock_draft_simulation_context", evidence
    if context_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT:
        return DRAFT_TYPE_LIVE, "live_draft_result_context", evidence
    creation_origin = str(evidence.get("creation_origin") or "").strip()
    if creation_origin == CREATION_ORIGIN_VALIDATED_IMPORT:
        return DRAFT_TYPE_IMPORTED, "immutable_creation_origin_validated_import", evidence
    if creation_origin == CREATION_ORIGIN_LIVE_DRAFT_ROOM:
        return DRAFT_TYPE_LIVE, "immutable_creation_origin_live_draft_room", evidence
    if (
        evidence.get("live_evidence_found")
        and evidence.get("import_evidence_found")
        and not creation_origin
    ):
        return DRAFT_TYPE_IMPORTED, "origin_conflict", evidence
    if _strong_live_draft_membership(evidence) and not evidence.get("import_evidence_found"):
        return DRAFT_TYPE_LIVE, "strong_live_draft_membership", evidence
    if _context_explicit_live_origin(context):
        return DRAFT_TYPE_LIVE, "context_explicit_live_origin", evidence
    if evidence.get("explicit_live_origin"):
        return DRAFT_TYPE_LIVE, "canonical_shared_live_origin", evidence
    # Prefer an already-stamped Live Draft archive over Real-League default Import.
    existing_archive_type = str(evidence.get("existing_archive_type") or "").strip()
    if existing_archive_type == DRAFT_TYPE_LIVE and not evidence.get("explicit_import_origin"):
        return DRAFT_TYPE_LIVE, "existing_archive_live_draft_type", evidence
    if evidence.get("live_evidence_found") and not evidence.get("import_evidence_found"):
        return DRAFT_TYPE_LIVE, "live_evidence_without_import", evidence
    if (
        evidence.get("explicit_import_origin")
        and not evidence.get("joined_via_live_draft")
        and not evidence.get("preassigned_live_draft_owner")
    ):
        return DRAFT_TYPE_IMPORTED, "canonical_shared_import_origin", evidence
    if context_type == CONTEXT_TYPE_REAL_LEAGUE:
        return DRAFT_TYPE_IMPORTED, "real_league_default_import", evidence
    return DRAFT_TYPE_SIMULATOR, "simulator_fallback", evidence


def _shared_origin_fields_are_live(shared_doc: dict[str, Any] | None) -> bool:
    draft_type, reason, _ = resolve_archive_draft_type_with_reason(shared_doc=shared_doc)
    return draft_type == DRAFT_TYPE_LIVE and reason in {
        "canonical_shared_live_origin",
        "context_explicit_live_origin",
    }


def repair_canonical_shared_doc_origin_in_place(
    session: dict[str, Any],
    *,
    context: dict[str, Any],
    shared_doc: dict[str, Any],
    selected_reason: str,
    draft_type: str,
) -> dict[str, Any] | None:
    """Repair canonical shared origin metadata when Live Draft evidence is confirmed."""
    if read_immutable_creation_origin(context=context, shared_doc=shared_doc) == CREATION_ORIGIN_VALIDATED_IMPORT:
        return None
    if draft_type != DRAFT_TYPE_LIVE:
        return None
    if selected_reason not in {
        "strong_live_draft_membership",
        "context_explicit_live_origin",
        "canonical_shared_live_origin",
        "immutable_creation_origin_live_draft_room",
    }:
        return None
    if _shared_origin_fields_are_live(shared_doc):
        return shared_doc
    try:
        from fantasy_shared_league_store import get_shared_league_store
    except ImportError:
        return None
    league_id = str((shared_doc or {}).get("league_id") or "").strip()
    if not league_id:
        try:
            from fantasy_league_identity import resolve_canonical_league_id

            league_id = str(resolve_canonical_league_id(context) or "").strip()
        except ImportError:
            league_id = ""
    if not league_id:
        return None
    repaired = copy.deepcopy(shared_doc)
    before = {
        "created_from": str(repaired.get("created_from") or "").strip(),
        "source_draft_type": str(repaired.get("source_draft_type") or "").strip(),
        "source": str(repaired.get("source") or "").strip(),
    }
    repaired["created_from"] = "live_draft"
    repaired["source_draft_type"] = DRAFT_TYPE_LIVE
    repaired["source"] = SOURCE_LIVE_DRAFT_ROOM
    repaired_meta = dict(repaired.get("metadata") or {})
    repaired_meta["created_from"] = "live_draft"
    repaired_meta["source_draft_type"] = DRAFT_TYPE_LIVE
    repaired_meta["source"] = SOURCE_LIVE_DRAFT_ROOM
    repaired["metadata"] = repaired_meta
    backend = get_shared_league_store()
    saved = backend.save(repaired)
    trace = dict(session.get("_draft_origin_repair_diag") or {})
    trace["canonical_origin_before"] = before
    trace["canonical_origin_after"] = {
        "created_from": "live_draft",
        "source_draft_type": DRAFT_TYPE_LIVE,
        "source": SOURCE_LIVE_DRAFT_ROOM,
    }
    session["_draft_origin_repair_diag"] = trace
    return saved if isinstance(saved, dict) else repaired


def ensure_live_draft_membership_metadata(
    context: dict[str, Any],
    shared_doc: dict[str, Any] | None,
    *,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backfill live-draft membership flags when ownership proves preassigned Live Draft."""
    if not isinstance(context, dict):
        return context
    out = copy.deepcopy(context)
    meta = dict(out.get("metadata") or {})
    if meta.get("joined_via_live_draft") and meta.get("preassigned_live_draft_owner"):
        return out
    if _accepted_invite_claims_team(shared_doc, str(out.get("my_team_name") or ""), session=session):
        return out
    evidence = collect_origin_evidence(shared_doc=shared_doc, context=out, session=session)
    if (
        evidence.get("explicit_import_origin")
        and not evidence.get("joined_via_live_draft")
        and not evidence.get("preassigned_live_draft_owner")
    ):
        return out
    if not _account_owns_team_in_shared(shared_doc, out, session=session):
        return out
    commissioner = str(
        meta.get("commissioner_user_id") or (shared_doc or {}).get("commissioner_user_id") or ""
    ).strip()
    uid = _session_user_id(session)
    if uid and commissioner and uid == commissioner:
        return out
    meta["joined_via_live_draft"] = True
    meta["preassigned_live_draft_owner"] = True
    meta.pop("joined_via_invite", None)
    out["metadata"] = meta
    return out


DRAFT_ORIGIN_REPAIR_DIAG_KEY = "_draft_origin_repair_diag"


def render_draft_origin_repair_diagnostics(
    st: Any,
    session: dict[str, Any],
    *,
    developer_mode: bool = False,
) -> None:
    """Developer Mode panel for draft-origin repair diagnostics."""
    if not developer_mode:
        return
    try:
        from page_diagnostics import inline_diagnostics_enabled
    except ImportError:
        inline_diagnostics_enabled = lambda dm: dm  # type: ignore[assignment,misc]
    if not inline_diagnostics_enabled(developer_mode):
        return
    try:
        diag = session.get(DRAFT_ORIGIN_REPAIR_DIAG_KEY)
        if not isinstance(diag, dict) or not diag:
            return
        with st.expander(
            "Draft origin repair diagnostics",
            expanded=False,
            key="draft_origin_repair_diag_panel",
        ):
            st.json(diag)
    except Exception:
        return


def resolve_archive_draft_type_from_origin(
    *,
    context: dict[str, Any] | None = None,
    shared_doc: dict[str, Any] | None = None,
    archive_entry: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> str:
    """Resolve saved-draft library draft_type from conflict-aware origin evidence."""
    draft_type, _, _ = resolve_archive_draft_type_with_reason(
        context=context,
        shared_doc=shared_doc,
        archive_entry=archive_entry,
        session=session,
    )
    return draft_type


def resolve_archive_draft_type_from_context(context: dict[str, Any] | None) -> str:
    """Map league context origin metadata to saved-draft library draft_type."""
    return resolve_archive_draft_type_from_origin(context=context)


def apply_draft_origin_to_context(
    context: dict[str, Any],
    *,
    shared_doc: dict[str, Any] | None = None,
    archive_entry: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp context source/metadata from canonical origin resolution."""
    out = copy.deepcopy(context)
    draft_type, selected_reason, evidence = resolve_archive_draft_type_with_reason(
        context=out,
        shared_doc=shared_doc,
        archive_entry=archive_entry,
        session=session,
    )
    meta = dict(out.get("metadata") or {})
    if draft_type == DRAFT_TYPE_LIVE:
        out["source"] = SOURCE_LIVE_DRAFT_ROOM
        meta["created_from"] = "live_draft"
        meta["source_draft_type"] = DRAFT_TYPE_LIVE
    elif draft_type == DRAFT_TYPE_IMPORTED:
        out["source"] = SOURCE_IMPORTED_DRAFT
        meta["source_draft_type"] = DRAFT_TYPE_IMPORTED
        meta["created_from"] = str(meta.get("created_from") or "imported_draft").strip() or "imported_draft"
        meta.pop("joined_via_live_draft", None)
        meta.pop("preassigned_live_draft_owner", None)
    elif draft_type == DRAFT_TYPE_SIMULATOR:
        out["source"] = SOURCE_DRAFT_SIMULATOR
        meta["source_draft_type"] = DRAFT_TYPE_SIMULATOR
    out["metadata"] = meta
    if isinstance(session, dict):
        session[DRAFT_ORIGIN_REPAIR_DIAG_KEY] = {
            "origin_tokens_found": evidence.get("origin_tokens_found") or [],
            "live_evidence_found": bool(evidence.get("live_evidence_found")),
            "import_evidence_found": bool(evidence.get("import_evidence_found")),
            "joined_via_live_draft": bool(evidence.get("joined_via_live_draft")),
            "preassigned_live_draft_owner": bool(evidence.get("preassigned_live_draft_owner")),
            "accepted_invite_found": bool(evidence.get("accepted_invite_found")),
            "selected_draft_type": draft_type,
            "selected_reason": selected_reason,
        }
    return out


def repair_archive_draft_type_for_entry(
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repair archive origin label in place from linked league context metadata."""
    if not isinstance(entry, dict):
        return entry
    draft_id = str(entry.get("draft_id") or "").strip()
    if not draft_id:
        return entry
    ctx = context
    if ctx is None:
        linked_id = str(entry.get("league_context_id") or "").strip()
        ctx = get_league_context(session, linked_id) if linked_id else None
        if not isinstance(ctx, dict):
            ctx = get_league_context(session, context_id_for_archive(draft_id))
    shared_doc = None
    if isinstance(ctx, dict):
        try:
            from fantasy_league_identity import resolve_canonical_league_id
            from fantasy_shared_league_store import load_shared_league

            league_id = str(resolve_canonical_league_id(ctx) or "").strip()
            if league_id:
                shared_doc = load_shared_league(league_id)
        except ImportError:
            shared_doc = None
    expected = resolve_archive_draft_type_from_origin(
        context=ctx if isinstance(ctx, dict) else None,
        shared_doc=shared_doc if isinstance(shared_doc, dict) else None,
        archive_entry=entry,
        session=session,
    )
    current = str(entry.get("draft_type") or "").strip()
    if current == expected:
        return entry
    repaired = dict(entry)
    repaired["draft_type"] = expected
    entries = session.get(DRAFT_ARCHIVE_KEY)
    if isinstance(entries, list):
        session[DRAFT_ARCHIVE_KEY] = [
            repaired if str(row.get("draft_id") or "").strip() == draft_id else row
            for row in entries
            if isinstance(row, dict)
        ]
    return repaired


def repair_archive_draft_types_from_contexts(session: dict[str, Any]) -> int:
    """Backfill misclassified archive draft_type values from league context origin."""
    try:
        from fantasy_creation_origin_repair import repair_known_canonical_creation_origins

        repair_known_canonical_creation_origins(session)
    except ImportError:
        pass
    from draft_archive_state import list_draft_archives
    from fantasy_league_identity import resolve_canonical_league_id

    repaired = 0
    for entry in list_draft_archives(session):
        if not isinstance(entry, dict):
            continue
        draft_id = str(entry.get("draft_id") or "").strip()
        if not draft_id:
            continue
        archive_type_before = str(entry.get("draft_type") or "").strip()
        linked_id = str(entry.get("league_context_id") or "").strip()
        ctx = get_league_context(session, linked_id) if linked_id else None
        if not isinstance(ctx, dict):
            ctx = get_league_context(session, context_id_for_archive(draft_id))
        shared_doc = None
        if isinstance(ctx, dict):
            league_id = str(resolve_canonical_league_id(ctx) or "").strip()
            if league_id:
                try:
                    from fantasy_shared_league_store import load_shared_league

                    shared_doc = load_shared_league(league_id)
                except ImportError:
                    shared_doc = None
        if isinstance(ctx, dict):
            ctx = ensure_live_draft_membership_metadata(
                ctx,
                shared_doc if isinstance(shared_doc, dict) else None,
                session=session,
            )
            repaired_ctx = apply_draft_origin_to_context(
                ctx,
                shared_doc=shared_doc if isinstance(shared_doc, dict) else None,
                archive_entry=entry,
                session=session,
            )
            if repaired_ctx != ctx:
                upsert_league_context(session, repaired_ctx, mark_persist_authoritative=False)
                ctx = repaired_ctx
        expected, selected_reason, evidence = resolve_archive_draft_type_with_reason(
            context=ctx if isinstance(ctx, dict) else None,
            shared_doc=shared_doc if isinstance(shared_doc, dict) else None,
            archive_entry=entry,
            session=session,
        )
        if isinstance(shared_doc, dict) and isinstance(ctx, dict):
            repaired_shared = repair_canonical_shared_doc_origin_in_place(
                session,
                context=ctx,
                shared_doc=shared_doc,
                selected_reason=selected_reason,
                draft_type=expected,
            )
            if isinstance(repaired_shared, dict):
                shared_doc = repaired_shared
        session[DRAFT_ORIGIN_REPAIR_DIAG_KEY] = {
            "origin_tokens_found": evidence.get("origin_tokens_found") or [],
            "live_evidence_found": bool(evidence.get("live_evidence_found")),
            "import_evidence_found": bool(evidence.get("import_evidence_found")),
            "joined_via_live_draft": bool(evidence.get("joined_via_live_draft")),
            "preassigned_live_draft_owner": bool(evidence.get("preassigned_live_draft_owner")),
            "accepted_invite_found": bool(evidence.get("accepted_invite_found")),
            "selected_draft_type": expected,
            "selected_reason": selected_reason,
            "archive_type_before": archive_type_before,
            "archive_type_after": expected,
            **dict(session.get(DRAFT_ORIGIN_REPAIR_DIAG_KEY) or {}),
        }
        if str(entry.get("draft_type") or "").strip() == expected:
            continue
        repair_archive_draft_type_for_entry(
            session,
            entry,
            context=ctx if isinstance(ctx, dict) else None,
        )
        session[DRAFT_ORIGIN_REPAIR_DIAG_KEY]["archive_type_after"] = expected
        repaired += 1
    if repaired:
        try:
            from workflow_persist_guard import mark_workflow_persist_authoritative

            mark_workflow_persist_authoritative(session)
        except ImportError:
            pass
    return repaired


def _archive_stub_from_league_context(context: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild a minimal saved-draft row when league context survived but archive row did not."""
    meta = context.get("metadata") or {}
    draft_id = str(meta.get("source_draft_id") or "").strip()
    if not draft_id:
        return None
    my_team = str(context.get("my_team_name") or "").strip()
    draft_name = str(context.get("display_name") or context.get("league_name") or "Saved Draft").strip()
    league_rosters = context.get("league_rosters") or {}
    players: list[dict[str, Any]] = []
    if isinstance(league_rosters, dict) and my_team:
        team_entry = league_rosters.get(my_team) or {}
        if isinstance(team_entry, dict):
            for player in team_entry.get("players") or []:
                if isinstance(player, dict):
                    players.append(dict(player))
    draft_type = resolve_archive_draft_type_from_context(context)
    now = str(meta.get("updated_at") or meta.get("created_at") or _utc_now_iso())
    return {
        "draft_id": draft_id,
        "draft_name": draft_name,
        "team_name": my_team,
        "draft_type": draft_type,
        "players": players,
        "league_rosters": copy.deepcopy(league_rosters) if isinstance(league_rosters, dict) else {},
        "league_context_id": str(context.get("league_context_id") or context_id_for_archive(draft_id)),
        "created_at": str(meta.get("created_at") or now),
        "updated_at": now,
        "repaired_from_context": True,
    }


def repair_missing_draft_archives_from_contexts(
    session: dict[str, Any],
    *,
    require_visibility: bool = True,
) -> int:
    """Restore archive list entries from league contexts when restore wiped draft_archive_teams."""
    from draft_archive_state import DRAFT_ARCHIVE_KEY, DELETED_DRAFT_ARCHIVE_IDS_KEY, get_draft_archive

    store = ensure_fantasy_league_context_state(session)
    contexts = store.get("contexts") or {}
    if not isinstance(contexts, dict):
        return 0
    deleted_drafts = {
        str(item).strip()
        for item in (session.get(DELETED_DRAFT_ARCHIVE_IDS_KEY) or [])
        if str(item).strip()
    }
    deleted_contexts = {
        str(item).strip()
        for item in (store.get("deleted_context_ids") or [])
        if str(item).strip()
    }
    raw = session.get(DRAFT_ARCHIVE_KEY)
    entries = [dict(x) for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []
    existing_ids = {str(e.get("draft_id") or "").strip() for e in entries if str(e.get("draft_id") or "").strip()}
    try:
        from draft_archive_visibility import is_saved_draft_visible_to_session
    except ImportError:
        is_saved_draft_visible_to_session = None
    repaired: list[dict[str, Any]] = []
    for context in contexts.values():
        if not isinstance(context, dict):
            continue
        context_id = str(context.get("league_context_id") or "").strip()
        if context_id and context_id in deleted_contexts:
            continue
        stub = _archive_stub_from_league_context(context)
        if not stub:
            continue
        draft_id = str(stub.get("draft_id") or "").strip()
        if not draft_id or draft_id in deleted_drafts or draft_id in existing_ids or get_draft_archive(session, draft_id):
            continue
        if (
            require_visibility
            and is_saved_draft_visible_to_session is not None
            and not is_saved_draft_visible_to_session(
            session,
            {"draft_id": draft_id, "league_context_id": context_id},
            context=context,
        )
        ):
            continue
        repaired.append(stub)
        existing_ids.add(draft_id)
    if not repaired:
        return 0
    session[DRAFT_ARCHIVE_KEY] = entries + repaired
    try:
        from workflow_persist_guard import mark_workflow_persist_authoritative

        mark_workflow_persist_authoritative(session)
    except ImportError:
        pass
    session["_draft_archives_repaired_from_contexts"] = len(repaired)
    return len(repaired)


def apply_fantasy_league_context_disk_state(session: dict[str, Any], state: dict[str, Any]) -> None:
    """Restore league context store from disk/cloud and run legacy archive migration."""
    blob = state.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY)
    if isinstance(blob, dict):
        session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = copy.deepcopy(blob)
    else:
        ensure_fantasy_league_context_state(session)
    migrate_legacy_archives_to_contexts(session)
    migrate_global_pending_trade_targets(session)
    try:
        repair_missing_draft_archives_from_contexts(session)
    except Exception:
        pass
    try:
        from draft_archive_visibility import sanitize_workflow_library_for_account

        sanitize_workflow_library_for_account(session, persist_cleanup=False)
    except ImportError:
        pass
