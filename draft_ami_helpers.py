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
    if "C" not in found and re.search(r"\bat\s+c\b", low):
        found.append("C")
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
                # Core projections
                "Projected HR",
                "Projected RBI",
                "Projected SB",
                "Projected OPS",
                "Projected BA",
                "Projected R",
                # ADP / market consensus context
                "ADP",
                "ADP Rank",
                "FantasyPros Rank",
                "Expert Avg Rank",
                # Risk / disagreement — how much experts agree on this player
                "Risk / Disagreement",
                "Expert Std Dev",
                # Current-season production rank for upside/risk framing
                "Current Rank",
                "Current Production Score",
                # Plain-language reason
                "Reason",
            ):
                if col in row.index and pd.notna(row.get(col)):
                    val = row.get(col)
                    if col == "Reason" and val:
                        entry["reason"] = str(val)[:300]
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
        overall_pick = idx + 1
        round_from_slot = slot.get("Round")
        out["current_pick"] = overall_pick
        if round_from_slot is not None and str(round_from_slot).strip():
            out["draft_round"] = int(round_from_slot)
        elif num_teams:
            out["draft_round"] = (idx // num_teams) + 1
        out["pick_in_round"] = slot.get("Pick")
        on_clock = str(slot.get("Team") or "")
        out["on_clock_team"] = on_clock
        if user_team:
            out["your_team"] = user_team
            out["my_next_pick"] = live_draft_next_pick_for_team(live_room, user_team)
            roster = (live_room.get("rosters") or {}).get(user_team) or []
            roster_detail: list[dict[str, str]] = []
            roster_index: dict[str, str] = {}
            for p in roster[:24]:
                if not isinstance(p, dict):
                    continue
                name = str(p.get("fullName") or p.get("Player") or "").strip()
                pos = str(
                    p.get("Primary Position") or p.get("position") or p.get("pos") or ""
                ).strip()
                if name:
                    roster_detail.append({"player": name, "Primary Position": pos})
                    if pos:
                        roster_index[name.lower()] = pos
            out["user_roster"] = [str(r.get("player") or "")[:80] for r in roster_detail if r.get("player")]
            if roster_detail:
                out["user_roster_detail"] = roster_detail
            if roster_index:
                out["roster_position_index"] = roster_index
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


def infer_needed_positions_from_roster_detail(
    detail: list[dict[str, str]],
    *,
    draft_format: str = "5x5 Roto",
) -> tuple[list[str], list[str]]:
    """Position/category needs from roster detail rows (team review send path)."""
    import pandas as pd

    rows = [
        {
            "player": str(r.get("player") or r.get("Player") or "").strip(),
            "Primary Position": str(r.get("Primary Position") or r.get("position") or "").strip(),
        }
        for r in detail
        if isinstance(r, dict) and str(r.get("player") or r.get("Player") or "").strip()
    ]
    roster_df = pd.DataFrame(rows)
    return infer_draft_assistant_needs(roster_df, pd.DataFrame(), draft_format=draft_format)


def build_roster_display_lines(
    names: list[str],
    detail: list[dict[str, str]],
    index: dict[str, str],
) -> list[str]:
    """Human-readable roster lines for AMI solvers (e.g. 'SS: Francisco Lindor')."""
    lines: list[str] = []
    detail_by_name = {
        str(r.get("player") or r.get("Player") or "").strip().lower(): str(
            r.get("Primary Position") or r.get("position") or ""
        ).strip()
        for r in detail
        if isinstance(r, dict)
    }
    for name in names:
        clean = str(name or "").strip()
        if not clean:
            continue
        token = clean.lower()
        pos = detail_by_name.get(token) or str(index.get(token) or "").strip()
        lines.append(f"{pos or '?'}: {clean}")
    return lines


def _available_pool_count_and_source(block: dict[str, Any] | None) -> tuple[int, str]:
    if not isinstance(block, dict):
        return 0, ""
    avail = block.get("available_players")
    count = len(avail) if isinstance(avail, list) else 0
    diag = block.get("player_pool_diagnostics")
    source = str(diag.get("player_pool_source") or "") if isinstance(diag, dict) else ""
    return count, source


def _roster_position_detail_for_names(
    session_state: dict[str, Any],
    roster_names: list[str],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Resolve roster name → position from global lookup, pool, and cached AMI rows."""
    detail: list[dict[str, str]] = []
    index: dict[str, str] = {}

    global_lookup: dict[str, str] = {}
    for src in (
        session_state.get("_ami_player_position_lookup"),
        (session_state.get("_ami_draft_snapshot") or {}).get("player_position_lookup"),
        (session_state.get("_ami_draft_snapshot") or {}).get("roster_position_index"),
    ):
        if isinstance(src, dict):
            global_lookup.update({str(k).lower(): str(v) for k, v in src.items() if k and v})

    snap = session_state.get("_ami_draft_snapshot")
    existing_detail: dict[str, str] = {}
    if isinstance(snap, dict):
        for row in snap.get("user_roster_detail") or []:
            if isinstance(row, dict):
                name = str(row.get("player") or row.get("Player") or "").strip()
                pos = _index_row_position(row)
                if name and pos:
                    existing_detail[name.lower()] = pos

    pool_rows: list[dict[str, Any]] = []
    if isinstance(snap, dict):
        for key in ("available_players", "recommended_players", "best_available_players"):
            for row in snap.get(key) or []:
                if isinstance(row, dict):
                    pool_rows.append(row)
    lookup = session_state.get("_ami_undrafted_pool_lookup")
    if isinstance(lookup, dict):
        pool_rows.extend(v for v in lookup.values() if isinstance(v, dict))

    def _pos_for_name(name: str) -> str:
        token = name.lower()
        if token in global_lookup:
            return global_lookup[token]
        if token in existing_detail:
            return existing_detail[token]
        for row in pool_rows:
            row_name = str(row.get("player") or row.get("Player") or row.get("fullName") or "").strip()
            if row_name.lower() == token:
                pos = str(
                    row.get("Primary Position") or row.get("position") or row.get("pos") or ""
                ).strip()
                if pos:
                    return pos
        return _position_for_name_from_yearly_data(name)

    for name in roster_names:
        clean = str(name or "").split(" (")[0].strip()
        if not clean:
            continue
        pos = _pos_for_name(clean)
        detail.append({"player": clean, "Primary Position": pos})
        if pos:
            index[clean.lower()] = pos
    return detail, index


_YEARLY_NAME_POSITION_MAP: dict[str, str] | None = None


def _yearly_name_position_map() -> dict[str, str]:
    global _YEARLY_NAME_POSITION_MAP
    if _YEARLY_NAME_POSITION_MAP is not None:
        return _YEARLY_NAME_POSITION_MAP
    out: dict[str, str] = {}
    try:
        from draft_pool_engine import load_yearly_stat_data
    except ImportError:
        _YEARLY_NAME_POSITION_MAP = out
        return out
    try:
        yearly_df = load_yearly_stat_data()
    except Exception:
        _YEARLY_NAME_POSITION_MAP = out
        return out
    if yearly_df is None or getattr(yearly_df, "empty", True) or "fullName" not in yearly_df.columns:
        _YEARLY_NAME_POSITION_MAP = out
        return out
    pos_col = "Primary Position" if "Primary Position" in yearly_df.columns else None
    if not pos_col:
        _YEARLY_NAME_POSITION_MAP = out
        return out
    for _, row in yearly_df.iterrows():
        name = str(row.get("fullName") or "").strip().lower()
        pos = str(row.get(pos_col) or "").strip()
        if name and pos:
            out.setdefault(name, pos)
    _YEARLY_NAME_POSITION_MAP = out
    return out


def _position_for_name_from_yearly_data(name: str) -> str:
    """Last-resort position lookup from yearly stat table (board rows often lack Primary Position)."""
    clean = str(name or "").split(" (")[0].strip()
    if not clean:
        return ""
    return _yearly_name_position_map().get(clean.lower(), "")


def _board_player_position_lookup(session_state: dict[str, Any]) -> dict[str, str]:
    """Player name → position from canonical draft board rows."""
    out: dict[str, str] = {}
    try:
        from draft_room_state import get_canonical_draft_board
    except ImportError:
        return out
    board = get_canonical_draft_board(session_state)
    if board is None or getattr(board, "empty", True) or "Player" not in board.columns:
        return out
    pos_col = "Primary Position" if "Primary Position" in board.columns else None
    for _, row in board.iterrows():
        name = str(row.get("Player") or "").strip()
        if not name:
            continue
        pos = ""
        if pos_col:
            pos = str(row.get(pos_col) or "").strip()
        if not pos:
            pos = _position_for_name_from_yearly_data(name)
        if pos:
            out[name.lower()] = pos
    return out


def extract_draft_team_from_question(
    question: str,
    *,
    my_team: str = "",
    team_names: list[str] | None = None,
) -> str:
    """Resolve which fantasy team the user wants reviewed (empty = default/my team)."""
    q = str(question or "").strip()
    low = q.lower()
    names = [str(n).strip() for n in (team_names or []) if str(n).strip()]
    if not low:
        return my_team

    if re.search(r"\bmy (?:team|roster|picks|draft)\b", low) and not re.search(r"\bteam\s+\d", low):
        return my_team

    m = re.search(r"\bteam\s+(\d+|[a-z])\b", low)
    if m:
        token = m.group(1)
        label = f"team {token}".lower()
        for name in names:
            if name.lower() == label or name.lower().endswith(f" {token.lower()}"):
                return name
        if token.isdigit():
            return f"Team {token}"
        return f"Team {token.upper()}"

    m = re.search(
        r"(?:rate|review|grade|how (?:would|do) you rate)\s+(.+?)(?:'s|’s)\s+(?:picks|draft|roster|team)",
        q,
        flags=re.I,
    )
    if m:
        owner = m.group(1).strip()
        for name in names:
            if owner.lower() in name.lower():
                return name
        return owner

    for name in names:
        if name.lower() in low and any(w in low for w in ("picks", "draft", "roster", "team")):
            return name

    return ""


def team_names_in_draft_order(board: Any) -> list[str]:
    """Return fantasy team names in round-1 pick order (Team 1 = pick 1, etc.)."""
    import pandas as pd

    if board is None or not hasattr(board, "empty") or board.empty or "Team" not in board.columns:
        return []
    df = board
    if "Round" in df.columns and "Pick" in df.columns:
        try:
            r1 = df[pd.to_numeric(df["Round"], errors="coerce") == 1].sort_values("Pick", kind="stable")
        except Exception:
            r1 = df.iloc[0:0]
        order: list[str] = []
        seen: set[str] = set()
        for raw in r1["Team"].dropna().astype(str):
            name = raw.strip()
            if name and name not in seen:
                order.append(name)
                seen.add(name)
        if order:
            return order
    return sorted(df["Team"].dropna().astype(str).unique().tolist())


def resolve_board_team_name(
    team_names: list[str],
    target: str,
    *,
    draft_order: list[str] | None = None,
) -> str:
    """Map a user label like Team 2 to the canonical board team column value."""
    target = str(target or "").strip()
    if not target:
        return ""
    names = [str(n).strip() for n in (team_names or []) if str(n).strip()]
    order = [str(n).strip() for n in (draft_order or []) if str(n).strip()] or names
    if not names and not order:
        return target

    for name in names:
        if name == target:
            return name
    tl = target.lower()
    for name in names:
        if name.lower() == tl:
            return name

    m = re.match(r"team\s*(\d+|[a-z])", tl, flags=re.I)
    if m:
        token = m.group(1).lower()
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(order):
                return order[idx]
        for name in names:
            compact = re.sub(r"\s+", "", name.lower())
            if compact == f"team{token}":
                return name
            if name.lower().endswith(f" {token}") or name.lower().endswith(token):
                return name

    for name in names:
        nl = name.lower()
        if tl in nl or nl in tl:
            return name
    return target


def roster_for_team_from_board(
    session_state: dict[str, Any],
    team_name: str,
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    """Return roster names, detail rows, and position index for a fantasy team on the board."""
    try:
        from draft_room_state import get_canonical_draft_board
    except ImportError:
        return [], [], {}

    board = get_canonical_draft_board(session_state)
    if board.empty or "Player" not in board.columns or "Team" not in board.columns:
        return [], [], {}

    team_names = sorted(board["Team"].dropna().astype(str).unique().tolist())
    draft_order = team_names_in_draft_order(board)
    team = resolve_board_team_name(
        team_names,
        str(team_name or "").strip(),
        draft_order=draft_order,
    )
    if not team:
        return [], [], {}

    rows = board[board["Team"].astype(str).str.strip() == team]
    if rows.empty:
        rows = board[board["Team"].astype(str).str.strip().str.lower() == team.lower()]
    names = [
        str(p).strip()
        for p in rows["Player"].dropna().astype(str).tolist()
        if str(p).strip()
    ]
    detail, index = _roster_position_detail_for_names(session_state, names)
    board_pos = _board_player_position_lookup(session_state)
    if board_pos:
        enriched_detail: list[dict[str, str]] = []
        enriched_index: dict[str, str] = dict(index)
        seen: set[str] = set()
        for entry in detail:
            clean = str(entry.get("player") or "").strip()
            if not clean:
                continue
            pos = str(entry.get("Primary Position") or "").strip() or board_pos.get(clean.lower(), "")
            enriched_detail.append({"player": clean, "Primary Position": pos})
            if pos:
                enriched_index[clean.lower()] = pos
            seen.add(clean.lower())
        for name in names:
            token = name.lower()
            if token in seen:
                continue
            pos = board_pos.get(token, "")
            enriched_detail.append({"player": name, "Primary Position": pos})
            if pos:
                enriched_index[token] = pos
        detail, index = enriched_detail, enriched_index
    if names and not all(index.get(str(n).lower()) for n in names):
        for name in names:
            token = str(name).lower()
            if index.get(token):
                continue
            pos = _position_for_name_from_yearly_data(name)
            if pos:
                index[token] = pos
                for row in detail:
                    if str(row.get("player") or "").strip().lower() == token:
                        row["Primary Position"] = pos
                        break
                else:
                    detail.append({"player": name, "Primary Position": pos})
    return names, detail, index


def refresh_draft_ami_metadata_from_board(
    session_state: dict[str, Any],
    *,
    source_page: str = "",
) -> dict[str, Any]:
    """Refresh pick, round, and roster positions from canonical board (matches UI summary)."""
    meta: dict[str, Any] = {"refreshed": False}
    low_page = str(source_page or "").lower()
    if "live draft" in low_page:
        return meta
    try:
        from draft_ami_cache_builder import extract_board_draft_context
        from draft_room_state import get_canonical_draft_board
    except ImportError:
        return meta

    board = get_canonical_draft_board(session_state)
    if board.empty or "Player" not in board.columns:
        return meta

    ctx = extract_board_draft_context(board, session_state)
    current_pick = int(ctx["current_pick"])
    draft_round = int(ctx.get("draft_round") or 1)
    my_roster = list(ctx.get("my_roster") or [])

    roster_detail, roster_index = _roster_position_detail_for_names(session_state, my_roster)
    if not roster_index and "Primary Position" in board.columns and ctx.get("assistant_team"):
        team = str(ctx["assistant_team"])
        for _, row in board[board["Team"].astype(str) == team].iterrows():
            name = str(row.get("Player") or "").strip()
            pos = str(row.get("Primary Position") or "").strip()
            if name:
                roster_detail.append({"player": name, "Primary Position": pos})
                if pos:
                    roster_index[name.lower()] = pos

    for block_key in ("_ami_draft_snapshot", "_ami_draft_projection"):
        block = session_state.get(block_key)
        if not isinstance(block, dict):
            continue
        block["current_pick"] = current_pick
        block["draft_round"] = draft_round

    meta.update(
        {
            "refreshed": True,
            "current_pick": current_pick,
            "draft_round": draft_round,
            "roster_position_count": len(roster_index),
        }
    )
    return meta


def draft_ami_cache_has_pool(session_state: dict[str, Any]) -> bool:
    """True only for a full position-representative pool — not a best_available slice (~6)."""

    def _is_warm_pool(block: dict[str, Any] | None) -> bool:
        count, source = _available_pool_count_and_source(block)
        if count < AMI_POOL_TOP_OVERALL:
            return False
        if source == AMI_POOL_SOURCE:
            return True
        return count >= 20

    proj = session_state.get("_ami_draft_projection")
    if isinstance(proj, dict) and _is_warm_pool(proj):
        return True
    snap = session_state.get("_ami_draft_snapshot")
    return isinstance(snap, dict) and _is_warm_pool(snap)


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

    try:
        from draft_ami_cache_builder import (
            apply_draft_assistant_cache_to_session,
            build_draft_assistant_ami_cache_from_board_state,
        )
    except ImportError as exc:
        trace["reason"] = f"draft_ami_cache_builder: {exc}"
        return _finalize_cache_build_trace(trace)

    built = build_draft_assistant_ami_cache_from_board_state(board, session_state)
    if not built.get("ok"):
        trace["reason"] = built.get("reason") or "build_failed"
        trace.update(built.get("trace") or {})
        return _finalize_cache_build_trace(trace)

    try:
        apply_meta = apply_draft_assistant_cache_to_session(
            session_state,
            built["cache_inputs"],
            page=page,
        )
    except Exception as exc:
        trace["reason"] = f"cache_write: {exc}"
        log.exception("build_draft_assistant_ami_cache_from_board cache write failed")
        return _finalize_cache_build_trace(trace)

    trace.update(built.get("trace") or {})
    trace.update(
        {
            "cache_action": "built_from_board",
            "available_players_count": apply_meta.get("available_players_count"),
            "player_pool_source": apply_meta.get("player_pool_source"),
            "current_pick": apply_meta.get("current_pick"),
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


def _index_row_position(row: Any) -> str:
    if isinstance(row, dict):
        for key in ("Primary Position", "position", "pos", "Position"):
            val = row.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        return ""
    for key in ("Primary Position", "position", "pos", "Position"):
        if hasattr(row, "get"):
            val = row.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return ""


def build_player_position_index_from_session(session_state: dict[str, Any]) -> dict[str, str]:
    """Name → position map for drafted and available players (AMI send + position counts)."""
    index: dict[str, str] = {}

    def _add(name: str, pos: str) -> None:
        clean = str(name or "").split(" (")[0].strip()
        pos_val = str(pos or "").strip()
        if clean and pos_val:
            index[clean.lower()] = pos_val

    lookup = session_state.get("_ami_undrafted_pool_lookup")
    if isinstance(lookup, dict):
        for key, row in lookup.items():
            if isinstance(row, dict):
                pos = _index_row_position(row)
                if pos:
                    _add(str(key), pos)

    global_lookup = session_state.get("_ami_player_position_lookup")
    if isinstance(global_lookup, dict):
        for name, pos in global_lookup.items():
            if name and pos:
                _add(str(name), str(pos))

    snap = session_state.get("_ami_draft_snapshot")
    if isinstance(snap, dict):
        roster_index = snap.get("roster_position_index")
        if isinstance(roster_index, dict):
            for name, pos in roster_index.items():
                if name and pos:
                    _add(str(name), str(pos))
        for row in snap.get("user_roster_detail") or []:
            if isinstance(row, dict):
                name = str(row.get("player") or row.get("Player") or "").strip()
                pos = _index_row_position(row)
                if name and pos:
                    _add(name, pos)
        for pool_key in (
            "draft_room_board",
            "available_players",
            "recommended_players",
            "best_available_players",
        ):
            for row in snap.get(pool_key) or []:
                if isinstance(row, dict):
                    name = str(row.get("player") or row.get("Player") or "").strip()
                    pos = _index_row_position(row)
                    if name and pos:
                        _add(name, pos)

    try:
        from draft_room_state import get_canonical_draft_board

        board = get_canonical_draft_board(session_state)
        if board is not None and hasattr(board, "iterrows") and "Player" in board.columns:
            pos_col = "Primary Position" if "Primary Position" in board.columns else None
            for _, row in board.iterrows():
                name = str(row.get("Player") or "").strip()
                pos = str(row.get(pos_col) or "").strip() if pos_col else ""
                if name and pos:
                    _add(name, pos)
    except Exception:
        pass

    return index
