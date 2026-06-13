"""Draft AMI context helpers — JSON-safe snapshots without Streamlit UI deps."""

from __future__ import annotations

from typing import Any

AMI_REC_COLUMNS = (
    "Primary Position",
    "Model Rank",
    "Market Rank",
    "Expected Fantasy Value",
    "Draft Fit Score",
    "Fantasy Edge",
    "Scarcity Score",
    "Positional Fit",
    "Sleeper Score",
    "Decision Score",
    "Survival Probability",
    "Survival Label",
    "Reason",
    "Strategy",
)


def compact_recommendation_rows(df_or_rows: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    """Normalize recommendation DataFrames or row dicts for AMI payloads."""
    rows: list[dict[str, Any]] = []
    if df_or_rows is None:
        return rows
    if hasattr(df_or_rows, "iterrows") and not getattr(df_or_rows, "empty", True):
        import pandas as pd

        for _, row in df_or_rows.head(limit).iterrows():
            name = str(row.get("fullName") or row.get("Player") or row.get("player") or "").strip()
            if not name:
                continue
            entry: dict[str, Any] = {"player": name}
            for col in AMI_REC_COLUMNS:
                if col in row.index and pd.notna(row.get(col)):
                    val = row.get(col)
                    if col in ("Reason", "Strategy") and val:
                        entry[col.lower()] = str(val)[:240]
                    else:
                        entry[col] = val
            rows.append(entry)
        return rows
    if isinstance(df_or_rows, list):
        for item in df_or_rows[:limit]:
            if isinstance(item, dict):
                name = str(item.get("Player") or item.get("fullName") or item.get("player") or "").strip()
                if name:
                    rows.append({"player": name, **{k: v for k, v in item.items() if k in AMI_REC_COLUMNS}})
            elif item:
                rows.append({"player": str(item).strip()})
    return rows


def compact_fantasy_market_rows(df_or_rows: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    """Sleepers/busts rows with Fantasy Edge and reasons."""
    rows: list[dict[str, Any]] = []
    if df_or_rows is None:
        return rows
    if hasattr(df_or_rows, "iterrows") and not getattr(df_or_rows, "empty", True):
        import pandas as pd

        for _, row in df_or_rows.head(limit).iterrows():
            name = str(row.get("fullName") or row.get("Player") or "").strip()
            if not name:
                continue
            entry: dict[str, Any] = {"player": name}
            for col in (
                "Team",
                "Primary Position",
                "Age",
                "Market Rank",
                "Model Rank",
                "Fantasy Edge",
                "Expected Fantasy Value",
                "Projected HR",
                "Projected RBI",
                "Projected SB",
                "Reason",
            ):
                if col in row.index and pd.notna(row.get(col)):
                    val = row.get(col)
                    if col == "Reason" and val:
                        entry["reason"] = str(val)[:240]
                    else:
                        entry[col] = val
            rows.append(entry)
    return rows


def gather_live_draft_ami_section(session: dict[str, Any], room: dict[str, Any] | None = None) -> dict[str, Any]:
    """Live Draft Room context for AMI (round, pick, board, recs, queue)."""
    out: dict[str, Any] = {}
    try:
        from live_draft_state import prepare_live_draft_state
    except ImportError:
        prepare_live_draft_state = None  # type: ignore[assignment]

    if prepare_live_draft_state is not None:
        prepare_live_draft_state(session)
    live_room = room if isinstance(room, dict) and room else session.get("live_draft_room")
    if not isinstance(live_room, dict) or not live_room:
        return out

    try:
        from streamlit_app import (
            live_draft_current_slot,
            live_draft_next_pick_for_team,
            live_draft_recommendations,
            serialize_live_draft_room,
        )
    except Exception:
        return out

    serialized = serialize_live_draft_room(live_room)
    cfg = dict(serialized.get("config") or live_room.get("config") or {})
    out["draft_state"] = {
        "status": serialized.get("status"),
        "current_pick_index": serialized.get("current_pick_index"),
        "draft_room_id": serialized.get("draft_room_id"),
    }
    for k in ("scoring_type", "draft_type", "league_name", "picks_per_team", "num_teams", "your_team"):
        if cfg.get(k) is not None:
            out.setdefault("scoring_settings", {})[k] = cfg.get(k)

    slot = live_draft_current_slot(live_room)
    user_team = str(cfg.get("your_team") or session.get("room_your_team") or "")
    if slot:
        idx = int(serialized.get("current_pick_index") or 0)
        num_teams = int(cfg.get("num_teams") or len(live_room.get("teams") or []) or 12)
        out["current_pick"] = int(slot.get("Pick") or idx + 1)
        out["draft_round"] = (idx // num_teams) + 1 if num_teams else None
        on_clock = str(slot.get("Team") or "")
        out["on_clock_team"] = on_clock
        if user_team:
            out["your_team"] = user_team
            out["my_next_pick"] = live_draft_next_pick_for_team(live_room, user_team)
            roster = (live_room.get("rosters") or {}).get(user_team) or []
            out["user_roster"] = [
                str(p.get("fullName") or p.get("Player") or p)[:80]
                for p in roster[:24]
                if isinstance(p, dict)
            ]
            if on_clock == user_team:
                out["my_pick_now"] = True

    board = live_room.get("draft_board") or []
    if isinstance(board, list) and board:
        out["latest_picks"] = [
            {
                "round": b.get("Round"),
                "pick": b.get("Pick"),
                "team": b.get("Draft Team") or b.get("Team"),
                "player": b.get("Player") or b.get("fullName"),
                "position": b.get("Primary Position"),
            }
            for b in board[-12:]
            if isinstance(b, dict)
        ]

    top_rec, best_avail, pos_fit, value_sleep = live_draft_recommendations(live_room, top_n=8)
    out["recommended_players"] = compact_recommendation_rows(top_rec)
    out["available_players"] = compact_recommendation_rows(best_avail)
    out["positional_fits"] = compact_recommendation_rows(pos_fit)
    out["sleepers"] = compact_recommendation_rows(value_sleep)
    if pos_fit is not None and hasattr(pos_fit, "empty") and not pos_fit.empty:
        try:
            gaps = sorted(
                {
                    str(p)
                    for p in pos_fit.get("Primary Position", []).dropna().astype(str).tolist()
                    if str(p).strip()
                }
            )
            if gaps:
                out["needed_positions"] = gaps[:8]
        except Exception:
            pass
    merge_draft_workflow_into_snapshot(session, out)
    return out


def merge_draft_workflow_into_snapshot(session: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Attach queue, watchlist, and tracked players to any draft AMI snapshot."""
    try:
        from draft_state import gather_draft_workflow

        dw = gather_draft_workflow(session)
        if dw.get("queue"):
            snapshot["draft_queue"] = list(dw["queue"])[:12]
        if dw.get("watchlist_focus"):
            snapshot["watchlist_focus"] = list(dw["watchlist_focus"])[:20]
        if dw.get("watchlist_favorites"):
            snapshot["watchlist_favorites"] = list(dw["watchlist_favorites"])[:20]
    except Exception:
        pass
    tracked = session.get("workflow_recently_viewed")
    if isinstance(tracked, list) and tracked:
        snapshot["tracked_players"] = [str(x).strip() for x in tracked[:20] if str(x).strip()]
    return snapshot


def draft_ami_guidance(page: str) -> str:
    """Solver framing for draft acceptance questions."""
    p = str(page or "").strip()
    if p == "Fantasy Sleepers & Busts":
        return (
            "Use sleepers_snapshot only — not generic rankings. "
            "Lead with direct sleeper/bust recommendation, roster fit, Fantasy Edge, drafted_exclusions. "
            "Questions: Should I take this sleeper? Which fits my roster? Highest upside? Safest? "
            "Structure: direct answer → why → scarcity → risk/upside → alternatives → what-if strategies."
        )
    if p == "Live Draft Room":
        return (
            "Use draft_snapshot from saved live draft + canonical board. "
            "Reference current round, current pick, my_next_pick, on_clock_team, latest_picks, queue, watchlist. "
            "Questions: On the clock — who to take? Reach or wait? Safest vs highest-upside pick? "
            "Structure: direct answer → roster fit → scarcity → risk/upside → alternatives → what-if."
        )
    if p == "Draft Assistant Simulator":
        return (
            "Use draft_snapshot + draft_projection from the saved canonical draft board. "
            "Reference drafted players, available pool, queue, watchlist, tracked players, needs, scarcity, recs. "
            "Questions: Who next? Roster needs? Best values? Risk? Power/speed/pitching priority shifts? "
            "Structure: direct answer → why → scarcity → risk/upside → alternatives → what-if."
        )
    if p == "Trend Value":
        return (
            "Use trend_summary, metrics, and draft_status for the focused player. "
            "Tie slope/R²/delta to draft timing and valuation — not generic trend commentary. "
            "Questions: Over/undervalued? Right time to draft? Risk profile?"
        )
    if p == "Valuation":
        return (
            "Use valuation_snapshot and draft_status. Compare Valuation Score, trend component, and market rank. "
            "Questions: Over/undervalued? Right time to draft? Risk profile?"
        )
    return (
        "Answer using draft_snapshot and draft_projection: drafted players, canonical draft board, "
        "queue, top recommendations, roster/team needs, scarcity, and best available. "
        "Never give generic advice — use the structured context only."
    )
