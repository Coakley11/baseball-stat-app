"""Gate expire/autopick when Control Center Pause/Resume is pending this ScriptRun.

Expire historically runs before Control Center so a zero-second Auto Pick cannot
lose to Pause. That ordering also drops a same-run Pause click at 0s: expire
commits + schedules a page_autopick rerun before ``st.button(live_draft_pause)``
can return True, so the room never becomes ``paused``.

When the incoming widget payload already carries ``live_draft_pause`` /
``live_draft_resume``, skip expire for this run and let Control Center handle it.
"""

from __future__ import annotations

from typing import Any

PAUSE_RESUME_USER_KEYS = ("live_draft_pause", "live_draft_resume")


def _widget_id_matches_control_key(widget_id: str, user_key: str) -> bool:
    wid = str(widget_id or "")
    key = str(user_key or "")
    if not wid or not key:
        return False
    return wid.endswith(f"-{key}") or wid.endswith(key) or key in wid


def _truthy_trigger(val: Any) -> bool:
    if val is True:
        return True
    if val is False or val is None:
        return False
    if isinstance(val, (int, float)) and val == 1:
        return True
    rep = str(val).strip().lower()
    return rep in ("true", "1")


def control_center_pause_resume_pending(st: Any | None = None) -> bool:
    """Return True when Pause or Resume button trigger is present this ScriptRun."""
    ss = None
    try:
        from live_draft_streamlit_widget_metadata_diag import get_streamlit_session_state

        ss = get_streamlit_session_state(st)
    except ImportError:
        ss = None
    if ss is None and st is not None:
        try:
            cand = getattr(st, "session_state", None)
            if cand is not None and hasattr(cand, "_new_widget_state"):
                ss = cand
        except Exception:
            ss = None
    if ss is None:
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx

            ctx = get_script_run_ctx()
            if ctx is not None:
                ss = getattr(ctx, "session_state", None)
        except Exception:
            ss = None
    if ss is None:
        return False

    new_state = getattr(ss, "_new_widget_state", None)
    if new_state is None:
        return False
    states = getattr(new_state, "states", None) or {}
    try:
        items = list(states.items()) if hasattr(states, "items") else []
    except Exception:
        items = []
    for wid, _stored in items:
        wid_s = str(wid or "")
        if not any(_widget_id_matches_control_key(wid_s, k) for k in PAUSE_RESUME_USER_KEYS):
            continue
        try:
            val = new_state.get(wid_s)
        except Exception:
            val = _stored
        if _truthy_trigger(val):
            return True
        # Button triggers often appear as True in deserialized form even when
        # .get returns a proto-ish object — treat presence of a matching trigger
        # id in activated set as pending when value lookup is opaque.
        if val is not None and val is not False:
            try:
                if bool(getattr(val, "trigger_value", False)):
                    return True
            except Exception:
                pass
            if _truthy_trigger(getattr(val, "value", None)):
                return True
    return False
