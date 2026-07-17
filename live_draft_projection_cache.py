"""Cached queue / pick projections — never block live draft mutations."""

from __future__ import annotations

from typing import Any

PROJECTION_CACHE_KEY = "_live_draft_projection_cache"
PROJECTION_UPDATING_KEY = "_live_draft_projection_updating"


def projection_cache_key(
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
) -> tuple:
    room = room if isinstance(room, dict) else (session.get("live_draft_room") or {})
    room = room if isinstance(room, dict) else {}
    room_id = str(room.get("draft_room_id") or session.get("active_shared_draft_room_code") or "")
    pick_idx = int(room.get("current_pick_index") or 0)
    queue = session.get("draft_queue") or []
    queue_rev = len(queue)
    try:
        queue_rev = hash(tuple(str(x) for x in queue[:40]))
    except Exception:
        pass
    drafted = room.get("drafted_player_ids") or []
    drafted_rev = len(drafted) if isinstance(drafted, list) else 0
    settings_rev = str(session.get("live_draft_proj_window") or "") + "|" + str(session.get("live_draft_scoring") or "")
    return (room_id, pick_idx, queue_rev, drafted_rev, settings_rev)


def get_cached_queue_projection(session: dict[str, Any], room: dict[str, Any] | None = None) -> Any:
    cache = session.get(PROJECTION_CACHE_KEY)
    if not isinstance(cache, dict):
        return None
    if cache.get("key") != projection_cache_key(session, room):
        return cache.get("value")  # stale-ok display
    return cache.get("value")


def projection_is_stale(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    cache = session.get(PROJECTION_CACHE_KEY)
    if not isinstance(cache, dict):
        return True
    return cache.get("key") != projection_cache_key(session, room)


def store_queue_projection(session: dict[str, Any], value: Any, room: dict[str, Any] | None = None) -> None:
    session[PROJECTION_CACHE_KEY] = {
        "key": projection_cache_key(session, room),
        "value": value,
    }
    session.pop(PROJECTION_UPDATING_KEY, None)


def mark_projection_updating(session: dict[str, Any]) -> None:
    session[PROJECTION_UPDATING_KEY] = True


def should_recompute_projection(session: dict[str, Any], room: dict[str, Any] | None = None) -> bool:
    """True only when dependency revisions changed — never on bare timer ticks."""
    if session.get("_live_draft_timer_fragment_tick") or session.get("_live_draft_queue_only_tick"):
        return False
    return projection_is_stale(session, room)
