"""Server-side authorization for every write to a Shared League document.

The app writes baseball_shared_leagues with the service-role key, which bypasses row-level
security, so the database cannot tell accounts apart: this module is the authorization.

Rules, decided against the STORED document (never the caller's local copy):

- Every Shared League action needs a verified sign-in (sign-in enabled, and this session signed
  in with an Auth user id). With sign-in off the app runs as one configured account and no
  Shared League read, write, join, claim or invite is allowed (owner decision 2026-11-05).
- A new league may be created by a signed-in account, which becomes its commissioner. A league
  made from a Shared Draft room may be created only by that room's stored host.
- An existing league may be changed only by its commissioner, a team owner, or an account with a
  pending or accepted invite. Revoked, declined and expired invites confer nothing.
- The commissioner is the stored ``commissioner_user_id``. Nothing in a member's own copy can
  make them commissioner.
- A member who is not the commissioner may change only their own part of the league:
  * their own pending invite, to accepted or declined;
  * team ownership records that name themselves, for a team nobody else holds (one team);
  * trade proposals they are a party to (new proposals from their own team);
  * their own team's roster, plus both rosters of a trade they accept in this write;
  * their own team's lineup snapshots in periods that are still open (upcoming);
  * new league activity entries.
  Every other field keeps its stored value (default deny).

Code that runs outside a Streamlit session (scripts, tests, maintenance) is not a user request
and is not checked here.
"""

from __future__ import annotations

import copy
import json
import time
from typing import Any, Iterable, MutableMapping

# Kept for compatibility: the fields a non-commissioner could never change. Default deny now covers
# these and every other league-wide field (see MEMBER_WRITABLE_FIELDS).
COMMISSIONER_ONLY_FIELDS = ("commissioner_user_id", "league_name", "draft_id")
MEMBER_WRITABLE_FIELDS = frozenset(
    {"league_invites", "team_ownership", "trade_proposals", "league_rosters", "season_ledger",
     "league_activity", "revision", "updated_at", "league_id"}
)
REFUSAL_KEY = "_shared_league_write_refused"
PINNED_KEY = "_shared_league_write_pinned"

INVITE_PENDING = "pending"
INVITE_ACCEPTED = "accepted"
INVITE_DECLINED = "declined"
LIVE_INVITE_STATUSES = frozenset({INVITE_PENDING, INVITE_ACCEPTED})

TRADE_PENDING = "pending"
TRADE_ACCEPTED = "accepted"
TRADE_SYSTEM_STATUSES = frozenset({"stale", "expired"})  # invalidation, never execution

ROOM_LEAGUE_PREFIX = "league:room-"


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


# --- Identity --------------------------------------------------------------------------------------


def sign_in_enabled() -> bool:
    try:
        from suite_auth import is_auth_enabled

        return bool(is_auth_enabled())
    except ImportError:
        return True


def verified_account_ids(session: MutableMapping[str, Any] | None) -> list[str]:
    """This session's own account ids, only when it is a verified sign-in: sign-in enabled, the
    session signed in, and an Auth user id present. The Auth id and the suite account id differ
    in the hosted app (rooms use the Auth id; league records the suite id), so both are returned.
    Never an email prefix, a workspace or the deployment's fallback account; never with sign-in off.
    """
    if not isinstance(session, MutableMapping):
        return []
    try:
        from suite_auth import AUTH_SESSION_KEY, AUTH_USER_ID_KEY
    except ImportError:
        AUTH_SESSION_KEY, AUTH_USER_ID_KEY = "_suite_auth_session", "_suite_auth_user_id"
    auth_id = str(session.get(AUTH_USER_ID_KEY) or "").strip()
    if not sign_in_enabled():
        # Sign-in off: never an account in a user request (owner decision 2026-11-05). Scripts and
        # tests are not user requests (as in authorize_league_write): they keep the session's ids.
        if current_session() is not None:
            return []
        ids = [v for v in (auth_id, str(session.get("_suite_cloud_user_id") or "").strip()) if v]
        return list(dict.fromkeys(ids))
    if not session.get(AUTH_SESSION_KEY) or not auth_id:
        return []
    ids = [auth_id]
    cloud = str(session.get("_suite_cloud_user_id") or "").strip()
    if cloud and cloud not in ids:
        ids.append(cloud)
    return ids


# Old name, used by other modules and tests: now verified-only.
_session_account_ids = verified_account_ids


def shared_league_sign_in_error(session: MutableMapping[str, Any] | None) -> str:
    """'' when this user request may use Shared Leagues; otherwise the message to show.
    Outside a user request (scripts, tests) there is nothing to check, as in authorize_league_write."""
    live = current_session()
    if live is None:
        return ""
    if verified_account_ids(session if isinstance(session, MutableMapping) and session else live):
        return ""
    if not sign_in_enabled():
        return "Shared Leagues need a signed-in account. Sign-in is off in this app, so this is unavailable."
    return "Sign in to use Shared Leagues."


def _identity(session: MutableMapping[str, Any]) -> tuple[str, str, str]:
    """(user id, external id, workspace) for record matching; empty unless verified."""
    ids = verified_account_ids(session)
    if not ids:
        return "", "", ""
    from fantasy_shared_league_startup_sync import _resolve_startup_identity

    _uid, external, workspace = _resolve_startup_identity(session)
    return ids[0], external, workspace


def _ids_match(stored: str, ids: Iterable[str]) -> bool:
    from fantasy_league_team_ownership import account_user_ids_match

    stored = str(stored or "").strip()
    return bool(stored) and any(account_user_ids_match(stored, uid) for uid in ids if uid)


def _record_is_session(session: MutableMapping[str, Any], record: Any) -> bool:
    """True when a team-ownership record or invite names this signed-in account. A record that
    carries an account id must match that id; usernames, workspaces and emails count only for
    records that have no account id (finding 7)."""
    if not isinstance(record, dict):
        return False
    ids = verified_account_ids(session)
    if not ids:
        return False
    stored = str(record.get("user_id") or record.get("account_user_id") or record.get("invitee_user_id") or "").strip()
    if stored:
        return _ids_match(stored, ids)
    from fantasy_shared_league_startup_sync import _record_matches_account, session_auth_email

    _uid, external, workspace = _identity(session)
    email = session_auth_email(session)
    return any(
        _record_matches_account(record, user_id=uid, external_id=external, workspace_id=workspace, email=email)
        for uid in ids
    )


def _record_has_identity(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    return any(
        str(record.get(key) or "").strip()
        for key in ("user_id", "account_user_id", "external_id", "email", "workspace_id", "invitee_user_id")
    )


# --- Commissioner and membership ---------------------------------------------------------------------


def stored_commissioner_id(document: dict[str, Any] | None) -> str:
    return str((document or {}).get("commissioner_user_id") or "").strip()


def commissioner_ids(document: dict[str, Any] | None) -> list[str]:
    """Who the STORED league's commissioner is. The stored ``commissioner_user_id`` when it is
    set. A league made from a Shared Draft room that never recorded one (stored before
    2026-11-05) has the stored room's host as commissioner: the policy for every room league
    (owner decision 2026-11-05), read from the room and never written. No commissioner otherwise:
    nothing is guessed from team ownership or a local copy."""
    explicit = stored_commissioner_id(document)
    if explicit:
        return [explicit]
    code = _room_code_of(document)
    if not code:
        return []
    status, room = load_stored_room(code)
    return room_host_ids(room) if status == LOAD_FOUND else []


def is_league_commissioner(session: MutableMapping[str, Any], document: dict[str, Any] | None) -> bool:
    """The stored league's commissioner, matched against this verified sign-in only."""
    ids = verified_account_ids(session)
    return bool(ids) and any(_ids_match(commissioner, ids) for commissioner in commissioner_ids(document))


def _invite_is_live(invite: Any) -> bool:
    return isinstance(invite, dict) and str(invite.get("status") or "").strip().lower() in LIVE_INVITE_STATUSES


def is_league_member_or_invitee(session: MutableMapping[str, Any], document: dict[str, Any] | None) -> bool:
    """Commissioner, a team owner, or the subject of a pending or accepted invite."""
    if not isinstance(document, dict) or not verified_account_ids(session):
        return False
    if is_league_commissioner(session, document):
        return True
    owners = [r for r in (document.get("team_ownership") or {}).values() if isinstance(r, dict)]
    invites = [i for i in (document.get("league_invites") or []) if _invite_is_live(i)]
    return any(_record_is_session(session, record) for record in owners + invites)


def owned_teams(session: MutableMapping[str, Any], document: dict[str, Any] | None) -> set[str]:
    """Teams whose stored ownership record names this signed-in account."""
    out: set[str] = set()
    for team, record in ((document or {}).get("team_ownership") or {}).items():
        if _record_is_session(session, record):
            out.add(str(team))
    return out


# --- Stored commissioner lookups for the UI (league data, shared by every session) ------------------

_COMMISSIONER_TTL_S = 12.0
_COMMISSIONER_CACHE: dict[str, tuple[float, str, tuple[str, ...]]] = {}


def stored_commissioner(league_id: str, *, store: Any = None, fresh: bool = False) -> tuple[str, list[str]]:
    """(found | missing | error, commissioner ids) for a stored league (see commissioner_ids).
    Cached briefly by league id (it holds no per-user data); writes always decide against a fresh
    read in authorize_league_write."""
    lid = str(league_id or "").strip()
    if not lid:
        return LOAD_MISSING, []
    now = time.monotonic()
    hit = _COMMISSIONER_CACHE.get(lid)
    if not fresh and store is None and hit is not None and now - hit[0] < _COMMISSIONER_TTL_S:
        return hit[1], list(hit[2])
    status, doc = checked_load(lid, store)
    commissioners = commissioner_ids(doc) if status == LOAD_FOUND else []
    if store is None:
        _COMMISSIONER_CACHE[lid] = (now, status, tuple(commissioners))
    return status, commissioners


def clear_stored_commissioner_cache(league_id: str = "") -> None:
    if league_id:
        _COMMISSIONER_CACHE.pop(str(league_id).strip(), None)
    else:
        _COMMISSIONER_CACHE.clear()


# --- Loads ----------------------------------------------------------------------------------------

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


# --- Shared Draft room host (league creation from a room) ------------------------------------------


def room_host_ids(room_document: dict[str, Any] | None) -> list[str]:
    """Every host identifier the STORED room records (participant id and account id)."""
    if not isinstance(room_document, dict):
        return []
    out: list[str] = []
    for key in ("commissioner_participant_id", "host_participant_id", "host_user_id"):
        value = str(room_document.get(key) or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def session_is_room_host(session: MutableMapping[str, Any], room_document: dict[str, Any] | None) -> bool:
    ids = verified_account_ids(session)
    return bool(ids) and any(_ids_match(host, ids) for host in room_host_ids(room_document))


def _room_code_of(document: dict[str, Any] | None) -> str:
    doc = document or {}
    code = str(doc.get("source_room_code") or (doc.get("metadata") or {}).get("source_room_code") or "").strip()
    if not code:
        league_id = str(doc.get("league_id") or "").strip()
        if league_id.startswith(ROOM_LEAGUE_PREFIX):
            code = league_id[len(ROOM_LEAGUE_PREFIX):]
    return code.upper()


def load_stored_room(room_code: str) -> tuple[str, dict[str, Any] | None]:
    """(found | missing | error, stored room document) by join code."""
    code = str(room_code or "").strip().upper()
    if not code:
        return LOAD_MISSING, None
    try:
        from draft_room_shared_state import load_shared_room

        doc = load_shared_room(code)
    except Exception:
        return LOAD_ERROR, None
    return (LOAD_FOUND, doc) if isinstance(doc, dict) else (LOAD_MISSING, None)


def room_participant_ids(room_document: dict[str, Any] | None) -> list[str]:
    """Every seated participant id the STORED room records."""
    if not isinstance(room_document, dict):
        return []
    out: list[str] = []
    for key in ("participants", "joined_participants"):
        block = room_document.get(key)
        if isinstance(block, dict):
            for pid, meta in block.items():
                for value in (pid, *(((meta or {}).get(k) for k in ("user_id", "auth_user_id", "participant_id")) if isinstance(meta, dict) else ())):
                    value = str(value or "").strip()
                    if value and value not in out:
                        out.append(value)
    return out


_ROOM_LIVE = frozenset({"in_progress"})
_ROOM_DONE = frozenset({"complete"})


def room_pick_write_refusal(
    session: MutableMapping[str, Any] | None,
    stored_room: dict[str, Any] | None,
    live_room: dict[str, Any] | None,
) -> str:
    """'' when this account may commit ``live_room`` over the stored Shared Draft room; otherwise
    a reason (security review 2026-11-05, R-6). The writer must be seated in the stored room or be
    its host. A participant who is not the host may move the draft only from in progress to
    complete (the final pick); pausing, resuming, ending and other status changes are the host's.
    Outside a user request (scripts, tests) there is nothing to check."""
    if current_session() is None or not isinstance(stored_room, dict):
        return ""
    ids = verified_account_ids(session)
    if not ids:
        return "sign_in_required"
    if session_is_room_host(session, stored_room):
        return ""
    if not any(_ids_match(pid, ids) for pid in room_participant_ids(stored_room)):
        return "not_seated"
    stored_inner = stored_room.get("room") if isinstance(stored_room.get("room"), dict) else {}
    old_status = str(stored_inner.get("status") or stored_room.get("status") or "").strip()
    new_status = str((live_room or {}).get("status") or old_status).strip()
    if new_status != old_status and not (old_status in _ROOM_LIVE and new_status in _ROOM_DONE):
        return "status_host_only"
    return ""


ROOM_HOST_UNKNOWN = "room_host_unknown"
NOT_ROOM_HOST = "not_room_host"


def room_league_creation_error(session: MutableMapping[str, Any], room_code: str) -> str:
    """'' when this signed-in account is the stored host of ``room_code``; otherwise a reason:
    not_room_host, room_host_unknown (an older room with no recorded host: never guessed),
    room_unverifiable (the room could not be read) or room_missing."""
    status, room = load_stored_room(room_code)
    if status == LOAD_ERROR:
        return "room_unverifiable"
    if status == LOAD_MISSING:
        return "room_missing"
    if not room_host_ids(room):
        return ROOM_HOST_UNKNOWN
    return "" if session_is_room_host(session, room) else NOT_ROOM_HOST


# --- Write authorization --------------------------------------------------------------------------


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
    ids = verified_account_ids(session)
    if not ids:
        raise _refuse(session, incoming, "sign_in_required")
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
        return _authorize_create(session, incoming, ids)
    if not is_league_member_or_invitee(session, existing):
        raise _refuse(session, incoming, "not_a_league_member")
    if is_league_commissioner(session, existing):
        return incoming
    return _member_write(session, incoming, existing)


def _authorize_create(session: MutableMapping[str, Any], incoming: dict[str, Any], ids: list[str]) -> dict[str, Any]:
    out = copy.deepcopy(incoming)
    room_code = _room_code_of(out)
    if room_code:
        reason = room_league_creation_error(session, room_code)
        if reason:
            raise _refuse(session, incoming, reason)
    commissioner = stored_commissioner_id(out)
    if commissioner and not _ids_match(commissioner, ids):
        # A new league's commissioner is the account creating it, never someone else.
        raise _refuse(session, incoming, "commissioner_must_be_creator")
    if not commissioner:
        out["commissioner_user_id"] = ids[-1]  # the suite account id when known (league records use it)
    return out


def _member_write(session: MutableMapping[str, Any], incoming: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pinned: list[str] = []
    for key, value in existing.items():
        if key not in MEMBER_WRITABLE_FIELDS:
            out[key] = copy.deepcopy(value)
    for key in incoming:
        if key not in MEMBER_WRITABLE_FIELDS and _canon(incoming.get(key)) != _canon(existing.get(key)):
            pinned.append(key)
    for key in ("revision", "updated_at", "league_id"):
        if key in incoming:
            out[key] = copy.deepcopy(incoming[key])
        elif key in existing:
            out[key] = copy.deepcopy(existing[key])
    out.setdefault("commissioner_user_id", "")

    own_before = owned_teams(session, existing)
    out["league_invites"], dropped = _member_invites(session, existing.get("league_invites"), incoming.get("league_invites"))
    if dropped:
        pinned.append("league_invites")
    out["team_ownership"], dropped = _member_ownership(session, existing.get("team_ownership"), incoming.get("team_ownership"), own_before)
    if dropped:
        pinned.append("team_ownership")
    own_after = owned_teams(session, out)
    proposals, trade_teams, dropped = _member_trades(existing.get("trade_proposals"), incoming.get("trade_proposals"), own_after)
    if "trade_proposals" in existing or "trade_proposals" in incoming:
        out["trade_proposals"] = proposals
    if dropped:
        pinned.append("trade_proposals")
    rosters, dropped = _member_rosters(existing.get("league_rosters"), incoming.get("league_rosters"), own_after | trade_teams)
    if "league_rosters" in existing or "league_rosters" in incoming:
        out["league_rosters"] = rosters
    if dropped:
        pinned.append("league_rosters")
    ledger, dropped = _member_ledger(existing.get("season_ledger"), incoming.get("season_ledger"), own_after)
    if ledger is not None:
        out["season_ledger"] = ledger
    if dropped:
        pinned.append("season_ledger")
    out["league_activity"] = _member_activity(existing.get("league_activity"), incoming.get("league_activity"))
    if pinned:
        try:
            session[PINNED_KEY] = {"league_id": str(existing.get("league_id") or ""), "fields": sorted(set(pinned))}
        except Exception:
            pass
    return out


def _canon(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [dict(x) for x in (value or []) if isinstance(x, dict)] if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


_INVITE_IMMUTABLE = ("invite_id", "invitee_user_id", "invitee_external_id", "invitee_workspace_id",
                     "invited_by_user_id", "invited_by_display", "invited_by_username", "league_id",
                     "created_at", "invitee_email")


def _member_invites(session: MutableMapping[str, Any], existing: Any, incoming: Any) -> tuple[list[dict[str, Any]], bool]:
    """Stored invites; a member may only answer their own pending invite (accept or decline)."""
    result = _as_list(existing)
    index = {str(x.get("invite_id") or ""): i for i, x in enumerate(result)}
    dropped = False
    for inv in _as_list(incoming):
        iid = str(inv.get("invite_id") or "")
        if iid not in index:
            dropped = True  # a new invite: commissioner only
            continue
        current = result[index[iid]]
        if _canon(inv) == _canon(current):
            continue
        new_status = str(inv.get("status") or "").strip().lower()
        if (
            str(current.get("status") or "").strip().lower() == INVITE_PENDING
            and new_status in (INVITE_ACCEPTED, INVITE_DECLINED)
            and _record_is_session(session, current)
        ):
            answered = copy.deepcopy(inv)
            for key in _INVITE_IMMUTABLE:
                if key in current:
                    answered[key] = copy.deepcopy(current[key])
                else:
                    answered.pop(key, None)
            result[index[iid]] = answered
        else:
            dropped = True
    return result, dropped


def _member_ownership(
    session: MutableMapping[str, Any], existing: Any, incoming: Any, own_before: set[str]
) -> tuple[dict[str, Any], bool]:
    """Stored ownership; a member may write records naming themselves, for a team nobody else
    holds, and may hold one team."""
    stored = _as_dict(existing)
    result = copy.deepcopy(stored)
    dropped = False
    for team, record in _as_dict(incoming).items():
        current = stored.get(team)
        if _canon(record) == _canon(current):
            continue
        if not _record_is_session(session, record):
            dropped = True  # a record for someone else
            continue
        if _record_has_identity(current) and not _record_is_session(session, current):
            dropped = True  # someone else's team
            continue
        if own_before and str(team) not in own_before:
            dropped = True  # already owns another team in this league
            continue
        result[team] = copy.deepcopy(record)
    for team in stored:
        if team not in _as_dict(incoming) and incoming is not None:
            dropped = True  # removal attempts keep the stored record
    return result, dropped


def _member_trades(existing: Any, incoming: Any, own: set[str]) -> tuple[list[dict[str, Any]], set[str], bool]:
    """Stored proposals; a member may add proposals from their own team and update proposals they
    are a party to. Returns the teams whose rosters an accepted trade in this write may change."""
    result = _as_list(existing)
    index = {str(x.get("proposal_id") or ""): i for i, x in enumerate(result)}
    trade_teams: set[str] = set()
    dropped = False
    for prop in _as_list(incoming):
        pid = str(prop.get("proposal_id") or "")
        current = result[index[pid]] if pid in index else None
        if current is None:
            if pid and str(prop.get("proposer_team") or "") in own and str(prop.get("status") or "") == TRADE_PENDING:
                result.append(copy.deepcopy(prop))
                index[pid] = len(result) - 1
            else:
                dropped = True
            continue
        if _canon(prop) == _canon(current):
            continue
        parties = {str(current.get("proposer_team") or ""), str(current.get("recipient_team") or "")}
        old_status = str(current.get("status") or "")
        new_status = str(prop.get("status") or "")
        system = old_status == TRADE_PENDING and new_status in TRADE_SYSTEM_STATUSES
        if not (parties & own) and not system:
            dropped = True
            continue
        updated = copy.deepcopy(prop)
        for key in ("proposal_id", "proposer_team", "recipient_team"):
            updated[key] = copy.deepcopy(current.get(key))
        result[index[pid]] = updated
        if (
            old_status != TRADE_ACCEPTED
            and new_status == TRADE_ACCEPTED
            and str(current.get("recipient_team") or "") in own
        ):
            trade_teams |= {p for p in parties if p}
    return result, trade_teams, dropped


def _member_rosters(existing: Any, incoming: Any, allowed: set[str]) -> tuple[dict[str, Any], bool]:
    stored = _as_dict(existing)
    result = copy.deepcopy(stored)
    dropped = False
    incoming_rosters = _as_dict(incoming)
    for team, roster in incoming_rosters.items():
        if _canon(roster) == _canon(stored.get(team)):
            continue
        if str(team) in allowed:
            result[team] = copy.deepcopy(roster)
        else:
            dropped = True
    return result, dropped


def _member_ledger(existing: Any, incoming: Any, own: set[str]) -> tuple[dict[str, Any] | None, bool]:
    """Stored ledger; a member may set their own team's lineup in periods still upcoming.
    The calendar, results and finalizations are the commissioner's."""
    if not isinstance(existing, dict) or not isinstance(existing.get("periods"), dict):
        return (copy.deepcopy(existing) if isinstance(existing, dict) else None), isinstance(incoming, dict) and bool(incoming)
    result = copy.deepcopy(existing)
    if not isinstance(incoming, dict) or not isinstance(incoming.get("periods"), dict):
        return result, False
    try:
        from fantasy_season_ledger import period_status
    except ImportError:
        period_status = None  # type: ignore[assignment]
    dropped = False
    for pid, period in result["periods"].items():
        theirs = incoming["periods"].get(pid)
        if not isinstance(period, dict) or not isinstance(theirs, dict):
            continue
        open_period = not str(period.get("finalized_at") or "").strip() and theirs.get("start") == period.get("start")
        if open_period and period_status is not None:
            open_period = period_status(period) == "upcoming"
        lineups = period.setdefault("lineups", {})
        for team, snap in (theirs.get("lineups") or {}).items():
            if _canon(snap) == _canon(lineups.get(team)):
                continue
            if open_period and str(team) in own and isinstance(snap, dict):
                lineups[team] = copy.deepcopy(snap)
            else:
                dropped = True
        for key in theirs:
            if key != "lineups" and _canon(theirs.get(key)) != _canon(period.get(key)):
                dropped = True
    for key in incoming:
        if key != "periods" and _canon(incoming.get(key)) != _canon(existing.get(key)):
            dropped = True
    return result, dropped


def _member_activity(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    """Activity is append-only: stored entries stay as they are; new entries are added."""
    result = _as_list(existing)
    seen = {_canon(x) for x in result}
    for entry in _as_list(incoming):
        key = _canon(entry)
        if key not in seen:
            result.append(copy.deepcopy(entry))
            seen.add(key)
    return result


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


def _separate_accounts() -> bool:
    """True when sign-in is enabled (hosted). With sign-in off the app runs as its one configured
    account; its local copies are shown as local data and never refreshed from or written to a
    Shared League (see may_read_league)."""
    return sign_in_enabled()


def may_read_league(session: MutableMapping[str, Any], document: dict[str, Any] | None) -> bool:
    """A verified signed-in member or invitee of this stored league. Never with sign-in off in a
    user request. Scripts and tests with sign-in off run as the one local account (not a user
    request, as in authorize_league_write); with sign-in on the membership check always applies."""
    if not sign_in_enabled():
        return current_session() is None
    return bool(verified_account_ids(session)) and is_league_member_or_invitee(session, document)


def league_copy_access(session: MutableMapping[str, Any] | None, context: dict[str, Any] | None) -> str:
    if session is None or not isinstance(context, dict) or not _separate_accounts():
        return COPY_NOT_SHARED
    try:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE
        from fantasy_league_identity import resolve_canonical_league_id
    except ImportError:
        return COPY_NOT_SHARED
    if str(context.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return COPY_NOT_SHARED
    league_id = str(resolve_canonical_league_id(context) or "").strip()
    if not league_id:
        return COPY_NOT_SHARED
    # A signed-out guest has no account id, so may_read_league refuses it below: never an exemption.
    uid, external, _workspace = _identity(session)
    key = (league_id, uid, external)
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
    _COMMISSIONER_CACHE.clear()


def _refuse(session: MutableMapping[str, Any], incoming: dict[str, Any], reason: str) -> SharedLeagueWriteRefused:
    league_id = str((incoming or {}).get("league_id") or "").strip()
    try:
        session[REFUSAL_KEY] = {"league_id": league_id, "reason": reason}
    except Exception:
        pass
    return SharedLeagueWriteRefused(f"shared league write refused ({reason})")
