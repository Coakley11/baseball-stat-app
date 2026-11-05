"""Stable identity for drafts made in a Shared Draft room, and for leagues made from them.

Identity comes from the room, never from the roster content. Two rooms whose drafts end with the
same players stay two Library entries and two leagues; the roster fingerprint is only a similarity
hint (fantasy_league_context.find_archive_by_draft_fingerprint).

    Shared Draft room code R (6 characters, unique; rows are never deleted, so codes are not reused)
    Library entry for R, per account ...... room-<r>          (same id as shared_draft_recovery)
    League created from R ................. league:room-<r>
    An invitee's entry for league L ....... league-<L without "league:">

Existing records keep the ids they already have: a stored league id is never recomputed
(fantasy_league_identity.resolve_canonical_league_id), and an entry saved before this change is
reused for room R only when it provably came from R (its stored room code, or its league context's
source_room_code). An older entry without that proof is never matched or rewritten: at worst the
room gets a second entry, never an overwrite of another draft.
"""

from __future__ import annotations

import re
from typing import Any

ROOM_KEY_FIELD = "source_room_code"  # same field shared_draft_recovery stamps
ROOM_LEAGUE_PREFIX = "league:room-"


def shared_room_code(session: Any, room: dict[str, Any] | None) -> str:
    """The Shared Draft room code this Live Draft belongs to, or "" (a Solo Live Draft has none).

    Only real room codes count: the active Shared Draft room, the room's sync record, or a code
    stamped on the room. A Solo draft's internal draft_room_id is not a Shared Draft room."""
    room = room if isinstance(room, dict) else {}
    sync = room.get("sync") if isinstance(room.get("sync"), dict) else {}
    for candidate in (
        sync.get("room_code"),
        room.get("room_code"),
        (session.get("active_shared_draft_room_code") if hasattr(session, "get") else ""),
    ):
        code = str(candidate or "").strip().upper()
        if code and re.fullmatch(r"[A-Z0-9]{4,12}", code):
            return code
    return ""


def room_library_id(room_code: str) -> str:
    return "room-" + str(room_code or "").strip().lower()


def room_league_id(room_code: str) -> str:
    return ROOM_LEAGUE_PREFIX + str(room_code or "").strip().lower()


def league_library_id(league_id: str) -> str:
    """An invitee's Library entry for a Shared League: one per league, whatever its rosters."""
    key = re.sub(r"[^a-z0-9_-]+", "-", str(league_id or "").strip().lower().replace("league:", "", 1)).strip("-")
    return f"league-{key}" if key else ""


def _entries(session: Any) -> list[dict[str, Any]]:
    try:
        from draft_archive_state import list_draft_archives

        return [e for e in list_draft_archives(session) if isinstance(e, dict)]
    except ImportError:
        return []


def _context_for(session: Any, entry: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from fantasy_league_context import get_league_context_for_archive

        ctx = get_league_context_for_archive(session, entry)
        return ctx if isinstance(ctx, dict) else None
    except ImportError:
        return None


def find_room_library_entry(session: Any, room_code: str) -> dict[str, Any] | None:
    """This account's Library entry for room R, proven by identity only (never by content):
    1. the entry with id room-<r>; 2. an entry stamped with room code R;
    3. an older entry whose league context records source_room_code R."""
    code = str(room_code or "").strip().upper()
    if not code:
        return None
    entries = _entries(session)
    rid = room_library_id(code)
    for entry in entries:
        if str(entry.get("draft_id") or "") == rid:
            return entry
    for entry in entries:
        if str(entry.get(ROOM_KEY_FIELD) or "").strip().upper() == code:
            return entry
    for entry in entries:
        ctx = _context_for(session, entry)
        meta = (ctx or {}).get("metadata") if isinstance((ctx or {}).get("metadata"), dict) else {}
        if str(meta.get("source_room_code") or "").strip().upper() == code:
            return entry
    return None


def room_save_ids(session: Any, room_code: str) -> tuple[str, str]:
    """(Library id, league context id) for saving room R: the existing entry for R, else new ids."""
    try:
        from fantasy_league_context import context_id_for_archive
    except ImportError:  # pragma: no cover
        context_id_for_archive = lambda d: f"archive:{d}"  # type: ignore[assignment]
    existing = find_room_library_entry(session, room_code)
    if isinstance(existing, dict):
        draft_id = str(existing.get("draft_id") or "").strip()
        linked = str(existing.get("league_context_id") or "").strip()
        if linked.startswith("__ephemeral_"):
            linked = ""
        return draft_id, linked or context_id_for_archive(draft_id)
    draft_id = room_library_id(room_code)
    return draft_id, context_id_for_archive(draft_id)


def existing_room_league_id(session: Any, room_code: str) -> str:
    """The league id already given to a Shared League made from room R in this account (kept as
    stored, legacy fingerprint ids included), or ""."""
    entry = find_room_library_entry(session, room_code)
    ctx = _context_for(session, entry) if isinstance(entry, dict) else None
    if not isinstance(ctx, dict):
        return ""
    try:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE
    except ImportError:  # pragma: no cover
        CONTEXT_TYPE_REAL_LEAGUE = "real_league"  # type: ignore[assignment]
    if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return ""
    meta = ctx.get("metadata") if isinstance(ctx.get("metadata"), dict) else {}
    return str(meta.get("league_id") or ctx.get("league_id") or "").strip()


def league_for_room(session: Any, room_code: str) -> str:
    """The league id for a Shared League made from room R: the one it already has, else league:room-<r>."""
    return existing_room_league_id(session, room_code) or room_league_id(room_code)


def stamp_room(session: Any, draft_id: str, room_code: str) -> None:
    """Record room R on the Library entry (so later saves and recovery find it by identity)."""
    code = str(room_code or "").strip().upper()
    if not code or not draft_id:
        return
    try:
        from draft_archive_state import _set_archive_list, list_draft_archives
    except ImportError:
        return
    archives = list_draft_archives(session)
    changed = False
    for idx, row in enumerate(archives):
        if str(row.get("draft_id") or "") == str(draft_id) and str(row.get(ROOM_KEY_FIELD) or "").upper() != code:
            archives[idx] = {**row, ROOM_KEY_FIELD: code}
            changed = True
    if changed:
        _set_archive_list(session, archives)


def entry_for_league(session: Any, league_id: str) -> dict[str, Any] | None:
    """This account's entry already linked to Shared League L (to update, not duplicate, on re-accept)."""
    lid = str(league_id or "").strip()
    if not lid:
        return None
    target = league_library_id(lid)
    for entry in _entries(session):
        if str(entry.get("draft_id") or "") == target:
            return entry
    try:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE
    except ImportError:  # pragma: no cover
        CONTEXT_TYPE_REAL_LEAGUE = "real_league"  # type: ignore[assignment]
    for entry in _entries(session):
        ctx = _context_for(session, entry)
        if not isinstance(ctx, dict) or str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
            continue
        meta = ctx.get("metadata") if isinstance(ctx.get("metadata"), dict) else {}
        if str(meta.get("league_id") or ctx.get("league_id") or "").strip() == lid and meta.get("joined_via_invite"):
            return entry
    return None
