"""Page-specific Applied Math context extractors for Baseball."""

from __future__ import annotations

from typing import Any


def _player_name(raw: Any) -> str:
    return str(raw or "").split(" (")[0].strip()


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

    elif p == "Trend Value":
        pl = session_state.get("single_trend_dashboard_player")
        if pl:
            ctx["player"] = _player_name(pl)
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
