"""
Developer-only last activity event panel — no Continue logic.
"""

from __future__ import annotations

from typing import Any


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
        "player": str(trace.get("player") or "—"),
        "timestamp": str(trace.get("timestamp") or "—")[:19],
        "recorded": bool(trace.get("recorded")),
        "supabase_write_ok": bool(trace.get("supabase_write_ok")),
        "write_path": str(trace.get("write_path") or "—"),
        "error": str(trace.get("error") or ""),
    }


def render_trend_value_deploy_banner(st) -> None:
    """Always-visible deploy marker on Trend Value (proves correct build is running)."""
    from suite_deploy_marker import GIT_BRANCH, GIT_COMMIT_SHORT, SUITE_BUILD_LABEL

    st.success(
        f"**Trend activity diagnostics live · {SUITE_BUILD_LABEL}** · "
        f"commit `{GIT_COMMIT_SHORT}` · branch `{GIT_BRANCH}` · entry `streamlit_app.py`"
    )


def render_last_baseball_activity_event_panel(st) -> None:
    """Visible panel directly under the single-player trend chart — not buried in an expander."""
    st.markdown("#### Developer: Last Baseball Activity Event")
    row = last_activity_event_row()
    if not row:
        st.info(
            "No activity hook fired yet this session. Select Lorenzo Cain, keep at least one stat checked, "
            "and wait for the chart above to render."
        )
        return
    st.dataframe(
        [
            {
                "event_type": row["event_type"],
                "resume_key": row["resume_key"],
                "player": row["player"],
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


# Backward-compatible alias
def render_last_baseball_activity_event(st, *, expanded: bool = True) -> None:
    del expanded
    render_last_baseball_activity_event_panel(st)
