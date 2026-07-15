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


def _session_mapping_ok(session: Any) -> bool:
    """True for dicts and Streamlit SessionState / SessionStateProxy."""
    return session is not None and callable(getattr(session, "get", None))


def ux_latency_enabled(session: Any, st: Any | None = None) -> bool:
    """Recording ON when Developer Mode checkbox is on, or ``?ux_latency=1``.

    Session keys (any one is enough):
    - ``app_developer_mode`` — Developer Mode sidebar checkbox widget key
    - ``_suite_developer_mode_user`` — persisted user intent
    - ``_live_draft_ux_latency_force`` — set by ``?ux_latency=1``
    """
    if not _session_mapping_ok(session):
        return False
    if session.get("_live_draft_ux_latency_force"):
        return True
    # Prefer session flags first (works in unit tests without ScriptRunContext).
    # NOTE: must NOT require isinstance(session, dict) — Streamlit's session_state
    # is a SessionStateProxy, not a dict (that bug kept Recording OFF forever).
    if bool(session.get("app_developer_mode")) or bool(session.get("_suite_developer_mode_user")):
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


def ux_latency_enable_debug(session: Any, st: Any | None = None) -> dict[str, Any]:
    """Why recording is on/off — shown in the sidebar panel."""
    return {
        "recording_on": ux_latency_enabled(session, st),
        "session_type": type(session).__name__,
        "app_developer_mode": bool(session.get("app_developer_mode")) if _session_mapping_ok(session) else None,
        "_suite_developer_mode_user": bool(session.get("_suite_developer_mode_user"))
        if _session_mapping_ok(session)
        else None,
        "_live_draft_ux_latency_force": bool(session.get("_live_draft_ux_latency_force"))
        if _session_mapping_ok(session)
        else None,
    }


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
    """Sidebar expander — always mounted so it is findable.

    Recording is on when Developer Mode is checked **or** ``?ux_latency=1``.
    The expander title is always: ``UX latency (click → paint)``.
    """
    enabled = ux_latency_enabled(session, st)
    # Always show when forced or Developer Mode; otherwise still show a compact
    # how-to so the panel is discoverable after reboot.
    show_howto_only = not enabled
    log = [e for e in list(session.get(UX_LATENCY_LOG_KEY) or []) if isinstance(e, dict)]
    # Keep expanded during measurement mode so the panel is hard to miss.
    with st.sidebar.expander("UX latency (click → paint)", expanded=True):
        st.caption(
            "Location: left sidebar, under **Developer Mode**, above **Account & Sign In** / **Choose Page**. "
            "Available on every Baseball page (not only Live Draft Room)."
        )
        dbg = ux_latency_enable_debug(session, st)
        if show_howto_only:
            st.warning(
                "Recording is OFF. Turn **Developer Mode** ON (checkbox above), "
                "or open the app with `?ux_latency=1` in the URL, then click "
                "Add/Remove/Draft in Live Draft Room."
            )
            st.caption(
                f"Debug: session_type=`{dbg.get('session_type')}` · "
                f"app_developer_mode=`{dbg.get('app_developer_mode')}` · "
                f"persist=`{dbg.get('_suite_developer_mode_user')}` · "
                f"force=`{dbg.get('_live_draft_ux_latency_force')}`"
            )
            return
        st.success("Recording ON")
        st.caption(
            "first_visible_ms = first painted surface after click; "
            "settled_ms = fragment/page end."
        )
        if not log:
            st.info(
                "No interactions recorded yet. Go to **Live Draft Room** and click "
                "⭐ Add to Queue, Remove, or Draft — timings appear here after each click."
            )
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

            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        except TypeError:
            try:
                import pandas as pd

                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            except Exception:
                st.json(rows[-5:])
        except Exception:
            st.json(rows[-5:])
        latest = log[-1]
        add_diag = session.get("_live_draft_queue_add_diag")
        if isinstance(add_diag, dict):
            with st.expander("Queue Add diag (session mutate)", expanded=True):
                q_now = [str(x).strip() for x in (session.get("draft_queue") or []) if str(x).strip()]
                st.json(
                    {
                        **add_diag,
                        "draft_queue_now_len": len(q_now),
                        "draft_queue_now": q_now[:12],
                        "sortable_wipe_blocked": bool(
                            session.get("_live_draft_queue_sortable_wipe_blocked")
                        ),
                    }
                )
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
