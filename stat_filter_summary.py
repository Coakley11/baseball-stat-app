"""Active stat-minimum filter summaries for Career Totals and Historical Explorer."""

from __future__ import annotations

from typing import Any, Literal

STAT_MIN_COLUMNS = ("R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
RATE_STAT_COLUMNS = frozenset({"BA", "OBP", "SLG", "OPS"})

STAT_MIN_LABELS: dict[str, str] = {
    "R": "Runs",
    "AB": "At Bats",
    "H": "Hits",
    "2B": "Doubles",
    "3B": "Triples",
    "HR": "Home Runs",
    "RBI": "RBI",
    "SB": "Stolen Bases",
    "BB": "Walks",
    "BA": "Batting Average",
    "OBP": "OBP",
    "SLG": "SLG",
    "OPS": "OPS",
}

PAGE_HEADINGS: dict[str, str] = {
    "career": "Players with Career Totals of:",
    "hist": "Players with Single-Season Totals of:",
}


def _stat_min_key(prefix: str, stat: str) -> str:
    return f"{prefix}_{stat}_min"


def _coerce_positive_min(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    return num


def gather_active_stat_min_filters(
    session: dict[str, Any],
    *,
    prefix: str,
) -> list[tuple[str, float]]:
    """Return active minimum thresholds as (stat_code, value) in display order."""
    active: list[tuple[str, float]] = []
    for stat in STAT_MIN_COLUMNS:
        val = _coerce_positive_min(session.get(_stat_min_key(prefix, stat)))
        if val is not None:
            active.append((stat, val))
    return active


def format_stat_min_line(stat: str, value: float) -> str:
    label = STAT_MIN_LABELS.get(stat, stat)
    if stat in RATE_STAT_COLUMNS:
        return f"{label} ≥ {value:.3f}"
    if abs(value - round(value)) < 1e-9:
        return f"{label} ≥ {int(round(value)):,}"
    return f"{label} ≥ {value:g}"


def build_stat_filter_summary_lines(
    session: dict[str, Any],
    *,
    prefix: str,
) -> list[str]:
    return [format_stat_min_line(stat, val) for stat, val in gather_active_stat_min_filters(session, prefix=prefix)]


def build_stat_filter_summary_text(
    session: dict[str, Any],
    *,
    prefix: str,
) -> str | None:
    """Plain title + criteria text for display above results tables."""
    lines = build_stat_filter_summary_lines(session, prefix=prefix)
    if not lines:
        return None
    heading = PAGE_HEADINGS[prefix]
    criteria = " • ".join(lines)
    return f"{heading}\n\n{criteria}"


def snapshot_stat_min_widget_values(session: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    """All ``{prefix}_{stat}_min`` widget values (including zeros)."""
    return {_stat_min_key(prefix, stat): session.get(_stat_min_key(prefix, stat)) for stat in STAT_MIN_COLUMNS}


def build_stat_filter_summary_diagnostics(
    session: dict[str, Any],
    *,
    mode: Literal["career", "historical"],
) -> dict[str, Any]:
    prefix = "career" if mode == "career" else "hist"
    active = gather_active_stat_min_filters(session, prefix=prefix)
    diag: dict[str, Any] = {
        "mode": mode,
        "prefix": prefix,
        "renderer_called": bool(session.get(f"_filter_summary_called_{mode}")),
        "summary_displayed": bool(session.get(f"_filter_summary_displayed_{mode}")),
        "active_filter_count": len(active),
        "active_widget_keys": {_stat_min_key(prefix, stat): val for stat, val in active},
        "summary_lines": build_stat_filter_summary_lines(session, prefix=prefix),
        "summary_text": build_stat_filter_summary_text(session, prefix=prefix),
        "all_widget_values": snapshot_stat_min_widget_values(session, prefix=prefix),
    }
    try:
        from suite_deploy_marker import GIT_COMMIT_SHORT, GIT_BRANCH

        diag["deploy_commit"] = GIT_COMMIT_SHORT
        diag["deploy_branch"] = GIT_BRANCH
    except Exception:
        pass
    return diag


def render_stat_filter_summary_developer_diagnostics(
    st: Any,
    session: dict[str, Any],
    *,
    mode: Literal["career", "historical"],
) -> None:
    with st.expander("Filter summary diagnostics", expanded=True):
        st.json(build_stat_filter_summary_diagnostics(session, mode=mode))


def render_stat_filter_summary(
    st: Any,
    session: dict[str, Any],
    *,
    mode: Literal["career", "historical"],
) -> None:
    """Show active stat minimum filters above results tables (V1: stat mins only)."""
    prefix = "career" if mode == "career" else "hist"
    summary_text = build_stat_filter_summary_text(session, prefix=prefix)
    session[f"_filter_summary_called_{mode}"] = True
    session[f"_filter_summary_displayed_{mode}"] = summary_text is not None
    session[f"_filter_summary_line_count_{mode}"] = len(
        build_stat_filter_summary_lines(session, prefix=prefix)
    )
    if not summary_text:
        return
    st.markdown(summary_text)
