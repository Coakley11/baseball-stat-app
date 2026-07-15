"""Live Draft Chat Phase 1 — shared messages without bumping board revision."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

CHAT_DOC_KEY = "chat"
CHAT_SESSION_CACHE_KEY = "_live_draft_chat_cache"
CHAT_MAX_MESSAGES = 100
CHAT_MAX_TEXT_LEN = 400
CHAT_POLL_SEC = 2.5


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def empty_chat_payload() -> dict[str, Any]:
    return {"schema_version": 1, "chat_revision": 0, "messages": []}


def normalize_chat_payload(raw: Any) -> dict[str, Any]:
    base = empty_chat_payload()
    if not isinstance(raw, dict):
        return base
    messages = raw.get("messages")
    cleaned: list[dict[str, Any]] = []
    if isinstance(messages, list):
        for row in messages:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            cleaned.append(
                {
                    "id": str(row.get("id") or uuid.uuid4().hex[:12]),
                    "ts": str(row.get("ts") or "").strip() or _utc_now_iso(),
                    "participant_id": str(row.get("participant_id") or "").strip(),
                    "display_name": str(row.get("display_name") or "").strip() or "Manager",
                    "team": str(row.get("team") or "").strip(),
                    "text": text[:CHAT_MAX_TEXT_LEN],
                }
            )
    base["chat_revision"] = int(raw.get("chat_revision") or 0)
    base["messages"] = cleaned[-CHAT_MAX_MESSAGES:]
    return base


def author_label(message: dict[str, Any]) -> str:
    name = str(message.get("display_name") or "").strip() or "Manager"
    team = str(message.get("team") or "").strip()
    if team and team.lower() not in name.lower():
        return f"{name} ({team})"
    return name


def format_chat_timestamp(ts: str) -> str:
    raw = str(ts or "").strip()
    if not raw:
        return ""
    try:
        text = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return local.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return raw[:19]


def _active_room_code(session: dict[str, Any]) -> str:
    try:
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY

        return str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    except ImportError:
        return str(session.get("active_shared_draft_room_code") or "").strip().upper()


def _resolve_author(session: dict[str, Any]) -> tuple[str, str, str]:
    participant_id = ""
    display_name = "Manager"
    team = ""
    try:
        from draft_room_participant_state import active_participant_team, resolve_participant_id

        participant_id = str(resolve_participant_id(session) or "").strip()
        team = str(active_participant_team(session) or "").strip()
    except ImportError:
        pass
    try:
        from draft_room_membership import participant_display_name

        display_name = str(participant_display_name(session) or "").strip() or display_name
    except ImportError:
        pass
    if not team:
        room = session.get("live_draft_room")
        if isinstance(room, dict):
            team = str(room.get("your_team") or "").strip()
    # Prefer a short username over a long email when possible.
    if "@" in display_name:
        display_name = display_name.split("@", 1)[0].strip() or display_name
    return participant_id, display_name, team


def load_live_draft_chat(
    session: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Return chat payload for the active shared room (cached when unchanged)."""
    code = _active_room_code(session)
    if not code:
        return empty_chat_payload()
    cache = session.get(CHAT_SESSION_CACHE_KEY)
    if (
        not force
        and isinstance(cache, dict)
        and str(cache.get("room_code") or "").upper() == code
        and isinstance(cache.get("chat"), dict)
    ):
        return normalize_chat_payload(cache.get("chat"))
    doc: dict[str, Any] | None = None
    try:
        from draft_room_shared_state import get_shared_room_store, load_shared_room_document

        doc = load_shared_room_document(session, code)
        if not isinstance(doc, dict):
            doc = get_shared_room_store().load(code)
    except Exception:
        doc = None
    chat = normalize_chat_payload((doc or {}).get(CHAT_DOC_KEY))
    session[CHAT_SESSION_CACHE_KEY] = {"room_code": code, "chat": copy.deepcopy(chat)}
    return chat


def refresh_live_draft_chat_if_newer(session: dict[str, Any]) -> bool:
    """Pull chat from shared store. Returns True when messages changed."""
    code = _active_room_code(session)
    if not code:
        return False
    try:
        from draft_room_shared_state import get_shared_room_store

        doc = get_shared_room_store().load(code)
    except Exception:
        return False
    if not isinstance(doc, dict):
        return False
    remote = normalize_chat_payload(doc.get(CHAT_DOC_KEY))
    local = normalize_chat_payload((session.get(CHAT_SESSION_CACHE_KEY) or {}).get("chat"))
    if (
        int(remote.get("chat_revision") or 0) == int(local.get("chat_revision") or 0)
        and remote.get("messages") == local.get("messages")
    ):
        return False
    session[CHAT_SESSION_CACHE_KEY] = {"room_code": code, "chat": copy.deepcopy(remote)}
    return True


def append_live_draft_chat_message(session: dict[str, Any], text: str) -> tuple[bool, str]:
    """Persist a chat message on the shared room document without bumping board revision."""
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return False, "Type a message first."
    if len(cleaned) > CHAT_MAX_TEXT_LEN:
        cleaned = cleaned[:CHAT_MAX_TEXT_LEN]
    code = _active_room_code(session)
    if not code:
        return False, "Join a shared Live Draft room to use chat."
    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_shared_state import (
            invalidate_shared_room_document_cache,
            get_shared_room_store,
        )

        if not is_multiplayer_draft_active(session):
            return False, "Chat is available in shared Live Draft rooms."
        store = get_shared_room_store()
    except ImportError:
        return False, "Shared draft chat is unavailable."

    participant_id, display_name, team = _resolve_author(session)
    new_message = {
        "id": uuid.uuid4().hex[:12],
        "ts": _utc_now_iso(),
        "participant_id": participant_id,
        "display_name": display_name,
        "team": team,
        "text": cleaned,
    }

    last_err = "Could not send message."
    for _attempt in range(4):
        doc = store.load(code)
        if not isinstance(doc, dict):
            return False, "Shared room could not be loaded."
        board_rev = int(doc.get("revision") or 0)
        chat = normalize_chat_payload(doc.get(CHAT_DOC_KEY))
        messages = list(chat.get("messages") or [])
        messages.append(new_message)
        chat["messages"] = messages[-CHAT_MAX_MESSAGES:]
        chat["chat_revision"] = int(chat.get("chat_revision") or 0) + 1
        out = copy.deepcopy(doc)
        out[CHAT_DOC_KEY] = chat
        # Keep board revision unchanged so chat never trips pick/timer sync.
        out["revision"] = board_rev
        try:
            ok, current = store.save_if_revision(out, expected_revision=board_rev)
        except Exception as exc:
            last_err = str(exc) or last_err
            continue
        if ok and isinstance(current, dict):
            verified = normalize_chat_payload(current.get(CHAT_DOC_KEY))
            ids = {str(m.get("id") or "") for m in (verified.get("messages") or [])}
            if new_message["id"] not in ids:
                # Concurrent overwrite without our message — merge and retry.
                last_err = "Message collided — retrying…"
                continue
            session[CHAT_SESSION_CACHE_KEY] = {"room_code": code, "chat": copy.deepcopy(verified)}
            invalidate_shared_room_document_cache(session, code)
            return True, ""
        if isinstance(current, dict):
            last_err = "Someone else updated the room — retrying…"
            continue
        last_err = "Message not saved — try again."
    return False, last_err
