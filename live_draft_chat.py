"""Live Draft Chat — shared league messages without bumping board revision."""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo

    _EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - Windows without tzdata
    _EASTERN = timezone(timedelta(hours=-4), name="ET")

CHAT_DOC_KEY = "chat"
CHAT_SESSION_CACHE_KEY = "_live_draft_chat_cache"
CHAT_LAST_SEEN_REV_KEY = "_live_draft_chat_last_seen_rev"
CHAT_COLLAPSED_KEY = "_live_draft_chat_collapsed"
CHAT_SHOW_EARLIER_KEY = "_live_draft_chat_show_earlier"
CHAT_MAX_MESSAGES = 100
CHAT_MAX_TEXT_LEN = 400
CHAT_POLL_SEC = 2.5
CHAT_VISIBLE_LIMIT = 5
CHAT_SCHEMA_VERSION = 2

_MENTION_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9 _.'-]{0,40})")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def empty_chat_payload() -> dict[str, Any]:
    return {
        "schema_version": CHAT_SCHEMA_VERSION,
        "chat_revision": 0,
        "chat_disabled": False,
        "chat_scope": "",
        "messages": [],
    }


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
            msg_type = str(row.get("message_type") or row.get("type") or "user").strip() or "user"
            cleaned.append(
                {
                    "id": str(row.get("id") or uuid.uuid4().hex[:12]),
                    "league_id": str(row.get("league_id") or "").strip(),
                    "draft_id": str(row.get("draft_id") or "").strip(),
                    "ts": str(row.get("ts") or "").strip() or _utc_now_iso(),
                    "user_id": str(row.get("user_id") or row.get("participant_id") or "").strip(),
                    "participant_id": str(row.get("participant_id") or row.get("user_id") or "").strip(),
                    "display_name": str(row.get("display_name") or "").strip() or "Manager",
                    "team": str(row.get("team") or row.get("claimed_team") or "").strip(),
                    "claimed_team": str(row.get("claimed_team") or row.get("team") or "").strip(),
                    "text": text[:CHAT_MAX_TEXT_LEN],
                    "message_type": msg_type,
                }
            )
    base["schema_version"] = int(raw.get("schema_version") or CHAT_SCHEMA_VERSION)
    base["chat_revision"] = int(raw.get("chat_revision") or 0)
    base["chat_disabled"] = bool(raw.get("chat_disabled"))
    base["chat_scope"] = str(raw.get("chat_scope") or "").strip()
    # Stable chronological order for all clients.
    cleaned.sort(key=lambda m: (str(m.get("ts") or ""), str(m.get("id") or "")))
    base["messages"] = cleaned[-CHAT_MAX_MESSAGES:]
    return base


def canonical_chat_scope(session: dict[str, Any]) -> str:
    """Shared conversation key — room code only (same for every participant)."""
    code = _active_room_code(session)
    if not code:
        return ""
    return f"room:{code}"


def user_visible_messages(
    messages: list[dict[str, Any]],
    *,
    limit: int = CHAT_VISIBLE_LIMIT,
    include_system: bool = False,
) -> list[dict[str, Any]]:
    """Latest N user messages for the compact AIM window (system clutter hidden)."""
    filtered = []
    for msg in messages:
        if not include_system and str(msg.get("message_type") or "user") == "system":
            continue
        filtered.append(msg)
    if limit <= 0:
        return filtered
    return filtered[-int(limit) :]


def count_earlier_user_messages(messages: list[dict[str, Any]], *, visible_limit: int = CHAT_VISIBLE_LIMIT) -> int:
    user_msgs = [m for m in messages if str(m.get("message_type") or "user") != "system"]
    return max(0, len(user_msgs) - max(0, int(visible_limit)))


def author_label(message: dict[str, Any]) -> str:
    if str(message.get("message_type") or "") == "system":
        return "Draft System"
    name = str(message.get("display_name") or "").strip() or "Manager"
    team = str(message.get("claimed_team") or message.get("team") or "").strip()
    if team and team.lower() not in name.lower():
        return f"{name} ({team})"
    return name


def format_chat_timestamp(ts: str) -> str:
    """Display timestamps in Eastern Time."""
    raw = str(ts or "").strip()
    if not raw:
        return ""
    try:
        text = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        eastern = dt.astimezone(_EASTERN)
        return eastern.strftime("%I:%M %p").lstrip("0") + " ET"
    except ValueError:
        return raw[:19]


def sanitize_chat_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) > CHAT_MAX_TEXT_LEN:
        cleaned = cleaned[:CHAT_MAX_TEXT_LEN]
    return cleaned


def extract_mentions(text: str) -> list[str]:
    return [m.group(1).strip() for m in _MENTION_RE.finditer(str(text or ""))]


def message_mentions_viewer(message: dict[str, Any], session: dict[str, Any]) -> bool:
    text = str(message.get("text") or "")
    mentions = extract_mentions(text)
    if not mentions:
        return False
    _, display_name, team = _resolve_author(session)
    needles = {display_name.lower(), team.lower()}
    needles.discard("")
    for mention in mentions:
        key = mention.lower()
        if key in needles:
            return True
        for needle in needles:
            if needle and (needle in key or key in needle):
                return True
    return False


def _active_room_code(session: dict[str, Any]) -> str:
    try:
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY

        code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
    except ImportError:
        code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if code:
        return code
    try:
        from draft_room_context import resolve_shared_room_code

        return str(resolve_shared_room_code(session) or "").strip().upper()
    except ImportError:
        return ""
    except Exception:
        return ""


def _league_and_draft_ids(session: dict[str, Any]) -> tuple[str, str]:
    code = _active_room_code(session)
    # Prefer room code for both — do not invent divergent league/draft keys per account.
    return code, code


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
    if "@" in display_name:
        display_name = display_name.split("@", 1)[0].strip() or display_name
    return participant_id, display_name, team


def _is_authenticated_league_session(session: dict[str, Any]) -> bool:
    """Refuse logged-out demo workspace for authenticated league chat."""
    try:
        from suite_user import current_workspace_id

        ws = str(current_workspace_id(session) or "").strip().lower()
        if ws in {"", "local_default", "local_demo", "demo", "anonymous"}:
            # Allow multiplayer guests who still have a room code + participant.
            if not _active_room_code(session):
                return False
    except ImportError:
        pass
    try:
        from draft_room_context import is_multiplayer_draft_active

        return bool(is_multiplayer_draft_active(session))
    except ImportError:
        return False


def is_chat_commissioner(session: dict[str, Any]) -> bool:
    try:
        from draft_room_membership import is_room_host
        from draft_room_shared_state import load_shared_room_document

        code = _active_room_code(session)
        doc = load_shared_room_document(session, code) if code else None
        return bool(is_room_host(session, doc))
    except ImportError:
        return bool(session.get("_live_draft_mp_diag", {}).get("is_host"))


def chat_room_title(session: dict[str, Any]) -> str:
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        name = str(
            room.get("league_name")
            or room.get("draft_name")
            or (room.get("meta") or {}).get("league_name")
            or ""
        ).strip()
        if name:
            return name
    code = _active_room_code(session)
    return f"Room {code}" if code else "Live Draft Chat"


def unread_chat_count(session: dict[str, Any], chat: dict[str, Any] | None = None) -> int:
    payload = chat if isinstance(chat, dict) else load_live_draft_chat(session, force=False)
    rev = int(payload.get("chat_revision") or 0)
    seen = int(session.get(CHAT_LAST_SEEN_REV_KEY) or 0)
    if rev <= seen:
        return 0
    messages = list(payload.get("messages") or [])
    # Count messages after the last-seen revision window (best-effort by tail).
    return max(0, min(len(messages), rev - seen))


def mark_chat_seen(session: dict[str, Any], chat: dict[str, Any] | None = None) -> None:
    payload = chat if isinstance(chat, dict) else load_live_draft_chat(session, force=False)
    session[CHAT_LAST_SEEN_REV_KEY] = int(payload.get("chat_revision") or 0)


def load_live_draft_chat(
    session: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Return chat payload for the active shared room (same scope for every participant)."""
    code = _active_room_code(session)
    if not code:
        return empty_chat_payload()
    scope = canonical_chat_scope(session)
    cache = session.get(CHAT_SESSION_CACHE_KEY)
    if (
        not force
        and isinstance(cache, dict)
        and str(cache.get("room_code") or "").upper() == code
        and str(cache.get("chat_scope") or "") == scope
        and isinstance(cache.get("chat"), dict)
    ):
        return normalize_chat_payload(cache.get("chat"))
    doc: dict[str, Any] | None = None
    try:
        from draft_room_shared_state import get_shared_room_store, invalidate_shared_room_document_cache

        # Always read the authoritative shared store — never a per-user soft cache alone.
        if force:
            invalidate_shared_room_document_cache(session, code)
        doc = get_shared_room_store().load(code)
    except Exception:
        doc = None
    chat = normalize_chat_payload((doc or {}).get(CHAT_DOC_KEY))
    if scope and not chat.get("chat_scope"):
        chat["chat_scope"] = scope
    session[CHAT_SESSION_CACHE_KEY] = {
        "room_code": code,
        "chat_scope": scope,
        "chat": copy.deepcopy(chat),
    }
    return chat


def refresh_live_draft_chat_if_newer(session: dict[str, Any]) -> bool:
    """Pull chat from shared store. Returns True when messages changed."""
    code = _active_room_code(session)
    if not code:
        return False
    try:
        from draft_room_shared_state import get_shared_room_store, invalidate_shared_room_document_cache

        invalidate_shared_room_document_cache(session, code)
        doc = get_shared_room_store().load(code)
    except Exception:
        return False
    if not isinstance(doc, dict):
        return False
    scope = canonical_chat_scope(session)
    remote = normalize_chat_payload(doc.get(CHAT_DOC_KEY))
    if scope and not remote.get("chat_scope"):
        remote["chat_scope"] = scope
    local = normalize_chat_payload((session.get(CHAT_SESSION_CACHE_KEY) or {}).get("chat"))
    if (
        int(remote.get("chat_revision") or 0) == int(local.get("chat_revision") or 0)
        and remote.get("messages") == local.get("messages")
        and bool(remote.get("chat_disabled")) == bool(local.get("chat_disabled"))
    ):
        return False
    session[CHAT_SESSION_CACHE_KEY] = {
        "room_code": code,
        "chat_scope": scope,
        "chat": copy.deepcopy(remote),
    }
    return True


def _last_message_fingerprint(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""
    last = messages[-1]
    return f"{last.get('participant_id')}|{last.get('text')}|{str(last.get('ts') or '')[:16]}"


def _mutate_chat(
    session: dict[str, Any],
    mutator,
) -> tuple[bool, str]:
    code = _active_room_code(session)
    if not code:
        return False, "Join a shared Live Draft room to use chat."
    try:
        from draft_room_shared_state import (
            get_shared_room_store,
            invalidate_shared_room_document_cache,
        )

        store = get_shared_room_store()
    except ImportError:
        return False, "Shared draft chat is unavailable."

    last_err = "Could not update chat."
    for _attempt in range(4):
        doc = store.load(code)
        if not isinstance(doc, dict):
            return False, "Shared room could not be loaded."
        board_rev = int(doc.get("revision") or 0)
        chat = normalize_chat_payload(doc.get(CHAT_DOC_KEY))
        ok_mut, err, chat = mutator(chat)
        if not ok_mut:
            return False, err
        out = copy.deepcopy(doc)
        out[CHAT_DOC_KEY] = chat
        out["revision"] = board_rev
        try:
            ok, current = store.save_if_revision(out, expected_revision=board_rev)
        except Exception as exc:
            last_err = str(exc) or last_err
            continue
        if ok and isinstance(current, dict):
            verified = normalize_chat_payload(current.get(CHAT_DOC_KEY))
            session[CHAT_SESSION_CACHE_KEY] = {
                "room_code": code,
                "chat_scope": canonical_chat_scope(session),
                "chat": copy.deepcopy(verified),
            }
            invalidate_shared_room_document_cache(session, code)
            return True, ""
        if isinstance(current, dict):
            last_err = "Someone else updated the room — retrying…"
            continue
        last_err = "Chat not saved — try again."
    # Last resort: unconditional save with sidecar merge so chat is not lost forever.
    try:
        doc = store.load(code)
        if isinstance(doc, dict):
            chat = normalize_chat_payload(doc.get(CHAT_DOC_KEY))
            ok_mut, err, chat = mutator(chat)
            if not ok_mut:
                return False, err
            out = copy.deepcopy(doc)
            out[CHAT_DOC_KEY] = chat
            saved = store.save(out)
            verified = normalize_chat_payload((saved or out).get(CHAT_DOC_KEY))
            session[CHAT_SESSION_CACHE_KEY] = {
                "room_code": code,
                "chat_scope": canonical_chat_scope(session),
                "chat": copy.deepcopy(verified),
            }
            invalidate_shared_room_document_cache(session, code)
            return True, ""
    except Exception as exc:
        last_err = str(exc) or last_err
    return False, last_err


def append_live_draft_chat_message(
    session: dict[str, Any],
    text: str,
    *,
    message_type: str = "user",
    system_key: str | None = None,
) -> tuple[bool, str]:
    """Persist a chat message on the shared room document without bumping board revision."""
    cleaned = sanitize_chat_text(text)
    if not cleaned:
        return False, "Type a message first."
    if not _is_authenticated_league_session(session) and message_type != "system":
        return False, "Sign in to a shared Live Draft room to use chat."

    code = _active_room_code(session)
    if not code:
        return False, "Join a shared Live Draft room to use chat."

    league_id, draft_id = _league_and_draft_ids(session)
    chat_scope = canonical_chat_scope(session)
    participant_id, display_name, team = _resolve_author(session)
    msg_type = str(message_type or "user").strip() or "user"
    if msg_type == "system":
        # System clutter disabled for ordinary draft activity.
        return False, "System chat messages are disabled."

    new_message = {
        "id": uuid.uuid4().hex[:12],
        "league_id": league_id,
        "draft_id": draft_id,
        "chat_scope": chat_scope,
        "ts": _utc_now_iso(),
        "user_id": participant_id,
        "participant_id": participant_id,
        "display_name": display_name,
        "team": team,
        "claimed_team": team,
        "text": cleaned,
        "message_type": msg_type,
    }
    if system_key:
        new_message["system_key"] = str(system_key)

    def _mutator(chat: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        if chat.get("chat_disabled") and msg_type != "system":
            return False, "Chat is disabled for this league.", chat
        if chat_scope:
            chat["chat_scope"] = chat_scope
        messages = list(chat.get("messages") or [])
        if system_key:
            for existing in messages:
                if str(existing.get("system_key") or "") == str(system_key):
                    return True, "", chat  # idempotent system event
        if msg_type == "user" and messages:
            last = messages[-1]
            if (
                str(last.get("participant_id") or "") == participant_id
                and str(last.get("text") or "") == cleaned
            ):
                return False, "Duplicate message — already sent.", chat
        messages.append(new_message)
        messages.sort(key=lambda m: (str(m.get("ts") or ""), str(m.get("id") or "")))
        chat["messages"] = messages[-CHAT_MAX_MESSAGES:]
        chat["chat_revision"] = int(chat.get("chat_revision") or 0) + 1
        chat["schema_version"] = CHAT_SCHEMA_VERSION
        return True, "", chat

    return _mutate_chat(session, _mutator)


def delete_chat_message(session: dict[str, Any], message_id: str) -> tuple[bool, str]:
    if not is_chat_commissioner(session):
        return False, "Only the commissioner can delete messages."
    mid = str(message_id or "").strip()
    if not mid:
        return False, "Missing message id."

    def _mutator(chat: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        before = list(chat.get("messages") or [])
        after = [m for m in before if str(m.get("id") or "") != mid]
        if len(after) == len(before):
            return False, "Message not found.", chat
        chat["messages"] = after
        chat["chat_revision"] = int(chat.get("chat_revision") or 0) + 1
        return True, "", chat

    return _mutate_chat(session, _mutator)


def clear_system_chat_messages(session: dict[str, Any]) -> tuple[bool, str]:
    if not is_chat_commissioner(session):
        return False, "Only the commissioner can clear system messages."

    def _mutator(chat: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        before = list(chat.get("messages") or [])
        after = [m for m in before if str(m.get("message_type") or "user") != "system"]
        if len(after) == len(before):
            return True, "", chat
        chat["messages"] = after
        chat["chat_revision"] = int(chat.get("chat_revision") or 0) + 1
        return True, "", chat

    return _mutate_chat(session, _mutator)


def set_chat_disabled(session: dict[str, Any], disabled: bool) -> tuple[bool, str]:
    if not is_chat_commissioner(session):
        return False, "Only the commissioner can change chat settings."

    def _mutator(chat: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        chat["chat_disabled"] = bool(disabled)
        chat["chat_revision"] = int(chat.get("chat_revision") or 0) + 1
        return True, "", chat

    return _mutate_chat(session, _mutator)
