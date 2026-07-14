"""Draft Assistant — canonical board resolution from live/sim/context/archive sources."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Canonical fantasy draft board columns after normalization.
CANONICAL_BOARD_COLUMNS: tuple[str, ...] = ("Team", "Player", "Pick", "Round")


def _player_cell_filled(value: Any) -> bool:
    return bool(str(value or "").strip())


def _lower_col_map(columns: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in columns:
        key = str(col).strip().lower()
        if key and key not in out:
            out[key] = col
    return out


def _coalesce_duplicate_named_columns(work: pd.DataFrame, name: str) -> pd.Series:
    """If ``name`` appears more than once, coalesce to a single Series (first non-empty)."""
    col = work[name]
    if isinstance(col, pd.Series):
        return col
    if isinstance(col, pd.DataFrame):
        logger.warning(
            "normalize_draft_board_df: duplicate column %r width=%s columns=%s",
            name,
            col.shape[1],
            list(work.columns),
        )
        series = col.iloc[:, 0].copy()
        for idx in range(1, col.shape[1]):
            other = col.iloc[:, idx]
            blank = series.isna() | (series.astype(str).str.strip() == "") | (series.astype(str) == "nan")
            series = series.where(~blank, other)
        return series
    return pd.Series(col, index=work.index)


def _collapse_duplicate_columns(work: pd.DataFrame) -> pd.DataFrame:
    """Ensure each column label appears once after renames."""
    if not bool(work.columns.duplicated().any()):
        return work
    rebuilt = pd.DataFrame(index=work.index)
    for label in dict.fromkeys(str(c) for c in work.columns):
        rebuilt[label] = _coalesce_duplicate_named_columns(work, label)
    return rebuilt


def _apply_canonical_column_map(work: pd.DataFrame) -> pd.DataFrame:
    """Map aliases onto a single canonical schema without creating duplicate labels.

    Live Draft rows often contain both ``Team`` (MLB) and ``Fantasy Team``. Mapping both
    to ``Team`` produced duplicate columns so ``work["Team"]`` returned a DataFrame and
    ``.str`` crashed.
    """
    lower = _lower_col_map(work.columns)
    rename_map: dict[Any, str] = {}

    # Player: prefer existing Player, else fullName / Name.
    if "player" not in lower:
        for alias in ("fullname", "full_name", "player_name", "name"):
            if alias in lower:
                rename_map[lower[alias]] = "Player"
                break

    fantasy_aliases = ("fantasy team", "fantasy_team", "draft team", "draft_team")
    fantasy_col = next((lower[a] for a in fantasy_aliases if a in lower), None)
    raw_team_col = lower.get("team")
    mlb_col = lower.get("mlb team") or lower.get("mlb_team")

    if fantasy_col is not None:
        rename_map[fantasy_col] = "Team"
        if raw_team_col is not None and raw_team_col != fantasy_col:
            rename_map[raw_team_col] = "MLB Team"
        elif mlb_col is not None and mlb_col != fantasy_col:
            rename_map[mlb_col] = "MLB Team"
    elif raw_team_col is not None:
        rename_map[raw_team_col] = "Team"
    elif mlb_col is not None:
        rename_map[mlb_col] = "Team"

    for alias, dest in (
        ("pick", "Pick"),
        ("round", "Round"),
        ("primary position", "Primary Position"),
        ("primary_position", "Primary Position"),
        ("position", "Position"),
        ("pos", "Position"),
    ):
        if alias not in lower:
            continue
        src = lower[alias]
        if src in rename_map:
            continue
        # Skip if destination already present under another physical column.
        if dest.lower() in lower and lower[dest.lower()] != src:
            continue
        rename_map[src] = dest

    if rename_map:
        work = work.rename(columns=rename_map)
    return _collapse_duplicate_columns(work)


def validate_canonical_board_schema(df: pd.DataFrame) -> dict[str, Any]:
    """Return schema diagnostics. ``ok`` requires unique Team/Player Series."""
    cols = list(df.columns)
    required_present = [c for c in CANONICAL_BOARD_COLUMNS if c in cols]
    missing = [c for c in CANONICAL_BOARD_COLUMNS if c not in cols]
    duplicates = sorted({str(c) for c in cols if cols.count(c) > 1})
    team_is_series = True
    if "Team" in cols:
        team_is_series = isinstance(df["Team"], pd.Series)
    ok = "Player" in cols and "Team" in cols and not duplicates and team_is_series
    return {
        "ok": ok,
        "columns": cols,
        "required_present": required_present,
        "missing_required": missing,
        "duplicate_columns": duplicates,
        "team_is_series": team_is_series,
    }


def normalize_draft_board_df(df: pd.DataFrame | None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize Pick/Round/Team/Player board rows and dedupe by canonical Pick."""
    diag: dict[str, Any] = {
        "board_row_count_raw": 0,
        "board_row_count_normalized": 0,
        "unique_valid_pick_count": 0,
        "min_pick": None,
        "max_pick": None,
        "missing_pick_numbers": [],
        "schema": {},
    }
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(), diag

    work = df.copy()
    diag["board_row_count_raw"] = len(work)
    work = _apply_canonical_column_map(work)
    diag["schema"] = validate_canonical_board_schema(work)

    if "Player" not in work.columns:
        logger.warning(
            "normalize_draft_board_df: missing Player after remap | columns=%s",
            list(work.columns),
        )
        return pd.DataFrame(), diag

    player_series = _coalesce_duplicate_named_columns(work, "Player")
    work = _collapse_duplicate_columns(work)
    work["Player"] = player_series
    work = work[work["Player"].apply(_player_cell_filled)].copy()
    if work.empty:
        return pd.DataFrame(), diag

    if "Pick" in work.columns:
        pick_series = _coalesce_duplicate_named_columns(work, "Pick")
        work = _collapse_duplicate_columns(work)
        work["_pick_n"] = pd.to_numeric(pick_series, errors="coerce")
        work = work[work["_pick_n"].notna()].copy()
        work = work.sort_values("_pick_n", kind="stable")
        work = work.drop_duplicates(subset=["_pick_n"], keep="first")
        work["Pick"] = work["_pick_n"].astype(int)
        work = work.drop(columns=["_pick_n"], errors="ignore")
        work = _collapse_duplicate_columns(work)

    if "Round" in work.columns:
        round_series = _coalesce_duplicate_named_columns(work, "Round")
        work = _collapse_duplicate_columns(work)
        work["Round"] = pd.to_numeric(round_series, errors="coerce")

    if "Team" in work.columns:
        team_col = work["Team"]
        logger.info(
            "normalize_draft_board_df Team preprocess | type(work)=%s type(Team)=%s "
            "columns=%s dtypes=%s head=%s",
            type(work).__name__,
            type(team_col).__name__,
            list(work.columns),
            {str(k): str(v) for k, v in work.dtypes.items()},
            work.head(3).to_dict(orient="records"),
        )
        if isinstance(team_col, pd.DataFrame):
            logger.error(
                "normalize_draft_board_df: Team is DataFrame (duplicate columns) — coalescing. columns=%s",
                list(work.columns),
            )
            team_series = _coalesce_duplicate_named_columns(work, "Team")
            work = _collapse_duplicate_columns(work)
            work["Team"] = team_series.astype(str).str.strip()
        else:
            work["Team"] = team_col.astype(str).str.strip()

    schema_after = validate_canonical_board_schema(work)
    diag["schema"] = schema_after
    if not schema_after.get("team_is_series", True):
        logger.error("normalize_draft_board_df: Team still not a Series after collapse")
        return pd.DataFrame(), diag

    work = work.sort_values("Pick", kind="stable") if "Pick" in work.columns else work
    diag["board_row_count_normalized"] = len(work)
    if "Pick" in work.columns and not work.empty:
        picks = [int(x) for x in work["Pick"].tolist()]
        diag["unique_valid_pick_count"] = len(picks)
        diag["min_pick"] = min(picks)
        diag["max_pick"] = max(picks)
        if picks:
            expected = set(range(min(picks), max(picks) + 1))
            diag["missing_pick_numbers"] = sorted(expected - set(picks))
    return work.reset_index(drop=True), diag


def board_from_league_context(context: dict[str, Any] | None) -> pd.DataFrame:
    if not isinstance(context, dict):
        return pd.DataFrame()
    try:
        from fantasy_league_context import league_context_roster_dataframe

        raw = league_context_roster_dataframe(context)
    except ImportError:
        return pd.DataFrame()
    normalized, _ = normalize_draft_board_df(raw)
    return normalized


def board_from_archive(archive: dict[str, Any] | None, session: dict[str, Any] | None = None) -> pd.DataFrame:
    if not isinstance(archive, dict):
        return pd.DataFrame()
    snapshot = archive.get("snapshot") if isinstance(archive.get("snapshot"), dict) else {}
    for key in ("draft_board", "board", "final_board", "pick_history"):
        rows = snapshot.get(key) if isinstance(snapshot, dict) else None
        if isinstance(rows, list) and rows:
            frame = pd.DataFrame(rows)
            normalized, _ = normalize_draft_board_df(frame)
            if not normalized.empty:
                return normalized
    draft_id = str(archive.get("draft_id") or "").strip()
    if draft_id and session:
        try:
            from fantasy_league_context import context_id_for_archive, get_league_context

            ctx = get_league_context(session, str(archive.get("league_context_id") or context_id_for_archive(draft_id)))
            if isinstance(ctx, dict):
                return board_from_league_context(ctx)
        except ImportError:
            pass
    return pd.DataFrame()


def _board_has_populated_picks(df: pd.DataFrame) -> bool:
    if df is None or df.empty or "Player" not in df.columns:
        return False
    player = df["Player"]
    if isinstance(player, pd.DataFrame):
        player = player.iloc[:, 0]
    return bool(player.astype(str).str.strip().ne("").any())


def resolve_draft_assistant_board(
    session: dict[str, Any],
    *,
    effective_context: dict[str, Any] | None = None,
    active_archive: dict[str, Any] | None = None,
    live_room: dict[str, Any] | None = None,
    context_mode: str = "",
) -> dict[str, Any]:
    """Resolve Draft Assistant board with explicit source priority."""
    mode = str(context_mode or "").strip().lower()
    fp = (
        mode,
        str((effective_context or {}).get("league_context_id") or ""),
        str((active_archive or {}).get("draft_id") or ""),
        int(len((live_room or session.get("live_draft_room") or {}).get("draft_board") or []))
        if isinstance(live_room or session.get("live_draft_room"), dict)
        else 0,
        str(session.get("_suite_auth_user_id") or ""),
    )
    if session.get("_da_board_cache_fp") == fp:
        cached = session.get("_da_board_cache")
        if isinstance(cached, dict):
            return dict(cached)

    diag: dict[str, Any] = {
        "selected_source_kind": mode or "none",
        "selected_context_id": str((effective_context or {}).get("league_context_id") or ""),
        "selected_archive_id": str((active_archive or {}).get("draft_id") or ""),
        "selected_league_id": "",
        "board_source_used": "empty",
        "board_row_count_raw": 0,
        "board_row_count_normalized": 0,
        "unique_valid_pick_count": 0,
        "min_pick": None,
        "max_pick": None,
        "missing_pick_numbers": [],
    }
    if isinstance(effective_context, dict):
        try:
            from fantasy_league_identity import resolve_canonical_league_id

            diag["selected_league_id"] = str(resolve_canonical_league_id(effective_context) or "")
        except ImportError:
            pass

    candidates: list[tuple[str, pd.DataFrame]] = []

    if mode == "live_board":
        room = live_room if isinstance(live_room, dict) else session.get("live_draft_room")
        if isinstance(room, dict):
            board = room.get("draft_board")
            if isinstance(board, list) and board:
                candidates.append(("live_room_draft_board", pd.DataFrame(board)))
            try:
                from draft_room_state import get_canonical_draft_board

                canonical = get_canonical_draft_board(session)
                candidates.append(("live_canonical_board", canonical))
            except ImportError:
                pass
    elif mode == "simulator_board":
        try:
            from draft_room_state import get_canonical_draft_board

            candidates.append(("simulator_canonical_board", get_canonical_draft_board(session)))
        except ImportError:
            pass

    if isinstance(effective_context, dict):
        candidates.append(("effective_league_context", board_from_league_context(effective_context)))

    if isinstance(active_archive, dict):
        candidates.append(("active_archive", board_from_archive(active_archive, session)))

    if not isinstance(active_archive, dict) and mode in ("", "none", "research_context"):
        try:
            from draft_archive_state import get_active_draft_archive

            archive = get_active_draft_archive(session)
            if isinstance(archive, dict):
                candidates.append(("session_active_archive", board_from_archive(archive, session)))
        except ImportError:
            pass

    if mode not in ("live_board",) and not any(src.startswith("live") for src, _ in candidates):
        try:
            from draft_room_state import get_canonical_draft_board

            candidates.append(("fallback_canonical_board", get_canonical_draft_board(session)))
        except ImportError:
            pass

    best = pd.DataFrame()
    best_source = "empty"
    best_norm_diag: dict[str, Any] = {}
    for source_name, raw_df in candidates:
        if raw_df is None or not isinstance(raw_df, pd.DataFrame):
            continue
        normalized, norm_diag = normalize_draft_board_df(raw_df)
        if not _board_has_populated_picks(normalized):
            continue
        if len(normalized) > len(best):
            best = normalized
            best_source = source_name
            best_norm_diag = norm_diag

    diag["board_source_used"] = best_source
    diag.update(best_norm_diag)
    result = {"board": best, "diagnostics": diag}
    session["_da_board_cache_fp"] = fp
    session["_da_board_cache"] = result
    return result


def invalidate_draft_assistant_board_cache(session: dict[str, Any]) -> None:
    session.pop("_da_board_cache_fp", None)
    session.pop("_da_board_cache", None)
