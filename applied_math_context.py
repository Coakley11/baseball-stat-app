"""Page-specific Applied Math context extractors for Baseball."""

from __future__ import annotations

import copy
import logging
import re
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _player_name(raw: Any) -> str:
    return str(raw or "").split(" (")[0].strip()


_QUESTION_PLAYER_PATTERNS: tuple[str, ...] = (
    r"why is (.+?) the best",
    r"why is (.+?) a good",
    r"why is (.+?) worth",
    r"why (.+?)(?:\?|\s*$)",
    r"should i draft (.+?)(?:\?|\s|$)",
    r"is (.+?) (?:worth|available|the best)",
    r"how risky is (.+?)(?:\?|\s|$)",
)


def extract_player_from_question(question: str) -> str:
    """Pull a player name from a free-text AMI question (e.g. Jose Ramirez)."""
    q = str(question or "").strip()
    low = q.lower()
    for pat in _QUESTION_PLAYER_PATTERNS:
        m = re.search(pat, low, flags=re.I)
        if not m:
            continue
        name = q[m.start(1) : m.end(1)].strip().strip("?").strip()
        if len(name) >= 3 and name.lower() not in ("this player", "this pick", "he", "him", "this sleeper"):
            return name
    return ""


def _find_player_row_in_pools(name: str, *pools: Any) -> dict[str, Any] | None:
    target = _player_name(name).lower()
    if not target:
        return None
    for pool in pools:
        if not isinstance(pool, list):
            continue
        for item in pool:
            if isinstance(item, dict):
                row_name = _player_name(item.get("player") or item.get("Player") or item.get("fullName"))
                if row_name.lower() == target:
                    return item
            elif item and _player_name(item).lower() == target:
                return {"player": _player_name(item)}
    return None


def extract_comparison_players_from_question(question: str) -> tuple[str, str]:
    """Extract two players from X vs Y / X or Y draft compare questions."""
    try:
        from components.draft_market_question import extract_draft_compare_players

        return extract_draft_compare_players(question)
    except ImportError:
        pass
    q = str(question or "").strip()
    m = re.search(r"(.+?)\s+(?:vs\.?|versus|or)\s+(.+?)(?:\?|\s*$)", q, flags=re.I)
    if not m:
        return "", ""
    a = q[m.start(1) : m.end(1)].strip().strip("?,").strip()
    b = q[m.start(2) : m.end(2)].strip().strip("?,").strip()
    if len(a) >= 3 and len(b) >= 3:
        return a, b
    return "", ""


def attach_question_player_to_context(
    ctx: dict[str, Any],
    question: str,
    session_state: dict[str, Any],
) -> None:
    """At AMI send: bind question-named player(s) to context."""
    comp_a, comp_b = extract_comparison_players_from_question(question)
    if comp_a and comp_b:
        ctx["player_a"] = comp_a
        ctx["player_b"] = comp_b
        ctx["players"] = [comp_a, comp_b]
        snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
        for label, name in (("player_a_row", comp_a), ("player_b_row", comp_b)):
            row = _find_player_row_in_pools(
                name,
                snap.get("recommended_players"),
                snap.get("available_players"),
                snap.get("best_available_players"),
                ctx.get("available_players"),
                ctx.get("recommended_players"),
                ctx.get("best_available"),
                snap.get("draft_room_board"),
            )
            if row:
                ctx[label] = row
        return

    name = extract_player_from_question(question)
    if not name:
        return
    ctx["question_player"] = name
    ctx["player"] = name
    existing = ctx.get("players") if isinstance(ctx.get("players"), list) else []
    ctx["players"] = [name] + [p for p in existing if _player_name(p).lower() != name.lower()][:3]
    try:
        from baseball_ami_frame import player_draft_status

        ds = player_draft_status(session_state, name)
        if isinstance(ds, dict) and ds.get("player"):
            ctx["draft_status"] = ds
    except Exception:
        pass
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    proj = ctx.get("draft_projection") if isinstance(ctx.get("draft_projection"), dict) else {}
    row = _find_player_row_in_pools(
        name,
        snap.get("recommended_players"),
        snap.get("available_players"),
        snap.get("best_available_players"),
        proj.get("top_recommendations"),
        proj.get("available_players"),
        proj.get("best_available"),
        ctx.get("available_players"),
        ctx.get("recommended_players"),
        ctx.get("best_available"),
    )
    if row:
        ctx["question_player_row"] = row


def augment_ami_available_pool_at_send(
    ctx: dict[str, Any],
    question: str,
    session_state: dict[str, Any],
) -> None:
    """Merge send-time question positions/players into available_players."""
    lookup = session_state.get("_ami_undrafted_pool_lookup")
    if not isinstance(lookup, dict) or not lookup:
        return
    try:
        from draft_ami_helpers import augment_available_pool_for_question, detect_positions_from_question
    except ImportError:
        return

    comp_a, comp_b = extract_comparison_players_from_question(question)
    players = [n for n in (comp_a, comp_b, extract_player_from_question(question)) if _player_name(n)]
    augment_available_pool_for_question(
        ctx,
        lookup=lookup,
        requested_positions=detect_positions_from_question(question),
        question_players=players,
    )
    row = _find_player_row_in_pools(
        extract_player_from_question(question) or ctx.get("question_player") or "",
        ctx.get("available_players"),
        ctx.get("draft_snapshot", {}).get("available_players") if isinstance(ctx.get("draft_snapshot"), dict) else None,
    )
    if row and not ctx.get("question_player_row"):
        ctx["question_player_row"] = row


def build_draft_send_pipeline_diagnostics(
    ctx: dict[str, Any],
    session_state: dict[str, Any],
) -> dict[str, Any]:
    """Trace counts at Draft Assistant send time (pre-blob)."""
    snap = ctx.get("draft_snapshot") if isinstance(ctx.get("draft_snapshot"), dict) else {}
    proj = ctx.get("draft_projection") if isinstance(ctx.get("draft_projection"), dict) else {}
    cached_proj = session_state.get("_ami_draft_projection")
    cached_snap = session_state.get("_ami_draft_snapshot")
    pool_diag = ctx.get("player_pool_diagnostics") if isinstance(ctx.get("player_pool_diagnostics"), dict) else {}

    def _count(val: Any) -> int:
        return len(val) if isinstance(val, list) else 0

    return {
        "session_has_draft_projection": isinstance(cached_proj, dict),
        "session_has_draft_snapshot": isinstance(cached_snap, dict),
        "session_projection_available_count": _count(
            cached_proj.get("available_players") if isinstance(cached_proj, dict) else None
        ),
        "session_snapshot_available_count": _count(
            cached_snap.get("available_players") if isinstance(cached_snap, dict) else None
        ),
        "ctx_available_players_count": _count(ctx.get("available_players")),
        "ctx_draft_snapshot_available_count": _count(snap.get("available_players")),
        "ctx_draft_projection_available_count": _count(proj.get("available_players")),
        "ctx_best_available_count": _count(ctx.get("best_available")),
        "player_pool_source": pool_diag.get("player_pool_source"),
        "current_pick": ctx.get("current_pick") or snap.get("current_pick"),
        "draft_round": ctx.get("draft_round") or snap.get("draft_round"),
        "session_has_draft_board": session_state.get("session_has_draft_board"),
        "session_pick_count": session_state.get("session_pick_count"),
        "draft_board_source_key": session_state.get("draft_board_source_key"),
        "cache_build_action": (session_state.get("_ami_draft_cache_build_trace") or {}).get("cache_action"),
        "skip_reason": (session_state.get("_ami_draft_cache_build_trace") or {}).get("skip_reason"),
    }


def ensure_draft_assistant_ami_cache_at_send(
    session_state: dict[str, Any],
    *,
    source_page: str = "Draft Assistant Simulator",
) -> dict[str, Any]:
    """Build AMI draft cache from board when page body has not populated session cache."""
    try:
        from draft_ami_helpers import (
            _finalize_cache_build_trace,
            _session_board_pick_count,
            build_draft_assistant_ami_cache_from_board,
            draft_ami_cache_has_pool,
        )
    except ImportError as exc:
        trace = {"cache_action": "import_failed", "reason": str(exc), "skip_reason": str(exc)}
        session_state["_ami_draft_cache_build_trace"] = trace
        return trace

    low_page = str(source_page or "").lower()
    if "draft" not in low_page:
        trace = _finalize_cache_build_trace({"cache_action": "skipped", "reason": "not_draft_page"})
        session_state["_ami_draft_cache_build_trace"] = trace
        return trace

    if draft_ami_cache_has_pool(session_state):
        trace = _finalize_cache_build_trace({"cache_action": "already_present"})
        session_state["_ami_draft_cache_build_trace"] = trace
        return trace

    board_picks = _session_board_pick_count(session_state)
    if board_picks <= 0 and not session_state.get("session_has_draft_board"):
        trace = _finalize_cache_build_trace({"cache_action": "skipped", "reason": "no_board_picks"})
        session_state["_ami_draft_cache_build_trace"] = trace
        return trace

    page = "Draft Assistant Simulator" if "draft" in low_page else str(source_page or "")
    trace = _finalize_cache_build_trace(
        build_draft_assistant_ami_cache_from_board(session_state, page=page)
    )
    session_state["_ami_draft_cache_build_trace"] = trace
    if trace.get("cache_action") == "built_from_board":
        log.info("AMI draft cache built on demand: %s", trace)
    elif trace.get("skip_reason") not in (None, "none"):
        log.warning("AMI draft cache on-demand build skipped: %s", trace)
    return trace


def finalize_draft_context_for_send(ctx: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
    """Promote cached Draft Assistant pool/pick into send payload (sidebar runs before page cache)."""
    cached_snap = session_state.get("_ami_draft_snapshot")
    cached_proj = session_state.get("_ami_draft_projection")
    snap = dict(ctx.get("draft_snapshot")) if isinstance(ctx.get("draft_snapshot"), dict) else {}
    proj = dict(cached_proj) if isinstance(cached_proj, dict) else {}

    if isinstance(cached_snap, dict):
        for key in (
            "available_players",
            "best_available_players",
            "recommended_players",
            "current_pick",
            "draft_round",
            "needed_positions",
            "category_needs",
            "player_pool_diagnostics",
            "user_roster",
            "drafted_players",
            "my_next_pick",
        ):
            val = cached_snap.get(key)
            if val is not None and val != "" and val != [] and not snap.get(key):
                snap[key] = copy.deepcopy(val) if isinstance(val, (list, dict)) else val

    def _pool_len(val: Any) -> int:
        return len(val) if isinstance(val, list) else 0

    if proj:
        ctx["draft_projection"] = {
            **proj,
            **(ctx.get("draft_projection") if isinstance(ctx.get("draft_projection"), dict) else {}),
        }
        proj_avail = proj.get("available_players")
        ctx_avail_len = _pool_len(ctx.get("available_players"))
        proj_avail_len = _pool_len(proj_avail)
        if isinstance(proj_avail, list) and proj_avail_len >= ctx_avail_len and proj_avail_len > 0:
            ctx["available_players"] = copy.deepcopy(proj_avail)
        snap_avail_len = _pool_len(snap.get("available_players"))
        if isinstance(proj_avail, list) and proj_avail_len >= snap_avail_len and proj_avail_len > 0:
            snap["available_players"] = copy.deepcopy(proj_avail)
        if proj.get("best_available") and not ctx.get("best_available"):
            ctx["best_available"] = proj["best_available"]
        if proj.get("top_recommendations") and not ctx.get("recommended_players"):
            ctx["recommended_players"] = proj["top_recommendations"]
        if proj.get("player_pool_diagnostics"):
            merged_diag = dict(proj["player_pool_diagnostics"])
            merged_diag.update(ctx.get("player_pool_diagnostics") or {})
            ctx["player_pool_diagnostics"] = merged_diag
        pick = proj.get("current_pick")
        if pick is not None:
            ctx["current_pick"] = int(pick)
            snap["current_pick"] = int(pick)
        rnd = proj.get("draft_round")
        if rnd is not None:
            ctx["draft_round"] = int(rnd)
            snap["draft_round"] = int(rnd)

    if snap:
        ctx["draft_snapshot"] = snap
        if snap.get("best_available_players") and not ctx.get("best_available"):
            ctx["best_available"] = snap["best_available_players"]
        if snap.get("recommended_players") and not ctx.get("recommended_players"):
            ctx["recommended_players"] = snap["recommended_players"]
        if snap.get("current_pick") is not None and int(snap.get("current_pick") or 0) > 0:
            ctx["current_pick"] = int(snap["current_pick"])
        if snap.get("draft_round") is not None:
            ctx["draft_round"] = snap["draft_round"]

    diag = build_draft_send_pipeline_diagnostics(ctx, session_state)
    ctx["send_pipeline_diagnostics"] = diag
    if isinstance(ctx.get("available_players"), list) and ctx["available_players"]:
        pool_diag = dict(ctx.get("player_pool_diagnostics") or {})
        pool_diag["available_players_count"] = len(ctx["available_players"])
        ctx["player_pool_diagnostics"] = pool_diag
    return diag


def _copy_widget_value(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, (list, tuple)):
        return [_copy_widget_value(x) for x in val]
    if isinstance(val, dict):
        return {str(k): _copy_widget_value(v) for k, v in val.items()}
    try:
        import json

        json.dumps(val)
        return val
    except (TypeError, ValueError):
        return str(val)


def _snapshot_page_widgets(page: str, session_state: dict[str, Any]) -> dict[str, Any]:
    """Copy restore-able widget keys for a page from session state."""
    try:
        from page_state import PAGE_STATE_REGISTRY

        reg = PAGE_STATE_REGISTRY.get(str(page or "").strip(), {})
    except Exception:
        reg = {}
    out: dict[str, Any] = {}
    for key in reg.get("exact", []):
        if key in session_state and session_state[key] is not None and session_state[key] != "":
            out[key] = _copy_widget_value(session_state[key])
    for prefix in reg.get("prefixes", []):
        for key, val in session_state.items():
            if str(key).startswith(prefix) and val is not None and val != "":
                if key not in out:
                    out[key] = _copy_widget_value(val)
    return out


def build_source_state(page: str, session_state: dict[str, Any]) -> dict[str, Any]:
    """
    Serializable snapshot for Return Insight page restore (separate from solver context).
    """
    p = str(page or "").strip()
    widget_params = _snapshot_page_widgets(p, session_state)
    entity_params: dict[str, Any] = {"page": p}
    filter_params: dict[str, Any] = {}
    chart_params: dict[str, Any] = {}

    if p == "Comparison Tool":
        pa = session_state.get("sig_player_a_clean")
        pb = session_state.get("sig_player_b_clean")
        cp = session_state.get("compare_players") or session_state.get("compare_players_saved")
        if pa:
            entity_params["player_a_label"] = str(pa)
            widget_params.setdefault("sig_player_a_clean", str(pa))
        if pb:
            entity_params["player_b_label"] = str(pb)
            widget_params.setdefault("sig_player_b_clean", str(pb))
        if isinstance(cp, list) and cp:
            entity_params["compare_players"] = [_copy_widget_value(x) for x in cp[:3]]
            widget_params.setdefault("compare_players", entity_params["compare_players"])
        for fk in (
            "compare_stat",
            "compare_x_axis_mode",
            "compare_year_range",
            "compare_age_range",
            "compare_trend_mode",
            "compare_smooth_window",
        ):
            if fk in session_state and session_state[fk] is not None:
                filter_params[fk] = _copy_widget_value(session_state[fk])
        chart_params["chart_snapshot"] = {
            "page": p,
            "player_a": entity_params.get("player_a_label"),
            "player_b": entity_params.get("player_b_label"),
            "compare_players": entity_params.get("compare_players") or [],
            "stat": filter_params.get("compare_stat") or session_state.get("compare_stat"),
            "x_axis_mode": filter_params.get("compare_x_axis_mode") or session_state.get("compare_x_axis_mode"),
            "year_range": filter_params.get("compare_year_range") or session_state.get("compare_year_range"),
            "trend_mode": filter_params.get("compare_trend_mode") or session_state.get("compare_trend_mode"),
        }

    elif p == "Trend Value":
        ts = session_state.get("trend_state")
        multi = None
        pl = None
        if isinstance(ts, dict):
            if isinstance(ts.get("players_multi"), list):
                multi = ts["players_multi"]
            if ts.get("chart_player"):
                pl = ts.get("chart_player")
        if multi is None:
            multi = session_state.get("trend_players_multi") or session_state.get("trend_force_multi_labels")
        if pl is None:
            pl = session_state.get("single_trend_dashboard_player")
        if isinstance(multi, list) and multi:
            labels = [_copy_widget_value(x) for x in multi[:6]]
            entity_params["trend_players_multi"] = labels
            chart_params["trend_players_multi"] = labels
        if pl:
            entity_params["player_label"] = str(pl)
            widget_params.setdefault("single_trend_dashboard_player", str(pl))
        stats = session_state.get("single_trend_dashboard_stats")
        if stats:
            chart_params["stats"] = [_copy_widget_value(s) for s in stats[:6]]
        for fk in (
            "trend_lag",
            "trend_plot_stat",
            "trend_chart_mode",
            "trend_smooth_window",
            "trend_min_g",
            "trend_position_filter",
        ):
            if fk in session_state and session_state[fk] is not None:
                filter_params[fk] = _copy_widget_value(session_state[fk])
        chart_params["chart_snapshot"] = {
            "page": p,
            "players": entity_params.get("trend_players_multi")
            or ([str(pl)] if pl else []),
            "anchor_player": str(pl) if pl else "",
            "metric": session_state.get("trend_plot_stat"),
            "stats": chart_params.get("stats") or [],
            "window_seasons": session_state.get("trend_lag"),
            "chart_mode": session_state.get("trend_chart_mode"),
            "smooth_window": session_state.get("trend_smooth_window"),
            "trend_summary": session_state.get("_ami_trend_summary"),
        }

    elif p == "Historical Explorer":
        snap = session_state.get("_ami_historical_snapshot")
        if isinstance(snap, dict):
            chart_params["historical_snapshot"] = _copy_widget_value(snap)
        try:
            from historical_state import canonical_historical_filters, gather_historical_filters, is_historical_state_key

            canonical = canonical_historical_filters(session_state) or gather_historical_filters(session_state)
            for fk, val in canonical.items():
                if is_historical_state_key(fk):
                    filter_params[fk] = _copy_widget_value(val)
            for fk, val in session_state.items():
                if is_historical_state_key(str(fk)) and str(fk) not in filter_params and val is not None:
                    filter_params[str(fk)] = _copy_widget_value(val)
        except ImportError:
            for fk in (
                "historical_year_range_filter",
                "historical_sort_stat_filter",
                "historical_sort_order_filter",
                "historical_batting_hand_filter",
                "historical_position_filter",
                "historical_team_filter",
            ):
                if fk in session_state and session_state[fk] is not None:
                    filter_params[fk] = _copy_widget_value(session_state[fk])

    elif p == "Career Totals":
        try:
            from career_totals_state import canonical_career_filters, gather_career_filters, is_career_state_key

            canonical = canonical_career_filters(session_state) or gather_career_filters(session_state)
            for fk, val in canonical.items():
                if is_career_state_key(fk):
                    filter_params[fk] = _copy_widget_value(val)
            for fk, val in session_state.items():
                if is_career_state_key(str(fk)) and fk not in filter_params and val is not None:
                    filter_params[str(fk)] = _copy_widget_value(val)
        except ImportError:
            for fk in (
                "career_year_range_filter",
                "career_sort_stat_filter",
                "career_batting_hand_filter",
                "career_position_filter_mode",
                "career_position_filter",
                "career_team_filter",
                "career_by_team_toggle_filter",
            ):
                if fk in session_state and session_state[fk] is not None:
                    filter_params[fk] = _copy_widget_value(session_state[fk])
            for fk, val in session_state.items():
                if str(fk).startswith("career_") and str(fk).endswith("_min"):
                    filter_params[str(fk)] = _copy_widget_value(val)

    elif p == "Valuation":
        try:
            from valuation_state import canonical_valuation_state, gather_valuation_state, is_valuation_state_key

            canonical = canonical_valuation_state(session_state) or gather_valuation_state(session_state)
            for fk, val in canonical.items():
                if is_valuation_state_key(fk):
                    filter_params[fk] = _copy_widget_value(val)
            sp = (session_state.get("valuation_state") or {}).get("selected_player")
            if sp:
                entity_params["valuation_selected_player"] = str(sp)
            for fk, val in session_state.items():
                if is_valuation_state_key(str(fk)) and str(fk) not in filter_params and val is not None:
                    filter_params[str(fk)] = _copy_widget_value(val)
        except ImportError:
            pass

    elif p == "ML Predictions":
        try:
            from projections_state import canonical_projections_state, gather_projections_state, is_projections_state_key

            canonical = canonical_projections_state(session_state) or gather_projections_state(session_state)
            for fk, val in canonical.items():
                if is_projections_state_key(fk):
                    filter_params[fk] = _copy_widget_value(val)
            for fk, val in session_state.items():
                if is_projections_state_key(str(fk)) and str(fk) not in filter_params and val is not None:
                    filter_params[str(fk)] = _copy_widget_value(val)
        except ImportError:
            pass

    elif p == "Leaderboards":
        try:
            from leaderboards_state import canonical_leaderboards_filters, gather_leaderboards_filters, is_leaderboards_state_key

            canonical = canonical_leaderboards_filters(session_state) or gather_leaderboards_filters(session_state)
            for fk, val in canonical.items():
                if is_leaderboards_state_key(fk):
                    filter_params[fk] = _copy_widget_value(val)
            for fk, val in session_state.items():
                if is_leaderboards_state_key(str(fk)) and str(fk) not in filter_params and val is not None:
                    filter_params[str(fk)] = _copy_widget_value(val)
        except ImportError:
            pass

    elif p in ("Fantasy Sleepers & Busts", "Fantasy Standings Tracker", "Fantasy Lineup Assistant"):
        try:
            from fantasy_state import gather_fantasy_section, is_fantasy_state_key, section_for_page

            section = section_for_page(p)
            if section:
                canonical = gather_fantasy_section(session_state, section)
                for fk, val in canonical.items():
                    if is_fantasy_state_key(fk):
                        filter_params[fk] = _copy_widget_value(val)
                for fk, val in session_state.items():
                    if is_fantasy_state_key(str(fk)) and str(fk) not in filter_params and val is not None:
                        filter_params[str(fk)] = _copy_widget_value(val)
        except ImportError:
            pass
        if p == "Fantasy Sleepers & Busts":
            sleepers_snap = gather_sleepers_ami_snapshot(session_state)
            if sleepers_snap:
                entity_params["sleepers_snapshot"] = sleepers_snap

    elif "draft" in p.lower():
        try:
            from draft_state import (
                build_draft_ami_trace,
                canonical_draft_workflow,
                gather_draft_ami_snapshot,
                gather_draft_workflow,
            )

            dw = canonical_draft_workflow(session_state) or gather_draft_workflow(session_state)
            if isinstance(dw, dict):
                q = dw.get("queue") if isinstance(dw.get("queue"), list) else session_state.get("draft_queue")
                if isinstance(q, list) and q:
                    entity_params["draft_queue"] = [_copy_widget_value(x) for x in q[:6]]
                focus = dw.get("watchlist_focus")
                favorites = dw.get("watchlist_favorites")
                if isinstance(focus, list) and focus:
                    entity_params["watchlist_focus"] = [_copy_widget_value(x) for x in focus[:20]]
                if isinstance(favorites, list) and favorites:
                    entity_params["watchlist_favorites"] = [_copy_widget_value(x) for x in favorites[:20]]
            draft_snapshot = gather_draft_ami_snapshot(p, session_state)
            if draft_snapshot:
                entity_params["draft_snapshot"] = draft_snapshot
                filt = dict(filter_params)
                if isinstance(draft_snapshot.get("scoring_settings"), dict):
                    filt.update(draft_snapshot["scoring_settings"])
                filter_params = filt
        except ImportError:
            dq = session_state.get("draft_queue")
            if isinstance(dq, list) and dq:
                entity_params["draft_queue"] = [_copy_widget_value(x) for x in dq[:6]]

    result = {
        "source_app": "baseball",
        "source_page": p,
        "page_params": {"page": p},
        "entity_params": entity_params,
        "widget_params": widget_params,
        "filter_params": filter_params,
        "chart_params": chart_params,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if "draft" in p.lower():
        try:
            from draft_state import build_draft_ami_trace

            result["ami_trace"] = build_draft_ami_trace(result)
        except ImportError:
            pass
    return result


def apply_source_state_to_session(
    session_state: dict[str, Any],
    source_state: dict[str, Any],
    *,
    schedule_navigation: bool = True,
) -> None:
    """Map stored source_state into baseball pending-restore session keys."""
    if not source_state:
        return
    wp = dict(source_state.get("widget_params") or {})
    ent = dict(source_state.get("entity_params") or {})
    filt = dict(source_state.get("filter_params") or {})
    chart = dict(source_state.get("chart_params") or {})

    page = str(source_state.get("source_page") or source_state.get("page_params", {}).get("page") or "").strip()
    if page and schedule_navigation:
        session_state["_navigate_to_page"] = page
        session_state["_skip_page_restore_for"] = page
        session_state["_ami_return_restore_page"] = page
    elif page:
        session_state.pop("_navigate_to_page", None)
        try:
            from page_state import _collect_keys_for_page

            for key in _collect_keys_for_page(session_state, page):
                session_state.pop(key, None)
        except Exception:
            pass

    snap = chart.get("historical_snapshot")
    if isinstance(snap, dict):
        session_state["_ami_historical_snapshot"] = copy.deepcopy(snap)

    if page == "Trend Value":
        try:
            from trend_state import apply_trend_source_state_from_ami

            apply_trend_source_state_from_ami(session_state, source_state)
        except ImportError:
            multi = chart.get("trend_players_multi") or ent.get("trend_players_multi")
            if isinstance(multi, list):
                session_state["trend_players_multi"] = copy.deepcopy(multi[:6])
            tp = ent.get("player_label") or wp.get("single_trend_dashboard_player")
            if tp:
                session_state["single_trend_dashboard_player"] = str(tp)
        return

    if page == "Comparison Tool":
        try:
            from comparison_state import apply_comparison_source_state_from_ami

            apply_comparison_source_state_from_ami(session_state, source_state)
        except ImportError:
            cp = ent.get("compare_players") or wp.get("compare_players")
            if isinstance(cp, list) and cp:
                session_state["pending_compare_players"] = copy.deepcopy(cp[:3])
            pa = ent.get("player_a_label") or wp.get("sig_player_a_clean")
            pb = ent.get("player_b_label") or wp.get("sig_player_b_clean")
            if pa:
                session_state["pending_sig_player_a"] = str(pa)
            if pb:
                session_state["pending_sig_player_b"] = str(pb)
            for key, val in {**wp, **filt}.items():
                if val is not None and val != "":
                    session_state[key] = copy.deepcopy(val)
        return

    if page == "Historical Explorer":
        try:
            from historical_state import apply_historical_source_state_from_ami

            apply_historical_source_state_from_ami(session_state, source_state)
        except ImportError:
            for key, val in {**wp, **filt}.items():
                if val is not None and val != "":
                    session_state[key] = copy.deepcopy(val)
            snap = chart.get("historical_snapshot")
            if isinstance(snap, dict):
                session_state["_ami_historical_snapshot"] = copy.deepcopy(snap)
        return

    if page == "Career Totals":
        try:
            from career_totals_state import apply_career_source_state_from_ami

            apply_career_source_state_from_ami(session_state, source_state)
        except ImportError:
            for key, val in {**wp, **filt}.items():
                if val is not None and val != "":
                    session_state[key] = copy.deepcopy(val)
        return

    if page == "Valuation":
        try:
            from valuation_state import apply_valuation_source_state_from_ami

            apply_valuation_source_state_from_ami(session_state, source_state)
        except ImportError:
            for key, val in {**wp, **filt}.items():
                if val is not None and val != "":
                    session_state[key] = copy.deepcopy(val)
        return

    if page == "ML Predictions":
        try:
            from projections_state import apply_projections_source_state_from_ami

            apply_projections_source_state_from_ami(session_state, source_state)
        except ImportError:
            for key, val in {**wp, **filt}.items():
                if val is not None and val != "":
                    session_state[key] = copy.deepcopy(val)
        return

    if page == "Leaderboards":
        try:
            from leaderboards_state import apply_leaderboards_source_state_from_ami

            apply_leaderboards_source_state_from_ami(session_state, source_state)
        except ImportError:
            for key, val in {**wp, **filt}.items():
                if val is not None and val != "":
                    session_state[key] = copy.deepcopy(val)
        return

    if page in ("Fantasy Sleepers & Busts", "Fantasy Standings Tracker", "Fantasy Lineup Assistant"):
        try:
            from fantasy_state import apply_fantasy_source_state_from_ami

            apply_fantasy_source_state_from_ami(session_state, source_state)
        except ImportError:
            for key, val in {**wp, **filt}.items():
                if val is not None and val != "":
                    session_state[key] = copy.deepcopy(val)
        return

    if page and "draft" in page.lower():
        try:
            from draft_state import apply_draft_source_state_from_ami

            apply_draft_source_state_from_ami(session_state, source_state)
        except ImportError:
            dq = ent.get("draft_queue") or wp.get("draft_queue")
            if isinstance(dq, list):
                session_state["draft_queue"] = copy.deepcopy(dq[:6])
            focus = ent.get("watchlist_focus") or wp.get("draft_assistant_focus_players")
            favorites = ent.get("watchlist_favorites") or wp.get("workflow_favorite_targets")
            if isinstance(focus, list):
                session_state["draft_assistant_focus_players"] = copy.deepcopy(focus[:20])
            if isinstance(favorites, list):
                session_state["workflow_favorite_targets"] = copy.deepcopy(favorites[:20])
        for key, val in {**wp, **filt}.items():
            if val is not None and val != "":
                session_state[key] = copy.deepcopy(val)
        return

    for key in (
        "compare_players",
        "compare_players_saved",
        "sig_player_a_clean",
        "sig_player_b_clean",
    ):
        session_state.pop(key, None)

    for key, val in {**wp, **filt}.items():
        if val is not None and val != "":
            session_state[key] = copy.deepcopy(val)
            if key in (
                "compare_stat",
                "compare_x_axis_mode",
                "compare_year_range",
                "compare_age_range",
                "compare_trend_mode",
                "compare_smooth_window",
            ):
                session_state[f"{key}_saved"] = copy.deepcopy(val)

    cp = ent.get("compare_players") or wp.get("compare_players")
    if isinstance(cp, list) and cp:
        session_state["pending_compare_players"] = copy.deepcopy(cp[:3])
    pa = ent.get("player_a_label") or wp.get("sig_player_a_clean")
    pb = ent.get("player_b_label") or wp.get("sig_player_b_clean")
    if pa:
        session_state["pending_sig_player_a"] = str(pa)
    if pb:
        session_state["pending_sig_player_b"] = str(pb)

def cache_page_context(session_state: dict[str, Any], page: str, ctx: dict[str, Any]) -> None:
    if not page or not ctx:
        return
    store = session_state.setdefault("_ami_context_by_page", {})
    if not isinstance(store, dict):
        store = {}
    store[str(page)] = dict(ctx)
    session_state["_ami_context_by_page"] = store


def get_cached_page_context(session_state: dict[str, Any], page: str) -> dict[str, Any]:
    store = session_state.get("_ami_context_by_page")
    if not isinstance(store, dict):
        return {}
    block = store.get(str(page))
    return dict(block) if isinstance(block, dict) else {}


def cache_draft_assistant_ami_context(
    session_state: dict[str, Any],
    *,
    page: str,
    recs_df: Any,
    current_pick: int,
    my_roster: list[str],
    drafted_total: int,
    draft_format: str,
    assistant_team: str,
    needed_positions: list[str] | None = None,
    category_needs: list[str] | None = None,
    drafted_players: list[str] | None = None,
    best_available_df: Any = None,
    available_df: Any = None,
    position_scarcity: Any = None,
) -> None:
    """Cache top recommendation + canonical draft snapshot for AMI send."""
    try:
        from draft_ami_helpers import (
            build_position_representative_available_pool,
            compact_recommendation_rows,
            draft_ami_guidance,
        )
        from draft_state import gather_draft_ami_snapshot
    except Exception as exc:
        log.exception("cache_draft_assistant_ami_context imports failed: %s", exc)
        return

    draft_proj: dict[str, Any] = {
        "current_pick": int(current_pick),
        "my_roster_size": len(my_roster),
        "drafted_total": int(drafted_total),
        "draft_format": str(draft_format),
        "assistant_team": str(assistant_team),
        "my_roster": list(my_roster)[:16],
    }
    if needed_positions:
        draft_proj["needed_positions"] = list(needed_positions)[:8]
    if category_needs:
        draft_proj["category_needs"] = list(category_needs)[:8]
    if drafted_players:
        draft_proj["drafted_players"] = list(drafted_players)[:48]
    if position_scarcity is not None:
        try:
            draft_proj["position_scarcity"] = float(position_scarcity)
        except (TypeError, ValueError):
            draft_proj["position_scarcity"] = position_scarcity

    top_rows = compact_recommendation_rows(recs_df, limit=6)
    if top_rows:
        draft_proj["top_pick"] = top_rows[0]["player"]
        draft_proj["top_recommendations"] = top_rows

    best_rows = compact_recommendation_rows(best_available_df, limit=6)
    if best_rows:
        draft_proj["best_available"] = best_rows
    avail_src = available_df if available_df is not None else best_available_df
    avail_rows, pool_diag, pool_lookup = build_position_representative_available_pool(
        avail_src,
        needed_positions=needed_positions,
        drafted_players=drafted_players,
    )
    if avail_rows:
        draft_proj["available_players"] = avail_rows
    if pool_diag:
        draft_proj["player_pool_diagnostics"] = pool_diag
    if pool_lookup:
        session_state["_ami_undrafted_pool_lookup"] = pool_lookup

    team_count = int(session_state.get("room_team_count") or session_state.get("draft_teams") or 10)
    draft_round = max(1, (int(current_pick) - 1) // max(team_count, 1) + 1)
    draft_proj["draft_round"] = draft_round

    session_state["_ami_draft_projection"] = draft_proj
    snap = gather_draft_ami_snapshot(page, session_state)
    if top_rows:
        snap["assistant_top_pick"] = top_rows[0]
        snap["recommended_players"] = top_rows
    if best_rows:
        snap["best_available_players"] = best_rows
    if avail_rows:
        snap["available_players"] = avail_rows
    if pool_diag:
        snap["player_pool_diagnostics"] = pool_diag
    snap["current_pick"] = int(current_pick)
    snap["draft_round"] = draft_round
    if needed_positions:
        snap["needed_positions"] = list(needed_positions)[:8]
    if category_needs:
        snap["category_needs"] = list(category_needs)[:8]
    if drafted_players:
        snap["drafted_players"] = list(drafted_players)[:48]
    if my_roster:
        snap["user_roster"] = list(my_roster)[:16]
    session_state["_ami_draft_snapshot"] = snap
    cache_page_context(
        session_state,
        page,
        {
            "draft_projection": draft_proj,
            "draft_snapshot": snap,
            "current_pick": int(current_pick),
            "draft_round": snap.get("draft_round"),
            "roster": list(my_roster)[:12],
            "draft_format": str(draft_format),
            "ami_guidance": draft_ami_guidance(page),
            "player_pool_diagnostics": pool_diag,
        },
    )


def cache_live_draft_ami_context(
    session_state: dict[str, Any],
    *,
    page: str = "Live Draft Room",
    room: dict[str, Any] | None = None,
    top_rec_df: Any = None,
    best_avail_df: Any = None,
    pos_fit_df: Any = None,
    value_sleep_df: Any = None,
) -> None:
    """Cache live draft recommendations and board state for AMI send."""
    try:
        from draft_ami_helpers import compact_recommendation_rows, draft_ami_guidance, gather_live_draft_ami_section
        from draft_state import gather_draft_ami_snapshot
    except Exception:
        return

    live_section = gather_live_draft_ami_section(session_state, room)
    if top_rec_df is not None:
        live_section["recommended_players"] = compact_recommendation_rows(top_rec_df, limit=8)
    if best_avail_df is not None:
        live_section["available_players"] = compact_recommendation_rows(best_avail_df, limit=8)
    if pos_fit_df is not None:
        live_section["positional_fits"] = compact_recommendation_rows(pos_fit_df, limit=8)
    if value_sleep_df is not None:
        live_section["sleepers"] = compact_recommendation_rows(value_sleep_df, limit=8)

    snap = gather_draft_ami_snapshot(page, session_state)
    for key, val in live_section.items():
        if val is not None and val != "" and val != []:
            snap[key] = val

    draft_proj = {
        "current_pick": snap.get("current_pick"),
        "draft_round": snap.get("draft_round"),
        "my_next_pick": snap.get("my_next_pick"),
        "on_clock_team": snap.get("on_clock_team"),
        "my_pick_now": bool(snap.get("my_pick_now")),
        "top_pick": (
            live_section.get("recommended_players", [{}])[0].get("player")
            if live_section.get("recommended_players")
            else None
        ),
        "top_recommendations": live_section.get("recommended_players") or [],
        "best_available": live_section.get("available_players") or [],
        "needed_positions": live_section.get("needed_positions") or [],
        "my_roster": snap.get("user_roster") or [],
    }
    session_state["_ami_draft_projection"] = draft_proj
    session_state["_ami_draft_snapshot"] = snap
    cache_page_context(
        session_state,
        page,
        {
            "draft_projection": draft_proj,
            "draft_snapshot": snap,
            "ami_guidance": draft_ami_guidance(page),
            "current_pick": snap.get("current_pick"),
            "draft_round": snap.get("draft_round"),
            "roster": snap.get("user_roster") or [],
        },
    )


def gather_sleepers_ami_snapshot(session_state: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe sleepers page context for AMI."""
    cached = session_state.get("_ami_sleepers_snapshot")
    if isinstance(cached, dict) and cached.get("sleeper_candidates"):
        return copy.deepcopy(cached)

    snap: dict[str, Any] = {
        "page": "Fantasy Sleepers & Busts",
        "fantasy_format": session_state.get("fantasy_market_format"),
        "projection_window": session_state.get("fantasy_market_window"),
        "draft_sync_enabled": bool(session_state.get("sleeper_use_draft_room_needs", True)),
        "sync_team": session_state.get("sleeper_sync_team"),
        "focus_needed_positions": session_state.get("sleeper_focus_needed_positions"),
    }
    try:
        from draft_room_state import get_all_drafted_player_names, get_canonical_draft_board, get_canonical_draft_meta

        board = get_canonical_draft_board(session_state)
        snap["canonical_draft_meta"] = get_canonical_draft_meta(session_state)
        snap["drafted_exclusions"] = get_all_drafted_player_names(session_state)[:48]
        if board is not None and hasattr(board, "head"):
            filled = board[board["Player"].astype(str).str.strip().ne("")] if "Player" in board.columns else board
            snap["canonical_draft_board"] = filled.head(24).to_dict(orient="records")
            team = session_state.get("sleeper_sync_team") or session_state.get("room_your_team")
            if team and "Team" in board.columns:
                snap["synced_roster"] = (
                    board[board["Team"].astype(str) == str(team)]["Player"]
                    .dropna()
                    .astype(str)
                    .tolist()[:16]
                )
    except Exception:
        pass

    dw = session_state.get("draft_queue")
    if isinstance(dw, list) and dw:
        snap["draft_queue"] = [_copy_widget_value(x) for x in dw[:6]]
    focus = session_state.get("draft_assistant_focus_players")
    if isinstance(focus, list) and focus:
        snap["watchlist_focus"] = [_copy_widget_value(x) for x in focus[:12]]
    return snap


def cache_fantasy_sleepers_ami_context(
    session_state: dict[str, Any],
    *,
    sleepers_df: Any = None,
    busts_df: Any = None,
    synced_roster: list[str] | None = None,
    drafted_exclusions: list[str] | None = None,
    needed_positions: list[str] | None = None,
    fantasy_format: str = "",
    top_n: int = 12,
) -> None:
    """Cache ranked sleeper/bust tables and draft sync state for AMI."""
    try:
        from draft_ami_helpers import compact_fantasy_market_rows, draft_ami_guidance
    except Exception:
        return

    snap = gather_sleepers_ami_snapshot(session_state)
    snap["sleeper_candidates"] = compact_fantasy_market_rows(sleepers_df, limit=top_n)
    snap["bust_risks"] = compact_fantasy_market_rows(busts_df, limit=top_n)
    if synced_roster:
        snap["synced_roster"] = list(synced_roster)[:16]
    if drafted_exclusions:
        snap["drafted_exclusions"] = list(drafted_exclusions)[:48]
    if needed_positions:
        snap["roster_needs"] = list(needed_positions)[:8]
    if fantasy_format:
        snap["fantasy_format"] = str(fantasy_format)

    session_state["_ami_sleepers_snapshot"] = snap
    cache_page_context(
        session_state,
        "Fantasy Sleepers & Busts",
        {
            "sleepers_snapshot": snap,
            "sleeper_candidates": [r.get("player") for r in snap.get("sleeper_candidates", []) if r.get("player")],
            "bust_risks": [r.get("player") for r in snap.get("bust_risks", []) if r.get("player")],
            "drafted_exclusions": snap.get("drafted_exclusions") or [],
            "roster_needs": snap.get("roster_needs") or [],
            "ami_guidance": draft_ami_guidance("Fantasy Sleepers & Busts"),
        },
    )


def record_trend_intel(
    session_state: dict[str, Any],
    *,
    player: str,
    stat: str,
    intel_row: dict[str, Any] | None,
    year_start: int | None = None,
    year_end: int | None = None,
) -> None:
    """Cache slope/R² from Advanced Trend Intelligence for AMI sidebar."""
    summary: dict[str, Any] = {"stat": stat, "player": _player_name(player)}
    if year_start is not None and year_end is not None:
        summary["window"] = f"{year_start}–{year_end}"
    if isinstance(intel_row, dict):
        slope = intel_row.get("Slope") or intel_row.get("slope")
        r2 = intel_row.get("R²") or intel_row.get("R2") or intel_row.get("r2")
        direction = intel_row.get("Trend Direction") or intel_row.get("direction")
        net = intel_row.get("Net Change") or intel_row.get("delta")
        latest = intel_row.get("Latest") or intel_row.get("latest")
        if slope is not None:
            summary["slope"] = round(float(slope), 3) if _is_num(slope) else slope
        if r2 is not None:
            summary["r2"] = round(float(r2), 3) if _is_num(r2) else r2
        if direction:
            summary["direction"] = str(direction)
        if net is not None:
            summary["delta"] = net
        if latest is not None:
            summary["latest"] = latest
        parts = []
        if direction:
            parts.append(str(direction).lower())
        if slope is not None:
            parts.append(f"slope {slope}/yr")
        if r2 is not None:
            parts.append(f"R² {r2}")
        if parts:
            summary["summary"] = "; ".join(parts)
    session_state["_ami_trend_summary"] = summary
    try:
        from baseball_ami_frame import player_draft_status

        ds = player_draft_status(session_state, player)
        if ds.get("player"):
            summary["draft_status"] = ds
            session_state["_ami_player_draft_status"] = ds
    except ImportError:
        pass
    cache_page_context(session_state, "Trend Value", {"trend_summary": summary, "player": summary.get("player"), "metrics": [stat]})


def cache_valuation_ami_context(
    session_state: dict[str, Any],
    *,
    valuation_df: Any = None,
    selected_player: str = "",
    top_n: int = 10,
) -> None:
    """Cache valuation table + draft status for AMI."""
    try:
        from baseball_ami_frame import player_draft_status
        from draft_ami_helpers import draft_ami_guidance
    except Exception:
        return

    snap: dict[str, Any] = {
        "page": "Valuation",
        "selected_player": str(selected_player or "").strip(),
        "weights": {
            "current": session_state.get("value_w_current"),
            "trend": session_state.get("value_w_trend"),
        },
        "filters": {
            "lag": session_state.get("value_lag"),
            "position": session_state.get("value_position_filter"),
            "min_g": session_state.get("value_min_g"),
        },
    }
    top_rows: list[dict[str, Any]] = []
    if valuation_df is not None and hasattr(valuation_df, "iterrows") and not getattr(valuation_df, "empty", True):
        import pandas as pd

        ranked = valuation_df.sort_values("Valuation_Score", ascending=False).head(top_n)
        for _, row in ranked.iterrows():
            name = str(row.get("fullName") or "").strip()
            if not name:
                continue
            entry: dict[str, Any] = {"player": name}
            for col in (
                "Valuation_Score",
                "Perf_Score",
                "Trend_Score",
                "Primary Position",
                "Market Rank",
                "Model Rank",
                "Fantasy Edge",
                "proj_HR",
                "proj_SB",
                "proj_OPS",
            ):
                if col in row.index and pd.notna(row.get(col)):
                    entry[col] = row.get(col)
            top_rows.append(entry)
        snap["top_valuation_players"] = top_rows
        if not snap["selected_player"] and top_rows:
            snap["selected_player"] = top_rows[0]["player"]

    sel = snap.get("selected_player") or ""
    if sel:
        snap["draft_status"] = player_draft_status(session_state, sel)
    try:
        from draft_room_state import get_all_drafted_player_names

        snap["canonical_drafted_players"] = get_all_drafted_player_names(session_state)[:48]
    except Exception:
        pass

    session_state["_ami_valuation_snapshot"] = snap
    cache_page_context(
        session_state,
        "Valuation",
        {
            "valuation_snapshot": snap,
            "player": snap.get("selected_player"),
            "ami_guidance": draft_ami_guidance("Valuation"),
        },
    )


def _attach_canonical_draft_fields(ctx: dict[str, Any], session_state: dict[str, Any]) -> None:
    """Promote canonical draft board + drafted list for any page that needs draft awareness."""
    try:
        from draft_room_state import get_all_drafted_player_names, get_canonical_draft_board
    except ImportError:
        return
    if not ctx.get("canonical_drafted_players") and not ctx.get("drafted_players"):
        names = get_all_drafted_player_names(session_state)[:48]
        if names:
            ctx["canonical_drafted_players"] = names
            ctx["drafted_players"] = names[:24]
    if not ctx.get("canonical_draft_board"):
        board = get_canonical_draft_board(session_state)
        if board is not None and hasattr(board, "head"):
            filled = board[board["Player"].astype(str).str.strip().ne("")] if "Player" in board.columns else board
            ctx["canonical_draft_board"] = filled.head(24).to_dict(orient="records")


def _is_num(val: Any) -> bool:
    try:
        float(val)
        return True
    except (TypeError, ValueError):
        return False


def build_baseball_applied_math_context(page: str, session_state: dict[str, Any]) -> dict[str, Any]:
    """Return clean structured context for the active Baseball page."""
    p = str(page or "").strip()
    low = p.lower()
    ctx: dict[str, Any] = {"page": p}

    if p == "Historical Explorer":
        yr = session_state.get("historical_year_range_filter")
        if isinstance(yr, (list, tuple)) and len(yr) >= 2:
            ctx["filters_applied"] = f"Years {yr[0]}–{yr[1]}"
        sort_stat = session_state.get("historical_sort_stat_filter")
        if sort_stat:
            ctx["metrics"] = [str(sort_stat)]
            ctx["filters_applied"] = (ctx.get("filters_applied") or "") + f"; sort {sort_stat}"
        snap = session_state.get("_ami_historical_snapshot")
        if isinstance(snap, dict):
            ctx["historical_snapshot"] = snap
            if snap.get("top_players"):
                ctx["players"] = snap["top_players"][:5]
        hist_sel = session_state.get("historical_selected_player") or session_state.get("hist_selected_player")
        if hist_sel:
            ctx["player"] = _player_name(hist_sel)

    elif p == "Comparison Tool":
        pa = session_state.get("sig_player_a_clean")
        pb = session_state.get("sig_player_b_clean")
        if pa:
            ctx["player_a"] = _player_name(pa)
        if pb:
            ctx["player_b"] = _player_name(pb)
        if pa and pb:
            ctx["players"] = [ctx["player_a"], ctx["player_b"]]
        cmp_extra = session_state.get("_ami_comparison_context")
        if isinstance(cmp_extra, dict):
            ctx.update(cmp_extra)
        ctx["chart_snapshot"] = build_source_state(p, session_state).get("chart_params", {}).get("chart_snapshot")

    elif p == "Trend Value":
        pl = session_state.get("single_trend_dashboard_player")
        if pl:
            ctx["player"] = _player_name(pl)
        multi = session_state.get("trend_players_multi") or session_state.get("trend_force_multi_labels")
        if isinstance(multi, list) and multi:
            ctx["players"] = [_player_name(x) for x in multi[:6]]
        stats = session_state.get("single_trend_dashboard_stats") or []
        if stats:
            ctx["metrics"] = [str(s) for s in stats[:6]]
        plot_stat = session_state.get("trend_plot_stat")
        if plot_stat:
            ctx.setdefault("metrics", [])
            if str(plot_stat) not in ctx["metrics"]:
                ctx["metrics"].append(str(plot_stat))
        lag = session_state.get("trend_lag")
        if lag is not None:
            ctx["trend_window"] = f"{lag} seasons"
        ami = session_state.get("_ami_trend_summary")
        if isinstance(ami, dict) and ami:
            ctx["trend_summary"] = ami
            if ami.get("draft_status"):
                ctx["draft_status"] = ami["draft_status"]
        try:
            from baseball_ami_frame import player_draft_status
            from draft_ami_helpers import draft_ami_guidance

            pl_name = ctx.get("player") or _player_name(pl or ami.get("player") if isinstance(ami, dict) else "")
            if pl_name and not ctx.get("draft_status"):
                ctx["draft_status"] = player_draft_status(session_state, pl_name)
            _attach_canonical_draft_fields(ctx, session_state)
            ctx["ami_guidance"] = draft_ami_guidance("Trend Value")
        except ImportError:
            pass
        ctx["chart_snapshot"] = build_source_state(p, session_state).get("chart_params", {}).get("chart_snapshot")

    elif p == "Valuation":
        sel = session_state.get("valuation_selected_player")
        snap = session_state.get("_ami_valuation_snapshot")
        if not isinstance(snap, dict):
            snap = {}
        if sel:
            ctx["player"] = _player_name(sel)
        if snap:
            ctx["valuation_snapshot"] = snap
            if snap.get("selected_player"):
                ctx["player"] = _player_name(snap["selected_player"])
            if snap.get("top_valuation_players"):
                ctx["players"] = [
                    r.get("player") for r in snap["top_valuation_players"][:6] if isinstance(r, dict)
                ]
            if snap.get("draft_status"):
                ctx["draft_status"] = snap["draft_status"]
        try:
            from baseball_ami_frame import player_draft_status
            from draft_ami_helpers import draft_ami_guidance

            if ctx.get("player") and not ctx.get("draft_status"):
                ctx["draft_status"] = player_draft_status(session_state, ctx["player"])
            _attach_canonical_draft_fields(ctx, session_state)
            ctx["ami_guidance"] = draft_ami_guidance("Valuation")
        except ImportError:
            pass

    elif "draft" in low:
        dq = session_state.get("draft_queue") or []
        if isinstance(dq, list) and dq:
            ctx["player"] = _player_name(dq[0])
            ctx["players"] = [_player_name(x) for x in dq[:4]]
        try:
            from draft_ami_helpers import AMI_POOL_FINAL_CAP, draft_ami_guidance
            from draft_state import gather_draft_ami_snapshot

            snap = session_state.get("_ami_draft_snapshot")
            if not isinstance(snap, dict) or not snap:
                snap = gather_draft_ami_snapshot(p, session_state)
            if snap:
                ctx["draft_snapshot"] = snap
                if snap.get("current_pick"):
                    ctx["current_pick"] = snap["current_pick"]
                if snap.get("draft_round"):
                    ctx["draft_round"] = snap["draft_round"]
                if snap.get("my_next_pick"):
                    ctx["my_next_pick"] = snap["my_next_pick"]
                if snap.get("user_roster"):
                    ctx["roster"] = snap["user_roster"][:12]
                if snap.get("needed_positions"):
                    ctx["needed_positions"] = snap["needed_positions"]
                if snap.get("category_needs"):
                    ctx["category_needs"] = snap["category_needs"]
                if snap.get("recommended_players"):
                    ctx["recommended_players"] = [
                        r if isinstance(r, dict) else {"player": str(r)}
                        for r in snap["recommended_players"][:12]
                    ]
                if snap.get("available_players"):
                    ctx["available_players"] = [
                        r if isinstance(r, dict) else {"player": str(r)}
                        for r in snap["available_players"][:AMI_POOL_FINAL_CAP]
                    ]
                if snap.get("player_pool_diagnostics"):
                    ctx["player_pool_diagnostics"] = dict(snap["player_pool_diagnostics"])
                if snap.get("best_available_players"):
                    ctx["best_available"] = [
                        r if isinstance(r, dict) else {"player": str(r)}
                        for r in snap["best_available_players"][:12]
                    ]
                elif snap.get("available_players") and not ctx.get("best_available"):
                    ctx["best_available"] = ctx["available_players"][:12]
                if snap.get("sleepers"):
                    ctx["sleepers"] = [
                        r.get("player") for r in snap["sleepers"][:6] if isinstance(r, dict)
                    ]
                if snap.get("canonical_drafted_players"):
                    ctx["drafted_players"] = snap["canonical_drafted_players"][:24]
                if snap.get("draft_queue"):
                    ctx["draft_queue"] = snap["draft_queue"][:6]
                if snap.get("watchlist_focus"):
                    ctx["watchlist"] = snap["watchlist_focus"][:8]
                if snap.get("tracked_players"):
                    ctx["tracked_players"] = snap["tracked_players"][:12]
                if snap.get("draft_room_board"):
                    ctx["canonical_draft_board"] = snap["draft_room_board"][:12]
                if snap.get("scoring_settings"):
                    ctx["scoring_settings"] = snap["scoring_settings"]
                ctx["ami_guidance"] = draft_ami_guidance(p)
        except ImportError:
            pass
        proj = session_state.get("_ami_draft_projection")
        if isinstance(proj, dict):
            ctx["draft_projection"] = proj
            if proj.get("position_scarcity") is not None and "position_scarcity" not in ctx:
                ctx["position_scarcity"] = proj["position_scarcity"]
            if proj.get("available_players") and not ctx.get("available_players"):
                ctx["available_players"] = proj["available_players"]
            if proj.get("player_pool_diagnostics") and not ctx.get("player_pool_diagnostics"):
                ctx["player_pool_diagnostics"] = proj["player_pool_diagnostics"]
        try:
            _attach_canonical_draft_fields(ctx, session_state)
        except Exception:
            pass

    elif p == "Fantasy Sleepers & Busts":
        try:
            from draft_ami_helpers import draft_ami_guidance

            snap = session_state.get("_ami_sleepers_snapshot")
            if not isinstance(snap, dict) or not snap.get("sleeper_candidates"):
                snap = gather_sleepers_ami_snapshot(session_state)
            if snap:
                ctx["sleepers_snapshot"] = snap
                if snap.get("sleeper_candidates"):
                    ctx["sleeper_candidates"] = [
                        r.get("player") for r in snap["sleeper_candidates"][:8] if isinstance(r, dict)
                    ]
                    ctx["available_players"] = [
                        dict(r) for r in snap["sleeper_candidates"][:12] if isinstance(r, dict)
                    ]
                if snap.get("bust_risks"):
                    ctx["bust_risks"] = [
                        r.get("player") for r in snap["bust_risks"][:8] if isinstance(r, dict)
                    ]
                if snap.get("drafted_exclusions"):
                    ctx["drafted_exclusions"] = snap["drafted_exclusions"][:24]
                if snap.get("synced_roster"):
                    ctx["roster"] = snap["synced_roster"][:12]
                if snap.get("roster_needs"):
                    ctx["roster_needs"] = snap["roster_needs"]
                if snap.get("canonical_draft_board"):
                    ctx["canonical_draft_board"] = snap["canonical_draft_board"][:12]
                ctx["ami_guidance"] = draft_ami_guidance(p)
        except ImportError:
            pass

    cached = get_cached_page_context(session_state, p)
    if cached:
        for k, v in cached.items():
            if v is not None and v != "" and k not in ctx:
                ctx[k] = v
    try:
        from baseball_ami_frame import attach_baseball_ami_frame

        attach_baseball_ami_frame(ctx, p)
    except ImportError:
        pass
    return ctx


def merged_baseball_context(page: str, session_state: dict[str, Any]) -> dict[str, Any]:
    return build_baseball_applied_math_context(page, session_state)


def build_comparison_source_state(session_state: dict[str, Any]) -> dict[str, Any]:
    return build_source_state("Comparison Tool", session_state)


def build_trends_source_state(session_state: dict[str, Any]) -> dict[str, Any]:
    return build_source_state("Trend Value", session_state)


def build_historical_source_state(session_state: dict[str, Any]) -> dict[str, Any]:
    return build_source_state("Historical Explorer", session_state)


def build_draft_source_state(session_state: dict[str, Any], page: str) -> dict[str, Any]:
    return build_source_state(page, session_state)


def apply_comparison_source_state(session_state: dict[str, Any], source_state: dict[str, Any]) -> None:
    apply_source_state_to_session(session_state, source_state)


def apply_trends_source_state(session_state: dict[str, Any], source_state: dict[str, Any]) -> None:
    apply_source_state_to_session(session_state, source_state)


def apply_historical_source_state(session_state: dict[str, Any], source_state: dict[str, Any]) -> None:
    apply_source_state_to_session(session_state, source_state)


def apply_draft_source_state(session_state: dict[str, Any], source_state: dict[str, Any]) -> None:
    apply_source_state_to_session(session_state, source_state)
