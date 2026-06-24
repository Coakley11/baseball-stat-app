"""Controlled draft sources — queue, watchlist, tracked players, optional free pool."""

from __future__ import annotations

from typing import Any

ALLOW_FREE_POOL_KEY = "allow_free_pool_drafting"
ALLOWED_SOURCES = frozenset({"queue", "watchlist", "tracked", "free_pool"})


def _normalize_name(raw: Any) -> str:
    return str(raw or "").split(" (")[0].strip().lower()


def gather_participant_draft_sources(session: dict[str, Any]) -> dict[str, list[str]]:
    """Private draft candidate lists for the current participant."""
    try:
        from draft_state import gather_draft_workflow

        dw = gather_draft_workflow(session)
    except ImportError:
        dw = {}
    queue = [str(x).strip() for x in (dw.get("queue") or []) if str(x).strip()]
    watch = [str(x).strip() for x in (dw.get("watchlist_focus") or []) if str(x).strip()]
    watch += [str(x).strip() for x in (dw.get("watchlist_favorites") or []) if str(x).strip()]
    watch = list(dict.fromkeys(watch))
    tracked_raw = session.get("workflow_recently_viewed") or []
    tracked = [str(x).strip() for x in tracked_raw if str(x).strip()] if isinstance(tracked_raw, list) else []
    return {"queue": queue, "watchlist": watch, "tracked": tracked}


def allow_free_pool_drafting(session: dict[str, Any], *, live_room: dict[str, Any] | None = None) -> bool:
    """True when any available pool player may be drafted (commissioner setting)."""
    try:
        from draft_room_context import is_multiplayer_draft_active
    except ImportError:
        is_multiplayer_draft_active = lambda _s: False  # noqa: E731

    if ALLOW_FREE_POOL_KEY in session:
        return bool(session.get(ALLOW_FREE_POOL_KEY))
    room = live_room if isinstance(live_room, dict) else session.get("live_draft_room")
    if isinstance(room, dict):
        cfg = dict(room.get("config") or {})
        if ALLOW_FREE_POOL_KEY in cfg:
            return bool(cfg.get(ALLOW_FREE_POOL_KEY))
    return not is_multiplayer_draft_active(session)


def match_draft_source(player_name: str, sources: dict[str, list[str]]) -> str | None:
    """Return which private source matched, or None."""
    target = _normalize_name(player_name)
    if not target:
        return None
    for key in ("queue", "watchlist", "tracked"):
        for name in sources.get(key) or []:
            if _normalize_name(name) == target:
                return key
    return None


def is_allowed_draft_source(
    session: dict[str, Any],
    player_name: str,
    *,
    live_room: dict[str, Any] | None = None,
) -> tuple[bool, str, str | None]:
    """Return (allowed, reason, matched_source)."""
    name = str(player_name or "").strip()
    if not name:
        return False, "Select a player first.", None
    if allow_free_pool_drafting(session, live_room=live_room):
        return True, "", "free_pool"
    sources = gather_participant_draft_sources(session)
    matched = match_draft_source(name, sources)
    if matched:
        return True, "", matched
    return (
        False,
        "Draft from your Queue, Watchlist, or Tracked Players — or enable free pool drafting.",
        None,
    )


def _exclude_drafted_names(session: dict[str, Any], names: list[str]) -> list[str]:
    try:
        from draft_room_state import get_all_drafted_player_names
    except ImportError:
        return names
    drafted = {_normalize_name(n) for n in get_all_drafted_player_names(session)}
    return [n for n in names if _normalize_name(n) not in drafted]


def allowed_draft_player_names(
    session: dict[str, Any],
    *,
    live_room: dict[str, Any] | None = None,
    available_names: list[str] | None = None,
) -> list[str]:
    """Names the participant may draft (intersection with available when provided)."""
    if allow_free_pool_drafting(session, live_room=live_room):
        names = list(available_names or [])
        return _exclude_drafted_names(session, names)
    sources = gather_participant_draft_sources(session)
    candidates = list(dict.fromkeys((sources.get("queue") or []) + (sources.get("watchlist") or []) + (sources.get("tracked") or [])))
    candidates = _exclude_drafted_names(session, candidates)
    if not available_names:
        return candidates
    avail = {_normalize_name(n): n for n in available_names}
    out: list[str] = []
    for name in candidates:
        hit = avail.get(_normalize_name(name))
        if hit and hit not in out:
            out.append(hit)
    return out


def validate_shared_pick_commit(
    session: dict[str, Any],
    live_room: dict[str, Any],
    player_name: str,
) -> tuple[bool, str]:
    """Server-side pick validation before shared-room commit."""
    try:
        from draft_actions import can_draft_player, _resolve_player_name
        from draft_room_state import get_all_drafted_player_names
    except ImportError as exc:
        return False, str(exc)

    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active
        from draft_room_membership import validate_participant_may_draft
    except ImportError:
        active_participant_team = lambda _s: str(_s.get("room_your_team") or "")  # noqa: E731
        is_multiplayer_draft_active = lambda _s: False  # noqa: E731
        validate_participant_may_draft = None  # type: ignore[assignment,misc]

    name = str(player_name or "").strip()
    if not name:
        return False, "Select a player first."

    if is_multiplayer_draft_active(session) and validate_participant_may_draft is not None:
        ok_pick, pick_msg = validate_participant_may_draft(session, live_room)
        if not ok_pick:
            return False, pick_msg

    allowed, reason = can_draft_player(session, name)
    if not allowed:
        return False, reason

    drafted = get_all_drafted_player_names(session)
    resolved = _resolve_player_name(name, drafted)
    if resolved in drafted or name in drafted:
        return False, f"{name} is already drafted."

    src_ok, src_reason, _ = is_allowed_draft_source(session, name, live_room=live_room)
    if not src_ok:
        return False, src_reason

    return True, ""
