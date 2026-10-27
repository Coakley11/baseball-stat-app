"""Two-step buttons for actions that permanently remove something (one convention app-wide).

The first tap only asks; the action runs on an explicit Confirm. Both steps are on_click
callbacks, which run exactly once per click, so a rerun can never repeat a confirmation. An
unanswered request lapses after two minutes so a stale prompt can never fire later (session flags
must lapse on their own, because any st.session_state access can interrupt a run).
"""

from __future__ import annotations

import time
from typing import Any

# Material icons used for destructive actions (see feature_identity for page icons).
ICON_DELETE = ":material/delete:"
ICON_RESET = ":material/restart_alt:"
ICON_LEAVE = ":material/logout:"
ICON_CANCEL = ":material/cancel:"

_ARMED_PREFIX = "_confirm_armed::"
_FIRED_PREFIX = "_confirm_fired::"
_LAPSE_SECONDS = 120.0


def _arm(session: Any, key: str) -> None:
    session[f"{_ARMED_PREFIX}{key}"] = time.time()


def _disarm(session: Any, key: str) -> None:
    session.pop(f"{_ARMED_PREFIX}{key}", None)


def _fire(session: Any, key: str) -> None:
    session.pop(f"{_ARMED_PREFIX}{key}", None)
    session[f"{_FIRED_PREFIX}{key}"] = True


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
    session = st.session_state
    if session.pop(f"{_FIRED_PREFIX}{key}", False):
        return True
    armed_at = session.get(f"{_ARMED_PREFIX}{key}")
    if isinstance(armed_at, (int, float)) and time.time() - float(armed_at) > _LAPSE_SECONDS:
        _disarm(session, key)
        armed_at = None
    if not armed_at:
        st.button(label, key=f"{key}__ask", icon=icon, help=help, use_container_width=use_container_width,
                  on_click=_arm, args=(session, key))
        return False
    st.warning(warning, icon=":material/warning:")
    yes_col, no_col = st.columns(2)
    yes_col.button(confirm_label, key=f"{key}__yes", type="primary", icon=icon, use_container_width=True,
                   on_click=_fire, args=(session, key))
    no_col.button("Cancel", key=f"{key}__no", icon=":material/close:", use_container_width=True,
                  on_click=_disarm, args=(session, key))
    return False
