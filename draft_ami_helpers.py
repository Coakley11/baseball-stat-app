"""Draft AMI context helpers — JSON-safe snapshots without Streamlit UI deps."""

from __future__ import annotations

import re
from typing import Any

AMI_POOL_TOP_OVERALL = 12
AMI_POOL_TOP_PER_POSITION = 5
AMI_POOL_TOP_NEEDED_POSITION = 10
AMI_POOL_FINAL_CAP = 80
AMI_POOL_SOURCE = "position_representative_v1"

AMI_POSITION_TAGS: tuple[str, ...] = ("C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "CL", "DH", "P")

_POSITION_QUESTION_ALIASES: dict[str, tuple[str, ...]] = {
    "C": ("catcher", "catchers"),
    "1B": ("first base", "first baseman", "first basemen", "1b"),
    "2B": ("second base", "second baseman", "second basemen", "2b"),
    "3B": ("third base", "third baseman", "third basemen", "3b"),
    "SS": ("shortstop", "shortstops", "ss"),
    "OF": ("outfield", "outfielder", "outfielders", "of"),
    "SP": ("starting pitcher", "starting pitchers", "starter", "starters", "sp"),
    "RP": ("relief pitcher", "relief pitchers", "reliever", "relievers", "rp"),
    "CL": ("closer", "closers", "cl"),
    "DH": ("designated hitter", "dh"),
    "P": ("pitcher", "pitchers", "pitching"),
}

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


def _normalize_player_name(raw: Any) -> str:
    return str(raw or "").split(" (")[0].strip()


def _player_name_from_row(row: Any) -> str:
    if hasattr(row, "get"):
        return _normalize_player_name(row.get("fullName") or row.get("Player") or row.get("player"))
    return _normalize_player_name(row)


def _position_from_row(row: Any) -> str:
    if hasattr(row, "get"):
        return str(row.get("Primary Position") or row.get("position") or row.get("pos") or "").strip().upper()
    return ""


def _sort_available_df(df: Any) -> Any:
    import pandas as pd

    if df is None or not hasattr(df, "empty") or df.empty:
        return df
    out = df.copy()
    if "Expected Fantasy Value" in out.columns:
        return out.sort_values("Expected Fantasy Value", ascending=False)
    if "Market Rank" in out.columns:
        return out.sort_values("Market Rank", ascending=True)
    return out


def _filter_undrafted_df(df: Any, drafted_players: list[str] | None) -> Any:
    import pandas as pd

    if df is None or not hasattr(df, "empty") or df.empty:
        return df
    drafted = {_normalize_player_name(n).lower() for n in (drafted_players or []) if _normalize_player_name(n)}
    if not drafted:
        return df
    name_col = "fullName" if "fullName" in df.columns else ("Player" if "Player" in df.columns else None)
    if not name_col:
        return df
    mask = ~df[name_col].astype(str).map(lambda x: _normalize_player_name(x).lower()).isin(drafted)
    return df.loc[mask].copy()


def detect_positions_from_question(question: str) -> list[str]:
    """Detect fantasy positions referenced in a draft-market or roster question."""
    q = str(question or "").strip()
    if not q:
        return []
    low = q.lower()
    found: list[str] = []
    for pos, aliases in _POSITION_QUESTION_ALIASES.items():
        if pos in found:
            continue
        if re.search(rf"\b{re.escape(pos.lower())}\b", low):
            found.append(pos)
            continue
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", low):
                found.append(pos)
                break
    return found


def _position_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        pos = str(row.get("Primary Position") or row.get("position") or row.get("pos") or "?").strip().upper() or "?"
        out[pos] = out.get(pos, 0) + 1
    return out


def build_undrafted_player_lookup(df: Any, *, drafted_players: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Compact row lookup keyed by normalized player name (lowercase)."""
    import pandas as pd

    pool = _filter_undrafted_df(df, drafted_players)
    pool = _sort_available_df(pool)
    if pool is None or not hasattr(pool, "empty") or pool.empty:
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    for _, row in pool.iterrows():
        name = _player_name_from_row(row)
        if not name:
            continue
        key = name.lower()
        if key in lookup:
            continue
        rows = compact_recommendation_rows(pd.DataFrame([row]), limit=1)
        if rows:
            lookup[key] = rows[0]
    return lookup


def build_position_representative_available_pool(
    available_df: Any,
    *,
    needed_positions: list[str] | None = None,
    requested_positions: list[str] | None = None,
    question_players: list[str] | None = None,
    drafted_players: list[str] | None = None,
    top_overall: int = AMI_POOL_TOP_OVERALL,
    top_per_position: int = AMI_POOL_TOP_PER_POSITION,
    top_needed_position: int = AMI_POOL_TOP_NEEDED_POSITION,
    final_cap: int = AMI_POOL_FINAL_CAP,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    """
    Build a position-representative available_players payload for AMI.

    Combines top overall EV, top-N per position, extras for needed/question positions,
    and explicit question-player rows. Returns compact rows, diagnostics, and full lookup.
    """
    import pandas as pd

    empty_diag: dict[str, Any] = {
        "available_players_count": 0,
        "available_players_position_counts": {},
        "needed_positions": list(needed_positions or [])[:8],
        "requested_position": list(requested_positions or [])[:8],
        "catchers_in_available_players": 0,
        "player_pool_source": AMI_POOL_SOURCE,
        "player_pool_cap": int(final_cap),
        "drafted_exclusions_count": len(drafted_players or []),
    }
    if available_df is None or not hasattr(available_df, "empty") or available_df.empty:
        return [], empty_diag, {}

    pool = _filter_undrafted_df(available_df, drafted_players)
    pool = _sort_available_df(pool)
    if pool is None or pool.empty:
        return [], empty_diag, {}

    lookup = build_undrafted_player_lookup(pool, drafted_players=drafted_players)
    pos_col = "Primary Position" if "Primary Position" in pool.columns else None

    slice_keys: dict[str, list[str]] = {}

    def _keys_for_frame(frame: Any, label: str) -> list[str]:
        keys: list[str] = []
        if frame is None or not hasattr(frame, "empty") or frame.empty:
            slice_keys[label] = keys
            return keys
        for _, row in frame.iterrows():
            name = _player_name_from_row(row)
            key = name.lower()
            if key and key not in keys:
                keys.append(key)
        slice_keys[label] = keys
        return keys

    _keys_for_frame(pool.head(max(1, int(top_overall))), "overall")

    if pos_col:
        for pos in AMI_POSITION_TAGS:
            pos_frame = pool[pool[pos_col].astype(str).str.upper().eq(pos)]
            _keys_for_frame(pos_frame.head(max(1, int(top_per_position))), f"pos_{pos}")

    need_set = {str(p).strip().upper() for p in (needed_positions or []) if str(p).strip()}
    req_set = {str(p).strip().upper() for p in (requested_positions or []) if str(p).strip()}
    for pos in need_set | req_set:
        if not pos_col:
            break
        pos_frame = pool[pool[pos_col].astype(str).str.upper().eq(pos)]
        _keys_for_frame(pos_frame.head(max(1, int(top_needed_position))), f"need_{pos}")

    question_keys: list[str] = []
    for raw_name in question_players or []:
        key = _normalize_player_name(raw_name).lower()
        if key and key in lookup and key not in question_keys:
            question_keys.append(key)
    slice_keys["question"] = question_keys

    protected: set[str] = set()
    for label, keys in slice_keys.items():
        if label == "overall":
            continue
        protected.update(keys)

    merged_keys: list[str] = []
    seen: set[str] = set()
    for label in ["overall"] + [k for k in slice_keys if k != "overall" and k != "question"] + ["question"]:
        for key in slice_keys.get(label, []):
            if key and key not in seen:
                seen.add(key)
                merged_keys.append(key)

    if len(merged_keys) > int(final_cap):
        overall_only = [k for k in slice_keys.get("overall", []) if k not in protected]
        trim = len(merged_keys) - int(final_cap)
        drop: set[str] = set()
        for key in reversed(overall_only):
            if len(drop) >= trim:
                break
            drop.add(key)
        merged_keys = [k for k in merged_keys if k not in drop]

    selected_rows = [lookup[k] for k in merged_keys if k in lookup]
    selected_rows.sort(key=lambda r: float(r.get("Expected Fantasy Value") or 0), reverse=True)

    requested = list(dict.fromkeys(list(requested_positions or [])))
    diag: dict[str, Any] = {
        "available_players_count": len(selected_rows),
        "available_players_position_counts": _position_counts(selected_rows),
        "needed_positions": list(needed_positions or [])[:8],
        "requested_position": requested[:8],
        "catchers_in_available_players": sum(
            1 for r in selected_rows if str(r.get("Primary Position", "")).upper() == "C"
        ),
        "player_pool_source": AMI_POOL_SOURCE,
        "player_pool_cap": int(final_cap),
        "drafted_exclusions_count": len(drafted_players or []),
        "undrafted_pool_size": len(lookup),
    }
    return selected_rows, diag, lookup


def augment_available_pool_for_question(
    ctx: dict[str, Any],
    *,
    lookup: dict[str, dict[str, Any]] | None,
    requested_positions: list[str] | None = None,
    question_players: list[str] | None = None,
    final_cap: int = AMI_POOL_FINAL_CAP,
) -> dict[str, Any]:
    """At send time: add question-player and requested-position rows missing from cached pool."""
    if not isinstance(lookup, dict) or not lookup:
        return ctx.get("player_pool_diagnostics") if isinstance(ctx.get("player_pool_diagnostics"), dict) else {}

    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    proj = ctx.get("draft_projection") if isinstance(ctx.get("draft_projection"), dict) else {}
    existing = list(ctx.get("available_players") or snap.get("available_players") or proj.get("available_players") or [])
    seen = {
        _normalize_player_name(r.get("player") if isinstance(r, dict) else r).lower()
        for r in existing
        if (isinstance(r, dict) and r.get("player")) or r
    }
    merged = [r for r in existing if isinstance(r, dict)]
    added_keys: set[str] = set()

    req_positions = list(dict.fromkeys(list(requested_positions or [])))
    for pos in req_positions:
        pos_rows = [
            row
            for row in lookup.values()
            if str(row.get("Primary Position", "")).upper() == pos
        ]
        pos_rows.sort(key=lambda r: float(r.get("Expected Fantasy Value") or 0), reverse=True)
        for row in pos_rows[:AMI_POOL_TOP_NEEDED_POSITION]:
            key = _normalize_player_name(row.get("player")).lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(row)
                added_keys.add(key)

    for raw_name in question_players or []:
        key = _normalize_player_name(raw_name).lower()
        row = lookup.get(key)
        if row and key not in seen:
            seen.add(key)
            merged.append(row)
            added_keys.add(key)

    if len(merged) > max(1, int(final_cap)):
        drop_candidates = [
            r for r in merged
            if _normalize_player_name(r.get("player")).lower() not in added_keys
        ]
        drop_candidates.sort(key=lambda r: float(r.get("Expected Fantasy Value") or 0))
        while len(merged) > int(final_cap) and drop_candidates:
            victim = drop_candidates.pop(0)
            merged = [r for r in merged if r is not victim]

    merged.sort(key=lambda r: float(r.get("Expected Fantasy Value") or 0), reverse=True)

    ctx["available_players"] = merged
    snap["available_players"] = merged
    ctx["draft_snapshot"] = snap
    if proj:
        proj["available_players"] = merged
        ctx["draft_projection"] = proj

    diag = dict(ctx.get("player_pool_diagnostics") or snap.get("player_pool_diagnostics") or {})
    diag.update(
        {
            "available_players_count": len(merged),
            "available_players_position_counts": _position_counts(merged),
            "requested_position": req_positions[:8],
            "catchers_in_available_players": sum(
                1 for r in merged if str(r.get("Primary Position", "")).upper() == "C"
            ),
            "player_pool_source": AMI_POOL_SOURCE,
            "player_pool_cap": int(final_cap),
            "send_augmented": True,
        }
    )
    ctx["player_pool_diagnostics"] = diag
    snap["player_pool_diagnostics"] = diag
    ctx["draft_snapshot"] = snap
    return diag


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
