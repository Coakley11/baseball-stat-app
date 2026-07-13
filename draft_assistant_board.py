"""Draft Assistant — canonical board resolution from live/sim/context/archive sources."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _player_cell_filled(value: Any) -> bool:
    return bool(str(value or "").strip())


def normalize_draft_board_df(df: pd.DataFrame | None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize Pick/Round/Team/Player board rows and dedupe by canonical Pick."""
    diag: dict[str, Any] = {
        "board_row_count_raw": 0,
        "board_row_count_normalized": 0,
        "unique_valid_pick_count": 0,
        "min_pick": None,
        "max_pick": None,
        "missing_pick_numbers": [],
    }
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(), diag

    work = df.copy()
    diag["board_row_count_raw"] = len(work)

    rename_map: dict[str, str] = {}
    for col in work.columns:
        key = str(col).strip().lower()
        if key in ("player", "fullname", "full_name", "name"):
            rename_map[col] = "Player"
        elif key in ("team", "fantasy team", "fantasy_team"):
            rename_map[col] = "Team"
        elif key == "pick":
            rename_map[col] = "Pick"
        elif key == "round":
            rename_map[col] = "Round"
    if rename_map:
        work = work.rename(columns=rename_map)

    if "Player" not in work.columns:
        return pd.DataFrame(), diag

    work = work[work["Player"].apply(_player_cell_filled)].copy()
    if work.empty:
        return pd.DataFrame(), diag

    if "Pick" in work.columns:
        work["_pick_n"] = pd.to_numeric(work["Pick"], errors="coerce")
        work = work[work["_pick_n"].notna()].copy()
        work = work.sort_values("_pick_n", kind="stable")
        work = work.drop_duplicates(subset=["_pick_n"], keep="first")
        work["Pick"] = work["_pick_n"].astype(int)
        work = work.drop(columns=["_pick_n"])
    if "Round" in work.columns:
        work["Round"] = pd.to_numeric(work["Round"], errors="coerce")

    if "Team" in work.columns:
        work["Team"] = work["Team"].astype(str).str.strip()

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
            df = pd.DataFrame(rows)
            normalized, _ = normalize_draft_board_df(df)
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
    return bool(df["Player"].astype(str).str.strip().ne("").any())


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

    if mode not in ("live_board",) and not any(
        src.startswith("live") for src, _ in candidates
    ):
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
    return {"board": best, "diagnostics": diag}
