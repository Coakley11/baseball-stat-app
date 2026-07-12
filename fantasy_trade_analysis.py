"""Structured exact-trade analysis for Trade Center."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from fantasy_trade_player_index import (
    HITTER_STAT_CATEGORIES,
    format_player_option_label,
    format_player_stat_line,
    format_position_label,
    player_row,
)


def _player_names_label(players: list[str]) -> str:
    names = [str(p).strip() for p in players if str(p).strip()]
    if not names:
        return "—"
    if len(names) == 1:
        return names[0]
    return ", ".join(names)


def build_trade_analysis_package(
    *,
    give_players: list[str],
    receive_players: list[str],
    roster_stats: pd.DataFrame,
    standings: pd.DataFrame | None,
    my_team: str,
    evaluate_trade_fn: Callable[..., tuple[pd.DataFrame, str, float]],
    build_trade_verdict_text_fn: Callable[..., str],
    summarize_team_category_needs_fn: Callable[..., dict[str, bool]] | None = None,
    source_offer_id: str = "",
    source_idea_id: str = "",
) -> dict[str, Any]:
    give = [str(p).strip() for p in give_players if str(p).strip()]
    receive = [str(p).strip() for p in receive_players if str(p).strip()]
    trade_eval, verdict, weighted_gain = evaluate_trade_fn(
        give,
        receive,
        roster_stats,
        roster_stats,
        standings,
        my_team,
    )
    needs = summarize_team_category_needs_fn(standings, my_team) if callable(summarize_team_category_needs_fn) else {}

    player_rows: list[dict[str, Any]] = []
    for side, names in (("Give", give), ("Receive", receive)):
        for name in names:
            row = player_row(roster_stats, name)
            owner = str(row.get("Team") or "") if row is not None else ""
            player_rows.append(
                {
                    "side": side,
                    "player": name,
                    "position": format_position_label(roster_stats, name),
                    "owner": owner,
                    "stats_line": format_player_stat_line(roster_stats, name),
                }
            )

    category_rows = []
    helps: list[str] = []
    hurts: list[str] = []
    for _, rec in trade_eval.iterrows():
        cat = str(rec.get("Category") or "")
        net = pd.to_numeric(rec.get("Net Gain"), errors="coerce")
        give_val = pd.to_numeric(rec.get("Give Away"), errors="coerce")
        recv_val = pd.to_numeric(rec.get("Receive"), errors="coerce")
        change = float(net) if pd.notna(net) else 0.0
        category_rows.append(
            {
                "category": cat,
                "give": give_val,
                "receive": recv_val,
                "change": change,
            }
        )
        if change > 0:
            helps.append(cat)
        elif change < 0:
            hurts.append(cat)

    positions_lost = [format_position_label(roster_stats, p) for p in give]
    positions_gained = [format_position_label(roster_stats, p) for p in receive]

    interpretation_parts: list[str] = []
    interpretation_parts.append(build_trade_verdict_text_fn(trade_eval, weighted_gain))
    if hurts:
        interpretation_parts.append(f"This trade may weaken {', '.join(hurts[:3])}.")
    if helps:
        interpretation_parts.append(f"It strengthens {', '.join(helps[:3])}.")

    title = f"Analysis: {_player_names_label(give)} for {_player_names_label(receive)}"

    return {
        "title": title,
        "give_players": give,
        "receive_players": receive,
        "verdict": str(verdict or ""),
        "weighted_gain": float(weighted_gain) if pd.notna(weighted_gain) else 0.0,
        "verdict_text": build_trade_verdict_text_fn(trade_eval, weighted_gain),
        "trade_eval": trade_eval.to_dict(orient="records"),
        "category_rows": category_rows,
        "player_rows": player_rows,
        "helps": helps,
        "hurts": hurts,
        "positions_lost": positions_lost,
        "positions_gained": positions_gained,
        "interpretation": " ".join(interpretation_parts),
        "source_offer_id": source_offer_id,
        "source_idea_id": source_idea_id,
    }


def analysis_matches_selection(analysis: dict[str, Any] | None, *, give: list[str], receive: list[str]) -> bool:
    if not isinstance(analysis, dict):
        return False
    return list(analysis.get("give_players") or []) == list(give) and list(analysis.get("receive_players") or []) == list(receive)
