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


def render_last_baseball_activity_event(st, *, expanded: bool = True) -> None:
    from suite_deploy_marker import (
        DEPLOY_COMMITS_INCLUDED,
        GIT_BRANCH,
        GIT_COMMIT_SHORT,
        SUITE_BUILD_LABEL,
    )

    with st.expander("Developer: Last Baseball Activity Event", expanded=expanded):
        st.markdown("**Deploy verification**")
        st.code(
            f"build_marker={SUITE_BUILD_LABEL}\n"
            f"commit={GIT_COMMIT_SHORT}\n"
            f"branch={GIT_BRANCH}\n"
            f"includes={', '.join(DEPLOY_COMMITS_INCLUDED)}",
            language=None,
        )
        row = last_activity_event_row()
        if not row:
            st.caption("No activity hook fired yet this session. Render a Lorenzo Cain chart to populate.")
            return
        st.markdown("**Last write attempt**")
        display = {
            "event_type": row["event_type"],
            "resume_key": row["resume_key"],
            "player": row["player"],
            "timestamp": row["timestamp"],
            "recorded": row["recorded"],
            "supabase_write_ok": row["supabase_write_ok"],
            "write_path": row["write_path"],
        }
        st.dataframe([display], use_container_width=True, hide_index=True)
        if row["error"]:
            st.warning(f"Write error detail: `{row['error']}`")
