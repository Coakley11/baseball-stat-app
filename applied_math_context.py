"""Page-specific Applied Math context extractors for Baseball."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any


def _player_name(raw: Any) -> str:
    return str(raw or "").split(" (")[0].strip()


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

    elif "draft" in p.lower():
        dq = session_state.get("draft_queue")
        if isinstance(dq, list) and dq:
            entity_params["draft_queue"] = [_copy_widget_value(x) for x in dq[:6]]

    return {
        "source_app": "baseball",
        "source_page": p,
        "page_params": {"page": p},
        "entity_params": entity_params,
        "widget_params": widget_params,
        "filter_params": filter_params,
        "chart_params": chart_params,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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

    if page == "Career Totals":
        try:
            from career_totals_state import apply_career_source_state_from_ami

            apply_career_source_state_from_ami(session_state, source_state)
        except ImportError:
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
    cache_page_context(session_state, "Trend Value", {"trend_summary": summary, "player": summary.get("player"), "metrics": [stat]})


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
        ctx["chart_snapshot"] = build_source_state(p, session_state).get("chart_params", {}).get("chart_snapshot")

    elif "draft" in low:
        dq = session_state.get("draft_queue") or []
        if isinstance(dq, list) and dq:
            ctx["player"] = _player_name(dq[0])
            ctx["players"] = [_player_name(x) for x in dq[:4]]
        proj = session_state.get("_ami_draft_projection")
        if isinstance(proj, dict):
            ctx["draft_projection"] = proj

    cached = get_cached_page_context(session_state, p)
    if cached:
        for k, v in cached.items():
            if v is not None and v != "" and k not in ctx:
                ctx[k] = v
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
