"""Keep the Live Draft setup form's entered values across runs where the form is not drawn.

Streamlit drops a widget's stored value at the end of a run that does not draw that widget. After
"Create Shared Draft Room" sent the page to Home (or a creation timed out), the setup form came back
with blank or default league name, team names and timer, and a retry created a room with settings
the user never chose (QA 2026-11-05). On every run this remembers the setup values currently held,
in a key Streamlit never discards, and puts back any that went missing; "Reset Setup to Defaults"
forgets them.
"""

from __future__ import annotations

from typing import Any

MEMORY_KEY = "_live_draft_setup_memory"
_PREFIXES = ("live_draft_team_name_", "live_slot_")
# Draft Mode has its own persistence (a pending value applied before the radio, the preferred next
# mode and the saved preference). Putting back an older remembered mode would override a mode the
# user just chose (QA 2026-11-05: Shared reverted to Solo), so it is never remembered here.
_NOT_REMEMBERED = frozenset({"live_draft_setup_mode", "preferred_next_draft_mode"})


def _setup_keys() -> tuple[str, ...]:
    try:
        from live_draft_state import LIVE_DRAFT_SETTINGS_KEYS

        return tuple(LIVE_DRAFT_SETTINGS_KEYS)
    except ImportError:  # pragma: no cover
        return ("live_draft_league_name", "live_draft_timer", "live_draft_picks_per_team", "live_draft_team_count")


def _is_setup_key(key: Any) -> bool:
    k = str(key)
    if k in _NOT_REMEMBERED:
        return False
    return k in _setup_keys() or k.startswith(_PREFIXES)


def remember_and_restore_live_draft_setup(session: Any) -> list[str]:
    """Put back setup values that went missing since the last run, then remember the current ones.
    Returns the keys put back. Never overwrites a value the session holds."""
    if session.get("_live_draft_setup_seeding"):
        return []
    memory = session.get(MEMORY_KEY)
    memory = dict(memory) if isinstance(memory, dict) else {}
    restored: list[str] = []
    for key, value in memory.items():
        if key not in session and _is_setup_key(key):
            session[key] = value
            restored.append(key)
    for key in list(session.keys()):
        if _is_setup_key(key):
            value = session[key]
            if value is None or (isinstance(value, str) and not value.strip()):
                continue  # a blank never replaces a remembered value
            memory[str(key)] = value
    session[MEMORY_KEY] = memory
    return restored


def forget_live_draft_setup(session: Any) -> None:
    session.pop(MEMORY_KEY, None)
