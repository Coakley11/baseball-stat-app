"""Live Draft recommendation tables — team-on-clock scoped, no Streamlit imports."""

from __future__ import annotations

from typing import Any

import pandas as pd

from live_draft_recommendation_context import build_live_draft_recommendation_context


def _sort_draft_candidates(df, columns, *, ascending=None):
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return df
    if ascending is None:
        asc = [False] * len(cols)
    elif isinstance(ascending, bool):
        asc = [ascending] * len(cols)
    else:
        asc = list(ascending)
        if len(asc) < len(cols):
            asc = asc + [asc[-1] if asc else False] * (len(cols) - len(asc))
        asc = asc[: len(cols)]
    return df.sort_values(cols, ascending=asc, na_position="last")


def _score_available(available, roster_df, rule, target_counts, config=None, room=None):
    from live_draft_pick_scoring import (
        _draft_lab_infer_category_needs,
        apply_draft_pick_scoring,
        enrich_player_survival_metrics,
    )

    config = config or {}
    fantasy_format = config.get("fantasy_format", "5x5 Roto")
    current_pick = int(config.get("current_pick", 1) or 1)
    category_needs = config.get("category_needs")
    if category_needs is None and roster_df is not None and not roster_df.empty:
        try:
            from draft_needs import infer_hitter_category_needs

            category_needs = infer_hitter_category_needs(
                roster_df,
                available,
                fantasy_format=fantasy_format,
            )
        except ImportError:
            category_needs = _draft_lab_infer_category_needs(roster_df, available, fantasy_format)
    scored, gaps = apply_draft_pick_scoring(
        available,
        roster_df,
        fantasy_format=fantasy_format,
        target_counts=target_counts,
        current_pick=current_pick,
        category_needs=category_needs,
        needed_positions=config.get("needed_positions"),
        use_ml_blend=bool(config.get("use_ml_blend", False)),
        ml_blend_weight=float(config.get("ml_blend_weight") or 0),
        room=room,
    )
    scored = enrich_player_survival_metrics(
        scored,
        current_pick=current_pick,
        next_user_pick=config.get("next_user_pick"),
        num_teams=int(config.get("num_teams", 12) or 12),
    )
    rule = str(rule).strip().lower()
    if rule == "best market rank":
        scored["_pick_score"] = -pd.to_numeric(scored.get("Market Rank"), errors="coerce").fillna(9999)
        scored = _sort_draft_candidates(
            scored, ["_pick_score", "Decision Score", "Expected Fantasy Value"], ascending=False
        )
    elif rule == "best model rank":
        scored["_pick_score"] = -pd.to_numeric(scored.get("Model Rank"), errors="coerce").fillna(9999)
        scored = _sort_draft_candidates(
            scored, ["_pick_score", "Decision Score", "Expected Fantasy Value"], ascending=False
        )
    elif rule == "best projected fantasy value":
        scored = _sort_draft_candidates(
            scored, ["Expected Fantasy Value", "Model Rank"], ascending=[False, True]
        )
    elif rule == "best roster need":
        scored = _sort_draft_candidates(
            scored, ["Positional Fit", "Draft Fit Score", "Expected Fantasy Value"], ascending=False
        )
    else:
        scored = _sort_draft_candidates(
            scored, ["Decision Score", "Draft Fit Score", "Expected Fantasy Value"], ascending=False
        )
    return scored, gaps


def live_draft_recommendations(
    room: dict[str, Any],
    top_n: int = 8,
    team: str | None = None,
    session: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return recommendation tables for the team currently on the clock."""
    del team  # Live Draft always uses on-clock team; explicit overrides are ignored.
    context = build_live_draft_recommendation_context(room, session)
    team_on_clock = str(context.get("team_on_clock") or "").strip()
    if not team_on_clock:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    try:
        from live_draft_state import live_draft_get_available
    except ImportError:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    available = live_draft_get_available(room)
    if available.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    roster_df = pd.DataFrame(context.get("team_roster") or [])
    cfg = dict(context.get("league_settings") or {})
    cfg["current_pick"] = int(context.get("current_pick") or 1)
    cfg["next_user_pick"] = context.get("next_user_pick")
    cfg["num_teams"] = int(cfg.get("num_teams", len(room.get("teams", [])) or 12))
    cfg["needed_positions"] = list(context.get("needed_positions") or [])
    cfg["category_needs"] = list(context.get("category_needs") or [])
    target_counts = dict(context.get("target_counts") or {})

    try:
        from contextlib import nullcontext

        from page_perf_phases import session_perf_phase

        score_ctx = (
            session_perf_phase(session, "live_draft_score_available")
            if isinstance(session, dict)
            else nullcontext()
        )
    except ImportError:
        from contextlib import nullcontext

        score_ctx = nullcontext()

    with score_ctx:
        balanced, gaps = _score_available(
            available,
            roster_df,
            "balanced recommendation",
            target_counts,
            config=cfg,
            room=room,
        )

    if isinstance(session, dict):
        try:
            from live_draft_recommendation_context import RECOMMENDATION_CONTEXT_KEY

            diag = dict(session.get(RECOMMENDATION_CONTEXT_KEY) or {})
            if not balanced.empty:
                top = balanced.sort_values("Decision Score", ascending=False).head(1).iloc[0]
                diag["raw_value_score"] = float(pd.to_numeric(top.get("Expected Fantasy Value"), errors="coerce") or 0)
                diag["team_fit_score"] = float(pd.to_numeric(top.get("Roster Need Score"), errors="coerce") or 0)
                diag["scarcity_score"] = float(pd.to_numeric(top.get("Position Scarcity Score"), errors="coerce") or 0)
                diag["final_score"] = float(pd.to_numeric(top.get("Decision Score"), errors="coerce") or 0)
                try:
                    from live_draft_rec_badges import primary_recommendation_reason

                    diag["recommendation_reason"] = primary_recommendation_reason(
                        1,
                        top,
                        gaps=list(gaps or []),
                    )
                except ImportError:
                    diag["recommendation_reason"] = ""
            session[RECOMMENDATION_CONTEXT_KEY] = diag
        except ImportError:
            pass

    top_recommended = balanced.head(top_n)
    best_available = balanced.sort_values(
        ["Decision Score", "Expected Fantasy Value"], ascending=[False, False]
    ).head(top_n)
    positional = (
        balanced[balanced["Primary Position"].isin(gaps)]
        .sort_values(["Positional Fit", "Draft Fit Score"], ascending=[False, False])
        .head(top_n)
        if gaps
        else pd.DataFrame()
    )
    sleepers = balanced.sort_values(["Sleeper Score", "Draft Fit Score"], ascending=[False, False]).head(top_n)
    return top_recommended, best_available, positional, sleepers
