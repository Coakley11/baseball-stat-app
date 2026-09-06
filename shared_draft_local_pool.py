"""Rebuild the shared-draft player pool locally when the wire document omits it.

Shared room documents strip ``pool`` / ``pool_records`` for egress. Hosts and
guests must reconstruct the scoring pool on this client — never put the pool
back on the shared document.
"""

from __future__ import annotations

import time
from typing import Any, Callable

DRAFT_ROOM_PLAYER_POOL_KEY = "draft_room_player_pool"
DRAFT_ROOM_PLAYER_POOL_CODE_KEY = "draft_room_player_pool_room_code"
# Interactive paint failed while the local pool was still empty. A later
# fragment/poll tick may attach the pool without a board revision change —
# request one full-app ScriptRun so Add-to-Queue can register (not under
# run_every).
SHARED_REC_POOL_PENDING_KEY = "_live_draft_shared_rec_pool_pending"
SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY = "_live_draft_shared_rec_pool_ready_rerun_attempted"
SHARED_REC_POOL_PENDING_REASON_KEY = "_live_draft_shared_rec_pool_pending_reason"


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
    errors: list[str] = []
    try:
        from shared_draft_context import draft_pool_kwargs_from_session

        kw = draft_pool_kwargs_from_session(session)
    except Exception as exc:
        errors.append(f"draft_pool_kwargs:{type(exc).__name__}")
        kw = {}

    def _first(*values: Any, default: Any = None) -> Any:
        for value in values:
            if value is not None:
                return value
        return default

    lahman_year = int(session.get("_lahman_max_year") or cfg.get("lahman_max_year") or 0)
    draft_window = int(_first(cfg.get("projection_window"), kw.get("draft_window"), 3) or 3)
    fantasy_format = str(
        _first(cfg.get("fantasy_format"), kw.get("fantasy_format"), "5x5 Roto") or "5x5 Roto"
    )
    projection_style = str(
        _first(cfg.get("projection_style"), kw.get("projection_style"), "Balanced") or "Balanced"
    )
    use_ml_blend = bool(_first(cfg.get("use_ml_blend"), kw.get("use_ml_blend"), False))
    ml_blend_weight = float(_first(cfg.get("ml_blend_weight"), kw.get("ml_blend_weight"), 0) or 0)
    ml_min_games = int(
        _first(cfg.get("ml_min_games_for_signal"), kw.get("ml_min_games_for_signal"), 50) or 50
    )

    try:
        import importlib

        app_mod = importlib.import_module("streamlit_app")
        # Prefer the live wrapper when available — same kwargs the app uses elsewhere.
        live_fn = getattr(app_mod, "get_cached_unified_projection_pool_live", None)
        pool = None
        if callable(live_fn):
            try:
                pool = live_fn()
            except Exception as exc:
                errors.append(f"cached_pool_live:{type(exc).__name__}:{exc}"[:160])
                pool = None
        if pool_is_empty(pool):
            pool = app_mod.get_cached_unified_projection_pool(
                lahman_year,
                draft_window,
                fantasy_format,
                projection_style,
                use_ml_blend,
                ml_blend_weight,
                ml_min_games,
            )
        if not pool_is_empty(pool):
            if isinstance(session, dict):
                session.pop("_shared_local_pool_rebuild_error", None)
                session["_shared_local_pool_rebuild_rows"] = int(len(pool))
            return pool
        errors.append("cached_unified_pool_empty")
    except Exception as exc:
        errors.append(f"cached_unified:{type(exc).__name__}:{exc}"[:160])

    try:
        from live_draft_fast_solo_start import build_fast_market_pool

        market = session.get("market_df_live")
        if market is None:
            market = session.get("market_df")
        if market is None:
            # Last-resort: load market the same way the cached pool builder does.
            try:
                import importlib

                app_mod = importlib.import_module("streamlit_app")
                loader = getattr(app_mod, "load_fantasypros_market_data", None)
                if callable(loader):
                    market = loader()
            except Exception as exc:
                errors.append(f"market_loader:{type(exc).__name__}")
                market = None
        if market is not None and not getattr(market, "empty", True):
            rebuilt = build_fast_market_pool(market)
            if not pool_is_empty(rebuilt):
                if isinstance(session, dict):
                    session.pop("_shared_local_pool_rebuild_error", None)
                    session["_shared_local_pool_rebuild_rows"] = int(len(rebuilt))
                    session["_shared_local_pool_rebuild_source"] = "fast_market"
                return rebuilt
            errors.append("fast_market_pool_empty")
        else:
            errors.append("market_df_missing")
    except Exception as exc:
        errors.append(f"fast_market:{type(exc).__name__}:{exc}"[:160])

    if isinstance(session, dict) and errors:
        session["_shared_local_pool_rebuild_error"] = " | ".join(errors)[:400]
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
    after the first warm build. ``force_rebuild`` clears a stale empty/non-usable
    room pool so Start cannot open an empty live board.
    """
    if not isinstance(session, dict) or not isinstance(room, dict):
        return None
    code = _room_code(session, room)
    if force_rebuild:
        # Shared wire never carries pool; Start must not trust a leftover empty frame.
        if pool_is_empty(room.get("pool")):
            room.pop("pool", None)

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
    except Exception as exc:
        session["_shared_local_pool_rebuild_error"] = f"builder:{type(exc).__name__}:{exc}"[:240]
        rebuilt = None
    if pool_is_empty(rebuilt):
        return None
    room["pool"] = rebuilt
    remember_local_shared_player_pool(session, rebuilt, room_code=code)
    return rebuilt


def mark_shared_rec_pool_pending(session: dict[str, Any], *, reason: str = "") -> None:
    """Note that recommendation cards are waiting on a local pool rebuild."""
    if not isinstance(session, dict):
        return
    session[SHARED_REC_POOL_PENDING_KEY] = True
    session[SHARED_REC_POOL_PENDING_REASON_KEY] = str(reason or "empty_local_pool")[:120]
    # Allow one fresh empty→ready handoff after each new pending mark.
    session.pop(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY, None)


def clear_shared_rec_pool_pending(session: dict[str, Any]) -> None:
    if not isinstance(session, dict):
        return
    session.pop(SHARED_REC_POOL_PENDING_KEY, None)
    session.pop(SHARED_REC_POOL_PENDING_REASON_KEY, None)
    session.pop(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY, None)


def shared_rec_pool_pending(session: dict[str, Any]) -> bool:
    return bool(isinstance(session, dict) and session.get(SHARED_REC_POOL_PENDING_KEY))


def maybe_request_full_rerun_when_shared_pool_ready(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
    *,
    builder: Callable[[dict[str, Any], dict[str, Any] | None], Any] | None = None,
) -> bool:
    """If interactive failed on an empty pool and the pool is now ready, request a full ScriptRun.

    Safe for poll / readiness fragments: does not register Add-to-Queue widgets.
    Does not put ``pool`` back on the shared wire document.
    """
    if not shared_rec_pool_pending(session):
        return False
    if session.get(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY):
        return False
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        return False
    try:
        from live_draft_setup_mode import is_shared_multiplayer_intent

        if not is_shared_multiplayer_intent(session, room=live):
            return False
    except ImportError:
        if not str(session.get("active_shared_draft_room_code") or "").strip():
            return False

    attached = ensure_local_shared_player_pool(session, live, builder=builder)
    session["live_draft_room"] = live
    if pool_is_empty(attached) and pool_is_empty(live.get("pool")):
        return False

    session[SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY] = True
    session["_live_draft_shared_rec_pool_ready_rerun_ts"] = time.time()
    session["_live_draft_last_rerun_source"] = "shared_rec_pool_ready"
    # Clear stuck create "Starting…" once the live room has a usable local pool.
    try:
        from live_draft_start_progress import finish_live_draft_start, is_live_draft_start_in_flight

        if is_live_draft_start_in_flight(session):
            finish_live_draft_start(session, ok=True)
    except ImportError:
        session.pop("_live_draft_start_in_flight", None)
        session.pop("_start_live_draft_pending", None)

    if st is None:
        return True
    try:
        st.rerun(scope="app")
    except TypeError:
        st.rerun()
    return True
