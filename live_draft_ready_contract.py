"""Solo Ready-state contract — never present Start Draft on an unusable stub."""

from __future__ import annotations

from typing import Any


# Explicit pre-start lifecycle phases (session["_solo_prestart_phase"]).
PHASE_SETUP = "setup"
PHASE_CREATING = "creating"
PHASE_PREPARING = "preparing"
PHASE_READY = "ready"
PHASE_IN_PROGRESS = "in_progress"

PRESTART_PHASE_KEY = "_solo_prestart_phase"


def solo_structural_contract(room: dict[str, Any] | None) -> dict[str, Any]:
    """Structural Solo pre-start contract (no projection/pool requirement)."""
    result: dict[str, Any] = {
        "ok": False,
        "reasons": [],
        "teams": 0,
        "scheduled_picks": 0,
        "timer_seconds": 0,
    }
    if not isinstance(room, dict):
        result["reasons"].append("no_room")
        return result

    status = str(room.get("status") or "").strip().lower()
    if status != "not_started":
        result["reasons"].append(f"status_{status or 'empty'}")
        return result

    if not str(room.get("draft_room_id") or "").strip():
        result["reasons"].append("draft_room_id_missing")

    teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
    result["teams"] = len(teams)
    if len(teams) < 2:
        result["reasons"].append("teams_incomplete")

    pick_order = room.get("pick_order") or []
    if not isinstance(pick_order, list):
        pick_order = []
    result["scheduled_picks"] = len(pick_order)
    if len(pick_order) < 2:
        result["reasons"].append("pick_order_empty")

    cfg = dict(room.get("config") or {})
    timer_sec = int(cfg.get("timer_seconds") or 0)
    result["timer_seconds"] = timer_sec
    if timer_sec <= 0:
        result["reasons"].append("timer_seconds_missing")

    if not str(cfg.get("your_team") or cfg.get("user_team") or "").strip():
        if not teams:
            result["reasons"].append("your_team_missing")

    if int(cfg.get("picks_per_team") or cfg.get("rounds") or 0) < 1 and len(pick_order) < 2:
        result["reasons"].append("picks_per_team_missing")

    board = room.get("draft_board") or []
    if isinstance(board, list) and len(board) > 0:
        result["reasons"].append("board_already_started")

    deadline = room.get("timer_deadline")
    started = room.get("timer_started_at")
    if deadline is not None or started is not None:
        result["reasons"].append("timer_already_armed")

    hard = {
        "no_room",
        "teams_incomplete",
        "pick_order_empty",
        "timer_seconds_missing",
        "your_team_missing",
        "draft_room_id_missing",
        "board_already_started",
        "timer_already_armed",
        "picks_per_team_missing",
    }
    hard_reasons = [r for r in result["reasons"] if r in hard or str(r).startswith("status_")]
    result["ok"] = len(hard_reasons) == 0
    result["reasons"] = list(result["reasons"])
    return result


def solo_ready_contract(room: dict[str, Any] | None, session: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a Solo Ready room. ``ok`` means Start Draft is immediately actionable."""
    structural = solo_structural_contract(room)
    result: dict[str, Any] = {
        "ok": False,
        "reasons": list(structural.get("reasons") or []),
        "teams": int(structural.get("teams") or 0),
        "scheduled_picks": int(structural.get("scheduled_picks") or 0),
        "timer_seconds": int(structural.get("timer_seconds") or 0),
        "has_pool": False,
        "pool_has_projections": False,
        "timer_running": "timer_already_armed" in (structural.get("reasons") or []),
        "structurally_valid": bool(structural.get("ok")),
        "phase": PHASE_SETUP,
    }
    if not isinstance(room, dict):
        result["can_show_ready"] = False
        result["can_start"] = False
        return result

    pool = room.get("pool")
    has_pool = pool is not None and not getattr(pool, "empty", True)
    result["has_pool"] = bool(has_pool)
    if not has_pool:
        result["reasons"].append("pool_missing")
    else:
        try:
            from live_draft_fast_solo_start import _pool_has_projection_player_grades

            result["pool_has_projections"] = bool(_pool_has_projection_player_grades(pool))
        except ImportError:
            cols = set(str(c) for c in getattr(pool, "columns", []))
            result["pool_has_projections"] = bool(
                cols.intersection({"Blended Projection Score", "proj_HR", "proj_RBI"})
            )

    session = session if isinstance(session, dict) else {}
    if session.get("_live_draft_start_in_flight") or session.get("_live_draft_manual_pick_in_flight"):
        result["reasons"].append("start_in_flight")

    # Ready UI may show while projections warm; Start requires canonical projections.
    result["can_show_ready"] = bool(result["structurally_valid"])
    result["can_start"] = bool(
        result["structurally_valid"]
        and result["pool_has_projections"]
        and "start_in_flight" not in result["reasons"]
        and "pool_missing" not in result["reasons"]
    )
    result["ok"] = bool(result["can_start"])
    if result["can_start"]:
        result["phase"] = PHASE_READY
    elif result["structurally_valid"]:
        result["phase"] = PHASE_PREPARING
    else:
        result["phase"] = PHASE_SETUP
    return result


def is_valid_solo_ready_room(room: dict[str, Any] | None, session: dict[str, Any] | None = None) -> bool:
    return bool(solo_ready_contract(room, session).get("can_show_ready"))


def enforce_prestart_invariants(
    room: dict[str, Any] | None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hard pre-Start invariants for Solo Ready / Setup / Preparing rooms.

    While status is not ``in_progress`` / ``paused`` / ``complete``:
    - no active deadline / countdown
    - board length == 0
    - current pick index == 0 (Pick 1 pending)
    - expiration / Auto Pick must not execute (callers also gate on status)

    Mutates ``room`` in place when safe. Returns a diagnostic dict.
    """
    out: dict[str, Any] = {
        "ok": False,
        "mutated": False,
        "status": "",
        "cleared_timer": False,
        "reset_board": False,
        "reset_pick_index": False,
    }
    if not isinstance(room, dict):
        out["reason"] = "no_room"
        return out
    status = str(room.get("status") or "").strip().lower()
    out["status"] = status
    if status in {"in_progress", "paused", "complete", "completed"}:
        out["ok"] = True
        out["skipped"] = True
        return out

    mutated = False
    if room.get("timer_deadline") is not None or room.get("timer_started_at") is not None:
        room["timer_deadline"] = None
        room["timer_started_at"] = None
        out["cleared_timer"] = True
        mutated = True
    if room.pop("timer_live_ready_at", None) is not None:
        mutated = True
        out["cleared_timer"] = True
    room["timer_handled_index"] = -1
    room.pop("last_processed_expiration_token", None)

    if int(room.get("current_pick_index") or 0) != 0:
        room["current_pick_index"] = 0
        out["reset_pick_index"] = True
        mutated = True

    board = room.get("draft_board")
    if isinstance(board, list) and board:
        # Solo Ready must never carry picks — wipe corrupt pre-start board.
        room["draft_board"] = []
        room["drafted_player_ids"] = []
        teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
        rosters = room.get("rosters") if isinstance(room.get("rosters"), dict) else {}
        room["rosters"] = {t: [] for t in teams} if teams else {}
        if isinstance(rosters, dict) and not teams:
            room["rosters"] = {str(k): [] for k in rosters.keys()}
        out["reset_board"] = True
        mutated = True

    if isinstance(session, dict):
        session["_solo_prestart_invariants"] = {
            "cleared_timer": out["cleared_timer"],
            "reset_board": out["reset_board"],
            "reset_pick_index": out["reset_pick_index"],
            "status": status,
        }

    out["mutated"] = mutated
    out["ok"] = True
    out["deadline"] = room.get("timer_deadline")
    out["board_len"] = len(room.get("draft_board") or []) if isinstance(room.get("draft_board"), list) else 0
    out["current_pick_index"] = int(room.get("current_pick_index") or 0)
    return out


def prestart_expiration_blocked(room: dict[str, Any] | None) -> bool:
    """True when expire / Auto Pick must not run (not yet In Progress with a live clock)."""
    if not isinstance(room, dict):
        return True
    status = str(room.get("status") or "").strip().lower()
    if status != "in_progress":
        return True
    try:
        from live_draft_timer_logic import first_pick_awaiting_live_ready

        if first_pick_awaiting_live_ready(room):
            return True
    except ImportError:
        if room.get("timer_deadline") is None and room.get("timer_started_at") is None:
            board = room.get("draft_board") or []
            if int(room.get("current_pick_index") or 0) == 0 and not board:
                return True
    return False


def is_uninhabitable_solo_ready_stub(room: Any) -> bool:
    """Corrupt not_started Solo rooms (Pick 1 of 0 / no teams) that must not sticky-Ready.

    Only clear truly empty shells. Soft structural gaps (timer config, etc.) are
    handled by Ready contract gating — do not bounce those rooms back to Setup.
    """
    if not isinstance(room, dict):
        return False
    status = str(room.get("status") or "").strip().lower()
    if status != "not_started":
        return False
    # Shared stubs with a room code are handled elsewhere.
    if str(room.get("room_code") or room.get("join_code") or "").strip():
        return False
    teams = [t for t in (room.get("teams") or []) if str(t).strip()]
    pick_order = room.get("pick_order") or []
    if len(teams) < 2 or not isinstance(pick_order, list) or len(pick_order) < 2:
        return True
    return False


def _archive_room_file(draft_room_id: str) -> None:
    rid = str(draft_room_id or "").strip()
    if not rid:
        return
    try:
        from pathlib import Path
        import time as _time

        rooms = Path(__file__).resolve().parent / "data" / "draft_rooms"
        path = rooms / f"{rid}.json"
        if path.exists():
            dest = rooms / f"_archive_{rid}_{int(_time.time())}.json"
            path.replace(dest)
    except Exception:
        pass


def clear_uninhabitable_solo_ready_stub(
    session: dict[str, Any],
    *,
    reason: str = "uninhabitable_solo_ready_stub",
) -> bool:
    """Atomically drop a broken Ready stub so Live Draft returns to Draft Setup.

    Clears runtime room, page-filter mirror, workspace pointer, and archives the
    on-disk room file so prepare cannot rehydrate the stub across reruns.
    """
    room = session.get("live_draft_room")
    if not is_uninhabitable_solo_ready_stub(room):
        return False
    rid = str((room or {}).get("draft_room_id") or "")
    try:
        from live_draft_state import (
            LIVE_DRAFT_PAGE_BLOCK,
            LIVE_DRAFT_ROOM_KEY,
            LIVE_DRAFT_STATE_KEY,
            write_canonical_live_draft_state,
        )

        try:
            from live_draft_room_mutation_audit import audited_pop_live_draft_room

            audited_pop_live_draft_room(session, reason=f"clear_ready_stub:{reason}")
        except ImportError:
            session.pop(LIVE_DRAFT_ROOM_KEY, None)
        session.pop(LIVE_DRAFT_STATE_KEY, None)
        pf = session.get("page_filter_state")
        if isinstance(pf, dict):
            block = pf.get(LIVE_DRAFT_PAGE_BLOCK)
            if isinstance(block, dict):
                block.pop(LIVE_DRAFT_ROOM_KEY, None)
        try:
            write_canonical_live_draft_state(
                session, None, reason=f"clear_ready_stub:{reason}", local_edit=True
            )
        except Exception:
            pass
    except ImportError:
        session.pop("live_draft_room", None)
        session.pop("live_draft_state", None)

    ws = session.get("baseball_workspace_state")
    if isinstance(ws, dict) and isinstance(ws.get("live_draft"), dict):
        stub = ws.get("live_draft") or {}
        if not rid or str(stub.get("draft_room_id") or "") == rid:
            ws.pop("live_draft", None)

    # Prevent soft-restore bounce: force Setup on next lifecycle resolve.
    session["_live_draft_force_setup_after_delete"] = True
    session.pop("active_shared_draft_room_code", None)
    session.pop("_shared_draft_room_code", None)
    session[PRESTART_PHASE_KEY] = PHASE_SETUP
    _archive_room_file(rid)
    session["_live_draft_cleared_ready_stub"] = {
        "reason": reason,
        "draft_room_id": rid,
        "atomic": True,
    }
    return True


def set_prestart_phase(session: dict[str, Any], phase: str) -> None:
    session[PRESTART_PHASE_KEY] = str(phase or PHASE_SETUP)


def ensure_ready_pool_warm(session: dict[str, Any], room: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach canonical projections while still in Ready (timer off).

    Prefer calling this on a dedicated Preparing ScriptRun (after widgets from
    the prior run have finished), not mid-interaction under Setup controls.

    Order matters: try the offline prewarm parquet *before* any path that imports
    ``streamlit_app`` / cold-builds the unified pool (those can block a ScriptRun
    for minutes and leave Start Draft disabled forever).
    """
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    out = {"ok": False, "attached": False, "reason": ""}
    if not isinstance(live, dict):
        out["reason"] = "no_room"
        return out
    set_prestart_phase(session, PHASE_PREPARING)
    try:
        from live_draft_fast_solo_start import (
            _pool_has_projection_player_grades,
            maybe_build_deferred_full_pool,
        )

        def _mark_ready(pool: Any, reason: str) -> dict[str, Any]:
            try:
                from draft_scoring_pool import (
                    POOL_KIND_VALID_PROJECTION,
                    POOL_VALUE_KIND_KEY,
                    ensure_draft_scoring_pool_columns,
                )

                pool = ensure_draft_scoring_pool_columns(pool)
                pool.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_VALID_PROJECTION
            except ImportError:
                pass
            live["pool"] = pool.copy()
            session["live_draft_room"] = live
            session["draft_room_player_pool"] = pool.copy()
            try:
                from live_draft_fast_solo_start import (
                    DEFERRED_FULL_POOL_DONE_KEY,
                    mark_process_projection_pool_warm,
                )

                session[DEFERRED_FULL_POOL_DONE_KEY] = True
                mark_process_projection_pool_warm()
            except ImportError:
                pass
            session.pop("_solo_needs_projection_player_grades", None)
            set_prestart_phase(session, PHASE_READY)
            return {"ok": True, "attached": True, "reason": reason}

        if _pool_has_projection_player_grades(live.get("pool")):
            out["ok"] = True
            out["reason"] = "already_warm"
            set_prestart_phase(session, PHASE_READY)
            return out

        # 1) Offline / accept prewarm parquet — fast, no streamlit_app import.
        try:
            from pathlib import Path

            import pandas as pd

            prewarm = (
                Path(__file__).resolve().parent
                / "data"
                / "tb_probe"
                / "prewarm_unified_pool.parquet"
            )
            if prewarm.exists():
                pool = pd.read_parquet(prewarm)
                if _pool_has_projection_player_grades(pool):
                    marked = _mark_ready(pool, "prewarm_parquet")
                    out.update(marked)
                    return out
            out["prewarm_missing"] = not prewarm.exists()
        except Exception as exc:
            out["prewarm_error"] = f"{type(exc).__name__}:{exc}"[:160]

        # 2) Canonical attach (may import streamlit_app — after parquet).
        try:
            from live_draft_canonical_pool import attach_canonical_pool_to_room

            attached = attach_canonical_pool_to_room(session, live, force=True)
            out["attach_reason"] = str(attached.get("reason") or "")
            live2 = session.get("live_draft_room") or live
            if _pool_has_projection_player_grades((live2 or {}).get("pool")):
                out["ok"] = True
                out["attached"] = True
                out["reason"] = str(attached.get("reason") or "attached_canonical")
                set_prestart_phase(session, PHASE_READY)
                return out
        except Exception as exc:
            out["attach_error"] = f"{type(exc).__name__}:{exc}"[:160]

        # 3) Deferred full-pool upgrade.
        try:
            upgraded = bool(maybe_build_deferred_full_pool(session, force=True))
            out["deferred_upgraded"] = upgraded
        except Exception as exc:
            out["deferred_error"] = f"{type(exc).__name__}:{exc}"[:160]
            upgraded = False
        live3 = session.get("live_draft_room") or live
        if upgraded and _pool_has_projection_player_grades((live3 or {}).get("pool")):
            out["ok"] = True
            out["attached"] = True
            out["reason"] = "deferred_full_pool"
            set_prestart_phase(session, PHASE_READY)
            return out

        # 4) Pinned unified builder last (cold miss is slow).
        try:
            import importlib
            from datetime import datetime

            app_mod = importlib.import_module("streamlit_app")
            get_pool = getattr(app_mod, "get_cached_unified_projection_pool", None)
            pool = None
            pin_errs: list[str] = []
            if callable(get_pool):
                for year_try in (2024, 2023, int(datetime.now().year) - 1):
                    try:
                        pool = get_pool(year_try, 3, "5x5 Roto", "Balanced", False, 0.0, 50)
                        if _pool_has_projection_player_grades(pool):
                            break
                        pin_errs.append(
                            f"y{year_try}:cols={list(getattr(pool, 'columns', [])[:6])}"
                        )
                        pool = None
                    except Exception as exc:
                        pin_errs.append(f"y{year_try}:{type(exc).__name__}:{exc}"[:80])
                        pool = None
            out["pin_errors"] = pin_errs[-6:]
            if _pool_has_projection_player_grades(pool):
                marked = _mark_ready(pool, "pinned_unified_builder")
                out.update(marked)
                return out
        except Exception as exc:
            out["pin_error"] = f"{type(exc).__name__}:{exc}"[:160]

        out["ok"] = False
        out["reason"] = "warm_failed"
        out["load_errors"] = list(session.get("_canonical_pool_load_errors") or [])
        live_fail = session.get("live_draft_room") or live
        pool_fail = (live_fail or {}).get("pool") if isinstance(live_fail, dict) else None
        out["pool_cols"] = [str(c) for c in list(getattr(pool_fail, "columns", []) or [])[:16]]
        return out
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}:{exc}"[:160]
        return out
