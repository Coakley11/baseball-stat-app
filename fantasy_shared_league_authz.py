"""Server-side authorization for every write to a Shared League document.

The app writes baseball_shared_leagues with the service-role key, which bypasses row-level
security, so the database cannot tell accounts apart: this module is the authorization. It used to
be missing: any signed-in account holding a copy of a league could push its local copy over the
shared one (rosters, settings, commissioner).

Rules, decided against the STORED document (never the caller's local copy):
- a new league may be created by any signed-in account;
- an existing league may be changed only by its commissioner, a team owner, or an account it has
  invited (so an invite can still be accepted or declined);
- a member who is not the commissioner cannot change the commissioner, the league name or the
  draft id: those keep their stored values.
Code that runs outside a Streamlit session (scripts, tests, maintenance) is not a user request
and is not checked here.
"""

from __future__ import annotations

import copy
from typing import Any, MutableMapping

COMMISSIONER_ONLY_FIELDS = ("commissioner_user_id", "league_name", "draft_id")
REFUSAL_KEY = "_shared_league_write_refused"


class SharedLeagueWriteRefused(RuntimeError):
    """The current account may not change this Shared League."""


def current_session() -> MutableMapping[str, Any] | None:
    """The Streamlit session running this code, or None outside a user request."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx(suppress_warning=True) is None:
            return None
        import streamlit as st

        return st.session_state
    except Exception:
        return None


def _identity(session: MutableMapping[str, Any]) -> tuple[str, str, str]:
    from fantasy_shared_league_startup_sync import _resolve_startup_identity

    return _resolve_startup_identity(session)


def is_league_commissioner(session: MutableMapping[str, Any], document: dict[str, Any] | None) -> bool:
    from fantasy_league_team_ownership import account_user_ids_match

    uid, _external, _workspace = _identity(session)
    stored = str((document or {}).get("commissioner_user_id") or "").strip()
    return bool(uid and stored and account_user_ids_match(stored, uid))


def is_league_member_or_invitee(session: MutableMapping[str, Any], document: dict[str, Any] | None) -> bool:
    """Commissioner, a team owner, or the subject of an invite (pending or accepted)."""
    if not isinstance(document, dict):
        return False
    if is_league_commissioner(session, document):
        return True
    from fantasy_shared_league_startup_sync import _record_matches_account

    uid, external, workspace = _identity(session)
    records: list[Any] = list((document.get("team_ownership") or {}).values()) + list(
        document.get("league_invites") or []
    )
    return any(
        isinstance(record, dict)
        and _record_matches_account(record, user_id=uid, external_id=external, workspace_id=workspace)
        for record in records
    )


def authorize_league_write(
    session: MutableMapping[str, Any] | None,
    incoming: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """The document to write, or raise SharedLeagueWriteRefused."""
    if session is None:
        return incoming
    uid, _external, _workspace = _identity(session)
    if not uid:
        raise _refuse(session, incoming, "not_signed_in")
    if not isinstance(existing, dict):
        return incoming  # creating a new league
    if not is_league_member_or_invitee(session, existing):
        raise _refuse(session, incoming, "not_a_league_member")
    if is_league_commissioner(session, existing):
        return incoming
    out = copy.deepcopy(incoming)
    for field in COMMISSIONER_ONLY_FIELDS:
        if field in existing:
            out[field] = copy.deepcopy(existing[field])
    return out


def _refuse(session: MutableMapping[str, Any], incoming: dict[str, Any], reason: str) -> SharedLeagueWriteRefused:
    league_id = str((incoming or {}).get("league_id") or "").strip()
    try:
        session[REFUSAL_KEY] = {"league_id": league_id, "reason": reason}
    except Exception:
        pass
    return SharedLeagueWriteRefused(f"shared league write refused ({reason})")
