"""Rebuild the shared-draft player pool locally when the wire document omits it.

Shared room documents strip ``pool`` / ``pool_records`` for egress. Hosts and
guests must reconstruct the scoring pool on this client — never put the pool
back on the shared document.
"""

from __future__ import annotations

import json
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


def _local_pool_disk_path(room_code: str) -> Any:
    from pathlib import Path

    code = str(room_code or "").strip().upper()
    root = Path(__file__).resolve().parent / "data" / "draft_room_local_pools"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{code}.pkl"


def load_local_pool_disk(room_code: str) -> Any:
    """Cross-process local pool artifact (not the shared room wire document)."""
    code = str(room_code or "").strip().upper()
    if not code:
        return None
    try:
        path = _local_pool_disk_path(code)
        if not path.is_file():
            return None
        import pickle

        with path.open("rb") as fh:
            pool = pickle.load(fh)
        if pool_is_empty(pool):
            return None
        return pool
    except Exception:
        return None


def save_local_pool_disk(room_code: str, pool: Any) -> None:
    code = str(room_code or "").strip().upper()
    if not code or pool_is_empty(pool):
        return
    try:
        import pickle

        path = _local_pool_disk_path(code)
        with path.open("wb") as fh:
            pickle.dump(pool, fh, protocol=pickle.HIGHEST_PROTOCOL)
        _live_pool_diag("disk_pool_saved", room_code=code, rows=int(len(pool)))
    except Exception as exc:
        _live_pool_diag("disk_pool_save_fail", room_code=code, error=f"{type(exc).__name__}:{exc}"[:120])

# Import-time marker so two-process browser proofs can confirm this module is loaded.
try:
    from pathlib import Path as _PoolPath

    _marker = _PoolPath(__file__).resolve().parent / "data" / "tb_probe" / "shared_pool_module_loaded.txt"
    _marker.parent.mkdir(parents=True, exist_ok=True)
    _marker.write_text(f"loaded ts={time.time()} file={__file__}\n", encoding="utf-8")
except Exception:
    pass


def _live_pool_diag(event: str, **fields: Any) -> None:
    """Append one JSON line for local two-process browser diagnosis (best-effort)."""
    row = {"event": event, "ts": time.time(), **fields}
    line = json.dumps(row, default=str)[:800]
    try:
        print(f"SHARED_POOL_DIAG|{line}", flush=True)
    except Exception:
        pass
    try:
        from pathlib import Path

        roots = [
            Path(__file__).resolve().parent / "data" / "tb_probe" / "pool_live_diag.jsonl",
            Path.cwd() / "data" / "tb_probe" / "pool_live_diag.jsonl",
        ]
        seen: set[str] = set()
        for path in roots:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        try:
            print(f"SHARED_POOL_DIAG_WRITE_FAIL|{type(exc).__name__}:{exc}", flush=True)
        except Exception:
            pass


def pool_is_empty(pool: Any) -> bool:
    return pool is None or getattr(pool, "empty", True)


def _is_session_mapping(session: Any) -> bool:
    """True for plain dicts and Streamlit SessionState (not isinstance(dict))."""
    return session is not None and hasattr(session, "get") and hasattr(session, "__setitem__")


def needs_local_shared_player_pool(
    session: dict[str, Any] | None,
    room: dict[str, Any] | None = None,
) -> bool:
    """True when this client must rebuild the stripped shared-wire pool locally.

    Prefer ``is_shared_multiplayer_intent``, but also treat an active room code /
    shared config stamp as authoritative. Live room_body historically gated
    ensure on intent alone; when that classifier briefly returned False for an
    otherwise active Shared room, ensure never ran and Add-to-Queue stayed empty.
    """
    if not _is_session_mapping(session):
        return False
    try:
        from live_draft_setup_mode import is_shared_multiplayer_intent

        if is_shared_multiplayer_intent(session, room=room):
            return True
    except Exception:
        # Intent classifier must not block room-code / config fallbacks.
        pass
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if _room_code(session, live if isinstance(live, dict) else None):
        return True
    if isinstance(live, dict):
        cfg = dict(live.get("config") or {})
        mode = str(cfg.get("draft_setup_mode") or live.get("draft_setup_mode") or "").strip().lower()
        if "shared" in mode:
            return True
    return False


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
    if pool_is_empty(pool) or not _is_session_mapping(session):
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
        from live_draft_fast_solo_start import build_fast_market_pool

        market = session.get("market_df_live")
        if market is None:
            market = session.get("market_df")
        # Prefer already-hydrated session market — safe from fragment/poll ScriptRuns
        # that cannot invoke Streamlit-coupled loaders (DuplicateElementKey / fragment write).
        if market is not None and not getattr(market, "empty", True):
            rebuilt = build_fast_market_pool(market)
            if not pool_is_empty(rebuilt):
                if _is_session_mapping(session):
                    session.pop("_shared_local_pool_rebuild_error", None)
                    session["_shared_local_pool_rebuild_rows"] = int(len(rebuilt))
                    session["_shared_local_pool_rebuild_source"] = "fast_market"
                return rebuilt
            errors.append("fast_market_pool_empty")
    except Exception as exc:
        errors.append(f"fast_market_session:{type(exc).__name__}:{exc}"[:160])

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
            try:
                pool = app_mod.get_cached_unified_projection_pool(
                    lahman_year,
                    draft_window,
                    fantasy_format,
                    projection_style,
                    use_ml_blend,
                    ml_blend_weight,
                    ml_min_games,
                )
            except Exception as exc:
                errors.append(f"cached_unified_call:{type(exc).__name__}:{exc}"[:160])
                pool = None
        if not pool_is_empty(pool):
            if _is_session_mapping(session):
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
                if _is_session_mapping(session):
                    session.pop("_shared_local_pool_rebuild_error", None)
                    session["_shared_local_pool_rebuild_rows"] = int(len(rebuilt))
                    session["_shared_local_pool_rebuild_source"] = "fast_market"
                return rebuilt
            errors.append("fast_market_pool_empty")
        else:
            errors.append("market_df_missing")
    except Exception as exc:
        errors.append(f"fast_market:{type(exc).__name__}:{exc}"[:160])

    if _is_session_mapping(session) and errors:
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

    Order: current room pool → same-room session stash → room-scoped disk cache
    (cross-process) → local rebuild.

    Workspace persist drops DataFrame pools. Retry rebuild whenever both the
    room and stash are empty — ``get_cached_unified_projection_pool`` is cheap
    after the first warm build. ``force_rebuild`` clears a stale empty/non-usable
    room pool so Start cannot open an empty live board.
    """
    if not _is_session_mapping(session) or not isinstance(room, dict):
        return None
    code = _room_code(session, room)
    _live_pool_diag(
        "ensure_enter",
        room_code=code,
        force_rebuild=bool(force_rebuild),
        room_pool_empty=pool_is_empty(room.get("pool")),
        stash_empty=pool_is_empty(session.get(DRAFT_ROOM_PLAYER_POOL_KEY)),
        pending=bool(session.get(SHARED_REC_POOL_PENDING_KEY)),
    )
    if force_rebuild:
        # Shared wire never carries pool; Start must not trust a leftover empty frame.
        if pool_is_empty(room.get("pool")):
            room.pop("pool", None)

    pool = room.get("pool")
    if not pool_is_empty(pool):
        remember_local_shared_player_pool(session, pool, room_code=code)
        save_local_pool_disk(code, pool)
        _live_pool_diag("ensure_hit_room_pool", room_code=code, rows=int(len(pool)))
        return pool

    fallback = session.get(DRAFT_ROOM_PLAYER_POOL_KEY)
    if not pool_is_empty(fallback) and _stash_matches_room(session, code):
        room["pool"] = fallback
        remember_local_shared_player_pool(session, fallback, room_code=code)
        save_local_pool_disk(code, fallback)
        _live_pool_diag("ensure_hit_stash", room_code=code, rows=int(len(fallback)))
        return fallback

    disk = load_local_pool_disk(code)
    if not pool_is_empty(disk):
        room["pool"] = disk
        remember_local_shared_player_pool(session, disk, room_code=code)
        if session.get(SHARED_REC_POOL_PENDING_KEY):
            session.pop(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY, None)
        _live_pool_diag("ensure_hit_disk", room_code=code, rows=int(len(disk)))
        return disk

    build = builder or rebuild_shared_room_player_pool
    try:
        rebuilt = build(session, room)
    except Exception as exc:
        session["_shared_local_pool_rebuild_error"] = f"builder:{type(exc).__name__}:{exc}"[:240]
        rebuilt = None
    if pool_is_empty(rebuilt):
        _live_pool_diag(
            "ensure_rebuild_empty",
            room_code=code,
            error=str(session.get("_shared_local_pool_rebuild_error") or "")[:200],
        )
        return None
    room["pool"] = rebuilt
    remember_local_shared_player_pool(session, rebuilt, room_code=code)
    save_local_pool_disk(code, rebuilt)
    # Pool just became available while interactive was waiting — allow one handoff rerun.
    if session.get(SHARED_REC_POOL_PENDING_KEY):
        session.pop(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY, None)
    _live_pool_diag(
        "ensure_rebuild_ok",
        room_code=code,
        rows=int(len(rebuilt)),
        source=str(session.get("_shared_local_pool_rebuild_source") or "cached_unified"),
    )
    return rebuilt


def mark_shared_rec_pool_pending(session: dict[str, Any], *, reason: str = "") -> None:
    """Note that recommendation cards are waiting on a local pool rebuild."""
    if not _is_session_mapping(session):
        return
    session[SHARED_REC_POOL_PENDING_KEY] = True
    session[SHARED_REC_POOL_PENDING_REASON_KEY] = str(reason or "empty_local_pool")[:120]
    # Allow one fresh empty→ready handoff after each new pending mark.
    session.pop(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY, None)


def clear_shared_rec_pool_pending(session: dict[str, Any]) -> None:
    if not _is_session_mapping(session):
        return
    session.pop(SHARED_REC_POOL_PENDING_KEY, None)
    session.pop(SHARED_REC_POOL_PENDING_REASON_KEY, None)
    session.pop(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY, None)
    session.pop("_live_draft_refresh_top_rec_handoff_attempted", None)


def shared_rec_pool_pending(session: dict[str, Any]) -> bool:
    return bool(_is_session_mapping(session) and session.get(SHARED_REC_POOL_PENDING_KEY))


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
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        return False
    if not needs_local_shared_player_pool(session, live):
        _live_pool_diag("handoff_skipped_not_shared", room_code=_room_code(session, live))
        return False

    attached = ensure_local_shared_player_pool(session, live, builder=builder)
    session["live_draft_room"] = live
    if pool_is_empty(attached) and pool_is_empty(live.get("pool")):
        _live_pool_diag("handoff_still_empty", room_code=_room_code(session, live))
        return False

    # Allow a retry if the first full ScriptRun after pool-ready still left cards empty
    # (pending remains). Throttle so poll/fragment ticks cannot loop-rerun.
    last_ts = float(session.get("_live_draft_shared_rec_pool_ready_rerun_ts") or 0)
    if session.get(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY) and (time.time() - last_ts) < 12.0:
        return False

    session[SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY] = True
    session["_live_draft_shared_rec_pool_ready_rerun_ts"] = time.time()
    session["_live_draft_last_rerun_source"] = "shared_rec_pool_ready"
    _live_pool_diag(
        "handoff_rerun_requested",
        room_code=_room_code(session, live),
        rows=int(len(attached)) if attached is not None and hasattr(attached, "__len__") else None,
    )
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
