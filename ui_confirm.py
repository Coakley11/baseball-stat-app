"""Two-step buttons for actions that permanently remove something (one convention app-wide).

The first tap only asks; the action runs on an explicit Confirm. Both steps are on_click
callbacks, which run exactly once per click, so a rerun can never repeat a confirmation. An
unanswered request lapses after two minutes so a stale prompt can never fire later.

The pending prompt is kept per browser session outside ``st.session_state``: in the full app a
flag set by the first tap's callback was gone again by the time the page rendered (browser run
2026-10-27, same session, no reload), so the prompt never appeared.
"""

from __future__ import annotations

import time
from typing import Any

# Material icons used for destructive actions (see feature_identity for page icons).
ICON_DELETE = ":material/delete:"
ICON_RESET = ":material/restart_alt:"
ICON_LEAVE = ":material/logout:"
ICON_CANCEL = ":material/cancel:"

_LAPSE_SECONDS = 120.0
_MAX_SESSIONS = 500
# {browser session id: {key: ("armed", ts) | ("fired", ts)}}
_PENDING: dict[str, dict[str, tuple[str, float]]] = {}
# Widget keys end in "_btn": page snapshots skip those (page_state._is_ephemeral_widget_key); a
# restored button value raises StreamlitValueAssignmentNotAllowedError.


def _session_id(st: Any) -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is not None and getattr(ctx, "session_id", ""):
            return str(ctx.session_id)
    except Exception:
        pass
    return f"obj:{id(st.session_state)}"


def _pending_for(st: Any) -> dict[str, tuple[str, float]]:
    sid = _session_id(st)
    pending = _PENDING.get(sid)
    if pending is None:
        if len(_PENDING) >= _MAX_SESSIONS:
            _PENDING.pop(next(iter(_PENDING)))
        pending = _PENDING[sid] = {}
    return pending


def _arm(pending: dict, key: str) -> None:
    pending[key] = ("armed", time.time())


def _disarm(pending: dict, key: str) -> None:
    pending.pop(key, None)


def _fire(pending: dict, key: str) -> None:
    pending[key] = ("fired", time.time())


def confirm_destructive_action(
    st: Any,
    *,
    key: str,
    label: str,
    warning: str,
    confirm_label: str,
    icon: str = ICON_DELETE,
    help: str | None = None,
    use_container_width: bool = False,
) -> bool:
    """Render a destructive button; return True only on the run right after Confirm."""
    pending = _pending_for(st)
    state, at = pending.get(key, ("", 0.0))
    if state and time.time() - at > _LAPSE_SECONDS:
        pending.pop(key, None)
        state = ""
    if state == "fired":
        pending.pop(key, None)
        return True
    if state != "armed":
        st.button(label, key=f"{key}__ask_btn", icon=icon, help=help, use_container_width=use_container_width,
                  on_click=_arm, args=(pending, key))
        return False
    st.warning(warning, icon=":material/warning:")
    yes_col, no_col = st.columns(2)
    yes_col.button(confirm_label, key=f"{key}__yes_btn", type="primary", icon=icon, use_container_width=True,
                   on_click=_fire, args=(pending, key))
    no_col.button("Cancel", key=f"{key}__no_btn", icon=":material/close:", use_container_width=True,
                  on_click=_disarm, args=(pending, key))
    return False
