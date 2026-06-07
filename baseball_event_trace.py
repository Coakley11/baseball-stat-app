"""
Developer-only last activity event panel — no Continue logic.
"""

from __future__ import annotations

from typing import Any

_TREND_EVENT_TYPES = frozenset(
    {
        "player_trend_viewed",
        "trend_comparison_viewed",
        "trend_analysis",
        "trend_filter_changed",
        "breakout_analysis",
    }
)


def last_activity_event_row() -> dict[str, Any] | None:
    from baseball_activity import last_activity_trace

    trace = last_activity_trace()
    if not trace:
        return None
    event_type = str(trace.get("event_type") or trace.get("event") or "").strip()
    if not event_type:
        return None
    return {
        "event_type": event_type,
        "resume_key": str(trace.get("resume_key") or "—"),
        "players": str(trace.get("players") or trace.get("player") or "—"),
        "player": str(trace.get("player") or "—"),
        "timestamp": str(trace.get("timestamp") or "—")[:19],
        "recorded": bool(trace.get("recorded")),
        "supabase_write_ok": bool(trace.get("supabase_write_ok")),
        "write_path": str(trace.get("write_path") or "—"),
        "error": str(trace.get("error") or ""),
    }


def render_trend_value_deploy_banner(st, *, developer_mode: bool = False) -> None:
    """Deploy marker on Trend Value — developer mode only."""
    if not developer_mode:
        return
    from suite_deploy_marker import GIT_BRANCH, GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

    st.success(
        f"**Trend activity diagnostics live · {SUITE_BUILD_LABEL}** · "
        f"commit `{GIT_COMMIT_SHORT}` · branch `{GIT_BRANCH}` · entry `streamlit_app.py`"
    )


def render_last_baseball_activity_event_panel(st) -> None:
    """Latest activity hook on Trend Value — single- or multi-player."""
    render_trend_activity_developer_panel(st)


def render_trend_activity_developer_panel(st) -> None:
    st.markdown("#### Developer: Latest Trend Activity Event")
    row = last_activity_event_row()
    if not row:
        st.info(
            "No trend activity hook fired yet this session. "
            "Single-player: select a player and render the dashboard chart. "
            "Multi-player: select 2+ players in **Player Trend Visualization** and wait for the comparison chart."
        )
        return
    st.dataframe(
        [
            {
                "event_type": row["event_type"],
                "resume_key": row["resume_key"],
                "players": row["players"],
                "timestamp": row["timestamp"],
                "recorded": row["recorded"],
                "supabase_write_ok": row["supabase_write_ok"],
                "write_path": row["write_path"],
                "error": row["error"] or "—",
            }
        ],
        use_container_width=True,
        hide_index=True,
    )
    if row["event_type"] not in _TREND_EVENT_TYPES:
        st.caption(
            f"Latest hook was `{row['event_type']}` (not a named-player trend event). "
            "Render a trend chart to refresh."
        )


def log_trend_chart_if_needed(
    st,
    *,
    player: str,
    chart_label: str,
    dashboard_stats: list[str],
    chart_mode: str,
    developer_mode: bool,
) -> tuple[bool, str]:
    """
    Fire player_trend_viewed after the single-player dashboard chart renders.
    Returns (logged_this_run, error_message).
    """
    from baseball_activity import log_player_trend_chart

    if not dashboard_stats:
        return False, "no stats selected — chart hook skipped"

    sig = (chart_label, tuple(dashboard_stats), chart_mode)
    already = st.session_state.get("_cc_trend_chart_sig")
    if not developer_mode and already == sig:
        return False, ""

    st.session_state["_cc_trend_chart_sig"] = sig
    try:
        log_player_trend_chart(
            player=player,
            trend_mode=chart_mode,
            stats=list(dashboard_stats),
        )
        return True, ""
    except Exception as exc:
        return False, str(exc)


def log_trend_comparison_if_needed(
    st,
    *,
    selected_labels: list[str],
    name_from_label,
    trend_stat: str,
    chart_mode: str,
    developer_mode: bool,
) -> tuple[bool, str]:
    """
    Fire trend_comparison_viewed after the multi-player trend chart renders.
    Returns (logged_this_run, error_message).
    """
    from baseball_activity import log_trend_comparison_viewed

    if len(selected_labels) < 2:
        return False, "need 2+ players for trend comparison hook"

    names = [str(name_from_label(lbl)).strip() for lbl in selected_labels]
    names = [n for n in names if n]
    if len(names) < 2:
        return False, "could not resolve player names from labels"

    sig = (tuple(selected_labels), trend_stat, chart_mode)
    already = st.session_state.get("_cc_trend_compare_sig")
    if not developer_mode and already == sig:
        return False, ""

    st.session_state["_cc_trend_compare_sig"] = sig
    try:
        log_trend_comparison_viewed(
            names[0],
            names[1],
            players=names[:6],
            trend_stat=trend_stat,
            chart_mode=chart_mode,
        )
        return True, ""
    except Exception as exc:
        return False, str(exc)


def render_last_baseball_activity_event(st, *, expanded: bool = True) -> None:
    del expanded
    render_trend_activity_developer_panel(st)
