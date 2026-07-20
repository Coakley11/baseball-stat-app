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
CHAT_STATUS_DOC_KEY = "_live_draft_chat_status_doc"
CHAT_LAST_SEEN_REV_KEY = "_live_draft_chat_last_seen_rev"
CHAT_LAST_SEEN_IDS_KEY = "_live_draft_chat_last_seen_ids"
CHAT_COLLAPSED_KEY = "_live_draft_chat_collapsed"
CHAT_SHOW_EARLIER_KEY = "_live_draft_chat_show_earlier"
CHAT_REPLY_TO_KEY = "_live_draft_chat_reply_to"
CHAT_MAX_MESSAGES = 100
CHAT_MAX_TEXT_LEN = 400
CHAT_POLL_SEC = 2.5
CHAT_VISIBLE_LIMIT = 5
CHAT_SCHEMA_VERSION = 3

VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"
MSG_TYPE_USER = "user"
MSG_TYPE_SYSTEM = "system"
MSG_TYPE_PRIVATE_REPLY = "private_reply"

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


def _normalize_message_row(row: dict[str, Any]) -> dict[str, Any] | None:
    text = str(row.get("text") or row.get("body") or "").strip()
    if not text:
        return None
    msg_type = str(row.get("message_type") or row.get("type") or MSG_TYPE_USER).strip() or MSG_TYPE_USER
    visibility = str(row.get("visibility") or "").strip().lower()
    if msg_type == MSG_TYPE_PRIVATE_REPLY:
        visibility = VISIBILITY_PRIVATE
    elif not visibility:
        visibility = VISIBILITY_PUBLIC
    sender = str(
        row.get("sender_participant_id")
        or row.get("participant_id")
        or row.get("user_id")
        or ""
    ).strip()
    recipient = str(row.get("recipient_participant_id") or "").strip()
    reply_to = str(row.get("reply_to_message_id") or "").strip()
    preview = str(row.get("reply_to_preview") or "").strip()[:CHAT_MAX_TEXT_LEN]
    reply_name = str(row.get("reply_to_display_name") or "").strip()
    out = {
        "id": str(row.get("id") or row.get("message_id") or uuid.uuid4().hex[:12]),
        "message_id": str(row.get("message_id") or row.get("id") or "").strip(),
        "client_message_id": str(row.get("client_message_id") or "").strip(),
        "league_id": str(row.get("league_id") or "").strip(),
        "draft_id": str(row.get("draft_id") or "").strip(),
        "room_id": str(row.get("room_id") or row.get("league_id") or "").strip(),
        "room_generation": str(row.get("room_generation") or "").strip(),
        "ts": str(row.get("ts") or row.get("created_at") or "").strip() or _utc_now_iso(),
        "created_at": str(row.get("created_at") or row.get("ts") or "").strip() or _utc_now_iso(),
        "user_id": sender,
        "participant_id": sender,
        "sender_participant_id": sender,
        "recipient_participant_id": recipient,
        "display_name": str(row.get("display_name") or "").strip() or "Manager",
        "team": str(row.get("team") or row.get("claimed_team") or "").strip(),
        "claimed_team": str(row.get("claimed_team") or row.get("team") or "").strip(),
        "text": text[:CHAT_MAX_TEXT_LEN],
        "body": text[:CHAT_MAX_TEXT_LEN],
        "message_type": msg_type,
        "visibility": visibility,
        "reply_to_message_id": reply_to,
        "reply_to_preview": preview,
        "reply_to_display_name": reply_name,
    }
    if not out["message_id"]:
        out["message_id"] = out["id"]
    return out


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
            normalized = _normalize_message_row(row)
            if normalized:
                cleaned.append(normalized)
    base["schema_version"] = int(raw.get("schema_version") or CHAT_SCHEMA_VERSION)
    base["chat_revision"] = int(raw.get("chat_revision") or 0)
    base["chat_disabled"] = bool(raw.get("chat_disabled"))
    base["chat_scope"] = str(raw.get("chat_scope") or "").strip()
    # Preserve store append order (send order). Do not sort by ts/id — same-second
    # timestamps would reorder messages across clients and break transcript history.
    base["messages"] = cleaned[-CHAT_MAX_MESSAGES:]
    return base


def participant_may_view_message(message: dict[str, Any], participant_id: str) -> bool:
    """Authoritative private visibility — by canonical participant id only."""
    if not isinstance(message, dict):
        return False
    visibility = str(message.get("visibility") or VISIBILITY_PUBLIC).strip().lower()
    msg_type = str(message.get("message_type") or MSG_TYPE_USER).strip()
    if visibility != VISIBILITY_PRIVATE and msg_type != MSG_TYPE_PRIVATE_REPLY:
        return True
    pid = str(participant_id or "").strip()
    if not pid:
        return False
    sender = str(
        message.get("sender_participant_id")
        or message.get("participant_id")
        or message.get("user_id")
        or ""
    ).strip()
    recipient = str(message.get("recipient_participant_id") or "").strip()
    return pid == sender or pid == recipient


def filter_messages_for_participant(
    messages: list[dict[str, Any]],
    participant_id: str,
) -> list[dict[str, Any]]:
    """Return only messages the participant is allowed to retrieve."""
    return [m for m in messages if participant_may_view_message(m, participant_id)]


def query_visible_chat_messages(
    session: dict[str, Any],
    *,
    force: bool = True,
) -> list[dict[str, Any]]:
    """Authoritative chat query — returns only messages this participant may retrieve.

    Private replies are filtered in the backend load path before the payload is
    cached or returned. Callers must use this (or ``load_live_draft_chat``) and
    must not read raw ``doc["chat"]`` for display.
    """
    chat = load_live_draft_chat(session, force=force)
    return list(chat.get("messages") or [])


def _room_generation(session: dict[str, Any]) -> str:
    code = _active_room_code(session)
    if not code:
        return ""
    try:
        from draft_room_shared_state import get_shared_room_store

        doc = get_shared_room_store().load(code)
    except Exception:
        return ""
    if not isinstance(doc, dict):
        return ""
    for key in ("room_generation", "generation", "room_gen"):
        val = str(doc.get(key) or "").strip()
        if val:
            return val
    room = doc.get("room")
    if isinstance(room, dict):
        for key in ("room_generation", "generation"):
            val = str(room.get(key) or "").strip()
            if val:
                return val
    return ""


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
    participant_id: str = "",
) -> list[dict[str, Any]]:
    """Latest N user messages for the compact AIM window (system clutter hidden)."""
    scoped = (
        filter_messages_for_participant(messages, participant_id)
        if participant_id
        else list(messages)
    )
    filtered = []
    for msg in scoped:
        msg_type = str(msg.get("message_type") or MSG_TYPE_USER)
        if not include_system and msg_type == MSG_TYPE_SYSTEM:
            continue
        filtered.append(msg)
    if limit <= 0:
        return filtered
    return filtered[-int(limit) :]


def count_earlier_user_messages(
    messages: list[dict[str, Any]],
    *,
    visible_limit: int = CHAT_VISIBLE_LIMIT,
    participant_id: str = "",
) -> int:
    scoped = (
        filter_messages_for_participant(messages, participant_id)
        if participant_id
        else list(messages)
    )
    user_msgs = [
        m
        for m in scoped
        if str(m.get("message_type") or MSG_TYPE_USER) != MSG_TYPE_SYSTEM
    ]
    return max(0, len(user_msgs) - max(0, int(visible_limit)))


def author_label(message: dict[str, Any]) -> str:
    if str(message.get("message_type") or "") == MSG_TYPE_SYSTEM:
        return "Draft System"
    name = str(message.get("display_name") or "").strip() or "Manager"
    team = str(message.get("claimed_team") or message.get("team") or "").strip()
    if team and team.lower() not in name.lower():
        return f"{name} ({team})"
    return name


def private_reply_label(message: dict[str, Any]) -> str:
    a = str(message.get("reply_to_display_name") or "").strip() or "Manager"
    b = str(message.get("display_name") or "").strip() or "Manager"
    # Prefer sender ↔ recipient display: original author first when available.
    return f"Private reply · {a} ↔ {b}"


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
        from draft_room_participant_state import (
            ACTIVE_PARTICIPANT_TEAM_KEY,
            active_participant_team,
            resolve_participant_id,
        )

        participant_id = str(resolve_participant_id(session) or "").strip()
        # Prefer session-cached team so chat polls never pull full shared_room_json.
        team = str(
            session.get(ACTIVE_PARTICIPANT_TEAM_KEY)
            or session.get("room_your_team")
            or ""
        ).strip()
        if not team:
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


def _viewer_participant_id(session: dict[str, Any]) -> str:
    """Participant id only — must not load the full shared room (chat poll path)."""
    try:
        from draft_room_participant_state import resolve_participant_id

        return str(resolve_participant_id(session) or "").strip()
    except ImportError:
        return str(session.get("draft_room_participant_id") or "").strip()


def _chat_for_viewer(chat: dict[str, Any], participant_id: str) -> dict[str, Any]:
    """Strip unauthorized private messages before session cache / UI."""
    out = copy.deepcopy(chat) if isinstance(chat, dict) else empty_chat_payload()
    raw_messages = list(out.get("messages") or [])
    out["messages"] = filter_messages_for_participant(raw_messages, participant_id)
    return out


def unread_chat_count(session: dict[str, Any], chat: dict[str, Any] | None = None) -> int:
    """Unread among messages visible to the viewer; private replies count for recipient only."""
    payload = chat if isinstance(chat, dict) else load_live_draft_chat(session, force=False)
    viewer = _viewer_participant_id(session)
    messages = filter_messages_for_participant(list(payload.get("messages") or []), viewer)
    seen_ids = session.get(CHAT_LAST_SEEN_IDS_KEY)
    if isinstance(seen_ids, (list, set, tuple)):
        seen = {str(x) for x in seen_ids}
        count = 0
        for msg in messages:
            mid = str(msg.get("id") or msg.get("message_id") or "")
            if not mid or mid in seen:
                continue
            sender = str(
                msg.get("sender_participant_id")
                or msg.get("participant_id")
                or ""
            ).strip()
            # Own sends never increase unread (including private replies you wrote).
            if viewer and sender == viewer:
                continue
            count += 1
        return count
    # Legacy revision window fallback.
    rev = int(payload.get("chat_revision") or 0)
    seen_rev = int(session.get(CHAT_LAST_SEEN_REV_KEY) or 0)
    if rev <= seen_rev:
        return 0
    return max(0, min(len(messages), rev - seen_rev))


def mark_chat_seen(session: dict[str, Any], chat: dict[str, Any] | None = None) -> None:
    payload = chat if isinstance(chat, dict) else load_live_draft_chat(session, force=False)
    session[CHAT_LAST_SEEN_REV_KEY] = int(payload.get("chat_revision") or 0)
    viewer = _viewer_participant_id(session)
    messages = filter_messages_for_participant(list(payload.get("messages") or []), viewer)
    session[CHAT_LAST_SEEN_IDS_KEY] = [
        str(m.get("id") or m.get("message_id") or "")
        for m in messages
        if str(m.get("id") or m.get("message_id") or "")
    ]


def _load_chat_sidecar_document(session: dict[str, Any], code: str) -> dict[str, Any] | None:
    """Load chat + revision only — never the full shared_room_json blob."""
    try:
        from draft_room_shared_state import get_shared_room_store
    except ImportError:
        return None
    store = get_shared_room_store()
    sidecar = None
    if hasattr(store, "load_chat_sidecar"):
        try:
            sidecar = store.load_chat_sidecar(code)
        except Exception:
            sidecar = None
    if isinstance(sidecar, dict):
        return sidecar
    # Fallback for older stores — still prefer not to invalidate soft cache.
    try:
        doc = store.load(code)
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    return {
        "room_code": code,
        "revision": int(doc.get("revision") or 0),
        "chat": doc.get("chat") if isinstance(doc.get("chat"), dict) else {},
        "_egress_kind": "full_room_fallback",
    }


def load_live_draft_chat(
    session: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Return chat payload filtered to the current participant's authorized messages."""
    code = _active_room_code(session)
    if not code:
        return empty_chat_payload()
    scope = canonical_chat_scope(session)
    viewer = _viewer_participant_id(session)
    cache = session.get(CHAT_SESSION_CACHE_KEY)
    if (
        not force
        and isinstance(cache, dict)
        and str(cache.get("room_code") or "").upper() == code
        and str(cache.get("chat_scope") or "") == scope
        and str(cache.get("viewer_participant_id") or "") == viewer
        and isinstance(cache.get("chat"), dict)
    ):
        return normalize_chat_payload(cache.get("chat"))
    sidecar = _load_chat_sidecar_document(session, code)
    chat_raw = (sidecar or {}).get("chat") if isinstance(sidecar, dict) else None
    chat = normalize_chat_payload(chat_raw)
    if scope and not chat.get("chat_scope"):
        chat["chat_scope"] = scope
    visible = _chat_for_viewer(chat, viewer)
    session[CHAT_SESSION_CACHE_KEY] = {
        "room_code": code,
        "chat_scope": scope,
        "viewer_participant_id": viewer,
        "chat": copy.deepcopy(visible),
    }
    if isinstance(sidecar, dict):
        session[CHAT_STATUS_DOC_KEY] = {
            "room_code": code,
            "revision": int(sidecar.get("revision") or 0),
            "host_user_id": str(sidecar.get("host_user_id") or ""),
            "host_participant_id": str(sidecar.get("host_participant_id") or ""),
            "joined_participants": copy.deepcopy(sidecar.get("joined_participants") or {}),
            "participants": copy.deepcopy(sidecar.get("participants") or {}),
            "room": session.get("live_draft_room")
            if isinstance(session.get("live_draft_room"), dict)
            else {},
        }
    return visible


def refresh_live_draft_chat_if_newer(session: dict[str, Any]) -> bool:
    """Pull chat sidecar from shared store. Returns True when visible messages changed."""
    code = _active_room_code(session)
    if not code:
        return False
    sidecar = _load_chat_sidecar_document(session, code)
    if not isinstance(sidecar, dict):
        return False
    scope = canonical_chat_scope(session)
    viewer = _viewer_participant_id(session)
    remote_full = normalize_chat_payload(sidecar.get(CHAT_DOC_KEY) or sidecar.get("chat"))
    if scope and not remote_full.get("chat_scope"):
        remote_full["chat_scope"] = scope
    remote = _chat_for_viewer(remote_full, viewer)
    local = normalize_chat_payload((session.get(CHAT_SESSION_CACHE_KEY) or {}).get("chat"))
    unchanged = (
        int(remote.get("chat_revision") or 0) == int(local.get("chat_revision") or 0)
        and remote.get("messages") == local.get("messages")
        and bool(remote.get("chat_disabled")) == bool(local.get("chat_disabled"))
    )
    # Always stamp cache after the sidecar GET so load_live_draft_chat(force=False)
    # in the same refresh cycle does not issue a second Supabase read.
    session[CHAT_SESSION_CACHE_KEY] = {
        "room_code": code,
        "chat_scope": scope,
        "viewer_participant_id": viewer,
        "chat": copy.deepcopy(remote),
    }
    # Lightweight membership from the same sidecar — chat status must not full-load.
    session[CHAT_STATUS_DOC_KEY] = {
        "room_code": code,
        "revision": int(sidecar.get("revision") or 0),
        "host_user_id": str(sidecar.get("host_user_id") or ""),
        "host_participant_id": str(sidecar.get("host_participant_id") or ""),
        "joined_participants": copy.deepcopy(sidecar.get("joined_participants") or {}),
        "participants": copy.deepcopy(sidecar.get("participants") or {}),
        "room": session.get("live_draft_room")
        if isinstance(session.get("live_draft_room"), dict)
        else {},
    }
    if unchanged:
        return False
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
            viewer = _viewer_participant_id(session)
            visible = _chat_for_viewer(verified, viewer)
            session[CHAT_SESSION_CACHE_KEY] = {
                "room_code": code,
                "chat_scope": canonical_chat_scope(session),
                "viewer_participant_id": viewer,
                "chat": copy.deepcopy(visible),
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
            viewer = _viewer_participant_id(session)
            visible = _chat_for_viewer(verified, viewer)
            session[CHAT_SESSION_CACHE_KEY] = {
                "room_code": code,
                "chat_scope": canonical_chat_scope(session),
                "viewer_participant_id": viewer,
                "chat": copy.deepcopy(visible),
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
        "message_id": "",
        "client_message_id": "",
        "league_id": league_id,
        "draft_id": draft_id,
        "room_id": league_id,
        "room_generation": _room_generation(session),
        "chat_scope": chat_scope,
        "ts": _utc_now_iso(),
        "created_at": _utc_now_iso(),
        "user_id": participant_id,
        "participant_id": participant_id,
        "sender_participant_id": participant_id,
        "recipient_participant_id": "",
        "display_name": display_name,
        "team": team,
        "claimed_team": team,
        "text": cleaned,
        "body": cleaned,
        "message_type": msg_type,
        "visibility": VISIBILITY_PUBLIC,
    }
    new_message["message_id"] = new_message["id"]
    if system_key:
        new_message["system_key"] = str(system_key)

    def _mutator(chat: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        if chat.get("chat_disabled") and msg_type != MSG_TYPE_SYSTEM:
            return False, "Chat is disabled for this league.", chat
        if chat_scope:
            chat["chat_scope"] = chat_scope
        messages = list(chat.get("messages") or [])
        if system_key:
            for existing in messages:
                if str(existing.get("system_key") or "") == str(system_key):
                    return True, "", chat  # idempotent system event
        if msg_type == MSG_TYPE_USER and messages:
            last = messages[-1]
            if (
                str(last.get("participant_id") or "") == participant_id
                and str(last.get("text") or "") == cleaned
            ):
                return False, "Duplicate message — already sent.", chat
        messages.append(new_message)
        chat["messages"] = messages[-CHAT_MAX_MESSAGES:]
        chat["chat_revision"] = int(chat.get("chat_revision") or 0) + 1
        chat["schema_version"] = CHAT_SCHEMA_VERSION
        return True, "", chat

    return _mutate_chat(session, _mutator)


def _participant_still_in_room(session: dict[str, Any], participant_id: str) -> bool:
    pid = str(participant_id or "").strip()
    if not pid:
        return False
    code = _active_room_code(session)
    if not code:
        return False
    try:
        from draft_room_shared_state import load_shared_room

        doc = load_shared_room(code)
    except Exception:
        return False
    if not isinstance(doc, dict):
        return False
    # Commissioner / host counts as in-room.
    for key in ("commissioner_participant_id", "host_participant_id", "host_user_id"):
        if str(doc.get(key) or "").strip() == pid:
            return True
    participants = doc.get("participants") or doc.get("member_ids") or []
    if isinstance(participants, dict):
        if pid in participants:
            return True
        for row in participants.values():
            if isinstance(row, dict) and str(
                row.get("participant_id") or row.get("user_id") or ""
            ).strip() == pid:
                return True
    elif isinstance(participants, list):
        for row in participants:
            if isinstance(row, str) and row.strip() == pid:
                return True
            if isinstance(row, dict) and str(
                row.get("participant_id") or row.get("user_id") or ""
            ).strip() == pid:
                return True
    seats = doc.get("team_claims") or doc.get("claimed_teams") or {}
    if isinstance(seats, dict):
        for owner in seats.values():
            if str(owner or "").strip() == pid:
                return True
            if isinstance(owner, dict) and str(
                owner.get("participant_id") or owner.get("user_id") or ""
            ).strip() == pid:
                return True
    # Message authors already in this room's chat count as belonging for reply targets.
    chat = normalize_chat_payload(doc.get(CHAT_DOC_KEY))
    for msg in chat.get("messages") or []:
        if str(msg.get("sender_participant_id") or msg.get("participant_id") or "").strip() == pid:
            return True
    return False


def find_chat_message_in_room(
    session: dict[str, Any],
    message_id: str,
    *,
    enforce_viewer_access: bool = True,
) -> dict[str, Any] | None:
    """Load a message from the room store for reply validation / preview.

    When ``enforce_viewer_access`` is True (default), private messages the
    current participant may not view are treated as not found — callers cannot
    retrieve unauthorized private rows through this API.
    """
    mid = str(message_id or "").strip()
    if not mid:
        return None
    code = _active_room_code(session)
    if not code:
        return None
    try:
        from draft_room_shared_state import get_shared_room_store

        doc = get_shared_room_store().load(code)
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    chat = normalize_chat_payload(doc.get(CHAT_DOC_KEY))
    found: dict[str, Any] | None = None
    for msg in chat.get("messages") or []:
        if str(msg.get("id") or msg.get("message_id") or "") == mid:
            # Must belong to this room/draft scope.
            msg_room = str(msg.get("room_id") or msg.get("league_id") or msg.get("draft_id") or "").strip().upper()
            if msg_room and msg_room != code:
                return None
            found = msg
            break
    if found is None:
        return None
    if enforce_viewer_access:
        viewer = _viewer_participant_id(session)
        if not participant_may_view_message(found, viewer):
            return None
    return found

def append_private_reply(
    session: dict[str, Any],
    *,
    reply_to_message_id: str,
    text: str,
    client_message_id: str = "",
) -> tuple[bool, str]:
    """Persist a private reply visible only to sender and original message author."""
    cleaned = sanitize_chat_text(text)
    if not cleaned:
        return False, "Type a message first."
    if not _is_authenticated_league_session(session):
        return False, "Sign in to a shared Live Draft room to use chat."
    code = _active_room_code(session)
    if not code:
        return False, "Join a shared Live Draft room to use chat."

    original = find_chat_message_in_room(session, reply_to_message_id)
    if not isinstance(original, dict):
        return False, "Original message not found in this room."

    sender_id, display_name, team = _resolve_author(session)
    if not sender_id:
        return False, "Missing participant identity."
    if not _participant_still_in_room(session, sender_id):
        return False, "You are not a participant in this room."

    # Cannot reply to a private message you cannot view.
    if not participant_may_view_message(original, sender_id):
        return False, "You cannot reply to that message."

    if str(original.get("message_type") or MSG_TYPE_USER) == MSG_TYPE_SYSTEM:
        return False, "You cannot reply to system messages."

    recipient_id = str(
        original.get("sender_participant_id")
        or original.get("participant_id")
        or original.get("user_id")
        or ""
    ).strip()
    if not recipient_id:
        return False, "Original sender is unknown."
    if recipient_id == sender_id:
        return False, "You cannot privately reply to your own message."
    if not _participant_still_in_room(session, recipient_id):
        return False, "Original sender is no longer in this room."

    league_id, draft_id = _league_and_draft_ids(session)
    chat_scope = canonical_chat_scope(session)
    client_key = str(client_message_id or "").strip() or uuid.uuid4().hex
    reply_name = str(original.get("display_name") or "").strip() or "Manager"
    preview = str(original.get("text") or original.get("body") or "").strip()[:CHAT_MAX_TEXT_LEN]

    new_message = {
        "id": uuid.uuid4().hex[:12],
        "message_id": "",
        "client_message_id": client_key,
        "league_id": league_id,
        "draft_id": draft_id,
        "room_id": league_id,
        "room_generation": _room_generation(session),
        "chat_scope": chat_scope,
        "ts": _utc_now_iso(),
        "created_at": _utc_now_iso(),
        "user_id": sender_id,
        "participant_id": sender_id,
        "sender_participant_id": sender_id,
        "recipient_participant_id": recipient_id,
        "display_name": display_name,
        "team": team,
        "claimed_team": team,
        "text": cleaned,
        "body": cleaned,
        "message_type": MSG_TYPE_PRIVATE_REPLY,
        "visibility": VISIBILITY_PRIVATE,
        "reply_to_message_id": str(original.get("id") or original.get("message_id") or ""),
        "reply_to_preview": preview,
        "reply_to_display_name": reply_name,
    }
    new_message["message_id"] = new_message["id"]

    def _mutator(chat: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        if chat.get("chat_disabled"):
            return False, "Chat is disabled for this league.", chat
        if chat_scope:
            chat["chat_scope"] = chat_scope
        messages = list(chat.get("messages") or [])
        # Idempotency: reuse same client_message_id → return existing (no duplicate).
        for existing in messages:
            if client_key and str(existing.get("client_message_id") or "") == client_key:
                return True, "", chat
        # Re-validate original still present in this room payload.
        orig_id = str(original.get("id") or "")
        found = any(str(m.get("id") or "") == orig_id for m in messages)
        if not found:
            return False, "Original message not found in this room.", chat
        messages.append(new_message)
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
