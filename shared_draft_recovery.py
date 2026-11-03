"""Recover a completed Shared Draft into the account's Saved Draft Library from its room record.

The shared room is the authority for a multiplayer draft's picks. If the room completed but Save to
Library failed (for example a refused cloud save) or the browser was closed, the account can rebuild
its Library entry from the stored room:

- only completed rooms in which the SIGNED-IN account holds a seat are listed (account id only:
  participant key, participant user_id/account_user_id, or the room's host id; never an email,
  name or workspace, and nothing at all without a signed-in id);
- the preview and the recovery re-load and re-authorize the room on the server each time;
- the room is read, never written; no Shared League and no other account is touched;
- the entry is built by the same save path as a normal Live Draft save, for this account's own team;
- an entry that already holds this draft (same room, or same draft content) is never replaced:
  recovery stops and offers to open it.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

RECOVERY_REASON = "shared_draft_recovered"
ROOM_KEY_FIELD = "source_room_code"
RECOVERED_FLAG = "recovered_from_shared_room"
COMPLETE_STATUSES = ("complete", "completed")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def signed_in_account_id(session: Any) -> str:
    """The signed-in account's id from this session, or "" (no fallback identity)."""
    try:
        return str(session.get("_suite_auth_user_id") or session.get("_suite_cloud_user_id") or "").strip()
    except Exception:
        return ""


def _ids_match(stored: str, uid: str) -> bool:
    stored, uid = str(stored or "").strip(), str(uid or "").strip()
    if not stored or not uid:
        return False
    if stored == uid:
        return True
    try:
        from fantasy_league_team_ownership import account_user_ids_match

        return bool(account_user_ids_match(stored, uid))
    except ImportError:
        return False


def _team_of(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    return str(record.get("assigned_team") or record.get("team") or record.get("claimed_team") or "").strip()


def account_seat(document: dict[str, Any] | None, uid: str) -> dict[str, str] | None:
    """{"role", "team", "participant_id"} for this account's seat in a room (head or document)."""
    if not isinstance(document, dict) or not uid:
        return None
    participants = document.get("participants") if isinstance(document.get("participants"), dict) else {}
    host_pid = str(document.get("host_participant_id") or "").strip()
    for pid, record in participants.items():
        if not isinstance(record, dict):
            continue
        ids = (str(pid), str(record.get("user_id") or ""), str(record.get("account_user_id") or ""))
        if any(_ids_match(value, uid) for value in ids):
            role = "commissioner" if host_pid and str(pid) == host_pid else "participant"
            return {"role": role, "team": _team_of(record), "participant_id": str(pid)}
    if _ids_match(str(document.get("host_user_id") or ""), uid):
        host_record = participants.get(host_pid) if host_pid else None
        return {"role": "commissioner", "team": _team_of(host_record), "participant_id": host_pid}
    return None


def _store(store: Any = None) -> Any:
    if store is not None:
        return store
    from draft_room_shared_state import get_shared_room_store

    return get_shared_room_store()


def _room_of(document: dict[str, Any]) -> dict[str, Any]:
    room = document.get("room") if isinstance(document.get("room"), dict) else document.get("live_room")
    return room if isinstance(room, dict) else {}


def _library_entries(session: Any) -> list[dict[str, Any]]:
    try:
        from draft_archive_state import list_draft_archives

        return [e for e in list_draft_archives(session) if isinstance(e, dict)]
    except ImportError:
        return []


def room_draft_id(room_code: str) -> str:
    """The Library id of a draft recovered from a room: one per room, whatever its picks."""
    return "room-" + str(room_code or "").strip().lower()


def existing_library_entry(session: Any, room_code: str, room: dict[str, Any] | None = None, team: str = "") -> dict[str, Any] | None:
    """The entry already recovered from THIS room (stable room identity: room code or room id).
    Content alone never makes a duplicate: two rooms can produce identical picks."""
    code = str(room_code or "").strip().upper()
    if not code:
        return None
    rid = room_draft_id(code)
    for entry in _library_entries(session):
        if str(entry.get(ROOM_KEY_FIELD) or "").strip().upper() == code or str(entry.get("draft_id") or "") == rid:
            return entry
    return None


def similar_library_entry(session: Any, room: dict[str, Any] | None, team: str) -> dict[str, Any] | None:
    """An entry with identical draft content that records no room (a normal Save to Draft Library):
    possibly this draft saved earlier, possibly another room with the same picks. A hint only;
    entries recovered from another room are never matched."""
    if not isinstance(room, dict) or not team:
        return None
    candidates = [e for e in _library_entries(session) if not str(e.get(ROOM_KEY_FIELD) or "").strip()]
    if not candidates:
        return None
    try:
        from fantasy_league_context import (
            build_league_rosters_from_live_room,
            compute_save_draft_fingerprint,
            find_archive_by_draft_fingerprint,
        )

        cfg = dict(room.get("config") or {})
        fingerprint = compute_save_draft_fingerprint(
            league_rosters=build_league_rosters_from_live_room(room, team),
            config=cfg,
            fantasy_format=str(cfg.get("fantasy_format") or cfg.get("scoring_type") or ""),
        )
        if not fingerprint:
            return None
        return find_archive_by_draft_fingerprint({"draft_archive_teams": copy.deepcopy(candidates)}, fingerprint)
    except ImportError:
        return None


def list_recoverable_rooms(session: Any, *, store: Any = None, limit: int = 200) -> list[dict[str, Any]]:
    """Completed rooms this signed-in account holds a seat in, newest first. Other rooms are never
    returned (not even their names)."""
    uid = signed_in_account_id(session)
    if not uid:
        return []
    backend = _store(store)
    lister = getattr(backend, "list_completed_room_heads", None)
    if not callable(lister):
        return []
    try:
        heads = lister(limit=limit)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for head in heads or []:
        if not isinstance(head, dict):
            continue
        if str(head.get("status") or "").strip().lower() not in COMPLETE_STATUSES:
            continue
        seat = account_seat(head, uid)
        if seat is None:
            continue
        code = str(head.get("room_code") or "").strip().upper()
        out.append(
            {
                "room_code": code,
                "league_name": str(head.get("league_name") or "Shared Draft"),
                "team": seat["team"],
                "role": seat["role"],
                "updated_at": str(head.get("updated_at") or ""),
                "revision": int(head.get("revision") or 0),
                "in_library": existing_library_entry(session, code) is not None,
            }
        )
    return out


def _integrity(room: dict[str, Any], document: dict[str, Any], team: str) -> tuple[list[str], list[str]]:
    """(problems that block recovery, fields that are missing but not needed to rebuild the entry)."""
    problems: list[str] = []
    missing: list[str] = []
    status = str(room.get("status") or document.get("status") or "").strip().lower()
    if status not in COMPLETE_STATUSES:
        problems.append(f"the room is not complete (status: {status or 'unknown'})")
    try:
        from live_draft_safe_mode import is_draft_truly_complete, total_expected_picks

        expected = int(total_expected_picks(room) or 0)
        if not is_draft_truly_complete(room):
            problems.append(f"the board is not full ({len(room.get('draft_board') or [])} of {expected} picks)")
    except ImportError:
        expected = 0
    cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
    teams = [str(t).strip() for t in (room.get("teams") or cfg.get("teams") or []) if str(t).strip()]
    if not teams:
        problems.append("the room lists no teams")
    if not team:
        problems.append("your team in this room could not be determined")
    elif teams and team not in teams:
        problems.append(f"your team '{team}' is not one of the room's teams")
    seen_players: set[str] = set()
    for index, pick in enumerate(room.get("draft_board") or [], start=1):
        if not isinstance(pick, dict):
            problems.append(f"pick {index} is unreadable")
            continue
        pick_team = str(pick.get("Fantasy Team") or pick.get("Team") or "").strip()
        player = str(pick.get("Player") or pick.get("player_name") or "").strip()
        if not player:
            problems.append(f"pick {index} has no player")
        if teams and pick_team not in teams:
            problems.append(f"pick {index} belongs to an unknown team '{pick_team}'")
        key = player.lower()
        if key and key in seen_players:
            problems.append(f"{player} was picked twice")
        seen_players.add(key)
        if not str(pick.get("playerID") or pick.get("player_id") or "").strip():
            missing.append(f"pick {index} ({player or '?'}): player id")
    if not cfg:
        missing.append("draft settings (config)")
    else:
        if not (cfg.get("slots") or cfg.get("slot_instances")):
            missing.append("roster slots")
        if not (cfg.get("fantasy_format") or cfg.get("scoring_type")):
            missing.append("scoring format")
        if not cfg.get("league_name"):
            missing.append("league name")
    return problems, missing


def load_recovery_preview(session: Any, room_code: str, *, store: Any = None) -> dict[str, Any]:
    """Re-load and re-authorize one room, and describe what recovery would save. Never writes."""
    uid = signed_in_account_id(session)
    code = str(room_code or "").strip().upper()
    if not uid:
        return {"ok": False, "error": "Sign in to recover a draft."}
    try:
        document = _store(store).load(code)
    except Exception:
        document = None
    seat = account_seat(document, uid) if isinstance(document, dict) else None
    if seat is None:
        # Same answer for "no such room" and "not your room": nothing about other rooms leaks.
        return {"ok": False, "error": "No completed Shared Draft of yours was found with that code."}
    room = _room_of(document)
    problems, missing = _integrity(room, document, seat["team"])
    cfg = room.get("config") if isinstance(room.get("config"), dict) else {}
    picks = [
        {
            "pick": p.get("Pick") or p.get("pick") or index,
            "round": p.get("Round") or p.get("round") or "",
            "team": str(p.get("Fantasy Team") or p.get("Team") or ""),
            "player": str(p.get("Player") or p.get("player_name") or ""),
        }
        for index, p in enumerate(room.get("draft_board") or [], start=1)
        if isinstance(p, dict)
    ]
    existing = existing_library_entry(session, code)
    similar = None if existing else similar_library_entry(session, room, seat["team"])
    return {
        "ok": not problems,
        "room_code": code,
        "revision": int(document.get("revision") or 0),
        "role": seat["role"],
        "team": seat["team"],
        "status": str(room.get("status") or document.get("status") or ""),
        "league_name": str(cfg.get("league_name") or "Shared Draft"),
        "settings": {
            "teams": list(room.get("teams") or cfg.get("teams") or []),
            "fantasy_format": cfg.get("fantasy_format") or cfg.get("scoring_type") or "",
            "rounds": cfg.get("picks_per_team") or cfg.get("rounds") or "",
            "roster_slots": copy.deepcopy(cfg.get("slots") or {}),
        },
        "picks": picks,
        "problems": problems,
        "missing": missing,
        "existing_draft_id": str((existing or {}).get("draft_id") or ""),
        "existing_draft_name": str((existing or {}).get("draft_name") or ""),
        "similar_draft_id": str((similar or {}).get("draft_id") or ""),
        "similar_draft_name": str((similar or {}).get("draft_name") or ""),
    }


def recover_completed_shared_draft(
    st: Any,
    session: Any,
    room_code: str,
    *,
    confirmed: bool,
    expected_revision: int,
    draft_name: str = "",
    keep_alongside_similar: bool = False,
    store: Any = None,
) -> dict[str, Any]:
    """Add this account's copy of a completed Shared Draft to its Library, after explicit confirmation.

    Re-checks everything the preview showed: sign-in, seat, integrity, an unchanged room revision,
    and that no entry already holds this draft. Saves through the normal Live Draft save path and
    the account's normal workspace save (Stage B merge-on-stale). The room is only read."""
    if not confirmed:
        return {"ok": False, "error": "Confirm the recovery first."}
    preview = load_recovery_preview(session, room_code, store=store)
    if not preview.get("room_code") or preview.get("error"):
        return {"ok": False, "error": preview.get("error") or "Recovery is not available."}
    if preview["problems"]:
        return {"ok": False, "error": "This room can't be recovered: " + "; ".join(preview["problems"]) + "."}
    if int(preview["revision"]) != int(expected_revision):
        return {"ok": False, "error": "The room changed since the preview. Preview it again before recovering."}
    if preview["existing_draft_id"]:
        return {
            "ok": False,
            "already_in_library": True,
            "existing_draft_id": preview["existing_draft_id"],
            "error": f"This draft is already in your Library as \"{preview['existing_draft_name']}\". Nothing was changed.",
        }
    if preview["similar_draft_id"] and not keep_alongside_similar:
        return {
            "ok": False,
            "similar_in_library": True,
            "similar_draft_id": preview["similar_draft_id"],
            "error": (
                f"A draft with the same picks is already in your Library as \"{preview['similar_draft_name']}\". "
                "It may be this draft saved earlier. Open it, or choose to keep both. Nothing was changed."
            ),
        }
    document = _store(store).load(preview["room_code"])
    room = copy.deepcopy(_room_of(document or {}))  # a private copy: the room record is never modified
    team = preview["team"]
    label = str(draft_name or "").strip() or f"{preview['league_name']} — {team}"

    from draft_archive_state import _set_archive_list, list_draft_archives
    from fantasy_league_context import save_live_draft_league_context

    before = copy.deepcopy(list_draft_archives(session))
    contexts_before = copy.deepcopy(session.get("fantasy_league_context_state"))
    rid = room_draft_id(preview["room_code"])
    entry, _context = save_live_draft_league_context(
        session, room, my_team_name=team, draft_name=label, save_only=True, draft_id=rid
    )
    draft_id = str((entry or {}).get("draft_id") or "")
    if not draft_id or any(str(e.get("draft_id") or "") == draft_id for e in before):
        # The save path matched an entry by content after all: never replace it. Put back exactly
        # what was there (archives and league contexts).
        _set_archive_list(session, before)
        if contexts_before is None:
            session.pop("fantasy_league_context_state", None)
        else:
            session["fantasy_league_context_state"] = contexts_before
        return {"ok": False, "already_in_library": True, "existing_draft_id": draft_id, "error": "This draft is already in your Library. Nothing was changed."}
    archives = list_draft_archives(session)
    for index, row in enumerate(archives):
        if str(row.get("draft_id") or "") == draft_id:
            stamped = dict(row)
            stamped[ROOM_KEY_FIELD] = preview["room_code"]
            stamped[RECOVERED_FLAG] = True
            stamped["recovered_at"] = _now()
            stamped["recovered_role"] = preview["role"]
            archives[index] = stamped
            break
    _set_archive_list(session, archives)
    # This confirmed recovery re-adds this room's entry: lift a deletion marker on the room's own
    # id only (an earlier recovered copy the account deleted). No other marker is touched.
    from draft_archive_state import DELETED_DRAFT_ARCHIVE_IDS_KEY

    markers = [str(x) for x in (session.get(DELETED_DRAFT_ARCHIVE_IDS_KEY) or [])]
    if rid in markers:
        session[DELETED_DRAFT_ARCHIVE_IDS_KEY] = [x for x in markers if x != rid]

    from draft_archive_ui import _persist_archive, _persist_failure_message

    saved = _persist_archive(session, st, reason=RECOVERY_REASON, entry={**(entry or {}), ROOM_KEY_FIELD: preview["room_code"]})
    if not saved:
        return {
            "ok": False,
            "kept_in_session": True,
            "draft_id": draft_id,
            "error": _persist_failure_message(session),
        }
    return {"ok": True, "draft_id": draft_id, "draft_name": label, "team": team}
