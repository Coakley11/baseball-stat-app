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
    from fantasy_shared_league_startup_sync import _record_matches_account, session_auth_email

    uid, external, workspace = _identity(session)
    records: list[Any] = list((document.get("team_ownership") or {}).values()) + list(
        document.get("league_invites") or []
    )
    return any(
        isinstance(record, dict)
        and _record_matches_account(
            record, user_id=uid, external_id=external, workspace_id=workspace, email=session_auth_email(session)
        )
        for record in records
    )


LOAD_FOUND = "found"
LOAD_MISSING = "missing"
LOAD_ERROR = "error"


def checked_load(league_id: str, store: Any = None) -> tuple[str, dict[str, Any] | None]:
    """(found | missing | error, document). The stores' load() returns None both for "no such
    league" and for a failed request, and an authorization decision must not mistake one for the
    other."""
    lid = str(league_id or "").strip()
    if not lid:
        return LOAD_MISSING, None
    if store is None:
        from fantasy_shared_league_store import get_shared_league_store

        store = get_shared_league_store()
    loader = getattr(store, "load_checked", None)
    if callable(loader):
        try:
            result = loader(lid)
        except Exception:
            return LOAD_ERROR, None
        if isinstance(result, tuple) and len(result) == 2 and result[0] in (LOAD_FOUND, LOAD_MISSING, LOAD_ERROR):
            return result
    try:
        doc = store.load(lid)
    except Exception:
        return LOAD_ERROR, None
    return (LOAD_FOUND, doc) if isinstance(doc, dict) else (LOAD_MISSING, None)


def authorize_league_write(
    session: MutableMapping[str, Any] | None,
    incoming: dict[str, Any],
    existing: dict[str, Any] | None,
    *,
    store: Any = None,
) -> dict[str, Any]:
    """The document to write, or raise SharedLeagueWriteRefused."""
    if session is None:
        return incoming
    uid, _external, _workspace = _identity(session)
    if not uid:
        raise _refuse(session, incoming, "not_signed_in")
    if not isinstance(existing, dict):
        # "No stored league" must be confirmed: a failed load is not permission to create, and the
        # store's own save may still find and update the existing row.
        status, _stored = checked_load(str((incoming or {}).get("league_id") or ""), store)
        if status == LOAD_ERROR:
            raise _refuse(session, incoming, "league_unverifiable")
        if status == LOAD_FOUND:
            # The caller built its document without the stored league (its read failed), so it
            # would drop other members' proposals, ownership and invites. Write nothing.
            raise _refuse(session, incoming, "stored_league_not_merged")
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


# --- Reads of an existing league copy (owner decision 2026-11-02) ---------------------------------
# A copy of a Shared League stored in an account's workspace is shown, and refreshed from the
# shared league, only for a member or invitee of that league. A copy that fails is HIDDEN and not
# refreshed, but never deleted, tombstoned or rewritten: what to do with stored copies is the
# owner's separate clean-up decision.
COPY_NOT_SHARED = "not_shared"  # not a Shared League copy (local league, mock, simulator): unchanged
COPY_ALLOWED = "allowed"
COPY_REFUSED = "refused"  # the stored league does not list this account
COPY_UNVERIFIED = "unverified"  # the stored league could not be read: neither shown nor refreshed

_COPY_DECISION_TTL_S = 12.0
_COPY_DECISIONS: dict[tuple[str, str, str], tuple[float, str]] = {}


def may_read_league(session: MutableMapping[str, Any], document: dict[str, Any] | None) -> bool:
    """A signed-in member or invitee of this stored league."""
    uid, _external, _workspace = _identity(session)
    return bool(uid) and is_league_member_or_invitee(session, document)


def league_copy_access(session: MutableMapping[str, Any] | None, context: dict[str, Any] | None) -> str:
    if session is None or not isinstance(context, dict):
        return COPY_NOT_SHARED
    try:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE
        from fantasy_league_identity import resolve_canonical_league_id
        from fantasy_shared_league_store import _anonymous_guest
    except ImportError:
        return COPY_NOT_SHARED
    if str(context.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return COPY_NOT_SHARED
    league_id = str(resolve_canonical_league_id(context) or "").strip()
    if not league_id or _anonymous_guest():
        return COPY_NOT_SHARED
    uid, external, _workspace = _identity(session)
    key = (league_id, uid, external)
    import time

    now = time.monotonic()
    hit = _COPY_DECISIONS.get(key)
    if hit is not None and now - hit[0] < _COPY_DECISION_TTL_S:
        return hit[1]
    status, doc = checked_load(league_id)
    if status == LOAD_MISSING:
        decision = COPY_NOT_SHARED
    elif status == LOAD_ERROR:
        decision = COPY_UNVERIFIED
    else:
        decision = COPY_ALLOWED if may_read_league(session, doc) else COPY_REFUSED
    _COPY_DECISIONS[key] = (now, decision)
    return decision


def league_copy_hidden(session: MutableMapping[str, Any] | None, context: dict[str, Any] | None) -> bool:
    """True when this stored league copy must not be shown to (or refreshed for) this account."""
    return league_copy_access(session, context) in (COPY_REFUSED, COPY_UNVERIFIED)


def clear_league_copy_decisions() -> None:
    _COPY_DECISIONS.clear()


def _refuse(session: MutableMapping[str, Any], incoming: dict[str, Any], reason: str) -> SharedLeagueWriteRefused:
    league_id = str((incoming or {}).get("league_id") or "").strip()
    try:
        session[REFUSAL_KEY] = {"league_id": league_id, "reason": reason}
    except Exception:
        pass
    return SharedLeagueWriteRefused(f"shared league write refused ({reason})")
