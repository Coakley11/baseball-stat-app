"""Live Draft Room setup mode — solo vs shared multiplayer."""

from __future__ import annotations

from typing import Any

LIVE_DRAFT_SETUP_MODE_KEY = "live_draft_setup_mode"
SETUP_MODE_SOLO = "solo"
SETUP_MODE_SHARED = "shared_multiplayer"
DRAFT_SETUP_MODE_CONFIG_KEY = "draft_setup_mode"


def normalize_setup_mode(mode: str | None) -> str:
    raw = str(mode or "").strip().lower()
    if raw in (SETUP_MODE_SHARED, "multiplayer", "shared"):
        return SETUP_MODE_SHARED
    return SETUP_MODE_SOLO


def get_live_draft_setup_mode(session: dict[str, Any], *, room: dict[str, Any] | None = None) -> str:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if isinstance(live, dict):
        cfg = live.get("config") or {}
        stored = str(cfg.get(DRAFT_SETUP_MODE_CONFIG_KEY) or "").strip()
        if stored:
            return normalize_setup_mode(stored)
    return normalize_setup_mode(session.get(LIVE_DRAFT_SETUP_MODE_KEY))


def set_live_draft_setup_mode(session: dict[str, Any], mode: str) -> str:
    normalized = normalize_setup_mode(mode)
    session[LIVE_DRAFT_SETUP_MODE_KEY] = normalized
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        cfg = dict(room.get("config") or {})
        cfg[DRAFT_SETUP_MODE_CONFIG_KEY] = normalized
        room["config"] = cfg
    return normalized


def is_solo_draft_mode(session: dict[str, Any], *, room: dict[str, Any] | None = None) -> bool:
    try:
        from draft_room_context import is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            return False
    except ImportError:
        pass
    return get_live_draft_setup_mode(session, room=room) == SETUP_MODE_SOLO


def is_shared_multiplayer_intent(session: dict[str, Any], *, room: dict[str, Any] | None = None) -> bool:
    return get_live_draft_setup_mode(session, room=room) == SETUP_MODE_SHARED


def shared_room_code(session: dict[str, Any]) -> str:
    try:
        from draft_room_context import resolve_shared_room_code

        return str(resolve_shared_room_code(session) or "").strip().upper()
    except ImportError:
        return str(session.get("active_shared_draft_room_code") or "").strip().upper()


def shared_room_ready_for_start(session: dict[str, Any]) -> bool:
    if not shared_room_code(session):
        return False
    room = session.get("live_draft_room")
    return isinstance(room, dict)


def can_start_live_draft(session: dict[str, Any]) -> tuple[bool, str]:
    if is_shared_multiplayer_intent(session):
        if not shared_room_ready_for_start(session):
            return (
                False,
                "Create the shared draft room first — a 6-character room code is required before starting.",
            )
        room = session.get("live_draft_room")
        if isinstance(room, dict) and str(room.get("status") or "") not in ("not_started", "in_progress", "paused"):
            return False, "Draft room is not ready to start."
        return True, ""
    return True, ""


def stamp_room_setup_mode(room: dict[str, Any], session: dict[str, Any]) -> None:
    mode = get_live_draft_setup_mode(session)
    cfg = dict(room.get("config") or {})
    cfg[DRAFT_SETUP_MODE_CONFIG_KEY] = mode
    room["config"] = cfg


def start_prepared_shared_room(session: dict[str, Any], st_obj: Any) -> dict[str, Any]:
    """Start an already-prepared not_started shared room without rebuilding the pool."""
    result: dict[str, Any] = {"handled": False, "ok": False, "error": ""}
    if not is_shared_multiplayer_intent(session):
        return result
    code = shared_room_code(session)
    room = session.get("live_draft_room")
    if not code or not isinstance(room, dict) or str(room.get("status") or "") != "not_started":
        return result
    result["handled"] = True
    try:
        from live_draft_timer_logic import live_draft_reset_timer
    except ImportError:
        result["error"] = "Live draft timer helpers unavailable."
        return result

    room["status"] = "in_progress"
    live_draft_reset_timer(room)
    session["live_draft_room"] = room
    user_team = str((room.get("config") or {}).get("your_team") or (room.get("config") or {}).get("user_team") or "")
    if user_team:
        session["room_your_team"] = user_team
    try:
        from draft_room_state import ACTIVE_DRAFT_MODE_LIVE, set_canonical_draft_meta

        set_canonical_draft_meta(
            session,
            mode=ACTIVE_DRAFT_MODE_LIVE,
            source="start_prepared_shared_room",
            pick_count=len(room.get("draft_board") or []),
        )
    except ImportError:
        pass
    try:
        from live_draft_state import commit_live_draft_room

        commit_live_draft_room(st_obj, session, room, reason="start_draft")
    except ImportError:
        pass
    try:
        from draft_room_context import commit_shared_room_state, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            ok, msg, _ = commit_shared_room_state(session, room)
            if not ok and msg:
                result["error"] = msg
                result["ok"] = False
                return result
    except ImportError:
        pass
    result["ok"] = True
    session["_live_draft_start_feedback"] = (
        f"Shared multiplayer draft started — Room Code **{code}**. Invite players with this code."
    )
    return result


def finalize_shared_room_create(
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    host_team: str,
    store: Any = None,
) -> tuple[str, str]:
    """Create shared room for a not_started live room. Returns (code, error)."""
    stamp_room_setup_mode(room, session)
    session["live_draft_room"] = room
    session["room_your_team"] = host_team
    try:
        from draft_room_context import create_and_host_shared_room

        code, _doc = create_and_host_shared_room(session, room, host_team=host_team, store=store)
    except ImportError as exc:
        return "", str(exc)
    if not code:
        err = str(session.pop("_draft_room_last_error", "") or "").strip()
        return "", err or "Could not create shared room. This draft cannot be joined by others."
    return code, ""
