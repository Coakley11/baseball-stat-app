"""Rebuild the shared-draft player pool locally when the wire document omits it.

Shared room documents strip ``pool`` / ``pool_records`` for egress. Hosts and
guests must reconstruct the scoring pool on this client — never put the pool
back on the shared document.
"""

from __future__ import annotations

from typing import Any, Callable

DRAFT_ROOM_PLAYER_POOL_KEY = "draft_room_player_pool"
DRAFT_ROOM_PLAYER_POOL_CODE_KEY = "draft_room_player_pool_room_code"


def pool_is_empty(pool: Any) -> bool:
    return pool is None or getattr(pool, "empty", True)


def _room_code(session: dict[str, Any], room: dict[str, Any] | None) -> str:
    if isinstance(room, dict):
        cfg = dict(room.get("config") or {})
        code = str(
            room.get("room_code")
            or cfg.get("room_code")
            or cfg.get("share_code")
            or ""
        ).strip().upper()
        if code:
            return code
    return str(
        session.get("active_shared_draft_room_code")
        or session.get("draft_room_share_code")
        or ""
    ).strip().upper()


def remember_local_shared_player_pool(
    session: dict[str, Any],
    pool: Any,
    *,
    room_code: str = "",
) -> None:
    """Keep a create/join-time pool so persist/publish can reattach it."""
    if pool_is_empty(pool) or not isinstance(session, dict):
        return
    session[DRAFT_ROOM_PLAYER_POOL_KEY] = pool
    code = str(room_code or "").strip().upper()
    if code:
        session[DRAFT_ROOM_PLAYER_POOL_CODE_KEY] = code


def _stash_matches_room(session: dict[str, Any], room_code: str) -> bool:
    cached = str(session.get(DRAFT_ROOM_PLAYER_POOL_CODE_KEY) or "").strip().upper()
    if not cached or not room_code:
        return True
    return cached == room_code


def rebuild_shared_room_player_pool(
    session: dict[str, Any],
    room: dict[str, Any] | None,
) -> Any:
    """Rebuild the projection/market pool using this client's local cache."""
    cfg = dict((room or {}).get("config") or {}) if isinstance(room, dict) else {}
    kw: dict[str, Any] = {}
    try:
        from shared_draft_context import draft_pool_kwargs_from_session

        kw = draft_pool_kwargs_from_session(session)
    except Exception:
        kw = {}

    def _first(*values: Any, default: Any = None) -> Any:
        for value in values:
            if value is not None:
                return value
        return default

    try:
        import importlib

        app_mod = importlib.import_module("streamlit_app")
        pool = app_mod.get_cached_unified_projection_pool(
            int(session.get("_lahman_max_year") or cfg.get("lahman_max_year") or 0),
            int(_first(cfg.get("projection_window"), kw.get("draft_window"), 3) or 3),
            str(_first(cfg.get("fantasy_format"), kw.get("fantasy_format"), "5x5 Roto") or "5x5 Roto"),
            str(_first(cfg.get("projection_style"), kw.get("projection_style"), "Balanced") or "Balanced"),
            bool(_first(cfg.get("use_ml_blend"), kw.get("use_ml_blend"), False)),
            float(_first(cfg.get("ml_blend_weight"), kw.get("ml_blend_weight"), 0) or 0),
            int(_first(cfg.get("ml_min_games_for_signal"), kw.get("ml_min_games_for_signal"), 50) or 50),
        )
        if not pool_is_empty(pool):
            return pool
    except Exception:
        pass

    try:
        from live_draft_fast_solo_start import build_fast_market_pool

        market = session.get("market_df_live")
        if market is None:
            market = session.get("market_df")
        if market is not None and not getattr(market, "empty", True):
            rebuilt = build_fast_market_pool(market)
            if not pool_is_empty(rebuilt):
                return rebuilt
    except Exception:
        pass
    return None


def ensure_local_shared_player_pool(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    builder: Callable[[dict[str, Any], dict[str, Any] | None], Any] | None = None,
    force_rebuild: bool = False,
) -> Any:
    """Attach a non-empty local pool onto ``room`` without writing the shared doc.

    Order: current room pool → same-room session stash → local rebuild.

    Workspace persist drops DataFrame pools. Retry rebuild whenever both the
    room and stash are empty — ``get_cached_unified_projection_pool`` is cheap
    after the first warm build. ``force_rebuild`` is kept for Start callers.
    """
    del force_rebuild
    if not isinstance(session, dict) or not isinstance(room, dict):
        return None
    code = _room_code(session, room)
    pool = room.get("pool")
    if not pool_is_empty(pool):
        remember_local_shared_player_pool(session, pool, room_code=code)
        return pool

    fallback = session.get(DRAFT_ROOM_PLAYER_POOL_KEY)
    if not pool_is_empty(fallback) and _stash_matches_room(session, code):
        room["pool"] = fallback
        remember_local_shared_player_pool(session, fallback, room_code=code)
        return fallback

    build = builder or rebuild_shared_room_player_pool
    try:
        rebuilt = build(session, room)
    except Exception:
        rebuilt = None
    if pool_is_empty(rebuilt):
        return None
    room["pool"] = rebuilt
    remember_local_shared_player_pool(session, rebuilt, room_code=code)
    return rebuilt
