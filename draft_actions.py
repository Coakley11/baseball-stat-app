"""Unified draft action — single safe path for drafting a player on the user's turn."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

DRAFT_SOURCES = frozenset(
    {
        "draft_room",
        "queue",
        "watchlist",
        "tracked",
        "live_queue",
        "live_draft_room",
    }
)


def _import_baseball_app():
    """Load Streamlit entry module (Linux deploy uses Streamlit_app.py)."""
    import importlib

    last_exc: Exception | None = None
    for name in ("streamlit_app", "Streamlit_app"):
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            last_exc = exc
    raise ImportError(str(last_exc or "streamlit_app/Streamlit_app not found"))


def _your_team(session: dict[str, Any], *, live_room: dict[str, Any] | None = None) -> str:
    if isinstance(live_room, dict):
        cfg = dict(live_room.get("config") or {})
        team = str(cfg.get("your_team") or cfg.get("user_team") or "").strip()
        if team:
            return team
    return str(session.get("room_your_team") or "").strip()


def _next_on_clock_pick_info(table: Any) -> dict[str, Any] | None:
    """First open pick row on the board (overall on-clock slot)."""
    try:
        from draft_room_state import _player_cell_filled, is_runtime_table
    except ImportError:
        return None
    if not is_runtime_table(table) or table.empty or "Player" not in table.columns:
        return None
    work = table.copy()
    if "Pick" in work.columns:
        work = work.sort_values("Pick", kind="stable")
    for idx, row in work.iterrows():
        if not _player_cell_filled(row.get("Player")):
            pick_val = row.get("Pick")
            try:
                pick_n = int(pick_val)
            except (TypeError, ValueError):
                pick_n = None
            return {
                "row_index": int(idx),
                "pick": pick_n,
                "on_clock_team": str(row.get("Team") or "").strip(),
            }
    return None


def _resolve_player_name(player_name: str, known_names: list[str] | set[str]) -> str:
    name = str(player_name or "").strip()
    if not name:
        return ""
    if name in known_names:
        return name
    lower = name.lower()
    for candidate in known_names:
        if str(candidate).strip().lower() == lower:
            return str(candidate).strip()
    return name


def _clear_ami_draft_cache(session: dict[str, Any]) -> None:
    for key in (
        "_ami_draft_projection",
        "_ami_draft_snapshot",
        "_ami_undrafted_pool_lookup",
        "_ami_draft_cache_build_trace",
    ):
        session.pop(key, None)


def _prune_drafted_from_queue(session: dict[str, Any]) -> list[str]:
    """Remove any already-drafted names from the queue (matches workflow sidebar behavior)."""
    try:
        from draft_room_state import get_all_drafted_player_names
        from draft_state import DRAFT_QUEUE_KEY, sync_draft_queue, _normalize_player_list
    except ImportError:
        return list(session.get("draft_queue") or [])

    drafted = set(get_all_drafted_player_names(session))
    q = _normalize_player_list(session.get(DRAFT_QUEUE_KEY))
    kept = [p for p in q if p not in drafted]
    if kept != q:
        sync_draft_queue(session, kept, reason="auto_remove_drafted")
    return kept


def _post_draft_side_effects(
    session: dict[str, Any],
    player_name: str,
    *,
    st_obj: Any = None,
    save_reason: str = "draft_player",
) -> dict[str, Any]:
    """Queue cleanup, AMI cache invalidation, pending sync, optional force-save."""
    trace: dict[str, Any] = {"saved": False, "queue_after": []}
    try:
        from draft_state import mark_draft_pending_sync, remove_player_from_draft_queue

        remove_player_from_draft_queue(session, player_name, reason="drafted")
        trace["queue_after"] = _prune_drafted_from_queue(session)
        mark_draft_pending_sync(session)
    except ImportError as exc:
        log.warning("post_draft queue cleanup failed: %s", exc)
        trace["queue_after"] = list(session.get("draft_queue") or [])

    _clear_ami_draft_cache(session)

    if st_obj is not None:
        try:
            from baseball_persistent_state import force_save_baseball_state

            trace["saved"] = bool(force_save_baseball_state(st_obj, reason=save_reason))
        except Exception as exc:
            log.warning("force_save_baseball_state failed: %s", exc)
    return trace


def draft_action_context(session: dict[str, Any]) -> dict[str, Any]:
    """Resolved turn + board context for draft buttons and validation."""
    ctx: dict[str, Any] = {
        "active_mode": "draft_room_simulator",
        "your_team": "",
        "on_clock_team": "",
        "current_pick": None,
        "is_your_pick": False,
        "draft_complete": False,
        "board_full": False,
        "live_draft_active": False,
    }
    try:
        from draft_room_state import (
            ACTIVE_DRAFT_MODE_LIVE,
            get_active_draft_mode,
            get_canonical_draft_board,
            table_pick_count,
        )
    except ImportError:
        return ctx

    mode = get_active_draft_mode(session)
    ctx["active_mode"] = mode
    live_room: dict[str, Any] | None = None

    if mode == ACTIVE_DRAFT_MODE_LIVE:
        try:
            from live_draft_state import LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state

            prepare_live_draft_state(session)
            room = session.get(LIVE_DRAFT_ROOM_KEY)
            if isinstance(room, dict) and str(room.get("status") or "") in ("in_progress", "paused"):
                live_room = room
                ctx["live_draft_active"] = True
                try:
                    app = _import_baseball_app()
                    slot_fn = app.live_draft_current_slot
                except Exception:
                    slot_fn = None
                slot = None
                if slot_fn:
                    try:
                        slot = slot_fn(live_room)
                    except (IndexError, KeyError, TypeError):
                        slot = None
                if slot is None:
                    ctx["draft_complete"] = True
                else:
                    ctx["on_clock_team"] = str(slot.get("Team") or "").strip()
                    try:
                        ctx["current_pick"] = int(slot.get("Pick"))
                    except (TypeError, ValueError):
                        ctx["current_pick"] = None
        except ImportError:
            pass

    your_team = _your_team(session, live_room=live_room)
    ctx["your_team"] = your_team

    if live_room is not None:
        ctx["is_your_pick"] = bool(
            your_team and ctx.get("on_clock_team") and your_team == ctx["on_clock_team"]
        )
        return ctx

    board = get_canonical_draft_board(session)
    on_clock = _next_on_clock_pick_info(board)
    if on_clock is None:
        if not board.empty:
            ctx["board_full"] = table_pick_count(board) >= len(board)
        ctx["draft_complete"] = True
    else:
        ctx["on_clock_team"] = on_clock.get("on_clock_team") or ""
        ctx["current_pick"] = on_clock.get("pick")
        ctx["is_your_pick"] = bool(
            your_team and ctx["on_clock_team"] and your_team == ctx["on_clock_team"]
        )
    return ctx


def can_draft_player(session: dict[str, Any], player_name: str) -> tuple[bool, str]:
    """Return (allowed, human-readable reason). Never allows out-of-turn drafting."""
    name = str(player_name or "").strip()
    if not name:
        return False, "Select a player first."

    ctx = draft_action_context(session)
    if ctx.get("draft_complete"):
        return False, "Draft is complete."
    if ctx.get("board_full") and not ctx.get("live_draft_active"):
        return False, "Board is full."

    if not ctx.get("your_team"):
        return False, "Set your team in Draft Room settings."

    if not ctx.get("is_your_pick"):
        on_clock = ctx.get("on_clock_team") or "another team"
        pick_n = ctx.get("current_pick")
        if pick_n:
            return False, f"Not your pick (Pick {pick_n}: {on_clock})."
        return False, f"Not your pick ({on_clock} is on the clock)."

    try:
        from draft_room_state import get_all_drafted_player_names
    except ImportError:
        return False, "Draft board module unavailable."

    drafted = get_all_drafted_player_names(session)
    resolved = _resolve_player_name(name, drafted)
    if resolved in drafted or name in drafted:
        return False, f"{name} is already drafted."

    if ctx.get("live_draft_active"):
        ok, reason = _live_player_available(session, name)
        if not ok:
            return False, reason

    return True, ""


def _live_player_available(session: dict[str, Any], player_name: str) -> tuple[bool, str]:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if not isinstance(room, dict):
            return False, "No active live draft."
        app = _import_baseball_app()
        available = app.live_draft_get_available(room)
    except Exception as exc:
        return False, f"Live draft pool unavailable: {exc}"

    if available is None or getattr(available, "empty", True):
        return False, "No players available in the live draft pool."

    col = "fullName" if "fullName" in available.columns else "Player"
    names = available[col].dropna().astype(str).tolist()
    resolved = _resolve_player_name(player_name, names)
    if resolved not in names and player_name not in names:
        return False, f"{player_name} is not available."
    return True, ""


def _find_live_player_row(session: dict[str, Any], player_name: str) -> dict[str, Any] | None:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if not isinstance(room, dict):
            return None
        app = _import_baseball_app()
        available = app.live_draft_get_available(room)
    except Exception:
        return None

    if available is None or getattr(available, "empty", True):
        return None

    col = "fullName" if "fullName" in available.columns else "Player"
    target = str(player_name or "").strip().lower()
    for _, row in available.iterrows():
        full = str(row.get(col) or "").strip()
        if full.lower() == target or full == player_name:
            return row.to_dict()
    return None


def _draft_simulator(
    session: dict[str, Any],
    player_name: str,
    *,
    source: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "player": player_name,
        "source": source,
        "mode": "draft_room_simulator",
        "target_pick": None,
        "on_clock_team": None,
        "error": "",
        "message": "",
    }
    allowed, reason = can_draft_player(session, player_name)
    if not allowed:
        result["error"] = "not_allowed"
        result["message"] = reason
        return result

    try:
        from draft_room_state import (
            ACTIVE_DRAFT_MODE_MANUAL,
            assign_player_to_board_row,
            get_canonical_draft_board,
            set_canonical_draft_meta,
            table_pick_count,
        )
    except ImportError as exc:
        result["error"] = "import_failed"
        result["message"] = str(exc)
        return result

    board = get_canonical_draft_board(session)
    on_clock = _next_on_clock_pick_info(board)
    if on_clock is None:
        result["error"] = "board_full"
        result["message"] = "Board is full — no open pick rows."
        return result

    row_idx = on_clock["row_index"]
    result["target_pick"] = on_clock.get("pick")
    result["on_clock_team"] = on_clock.get("on_clock_team")

    assign_result = assign_player_to_board_row(session, row_idx, player_name)
    result.update(
        {
            k: assign_result.get(k)
            for k in ("before_pick_count", "after_pick_count", "target_row_index")
            if k in assign_result
        }
    )
    if not assign_result.get("ok"):
        result["error"] = assign_result.get("error") or "assign_failed"
        result["message"] = assign_result.get("message") or "Could not assign player to board."
        return result

    set_canonical_draft_meta(
        session,
        mode=ACTIVE_DRAFT_MODE_MANUAL,
        source=f"draft_player:{source}",
        pick_count=int(assign_result.get("after_pick_count") or table_pick_count(board)),
    )
    result["ok"] = True
    pick_n = result.get("target_pick") or assign_result.get("target_row_index")
    result["message"] = f"Drafted {player_name} on pick {pick_n}."
    return result


def _draft_live(
    session: dict[str, Any],
    player_name: str,
    *,
    source: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "player": player_name,
        "source": source,
        "mode": "live_draft_room",
        "target_pick": None,
        "on_clock_team": None,
        "error": "",
        "message": "",
    }
    allowed, reason = can_draft_player(session, player_name)
    if not allowed:
        result["error"] = "not_allowed"
        result["message"] = reason
        return result

    try:
        from draft_room_state import sync_live_draft_room_to_canonical_board
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state, write_canonical_live_draft_state
    except ImportError as exc:
        result["error"] = "import_failed"
        result["message"] = str(exc)
        return result

    prepare_live_draft_state(session)
    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if not isinstance(room, dict):
        result["error"] = "no_live_room"
        result["message"] = "No active live draft."
        return result

    try:
        app = _import_baseball_app()
        slot = app.live_draft_current_slot(room)
        make_pick = app.live_draft_make_pick
    except Exception as exc:
        result["error"] = "live_helpers"
        result["message"] = str(exc)
        return result

    if slot is None:
        result["error"] = "draft_complete"
        result["message"] = "Draft is already complete."
        return result

    result["on_clock_team"] = str(slot.get("Team") or "").strip()
    try:
        result["target_pick"] = int(slot.get("Pick"))
    except (TypeError, ValueError):
        pass

    player_row = _find_live_player_row(session, player_name)
    if not player_row:
        result["error"] = "player_not_available"
        result["message"] = f"{player_name} is not available."
        return result

    ok, msg = make_pick(room, player_row, verdict=f"Draft ({source})")
    if not ok:
        result["error"] = "live_make_pick_failed"
        result["message"] = msg
        return result

    session[LIVE_DRAFT_ROOM_KEY] = room
    write_canonical_live_draft_state(session, room, reason=f"draft_player:{source}", local_edit=True)
    sync_live_draft_room_to_canonical_board(session, room)

    result["ok"] = True
    result["message"] = msg
    return result


def draft_player(
    session: dict[str, Any],
    player_name: str,
    *,
    source: str = "draft_room",
    st_obj: Any = None,
) -> dict[str, Any]:
    """
    Unified draft action. Drafts only when it is the user's pick.

    Validates turn, writes board/live state, cleans queue, clears AMI cache, syncs.
    """
    name = str(player_name or "").strip()
    src = str(source or "draft_room").strip().lower()
    if src not in DRAFT_SOURCES:
        src = "draft_room"

    result: dict[str, Any] = {
        "ok": False,
        "player": name,
        "source": src,
        "error": "",
        "message": "",
    }
    if not name:
        result["error"] = "no_player"
        result["message"] = "Select a player first."
        return result

    ctx = draft_action_context(session)
    try:
        from draft_room_state import ACTIVE_DRAFT_MODE_LIVE
    except ImportError:
        ACTIVE_DRAFT_MODE_LIVE = "live_draft_room"

    if ctx.get("active_mode") == ACTIVE_DRAFT_MODE_LIVE and ctx.get("live_draft_active"):
        result = _draft_live(session, name, source=src)
    else:
        result = _draft_simulator(session, name, source=src)

    if result.get("ok"):
        side = _post_draft_side_effects(session, name, st_obj=st_obj, save_reason=f"draft_player:{src}")
        result["queue_after"] = side.get("queue_after")
        result["saved"] = side.get("saved", False)

    result["draft_context"] = draft_action_context(session)
    return result
