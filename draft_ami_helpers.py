"""Draft AMI context helpers — JSON-safe snapshots without Streamlit UI deps."""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

POSITION_ORDER = ["C", "1B", "2B", "3B", "SS", "OF", "DH", "P"]

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

def _import_baseball_app():
    """Load the Streamlit entry module (Linux deploy uses Streamlit_app.py)."""
    import importlib

    last_exc: Exception | None = None
    for name in ("streamlit_app", "Streamlit_app"):
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            last_exc = exc
    raise ImportError(str(last_exc or "streamlit_app/Streamlit_app not found"))


def _session_board_pick_count(session_state: dict[str, Any]) -> int:
    """Filled picks on the richest in-memory board (editor cache, runtime, blob)."""
    try:
        from draft_room_state import _resolve_richest_draft_board

        _, count, _ = _resolve_richest_draft_board(session_state)
        if count > 0:
            return int(count)
    except ImportError:
        pass
    return int(session_state.get("session_pick_count") or 0)


def _finalize_cache_build_trace(trace: dict[str, Any]) -> dict[str, Any]:
    action = str(trace.get("cache_action") or "skipped")
    if action in ("built_from_board", "already_present"):
        trace["skip_reason"] = "none"
    else:
        trace.setdefault("skip_reason", trace.get("reason") or "unknown")
    return trace


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
        app = _import_baseball_app()
        live_draft_current_slot = app.live_draft_current_slot
        live_draft_next_pick_for_team = app.live_draft_next_pick_for_team
        live_draft_recommendations = app.live_draft_recommendations
        serialize_live_draft_room = app.serialize_live_draft_room
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


def infer_draft_assistant_needs(
    roster_df: Any,
    draft_df: Any,
    *,
    draft_format: str = "5x5 Roto",
) -> tuple[list[str], list[str]]:
    """Auto-detect position and category needs (mirrors Draft Assistant defaults)."""
    import pandas as pd

    target_position_counts = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0}
    roster_df_auto = roster_df if roster_df is not None else pd.DataFrame()
    current_position_counts = (
        roster_df_auto["Primary Position"].value_counts().to_dict()
        if not roster_df_auto.empty and "Primary Position" in roster_df_auto.columns
        else {}
    )
    needed_positions: list[str] = []
    for pos in POSITION_ORDER:
        target = target_position_counts.get(pos, 1)
        current = int(current_position_counts.get(pos, 0))
        if target > 0 and current < target:
            needed_positions.append(pos)
    if not needed_positions:
        needed_positions = ["OF", "DH"]

    if draft_format == "5x5 Roto":
        cat_defs = {"R": "proj_R", "HR": "proj_HR", "RBI": "proj_RBI", "SB": "proj_SB", "BA": "proj_BA"}
        default_cat_fallback = ["HR", "RBI"]
    else:
        cat_defs = {
            "Power": "proj_HR",
            "Run Production": "proj_RBI",
            "Speed": "proj_SB",
            "Walks/OPS": "proj_OPS",
            "Volume": "AB",
        }
        default_cat_fallback = ["Power", "Run Production"]

    category_needs: list[str] = []
    if not roster_df_auto.empty and draft_df is not None and hasattr(draft_df, "columns"):
        for label, col in cat_defs.items():
            if col not in roster_df_auto.columns or col not in draft_df.columns:
                continue
            roster_val = pd.to_numeric(roster_df_auto[col], errors="coerce").mean()
            pool_val = pd.to_numeric(draft_df[col], errors="coerce").mean()
            if pd.notna(roster_val) and pd.notna(pool_val) and roster_val < pool_val:
                category_needs.append(label)
    if not category_needs:
        category_needs = default_cat_fallback
    return needed_positions, category_needs


def draft_ami_cache_has_pool(session_state: dict[str, Any]) -> bool:
    def _pool_len(val: Any) -> int:
        return len(val) if isinstance(val, list) else 0

    proj = session_state.get("_ami_draft_projection")
    if isinstance(proj, dict) and _pool_len(proj.get("available_players")) > 0:
        return True
    snap = session_state.get("_ami_draft_snapshot")
    return isinstance(snap, dict) and _pool_len(snap.get("available_players")) > 0


def build_draft_assistant_ami_cache_from_board(
    session_state: dict[str, Any],
    *,
    page: str = "Draft Assistant Simulator",
) -> dict[str, Any]:
    """Build Draft Assistant AMI cache on demand from the canonical draft board."""
    trace: dict[str, Any] = {
        "cache_action": "skipped",
        "cache_source": "draft_board_on_demand",
    }
    if draft_ami_cache_has_pool(session_state):
        trace["cache_action"] = "already_present"
        return _finalize_cache_build_trace(trace)

    try:
        import pandas as pd
        from draft_room_state import (
            _resolve_richest_draft_board,
            draft_board_summary_for_team,
            get_canonical_draft_board,
            sync_draft_room_session_before_save,
            table_pick_count,
        )
    except ImportError as exc:
        trace["reason"] = f"draft_room_state: {exc}"
        return _finalize_cache_build_trace(trace)

    try:
        sync_draft_room_session_before_save(session_state)
    except Exception:
        pass

    board, pick_count, board_source = _resolve_richest_draft_board(session_state)
    trace["board_resolve_source"] = board_source
    trace["board_resolve_pick_count"] = pick_count
    trace["draft_board_source_key"] = session_state.get("draft_board_source_key")
    trace["session_has_draft_board"] = bool(session_state.get("session_has_draft_board"))
    trace["session_pick_count"] = session_state.get("session_pick_count")

    if pick_count <= 0 and (
        session_state.get("session_has_draft_board")
        or int(session_state.get("session_pick_count") or 0) > 0
    ):
        board = get_canonical_draft_board(session_state)
        pick_count = table_pick_count(board)
        trace["board_fallback"] = "get_canonical_draft_board"
        trace["board_resolve_pick_count"] = pick_count

    if board.empty or "Player" not in board.columns:
        if int(session_state.get("session_pick_count") or 0) > 0:
            trace["reason"] = "empty_board_despite_session_pick_count"
        else:
            trace["reason"] = "empty_board"
        return _finalize_cache_build_trace(trace)

    filled = board[board["Player"].astype(str).str.strip().ne("")]
    if filled.empty:
        trace["reason"] = "no_picks_on_board"
        return _finalize_cache_build_trace(trace)

    team_names = sorted(board["Team"].dropna().astype(str).unique().tolist()) if "Team" in board.columns else []
    assistant_team = str(
        session_state.get("draft_assistant_synced_team")
        or session_state.get("room_your_team")
        or (team_names[0] if team_names else "")
    ).strip()
    pick_adjustment = int(session_state.get("draft_pick_adjustment") or 0)
    num_teams = int(session_state.get("room_team_count") or len(team_names) or 12)
    summary = draft_board_summary_for_team(
        board,
        your_team=assistant_team,
        team_names=team_names,
        pick_adjustment=pick_adjustment,
        num_teams=num_teams,
    )
    current_pick = int(summary["current_pick"])

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

    try:
        app = _import_baseball_app()
    except Exception as exc:
        trace["reason"] = f"streamlit_app: {exc}"
        return _finalize_cache_build_trace(trace)

    market_df = app.load_fantasypros_market_data()
    if market_df.empty:
        trace["reason"] = "empty_market_df"
        return trace

    yearly_df = getattr(app, "yearly_df", None)
    if yearly_df is None:
        try:
            _, yearly_df, _ = app.load_data()
        except Exception as exc:
            trace["reason"] = f"load_data: {exc}"
            return _finalize_cache_build_trace(trace)

    draft_window = int(session_state.get("draft_window") or 3)
    draft_format = str(
        session_state.get("draft_format")
        or session_state.get("draft_lab_scoring_type")
        or "5x5 Roto"
    )
    use_ml = bool(session_state.get("draft_use_ml_blend", True))
    ml_weight = float(session_state.get("draft_ml_blend_weight") or 0.12)
    ml_min_games = int(session_state.get("draft_ml_min_games_signal") or 50)
    projection_style = str(session_state.get("fantasy_draft_projection_style") or "Balanced")

    try:
        draft_df = app.build_unified_draft_player_pool(
            yearly_df,
            market_df,
            draft_window=draft_window,
            fantasy_format=draft_format,
            projection_style=projection_style,
            use_ml_blend=use_ml,
            ml_blend_weight=ml_weight,
            ml_min_games_for_signal=ml_min_games,
        )
    except Exception as exc:
        trace["reason"] = f"build_pool: {exc}"
        log.exception("build_draft_assistant_ami_cache_from_board pool build failed")
        return _finalize_cache_build_trace(trace)

    roster_df_auto = draft_df[draft_df["fullName"].isin(set(my_roster))].copy()
    needed_positions, category_needs = infer_draft_assistant_needs(
        roster_df_auto,
        draft_df,
        draft_format=draft_format,
    )
    target_position_counts = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0}
    current_position_counts = (
        roster_df_auto["Primary Position"].value_counts().to_dict()
        if not roster_df_auto.empty and "Primary Position" in roster_df_auto.columns
        else {}
    )

    available = draft_df[~draft_df["fullName"].isin(drafted_or_owned)].copy()
    if available.empty:
        trace["reason"] = "no_undrafted_players"
        return trace

    try:
        available, _gaps, position_summary_rows = app.apply_draft_pick_scoring(
            available,
            roster_df_auto,
            fantasy_format=draft_format,
            target_counts=target_position_counts,
            current_pick=current_pick,
            category_needs=category_needs,
            needed_positions=needed_positions,
            use_ml_blend=use_ml,
            ml_blend_weight=ml_weight,
            return_position_summary=True,
            recommendation_mode="draft_fit",
        )
    except Exception as exc:
        trace["reason"] = f"apply_scoring: {exc}"
        log.exception("build_draft_assistant_ami_cache_from_board scoring failed")
        return _finalize_cache_build_trace(trace)

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

    top_n = int(session_state.get("draft_top_n") or 10)
    recs = available.sort_values("Draft Fit Score", ascending=False).head(top_n)
    avail_sorted = available.sort_values("Expected Fantasy Value", ascending=False)

    try:
        from applied_math_context import cache_draft_assistant_ami_context

        cache_draft_assistant_ami_context(
            session_state,
            page=page,
            recs_df=recs,
            current_pick=current_pick,
            my_roster=my_roster,
            drafted_total=len(drafted_or_owned),
            draft_format=draft_format,
            assistant_team=assistant_team,
            needed_positions=needed_positions,
            category_needs=category_needs,
            drafted_players=sorted(drafted_or_owned),
            best_available_df=avail_sorted.head(6),
            available_df=avail_sorted,
            position_scarcity=median_scarcity_dropoff,
        )
    except Exception as exc:
        trace["reason"] = f"cache_write: {exc}"
        log.exception("build_draft_assistant_ami_cache_from_board cache write failed")
        return _finalize_cache_build_trace(trace)

    pool_diag = session_state.get("_ami_draft_projection", {}).get("player_pool_diagnostics", {})
    trace.update(
        {
            "cache_action": "built_from_board",
            "current_pick": current_pick,
            "draft_round": summary.get("current_round"),
            "assistant_team": assistant_team,
            "available_players_count": len(
                (session_state.get("_ami_draft_projection") or {}).get("available_players") or []
            ),
            "player_pool_source": pool_diag.get("player_pool_source") if isinstance(pool_diag, dict) else None,
        }
    )
    return _finalize_cache_build_trace(trace)


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
