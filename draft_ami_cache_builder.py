"""Pure Draft Assistant AMI cache builder — no Streamlit UI imports."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

TARGET_POSITION_COUNTS = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0}


def extract_board_draft_context(
    board: pd.DataFrame,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Parse board + session settings into roster/pick context (pure)."""
    team_names = sorted(board["Team"].dropna().astype(str).unique().tolist()) if "Team" in board.columns else []
    assistant_team = str(
        settings.get("draft_assistant_synced_team")
        or settings.get("room_your_team")
        or (team_names[0] if team_names else "")
    ).strip()
    pick_adjustment = int(settings.get("draft_pick_adjustment") or 0)
    num_teams = int(settings.get("room_team_count") or len(team_names) or 12)

    from draft_room_state import draft_board_summary_for_team

    summary = draft_board_summary_for_team(
        board,
        your_team=assistant_team,
        team_names=team_names,
        pick_adjustment=pick_adjustment,
        num_teams=num_teams,
    )
    current_pick = int(summary["current_pick"])

    filled = board[board["Player"].astype(str).str.strip().ne("")]
    if assistant_team and "Team" in board.columns:
        my_roster = (
            board[board["Team"].astype(str) == str(assistant_team)]["Player"]
            .dropna()
            .astype(str)
            .tolist()
        )
        drafted_players = (
            board[board["Team"].astype(str) != str(assistant_team)]["Player"]
            .dropna()
            .astype(str)
            .tolist()
        )
    else:
        my_roster = []
        drafted_players = filled["Player"].dropna().astype(str).tolist()

    my_roster = sorted(list(dict.fromkeys(p for p in my_roster if str(p).strip())))
    drafted_players = sorted(list(dict.fromkeys(p for p in drafted_players if str(p).strip())))
    drafted_or_owned = set(drafted_players).union(set(my_roster))

    return {
        "assistant_team": assistant_team,
        "my_roster": my_roster,
        "drafted_players": drafted_players,
        "drafted_or_owned": drafted_or_owned,
        "current_pick": current_pick,
        "draft_round": summary.get("current_round"),
        "summary": summary,
        "team_count": num_teams,
    }


def _draft_settings_from_session(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "draft_window": int(settings.get("draft_window") or 3),
        "draft_format": str(
            settings.get("draft_format")
            or settings.get("draft_lab_scoring_type")
            or "5x5 Roto"
        ),
        "use_ml": bool(settings.get("draft_use_ml_blend", True)),
        "ml_weight": float(settings.get("draft_ml_blend_weight") or 0.12),
        "ml_min_games": int(settings.get("draft_ml_min_games_signal") or 50),
        "projection_style": str(settings.get("fantasy_draft_projection_style") or "Balanced"),
        "top_n": int(settings.get("draft_top_n") or 10),
    }


def build_draft_assistant_ami_cache_from_board_state(
    board: pd.DataFrame,
    settings: dict[str, Any],
    *,
    yearly_df: pd.DataFrame | None = None,
    market_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Build AMI draft projection inputs from board state without Streamlit UI.

    Returns dict with keys:
      ok, reason, cache_inputs (for cache_draft_assistant_ami_context), trace
    """
    trace: dict[str, Any] = {"builder": "draft_ami_cache_builder"}
    if board.empty or "Player" not in board.columns:
        return {"ok": False, "reason": "empty_board", "trace": trace}

    filled = board[board["Player"].astype(str).str.strip().ne("")]
    if filled.empty:
        return {"ok": False, "reason": "no_picks_on_board", "trace": trace}

    ctx = extract_board_draft_context(board, settings)
    draft_cfg = _draft_settings_from_session(settings)

    try:
        from draft_pool_engine import (
            apply_draft_pick_scoring,
            build_unified_draft_player_pool,
            load_draft_market_data,
            load_yearly_stat_data,
        )
    except ImportError as exc:
        return {"ok": False, "reason": f"draft_pool_engine: {exc}", "trace": trace}

    if market_df is None:
        try:
            market_df = load_draft_market_data()
        except Exception as exc:
            return {"ok": False, "reason": f"market_data: {exc}", "trace": trace}
    if market_df is None or getattr(market_df, "empty", True):
        return {"ok": False, "reason": "empty_market_df", "trace": trace}

    if yearly_df is None:
        try:
            yearly_df = load_yearly_stat_data()
        except Exception as exc:
            return {"ok": False, "reason": f"yearly_data: {exc}", "trace": trace}

    try:
        draft_df = build_unified_draft_player_pool(
            yearly_df,
            market_df,
            draft_window=draft_cfg["draft_window"],
            fantasy_format=draft_cfg["draft_format"],
            projection_style=draft_cfg["projection_style"],
            use_ml_blend=draft_cfg["use_ml"],
            ml_blend_weight=draft_cfg["ml_weight"],
            ml_min_games_for_signal=draft_cfg["ml_min_games"],
        )
    except Exception as exc:
        log.exception("build_draft_assistant_ami_cache_from_board_state pool build failed")
        return {"ok": False, "reason": f"build_pool: {exc}", "trace": trace}

    from draft_ami_helpers import infer_draft_assistant_needs

    roster_df_auto = draft_df[draft_df["fullName"].isin(set(ctx["my_roster"]))].copy()
    needed_positions, category_needs = infer_draft_assistant_needs(
        roster_df_auto,
        draft_df,
        draft_format=draft_cfg["draft_format"],
    )

    available = draft_df[~draft_df["fullName"].isin(ctx["drafted_or_owned"])].copy()
    if available.empty:
        return {"ok": False, "reason": "no_undrafted_players", "trace": trace}

    try:
        available, _gaps, position_summary_rows = apply_draft_pick_scoring(
            available,
            roster_df_auto,
            fantasy_format=draft_cfg["draft_format"],
            target_counts=TARGET_POSITION_COUNTS,
            current_pick=ctx["current_pick"],
            category_needs=category_needs,
            needed_positions=needed_positions,
            use_ml_blend=draft_cfg["use_ml"],
            ml_blend_weight=draft_cfg["ml_weight"],
            return_position_summary=True,
            recommendation_mode="draft_fit",
        )
    except Exception as exc:
        log.exception("build_draft_assistant_ami_cache_from_board_state scoring failed")
        return {"ok": False, "reason": f"apply_scoring: {exc}", "trace": trace}

    median_scarcity_dropoff = None
    if position_summary_rows:
        try:
            drop_vals = [
                float(r.get("Scarcity Dropoff"))
                for r in position_summary_rows
                if r.get("Scarcity Dropoff") is not None
            ]
            if drop_vals:
                median_scarcity_dropoff = float(pd.Series(drop_vals).median())
        except Exception:
            pass

    top_n = draft_cfg["top_n"]
    recs = available.sort_values("Draft Fit Score", ascending=False).head(top_n)
    avail_sorted = available.sort_values("Expected Fantasy Value", ascending=False)

    roster_detail: list[dict[str, str]] = []
    roster_index: dict[str, str] = {}
    if not roster_df_auto.empty:
        for _, row in roster_df_auto.iterrows():
            name = str(row.get("fullName") or row.get("Player") or "").strip()
            pos = str(row.get("Primary Position") or row.get("position") or "").strip()
            if name:
                roster_detail.append({"player": name, "Primary Position": pos})
                if pos:
                    roster_index[name.lower()] = pos

    trace.update(
        {
            "current_pick": ctx["current_pick"],
            "draft_round": ctx.get("draft_round"),
            "assistant_team": ctx["assistant_team"],
        }
    )

    return {
        "ok": True,
        "trace": trace,
        "cache_inputs": {
            "recs_df": recs,
            "current_pick": ctx["current_pick"],
            "draft_round": int(ctx.get("draft_round") or 1),
            "my_roster": ctx["my_roster"],
            "user_roster_detail": roster_detail,
            "roster_position_index": roster_index,
            "drafted_total": len(ctx["drafted_or_owned"]),
            "draft_format": draft_cfg["draft_format"],
            "assistant_team": ctx["assistant_team"],
            "needed_positions": needed_positions,
            "category_needs": category_needs,
            "drafted_players": sorted(ctx["drafted_or_owned"]),
            "best_available_df": avail_sorted.head(6),
            "available_df": avail_sorted,
            "position_scarcity": median_scarcity_dropoff,
        },
    }


def apply_draft_assistant_cache_to_session(
    session_state: dict[str, Any],
    cache_inputs: dict[str, Any],
    *,
    page: str = "Draft Assistant Simulator",
) -> dict[str, Any]:
    """Write cache_inputs into session via cache_draft_assistant_ami_context."""
    from applied_math_context import cache_draft_assistant_ami_context

    cache_draft_assistant_ami_context(session_state, page=page, **cache_inputs)
    proj = session_state.get("_ami_draft_projection") or {}
    pool_diag = proj.get("player_pool_diagnostics") if isinstance(proj, dict) else {}
    return {
        "available_players_count": len(proj.get("available_players") or []) if isinstance(proj, dict) else 0,
        "player_pool_source": pool_diag.get("player_pool_source") if isinstance(pool_diag, dict) else None,
        "current_pick": proj.get("current_pick") if isinstance(proj, dict) else None,
    }
