"""Recover the Account & Workspace control from a stray value on one of its button keys.

Streamlit refuses to draw a button (or upload / submit widget) whose key already holds a value set
through ``st.session_state`` and raises StreamlitValueAssignmentNotAllowedError. On D4J a phone
session hit this inside the sign-in control ("Account control failed ...
(StreamlitValueAssignmentNotAllowedError)") and could not sign in.

The recovery is deliberately narrow: only for that error, only for the key Streamlit names, at most
once per key per session (no rerun loop). Button keys are never cleared ahead of time, because
deleting a button's key before it draws would also drop a real click (e.g. Log out).
"""

from __future__ import annotations

import re
from typing import Any

RECOVERED_KEYS = "_account_control_recovered_keys"
_KEY_RE = re.compile(r"key`?\s*'([^']+)'")


def offending_key(exc: BaseException) -> str:
    """The widget key named by StreamlitValueAssignmentNotAllowedError ('' for other errors)."""
    if type(exc).__name__ != "StreamlitValueAssignmentNotAllowedError":
        return ""
    key = getattr(exc, "key", None) or (getattr(exc, "kwargs", None) or {}).get("key")
    if key:
        return str(key)
    m = _KEY_RE.search(str(exc))
    return m.group(1) if m else ""


def recover_from_value_assignment(session: Any, exc: BaseException) -> bool:
    """Drop the stray value Streamlit refused; True when the caller should rerun once."""
    key = offending_key(exc)
    if not key:
        return False
    done = list(session.get(RECOVERED_KEYS) or [])
    if key in done:
        return False  # already tried: show the message instead of looping
    try:
        if key in session:
            del session[key]
    except Exception:
        return False
    session[RECOVERED_KEYS] = done + [key]
    session["_account_control_last_recovery"] = key
    return True
