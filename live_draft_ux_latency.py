"""Live Draft UX latency — click → first paint → settled (Developer Mode).

This measures the *rendered* Streamlit path, not engine scoring.

Markers:
- click: widget on_click / button True branch (wall clock)
- first_visible: first section milestone after click that paints the
  intended surface (queue / board / on_clock / rec_cards / timer)
- settled: fragment body end (fragment-scope) or page_complete (app-scope)

Also records:
- rerun_scope: fragment | app | none
- second_rerun: same action spans a second script/fragment pass
- rebuild list for the measured pass
"""

from __future__ import annotations

import time
from typing import Any

UX_LATENCY_LOG_KEY = "_live_draft_ux_latency_log"
UX_LATENCY_ACTIVE_KEY = "_live_draft_ux_latency_active"
UX_LATENCY_RUN_MARK_KEY = "_live_draft_ux_latency_run_mark"
UX_LATENCY_MAX = 40

# Surfaces the user cares about.
ACTION_ADD_QUEUE = "add_to_queue"
ACTION_REMOVE_QUEUE = "remove_from_queue"
ACTION_REORDER_QUEUE = "reorder_queue"
ACTION_DRAFT_QUEUE = "draft_from_queue"
ACTION_DRAFT_REC = "draft_from_recommendation"
ACTION_BOARD_UPDATE = "board_update"
ACTION_ON_CLOCK = "on_clock_update"
ACTION_TIMER_RESET = "timer_reset"
ACTION_REC_CARDS = "recommendation_card_update"

FIRST_VISIBLE_BY_ACTION: dict[str, tuple[str, ...]] = {
    ACTION_ADD_QUEUE: ("queue_paint_start", "queue_paint_done"),
    ACTION_REMOVE_QUEUE: ("queue_paint_start", "queue_paint_done"),
    ACTION_REORDER_QUEUE: ("queue_paint_start", "queue_paint_done"),
    ACTION_DRAFT_QUEUE: ("board_paint_start", "on_clock_paint_start", "queue_paint_start"),
    ACTION_DRAFT_REC: ("board_paint_start", "on_clock_paint_start", "rec_cards_paint_start"),
    ACTION_BOARD_UPDATE: ("board_paint_start", "board_paint_done"),
    ACTION_ON_CLOCK: ("on_clock_paint_start", "on_clock_paint_done"),
    ACTION_TIMER_RESET: ("timer_paint_start", "timer_paint_done"),
    ACTION_REC_CARDS: ("rec_cards_paint_start", "rec_cards_paint_done"),
}


def ux_latency_enabled(session: dict[str, Any], st: Any | None = None) -> bool:
    if not isinstance(session, dict):
        return False
    if session.get("_live_draft_ux_latency_force"):
        return True
    # Prefer session flags first (works in unit tests without ScriptRunContext).
    if session.get("app_developer_mode") or session.get("_suite_developer_mode_user"):
        return True
    if st is not None:
        try:
            raw = st.query_params.get("ux_latency")
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else ""
            if str(raw or "").strip().lower() in {"1", "true", "yes", "on"}:
                session["_live_draft_ux_latency_force"] = True
                return True
        except Exception:
            pass
        try:
            from suite_workspace import developer_mode_checkbox_enabled

            return bool(developer_mode_checkbox_enabled(st=st))
        except Exception:
            pass
    return False


def _now() -> float:
    return time.perf_counter()


def _wall() -> float:
    return time.time()


def note_ux_action(
    session: dict[str, Any],
    action: str,
    *,
    source: str = "",
    detail: str = "",
    st: Any | None = None,
) -> dict[str, Any] | None:
    """Mark click-time for an interaction (call from on_click / button True)."""
    if not ux_latency_enabled(session, st):
        return None
    action = str(action or "").strip() or "unknown"
    entry: dict[str, Any] = {
        "action": action,
        "source": str(source or "").strip(),
        "detail": str(detail or "").strip()[:120],
        "click_perf": _now(),
        "click_wall": _wall(),
        "milestones": {},
        "rebuilds": [],
        "rerun_scope": "",
        "pass_count": 0,
        "first_visible_milestone": "",
        "first_visible_ms": None,
        "settled_ms": None,
        "second_rerun": False,
        "status": "open",
    }
    session[UX_LATENCY_ACTIVE_KEY] = entry
    log = list(session.get(UX_LATENCY_LOG_KEY) or [])
    log.append(entry)
    session[UX_LATENCY_LOG_KEY] = log[-UX_LATENCY_MAX:]
    return entry


def _active(session: dict[str, Any]) -> dict[str, Any] | None:
    entry = session.get(UX_LATENCY_ACTIVE_KEY)
    return entry if isinstance(entry, dict) and entry.get("status") == "open" else None


def mark_ux_milestone(
    session: dict[str, Any],
    name: str,
    *,
    rebuild: str = "",
    st: Any | None = None,
) -> None:
    """Record a paint/section milestone after an open action."""
    if not ux_latency_enabled(session, st):
        return
    entry = _active(session)
    if entry is None:
        return
    ms_map = entry.setdefault("milestones", {})
    if not isinstance(ms_map, dict):
        return
    if name in ms_map:
        return
    click = float(entry.get("click_perf") or 0.0)
    if click <= 0:
        return
    elapsed_ms = (_now() - click) * 1000.0
    ms_map[str(name)] = round(elapsed_ms, 1)
    if rebuild:
        rebuilds = entry.setdefault("rebuilds", [])
        if isinstance(rebuilds, list) and rebuild not in rebuilds:
            rebuilds.append(rebuild)
    # First visible for this action family.
    if entry.get("first_visible_ms") is None:
        targets = FIRST_VISIBLE_BY_ACTION.get(str(entry.get("action") or ""), ())
        if str(name) in targets:
            entry["first_visible_milestone"] = str(name)
            entry["first_visible_ms"] = round(elapsed_ms, 1)


def note_ux_rerun_scope(
    session: dict[str, Any],
    scope: str,
    *,
    st: Any | None = None,
) -> None:
    """Record whether the interaction escalated to fragment or full-app rerun."""
    if not ux_latency_enabled(session, st):
        return
    entry = _active(session)
    if entry is None:
        return
    entry["rerun_scope"] = str(scope or "")
    if int(entry.get("pass_count") or 0) >= 2:
        entry["second_rerun"] = True


def note_ux_pass_begin(session: dict[str, Any], *, st: Any | None = None) -> None:
    """Call at the start of fragment body / app LDR page when an action is open."""
    if not ux_latency_enabled(session, st):
        return
    entry = _active(session)
    if entry is None:
        return
    entry["pass_count"] = int(entry.get("pass_count") or 0) + 1
    if int(entry["pass_count"]) >= 2:
        entry["second_rerun"] = True
    mark_ux_milestone(session, f"pass_{entry['pass_count']}_begin", st=st)


def settle_ux_action(
    session: dict[str, Any],
    *,
    where: str = "settled",
    st: Any | None = None,
) -> None:
    """Mark the measured action settled (fragment end or page_complete)."""
    if not ux_latency_enabled(session, st):
        return
    entry = _active(session)
    if entry is None:
        return
    click = float(entry.get("click_perf") or 0.0)
    if click <= 0:
        return
    elapsed_ms = (_now() - click) * 1000.0
    mark_ux_milestone(session, where, st=st)
    entry["settled_ms"] = round(elapsed_ms, 1)
    entry["status"] = "settled"
    # Keep last settled visible; clear active pointer.
    session.pop(UX_LATENCY_ACTIVE_KEY, None)


def begin_script_run_mark(session: dict[str, Any], *, st: Any | None = None) -> None:
    """Detect whether an open action survived into a full app script run."""
    if not ux_latency_enabled(session, st):
        return
    entry = _active(session)
    if entry is None:
        return
    # Full app script hit while action open → not fragment-only.
    if not entry.get("rerun_scope"):
        entry["rerun_scope"] = "app"
    note_ux_pass_begin(session, st=st)
    mark_ux_milestone(session, "app_script_begin", rebuild="full_app_script", st=st)


def latest_ux_latency(session: dict[str, Any]) -> dict[str, Any] | None:
    log = list(session.get(UX_LATENCY_LOG_KEY) or [])
    for entry in reversed(log):
        if isinstance(entry, dict):
            return entry
    return None


def render_ux_latency_panel(st: Any, session: dict[str, Any]) -> None:
    """Developer Mode sidebar/expander with the last measured interactions."""
    if not ux_latency_enabled(session, st):
        return
    log = [e for e in list(session.get(UX_LATENCY_LOG_KEY) or []) if isinstance(e, dict)]
    with st.sidebar.expander("UX latency (click → paint)", expanded=True):
        st.caption(
            "Measures Streamlit paint path. first_visible_ms = first painted "
            "surface after click; settled_ms = fragment/page end. "
            "Add `?ux_latency=1` to force on."
        )
        if not log:
            st.caption("No interactions recorded yet — click Add/Remove/Draft in Live Draft Room.")
            return
        rows = []
        for e in log[-12:]:
            rows.append(
                {
                    "action": e.get("action"),
                    "source": e.get("source"),
                    "first_ms": e.get("first_visible_ms"),
                    "settled_ms": e.get("settled_ms"),
                    "scope": e.get("rerun_scope") or "?",
                    "2nd_rerun": bool(e.get("second_rerun")),
                    "rebuilds": ",".join(e.get("rebuilds") or [])[:80],
                    "status": e.get("status"),
                }
            )
        try:
            import pandas as pd

            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        except Exception:
            st.json(rows[-5:])
        latest = log[-1]
        with st.expander("Latest milestones", expanded=False):
            st.json(
                {
                    "action": latest.get("action"),
                    "detail": latest.get("detail"),
                    "first_visible_milestone": latest.get("first_visible_milestone"),
                    "first_visible_ms": latest.get("first_visible_ms"),
                    "settled_ms": latest.get("settled_ms"),
                    "rerun_scope": latest.get("rerun_scope"),
                    "second_rerun": latest.get("second_rerun"),
                    "pass_count": latest.get("pass_count"),
                    "rebuilds": latest.get("rebuilds"),
                    "milestones": latest.get("milestones"),
                }
            )
