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
    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            team = active_participant_team(session)
            if team:
                return team
    except ImportError:
        pass
    if isinstance(live_room, dict):
        cfg = dict(live_room.get("config") or {})
        team = str(cfg.get("your_team") or cfg.get("user_team") or "").strip()
        if team:
            return team
    return str(session.get("room_your_team") or "").strip()


def compute_draft_turn_enabled(ctx: dict[str, Any]) -> bool:
    """Same turn gate as page-level draft_button_diagnostics (no player selected)."""
    draft_status = str(ctx.get("draft_status") or "").strip()
    if draft_status == "in_progress":
        return bool(ctx.get("is_your_pick") and str(ctx.get("your_team") or "").strip())
    return bool(
        ctx.get("is_your_pick")
        and str(ctx.get("your_team") or "").strip()
        and draft_status not in ("", "not_started", "complete")
        and not ctx.get("draft_complete")
    )


def resolve_manual_draft_panel_gate(
    session: dict[str, Any],
    ctx: dict[str, Any] | None = None,
    *,
    multiplayer: bool = False,
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn/progress gate for Live Draft Manual Draft panel — aligned with page diagnostics."""
    if ctx is None:
        ctx = draft_action_context(session)

    your_team = str(ctx.get("your_team") or "").strip()
    on_clock_team = str(ctx.get("on_clock_team") or "").strip()
    draft_status = str(ctx.get("draft_status") or "").strip()
    participant_team = ""
    assigned_team = your_team
    if multiplayer:
        try:
            from draft_room_context import active_participant_team

            participant_team = str(active_participant_team(session) or "").strip()
            if participant_team:
                assigned_team = participant_team
        except ImportError:
            pass

    live_room = room if isinstance(room, dict) else session.get("live_draft_room")
    current_pick_index = ctx.get("current_pick_index")
    if isinstance(live_room, dict) and current_pick_index is None:
        try:
            current_pick_index = int(live_room.get("current_pick_index"))
        except (TypeError, ValueError):
            current_pick_index = live_room.get("current_pick_index")

    board_size = 0
    room_total_picks = int(ctx.get("total_picks") or 0)
    room_draft_complete = False
    if isinstance(live_room, dict):
        board_size = len(live_room.get("draft_board") or [])
        try:
            from live_draft_safe_mode import is_draft_truly_complete, total_expected_picks

            room_total_picks = total_expected_picks(live_room)
            room_draft_complete = is_draft_truly_complete(live_room)
        except ImportError:
            room_total_picks = len(live_room.get("pick_order") or [])
            room_draft_complete = room_total_picks > 0 and board_size >= room_total_picks

    draft_enabled = compute_draft_turn_enabled(ctx) and not room_draft_complete
    disable_reason = ""
    if isinstance(live_room, dict) and str(live_room.get("status") or "") == "paused":
        draft_enabled = False
        disable_reason = "draft_paused"

    should_render = draft_enabled
    if not should_render and not disable_reason:
        if room_draft_complete:
            disable_reason = "draft_complete"
        elif multiplayer and not participant_team:
            disable_reason = "multiplayer_assignment_missing"
        elif not assigned_team and not your_team:
            disable_reason = "missing_assigned_team"
        elif draft_status in ("", "not_started") or room_draft_complete:
            disable_reason = "draft_not_in_progress"
        elif not ctx.get("is_your_pick"):
            if assigned_team and on_clock_team and assigned_team != on_clock_team:
                disable_reason = "turn_team_mismatch"
            elif your_team and on_clock_team and your_team != on_clock_team:
                disable_reason = "turn_team_mismatch"
            else:
                disable_reason = "not_your_turn"
        else:
            disable_reason = "draft_not_in_progress"

    return {
        "draft_enabled": draft_enabled,
        "draft_button_should_render": should_render,
        "is_my_turn": bool(ctx.get("is_your_pick")),
        "is_your_pick": bool(ctx.get("is_your_pick")),
        "draft_status": draft_status or None,
        "on_clock_team": on_clock_team or None,
        "your_team": your_team or None,
        "assigned_team": assigned_team or None,
        "participant_team": participant_team or None,
        "current_pick": ctx.get("current_pick"),
        "current_pick_index": current_pick_index,
        "total_picks": room_total_picks,
        "multiplayer_mode": bool(multiplayer),
        "draft_button_disable_reason": disable_reason or None,
        "draft_complete": room_draft_complete,
        "draft_complete_reason": "board_full" if room_draft_complete else (ctx.get("draft_complete_reason") or None),
        "live_draft_active": bool(ctx.get("live_draft_active")),
    }


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
            from draft_room_state import ACTIVE_DRAFT_SOURCE_LIVE, resolve_active_draft_source, persist_draft_board_to_storage

            if resolve_active_draft_source(session) != ACTIVE_DRAFT_SOURCE_LIVE:
                persist_draft_board_to_storage(
                    st_obj,
                    session,
                    session.get("draft_room_table"),
                    reason=save_reason,
                )
        except Exception as exc:
            log.warning("persist_draft_board_to_storage failed: %s", exc)
        try:
            from live_draft_state import LIVE_DRAFT_ROOM_KEY, commit_live_draft_room

            room = session.get(LIVE_DRAFT_ROOM_KEY)
            if isinstance(room, dict) and str(room.get("status") or "") in ("in_progress", "paused"):
                commit_live_draft_room(st_obj, session, room, reason=save_reason)
        except Exception as exc:
            log.warning("commit_live_draft_room failed: %s", exc)
        try:
            from baseball_persistent_state import force_save_baseball_state

            trace["saved"] = bool(force_save_baseball_state(st_obj, reason=save_reason))
        except Exception as exc:
            log.warning("force_save_baseball_state failed: %s", exc)
    return trace


def draft_action_context(session: dict[str, Any]) -> dict[str, Any]:
    """Resolved turn + board context for draft buttons and validation."""
    try:
        from draft_room_state import (
            ACTIVE_DRAFT_MODE_LIVE,
            ACTIVE_DRAFT_MODE_MANUAL,
            ACTIVE_DRAFT_SOURCE_LIVE,
            ACTIVE_DRAFT_SOURCE_SIMULATOR,
            get_canonical_draft_board,
            resolve_active_draft_source,
            table_pick_count,
        )
    except ImportError:
        ACTIVE_DRAFT_MODE_LIVE = "live_draft_room"
        ACTIVE_DRAFT_MODE_MANUAL = "draft_room_simulator"
        ACTIVE_DRAFT_SOURCE_LIVE = "live"
        ACTIVE_DRAFT_SOURCE_SIMULATOR = "simulator"

        def resolve_active_draft_source(_session: dict[str, Any]) -> str:
            return ACTIVE_DRAFT_SOURCE_SIMULATOR

        def get_canonical_draft_board(_session: dict[str, Any]) -> Any:
            return _session.get("draft_room_table")

        def table_pick_count(_table: Any) -> int:
            return 0

    source = resolve_active_draft_source(session)
    ctx: dict[str, Any] = {
        "active_draft_source": source,
        "active_mode": ACTIVE_DRAFT_MODE_LIVE if source == ACTIVE_DRAFT_SOURCE_LIVE else ACTIVE_DRAFT_MODE_MANUAL,
        "your_team": "",
        "on_clock_team": "",
        "current_pick": None,
        "is_your_pick": False,
        "draft_complete": False,
        "draft_complete_reason": "",
        "draft_status": "",
        "total_picks": 0,
        "board_full": False,
        "live_draft_active": source == ACTIVE_DRAFT_SOURCE_LIVE,
    }
    live_room: dict[str, Any] | None = None

    if source == ACTIVE_DRAFT_SOURCE_LIVE:
        try:
            from live_draft_state import LIVE_DRAFT_ROOM_KEY, analyze_live_draft_progress, prepare_live_draft_state, repair_stale_live_draft_progress

            if not session.get("_live_draft_manual_pick_in_flight"):
                prepare_live_draft_state(session)
            room = session.get(LIVE_DRAFT_ROOM_KEY)
            if isinstance(room, dict):
                try:
                    from live_draft_safe_mode import reconcile_live_draft_room

                    room = reconcile_live_draft_room(session, room).room
                except ImportError:
                    room = repair_stale_live_draft_progress(dict(room))
                    session[LIVE_DRAFT_ROOM_KEY] = room
                progress = analyze_live_draft_progress(room)
                ctx["draft_status"] = str(progress.get("draft_status") or "")
                ctx["draft_complete"] = bool(progress.get("draft_complete"))
                ctx["draft_complete_reason"] = str(progress.get("draft_complete_reason") or "")
                ctx["current_pick"] = progress.get("current_pick")
                ctx["on_clock_team"] = progress.get("on_clock_team") or ""
                ctx["total_picks"] = int(progress.get("total_picks") or 0)
                ctx["current_pick_index"] = progress.get("current_pick_index")
                if not progress.get("draft_complete"):
                    live_room = room
        except ImportError:
            pass

        your_team = _your_team(session, live_room=live_room)
        ctx["your_team"] = your_team
        ctx["is_your_pick"] = bool(
            your_team and ctx.get("on_clock_team") and your_team == ctx["on_clock_team"]
        )
        ctx["draft_enabled"] = compute_draft_turn_enabled(ctx)
        return ctx

    your_team = _your_team(session)
    ctx["your_team"] = your_team
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
    ctx["draft_enabled"] = compute_draft_turn_enabled(ctx)
    return ctx


def draft_button_diagnostics(session: dict[str, Any], player_name: str = "") -> dict[str, Any]:
    """Dev Mode: why draft buttons are enabled/disabled."""
    ctx = draft_action_context(session)
    allowed = False
    reason = ""
    disable_reason = ""
    name = str(player_name or "").strip()
    participant_team = ""
    assigned_team = ""
    commissioner_mode = False
    player_source_valid = None
    try:
        from draft_room_context import active_participant_team, is_multiplayer_draft_active

        if is_multiplayer_draft_active(session):
            participant_team = active_participant_team(session)
            assigned_team = participant_team
    except ImportError:
        pass
    try:
        from draft_source_validation import allow_free_pool_drafting

        commissioner_mode = bool(allow_free_pool_drafting(session, live_room=session.get("live_draft_room")))
    except ImportError:
        pass
    if name:
        gate = resolve_player_draft_gate(session, name)
        allowed = bool(gate.get("allowed"))
        reason = "" if allowed else str(gate.get("disable_message") or "")
        disable_reason = "" if allowed else str(gate.get("disable_reason") or "")
        try:
            from draft_source_validation import is_allowed_draft_source

            src_ok, src_reason, _ = is_allowed_draft_source(
                session,
                name,
                live_room=session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None,
            )
            player_source_valid = src_ok
            if not src_ok and not disable_reason:
                disable_reason = "other_validation_failure"
                reason = src_reason or reason
        except ImportError:
            player_source_valid = None
    else:
        if str(ctx.get("draft_status") or "") == "not_started":
            reason = "Draft has not started yet."
            disable_reason = "draft_not_started"
        elif ctx.get("draft_complete"):
            reason_code = str(ctx.get("draft_complete_reason") or "")
            if reason_code == "missing_pick_order":
                reason = "Draft pick order is missing."
                disable_reason = "missing_pick_order"
            elif reason_code == "pick_index_past_end":
                reason = "Draft pick index is past the final pick."
                disable_reason = "pick_index_past_end"
            else:
                reason = "Draft is complete."
                disable_reason = "draft_complete"
        elif ctx.get("board_full") and not ctx.get("live_draft_active"):
            reason = "Board is full."
            disable_reason = "board_full"
        elif not ctx.get("your_team"):
            reason = "Set your team in Draft Room settings."
            disable_reason = "participant_team_mismatch"
        elif not ctx.get("is_your_pick"):
            on_clock = ctx.get("on_clock_team") or "another team"
            pick_n = ctx.get("current_pick")
            reason = f"Not your pick (Pick {pick_n}: {on_clock})." if pick_n else f"Not your pick ({on_clock})."
            disable_reason = "not_your_turn"
        else:
            allowed = True
            reason = ""
    out = {
        "active_draft_source": ctx.get("active_draft_source"),
        "active_draft_mode": ctx.get("active_mode"),
        "your_team": ctx.get("your_team") or None,
        "assigned_team": assigned_team or ctx.get("your_team") or None,
        "participant_team": participant_team or ctx.get("your_team") or None,
        "on_clock_team": ctx.get("on_clock_team") or None,
        "current_pick": ctx.get("current_pick"),
        "is_my_turn": ctx.get("is_your_pick"),
        "is_your_pick": ctx.get("is_your_pick"),
        "commissioner_mode": commissioner_mode,
        "player_source_valid": player_source_valid,
        "draft_enabled": allowed if name else compute_draft_turn_enabled(ctx),
        "disable_reason": disable_reason or (None if allowed else _classify_disable_reason(reason)),
        "reason_if_disabled": None if allowed else (reason or "Cannot draft"),
        "sample_player_allowed": allowed if name else None,
        "draft_complete": ctx.get("draft_complete"),
        "board_full": ctx.get("board_full"),
        "live_draft_active": ctx.get("live_draft_active"),
        "draft_status": ctx.get("draft_status"),
        "total_picks": ctx.get("total_picks"),
        "draft_complete_reason": ctx.get("draft_complete_reason") or None,
    }
    room = session.get("live_draft_room")
    if isinstance(room, dict):
        col_diag = room.get("_live_draft_pool_column_diag")
        if isinstance(col_diag, dict):
            out["pool_duplicate_columns"] = col_diag.get("duplicate_columns")
            out["pool_deduped"] = col_diag.get("deduped")
        scoring_diag = room.get("_live_draft_pool_scoring_diag")
        if isinstance(scoring_diag, dict):
            out["pool_scoring_derived"] = scoring_diag.get("derived_columns")
    ui_diag = dict(session.get("_live_draft_ui_diag") or {})
    if ui_diag:
        out.update(
            {
                "draft_button_should_render": ui_diag.get("draft_button_should_render"),
                "draft_button_rendered": ui_diag.get("draft_button_rendered"),
                "draft_button_enabled": ui_diag.get("draft_button_enabled"),
                "draft_button_disable_reason": ui_diag.get("draft_button_disable_reason"),
                "player_action_panel_rendered": ui_diag.get("player_action_panel_rendered"),
                "available_player_count": ui_diag.get("available_player_count"),
                "filtered_player_count": ui_diag.get("filtered_player_count"),
                "candidate_count": ui_diag.get("candidate_count"),
                "selected_player": ui_diag.get("selected_player"),
                "draft_action_disable_reason": ui_diag.get("draft_action_disable_reason") or out.get("disable_reason"),
                "render_path": ui_diag.get("render_path"),
                "pool_source": ui_diag.get("pool_source"),
                "manual_draft_panel_skipped": ui_diag.get("manual_draft_panel_skipped"),
            }
        )
    return out


def _classify_disable_reason(reason: str) -> str:
    text = str(reason or "").strip().lower()
    if not text:
        return "unknown"
    if "not your pick" in text:
        return "not_your_turn"
    if "already drafted" in text:
        return "player_already_drafted"
    if "queue" in text or "watchlist" in text or "tracked" in text:
        return "player_not_in_queue_watchlist_tracked"
    if "team" in text or "membership" in text:
        return "participant_team_mismatch"
    if "not available" in text:
        return "player_already_drafted"
    return "multiplayer_membership_guard" if "membership" in text else text[:48].replace(" ", "_")


DISABLE_REASON_PRIORITY: tuple[str, ...] = (
    "already_drafted",
    "player_not_available",
    "draft_complete",
    "draft_not_started",
    "missing_team_assignment",
    "not_your_turn",
    "other_validation_failure",
)


def _draft_round_for_pick(session: dict[str, Any], pick_n: int | None) -> int | None:
    if pick_n is None:
        return None
    team_count = 0
    try:
        team_count = int(session.get("room_team_count") or 0)
    except (TypeError, ValueError):
        team_count = 0
    if team_count < 1:
        room = session.get("live_draft_room")
        if isinstance(room, dict):
            cfg = dict(room.get("config") or {})
            try:
                team_count = int(cfg.get("team_count") or 0)
            except (TypeError, ValueError):
                team_count = 0
            if team_count < 1:
                names = cfg.get("team_names") or cfg.get("teams") or []
                if isinstance(names, list):
                    team_count = len(names)
    if team_count < 1:
        return None
    return ((int(pick_n) - 1) // team_count) + 1


def draft_status_summary(session: dict[str, Any]) -> dict[str, Any]:
    """Sidebar-friendly round/pick/on-clock/timer snapshot for active drafts."""
    ctx = draft_action_context(session)
    pick = ctx.get("current_pick")
    try:
        pick_n = int(pick) if pick is not None else None
    except (TypeError, ValueError):
        pick_n = None
    on_clock = str(ctx.get("on_clock_team") or "").strip()
    if not on_clock and pick_n is not None and not ctx.get("draft_complete"):
        try:
            from draft_room_state import get_canonical_draft_board

            board = get_canonical_draft_board(session)
            if hasattr(board, "columns") and "Pick" in board.columns and "Team" in board.columns:
                match = board[board["Pick"].astype(int) == pick_n]
                if not match.empty:
                    on_clock = str(match.iloc[0].get("Team") or "").strip()
        except Exception:
            pass
    if not on_clock:
        room = session.get("live_draft_room")
        if isinstance(room, dict):
            try:
                from live_draft_state import analyze_live_draft_progress
                from live_draft_timer_logic import live_draft_current_slot

                progress = analyze_live_draft_progress(room)
                on_clock = str(progress.get("on_clock_team") or "").strip()
                if not on_clock:
                    slot = progress.get("slot") or live_draft_current_slot(room)
                    if isinstance(slot, dict):
                        on_clock = str(slot.get("Team") or "").strip()
                if not on_clock:
                    picks = room.get("pick_order") or []
                    idx = int(room.get("current_pick_index") or 0)
                    if 0 <= idx < len(picks) and isinstance(picks[idx], dict):
                        on_clock = str(picks[idx].get("Team") or "").strip()
            except ImportError:
                pass
    timer_seconds: int | None = None
    if ctx.get("live_draft_active"):
        room = session.get("live_draft_room")
        if isinstance(room, dict) and str(room.get("status") or "") == "in_progress":
            try:
                from live_draft_timer_logic import ensure_live_draft_timer_for_pick, live_draft_seconds_remaining

                ensure_live_draft_timer_for_pick(room)
                timer_seconds = int(live_draft_seconds_remaining(room))
            except ImportError:
                timer_seconds = None
    return {
        **ctx,
        "round": _draft_round_for_pick(session, pick_n),
        "pick": pick_n,
        "on_clock_team": on_clock or None,
        "is_my_turn": bool(ctx.get("is_your_pick")),
        "timer_seconds": timer_seconds,
        "has_active_draft": bool(
            not ctx.get("draft_complete")
            and (pick_n is not None or on_clock or str(ctx.get("draft_status") or "") == "in_progress")
        ),
    }


def _on_clock_team_from_live_room(session: dict[str, Any], room: dict[str, Any]) -> str:
    """Resolve fantasy on-clock team from live draft room slot (same source as room banner)."""
    if not isinstance(room, dict):
        return ""
    try:
        from live_draft_state import analyze_live_draft_progress
        from live_draft_timer_logic import live_draft_current_slot, resolve_live_draft_on_clock_slot

        progress = analyze_live_draft_progress(room)
        on_clock = str(progress.get("on_clock_team") or "").strip()
        if on_clock and on_clock != "—":
            return on_clock
        slot = progress.get("slot")
        if not isinstance(slot, dict):
            slot = resolve_live_draft_on_clock_slot(room) or live_draft_current_slot(room)
        if isinstance(slot, dict):
            on_clock = str(slot.get("Team") or "").strip()
            if on_clock and on_clock != "—":
                return on_clock
        picks = room.get("pick_order") or []
        idx = int(room.get("current_pick_index") or progress.get("current_pick_index") or 0)
        if 0 <= idx < len(picks) and isinstance(picks[idx], dict):
            on_clock = str(picks[idx].get("Team") or "").strip()
            if on_clock and on_clock != "—":
                return on_clock
    except ImportError:
        pass
    try:
        from draft_room_state import get_canonical_draft_board

        board = get_canonical_draft_board(session)
        info = _next_on_clock_pick_info(board)
        if info:
            return str(info.get("on_clock_team") or "").strip()
    except Exception:
        pass
    return ""


def resolve_on_clock_team_label(
    session: dict[str, Any],
    *,
    summary: dict[str, Any] | None = None,
) -> str:
    """Shared on-clock label for sidebar + status lines (live room slot is source of truth)."""
    snap = summary if isinstance(summary, dict) else draft_status_summary(session)
    on_clock = str(snap.get("on_clock_team") or "").strip()
    if on_clock and on_clock != "—":
        return on_clock

    room = session.get("live_draft_room")
    if isinstance(room, dict):
        on_clock = _on_clock_team_from_live_room(session, room)
    if on_clock:
        return on_clock

    pick_n = snap.get("pick") or snap.get("current_pick")
    try:
        pick_int = int(pick_n) if pick_n is not None else None
    except (TypeError, ValueError):
        pick_int = None
    if pick_int is not None and not snap.get("draft_complete"):
        try:
            from draft_room_state import get_canonical_draft_board

            board = get_canonical_draft_board(session)
            if hasattr(board, "columns") and "Pick" in board.columns and "Team" in board.columns:
                match = board[board["Pick"].astype(int) == pick_int]
                if not match.empty:
                    return str(match.iloc[0].get("Team") or "").strip()
            info = _next_on_clock_pick_info(board)
            if info:
                return str(info.get("on_clock_team") or "").strip()
        except Exception:
            pass
    return ""


def resolve_player_draft_gate(
    session: dict[str, Any],
    player_name: str = "",
    *,
    source: str = "",
) -> dict[str, Any]:
    """
    Unified draft permission for buttons — returns disable_reason using priority order.
    """
    name = str(player_name or "").strip()
    ctx = draft_action_context(session)
    gate: dict[str, Any] = {
        "allowed": False,
        "disable_reason": "",
        "disable_message": "",
        "is_my_turn": bool(ctx.get("is_your_pick")),
        "is_your_pick": bool(ctx.get("is_your_pick")),
        "on_clock_team": ctx.get("on_clock_team") or "",
        "your_team": ctx.get("your_team") or "",
        "current_pick": ctx.get("current_pick"),
        "draft_status": ctx.get("draft_status") or "",
        "draft_complete": bool(ctx.get("draft_complete")),
        "active_draft_source": ctx.get("active_draft_source"),
    }

    if name:
        try:
            from draft_room_state import lookup_drafted_player_info

            drafted = lookup_drafted_player_info(session, name)
        except ImportError:
            drafted = None
        if drafted:
            team = str(drafted.get("drafted_by_team") or "").strip()
            gate["disable_reason"] = "already_drafted"
            gate["disable_message"] = f"Already drafted by {team}" if team else "Already drafted"
            return gate

    live_room = session.get("live_draft_room")
    if isinstance(live_room, dict):
        try:
            from live_draft_safe_mode import is_draft_truly_complete, total_expected_picks

            total = total_expected_picks(live_room)
            if total > 0 and is_draft_truly_complete(live_room):
                gate["disable_reason"] = "draft_complete"
                gate["disable_message"] = "Draft is complete."
                return gate
        except ImportError:
            pass

    if ctx.get("draft_complete"):
        reason_code = str(ctx.get("draft_complete_reason") or "")
        if reason_code == "not_started":
            gate["disable_reason"] = "draft_not_started"
            gate["disable_message"] = "Draft has not started yet."
            return gate
        gate["disable_reason"] = "draft_complete"
        gate["disable_message"] = "Draft is complete."
        return gate

    if str(ctx.get("draft_status") or "") == "not_started":
        gate["disable_reason"] = "draft_not_started"
        gate["disable_message"] = "Draft has not started yet."
        return gate

    if isinstance(live_room, dict) and str(live_room.get("status") or "") == "paused":
        gate["disable_reason"] = "other_validation_failure"
        gate["disable_message"] = "Draft is paused — resume to pick."
        return gate

    if ctx.get("board_full") and not ctx.get("live_draft_active"):
        gate["disable_reason"] = "draft_complete"
        gate["disable_message"] = "Board is full."
        return gate

    if not ctx.get("your_team"):
        gate["disable_reason"] = "missing_team_assignment"
        gate["disable_message"] = "Set your team in Draft Room settings."
        return gate

    if name and ctx.get("live_draft_active"):
        ok, reason = _live_player_available(session, name)
        if not ok:
            gate["disable_reason"] = "player_not_available"
            gate["disable_message"] = reason or "Player is not available."
            return gate

    if not ctx.get("is_your_pick"):
        on_clock = str(ctx.get("on_clock_team") or "").strip() or "another team"
        pick_n = ctx.get("current_pick")
        gate["disable_reason"] = "not_your_turn"
        if pick_n:
            gate["disable_message"] = f"Waiting for {on_clock} (Pick {pick_n})"
        else:
            gate["disable_message"] = f"Waiting for {on_clock}"
        return gate

    if name:
        try:
            from draft_source_validation import is_allowed_draft_source

            src_ok, src_reason, _ = is_allowed_draft_source(
                session,
                name,
                live_room=live_room if isinstance(live_room, dict) else None,
            )
            if not src_ok:
                gate["disable_reason"] = "other_validation_failure"
                gate["disable_message"] = src_reason or "Cannot draft from this list."
                return gate
        except ImportError:
            pass

    gate["allowed"] = True
    gate["disable_reason"] = ""
    gate["disable_message"] = ""
    return gate


def player_list_status_hint(session: dict[str, Any], player_name: str) -> str:
    """Short status for watchlist/tracked rows (drafted players stay visible)."""
    gate = resolve_player_draft_gate(session, player_name)
    if gate.get("disable_reason") == "already_drafted":
        return str(gate.get("disable_message") or "Already drafted")
    if gate.get("allowed"):
        return ""
    if gate.get("disable_reason") == "not_your_turn":
        return str(gate.get("disable_message") or "Not your turn")
    return str(gate.get("disable_message") or "")


def can_draft_player(session: dict[str, Any], player_name: str) -> tuple[bool, str]:
    """Return (allowed, human-readable reason). Never allows out-of-turn drafting."""
    gate = resolve_player_draft_gate(session, player_name)
    if gate.get("allowed"):
        return True, ""
    return False, str(gate.get("disable_message") or "Cannot draft.")


def _live_player_available(session: dict[str, Any], player_name: str) -> tuple[bool, str]:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, live_draft_get_available

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if not isinstance(room, dict):
            return False, "No active live draft."
        available = live_draft_get_available(room)
    except Exception as exc:
        return False, f"Live draft pool unavailable: {exc}"

    if available is None or getattr(available, "empty", True):
        return False, "No players available in the live draft pool."

    col = "fullName" if "fullName" in available.columns else "Player"
    series = available[col]
    if getattr(series, "ndim", 1) > 1:
        series = series.iloc[:, 0]
    names = series.dropna().astype(str).tolist()
    resolved = _resolve_player_name(player_name, names)
    if resolved not in names and player_name not in names:
        return False, f"{player_name} is not available."
    return True, ""


def _find_live_player_by_id(session: dict[str, Any], player_id: str) -> dict[str, Any] | None:
    pid = str(player_id or "").strip()
    if not pid:
        return None
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, live_draft_get_available

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if not isinstance(room, dict):
            return None
        available = live_draft_get_available(room)
    except Exception:
        return None
    if available is None or getattr(available, "empty", True):
        return None
    id_col = "playerID" if "playerID" in available.columns else ("player_id" if "player_id" in available.columns else "")
    if not id_col:
        return None
    for _, row in available.iterrows():
        if str(row.get(id_col) or "").strip() == pid:
            return row.to_dict()
    return None


def _find_live_player_row(session: dict[str, Any], player_name: str) -> dict[str, Any] | None:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, live_draft_get_available

        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if not isinstance(room, dict):
            return None
        available = live_draft_get_available(room)
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
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics, set_live_draft_pick_notice
    except ImportError:
        record_draft_commit_diagnostics = None  # type: ignore[assignment,misc]
        set_live_draft_pick_notice = None  # type: ignore[assignment,misc]

    try:
        from live_draft_expired_pick import clear_autopick_backoff_for_manual
        from live_draft_pick_commit import commit_manual_live_pick
        from live_draft_safe_mode import clear_safe_mode_after_successful_pick, prepare_manual_pick_recovery
        from live_draft_timer_logic import live_draft_current_slot
    except ImportError:
        clear_autopick_backoff_for_manual = None  # type: ignore[assignment,misc]
        commit_manual_live_pick = None  # type: ignore[assignment,misc]
        prepare_manual_pick_recovery = None  # type: ignore[assignment,misc]
        clear_safe_mode_after_successful_pick = None  # type: ignore[assignment,misc]
        live_draft_current_slot = None  # type: ignore[assignment,misc]

    if prepare_manual_pick_recovery is not None:
        prepare_manual_pick_recovery(session)
        room = session.get("live_draft_room")
        if not isinstance(room, dict):
            result["error"] = "no_live_room"
            result["message"] = "No active live draft."
            return result

    allowed, reason = can_draft_player(session, player_name)
    if not allowed:
        result["error"] = "not_allowed"
        result["message"] = reason
        if record_draft_commit_diagnostics is not None:
            record_draft_commit_diagnostics(
                session,
                draft_player_called=True,
                manual_pick_attempted=True,
                manual_pick_success=False,
                manual_pick_error=reason,
                supabase_commit_error=reason,
            )
        if set_live_draft_pick_notice is not None:
            set_live_draft_pick_notice(session, "error", reason)
        return result

    try:
        from draft_room_state import sync_live_draft_room_to_canonical_board
        from live_draft_state import LIVE_DRAFT_ROOM_KEY, mark_live_draft_local_edit, write_canonical_live_draft_state
    except ImportError as exc:
        result["error"] = "import_failed"
        result["message"] = str(exc)
        return result

    room = session.get(LIVE_DRAFT_ROOM_KEY)
    if not isinstance(room, dict):
        result["error"] = "no_live_room"
        result["message"] = "No active live draft."
        return result

    mark_live_draft_local_edit(session)
    session["_live_draft_manual_pick_in_flight"] = True

    try:
        from live_draft_state import is_live_draft_locally_dirty

        local_dirty_before = is_live_draft_locally_dirty(session)
    except ImportError:
        local_dirty_before = True

    try:
        from draft_room_context import is_multiplayer_draft_active

        mp = is_multiplayer_draft_active(session)
    except ImportError:
        mp = False

    if record_draft_commit_diagnostics is not None:
        record_draft_commit_diagnostics(
            session,
            draft_button_clicked=True,
            selected_player_at_click=player_name,
            selected_player_name=player_name,
            draft_player_called=True,
            manual_pick_attempted=True,
            commit_path="shared_room" if mp else "single_user",
            manual_pick_commit_path="shared_room" if mp else "single_user",
            board_size_before=len(room.get("draft_board") or []),
            board_size_before_manual_pick=len(room.get("draft_board") or []),
            current_pick_index_before=int(room.get("current_pick_index") or 0),
            current_pick_index_before_manual_pick=int(room.get("current_pick_index") or 0),
            local_dirty_before_commit=local_dirty_before,
        )

    if clear_autopick_backoff_for_manual is not None:
        clear_autopick_backoff_for_manual(session, room)

    expected_revision: int | None = None
    if mp:
        try:
            from live_draft_pick_commit import sync_expected_revision

            expected_revision = sync_expected_revision(session)
            room = session.get(LIVE_DRAFT_ROOM_KEY)
            if not isinstance(room, dict):
                result["error"] = "no_live_room"
                result["message"] = "No active live draft."
                return result
            if record_draft_commit_diagnostics is not None:
                record_draft_commit_diagnostics(
                    session,
                    room_revision_before=expected_revision,
                    supabase_revision_before=expected_revision,
                )
        except ImportError:
            pass

    if live_draft_current_slot is None:
        result["error"] = "live_helpers"
        result["message"] = "Live draft helpers unavailable."
        return result

    slot = live_draft_current_slot(room)

    if slot is None:
        session.pop("_live_draft_manual_pick_in_flight", None)
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
        session.pop("_live_draft_manual_pick_in_flight", None)
        result["error"] = "player_not_available"
        result["message"] = f"{player_name} is not available."
        if set_live_draft_pick_notice is not None:
            set_live_draft_pick_notice(session, "error", result["message"])
        return result

    if record_draft_commit_diagnostics is not None:
        player_id = str(player_row.get("playerID") or player_row.get("player_id") or "").strip()
        record_draft_commit_diagnostics(session, selected_player_id=player_id or None)

    if mp:
        try:
            from draft_room_membership import validate_participant_may_draft
            from draft_source_validation import validate_shared_pick_commit

            ok_pick, pick_msg = validate_participant_may_draft(session, room, player_name=player_name)
            if record_draft_commit_diagnostics is not None:
                record_draft_commit_diagnostics(
                    session,
                    validate_participant_may_draft_result=ok_pick,
                    validate_participant_may_draft_message=pick_msg or None,
                )
            if not ok_pick:
                result["error"] = "membership_guard"
                result["message"] = pick_msg
                if set_live_draft_pick_notice is not None:
                    set_live_draft_pick_notice(session, "error", pick_msg)
                return result
            ok_val, val_msg = validate_shared_pick_commit(session, room, player_name)
            if record_draft_commit_diagnostics is not None:
                record_draft_commit_diagnostics(
                    session,
                    validate_shared_pick_commit_result=ok_val,
                    validate_shared_pick_commit_message=val_msg or None,
                    validation_result=ok_val,
                )
            if not ok_val:
                result["error"] = "validation_failed"
                result["message"] = val_msg
                if set_live_draft_pick_notice is not None:
                    set_live_draft_pick_notice(session, "error", val_msg)
                return result
        except ImportError:
            pass

    if commit_manual_live_pick is None:
        result["error"] = "live_helpers"
        result["message"] = "Live draft commit path unavailable."
        return result

    commit = commit_manual_live_pick(
        session,
        room,
        player_row,
        source=source,
        verdict=f"Draft ({source})",
    )
    try:
        from live_draft_state import check_manual_commit_overwrite, is_live_draft_locally_dirty, record_manual_pick_snapshot

        if commit.ok:
            record_manual_pick_snapshot(session, commit.board_size_after, commit.current_pick_index_after)
            check_manual_commit_overwrite(session, source="after_draft_live_commit")
        if record_draft_commit_diagnostics is not None:
            record_draft_commit_diagnostics(
                session,
                local_dirty_after_commit=is_live_draft_locally_dirty(session),
            )
    except ImportError:
        pass
    if record_draft_commit_diagnostics is not None:
        record_draft_commit_diagnostics(
            session,
            manual_pick_success=commit.ok,
            manual_pick_error=None if commit.ok else commit.message,
            manual_pick_commit_path=commit.commit_path,
            board_size_after=commit.board_size_after,
            board_size_after_manual_pick=commit.board_size_after,
            current_pick_index_after=commit.current_pick_index_after,
            current_pick_index_after_manual_pick=commit.current_pick_index_after,
            shared_room_commit_called=commit.commit_path == "shared_room",
            commit_shared_room_pick_called=commit.commit_path == "shared_room",
            supabase_commit_success=commit.ok,
            supabase_commit_error=None if commit.ok else commit.message,
            rerun_after_commit=True,
        )

    if not commit.ok:
        session.pop("_live_draft_manual_pick_in_flight", None)
        result["error"] = commit.error or "shared_commit_failed"
        result["message"] = commit.message
        if commit.error == "shared_commit_failed":
            session["_draft_room_conflict_notice"] = commit.message
        if set_live_draft_pick_notice is not None:
            set_live_draft_pick_notice(session, "error", commit.message)
        return result

    try:
        from live_draft_expired_pick import clear_autopick_state_for_pick_advance

        clear_autopick_state_for_pick_advance(session, commit.current_pick_index_after)
    except ImportError:
        pass

    room = session.get(LIVE_DRAFT_ROOM_KEY) or room
    result["ok"] = True
    result["message"] = commit.message if commit.message != "Pick saved." else f"Drafted {player_name}."
    session.pop("_live_draft_manual_pick_in_flight", None)
    try:
        from live_draft_ui_cache import invalidate_draft_assistant_scoring_cache, invalidate_live_draft_ui_caches

        invalidate_live_draft_ui_caches(session)
        invalidate_draft_assistant_scoring_cache(session)
    except ImportError:
        session.pop("_live_draft_rec_cache", None)
    if clear_safe_mode_after_successful_pick is not None:
        clear_safe_mode_after_successful_pick(session, room)
    if set_live_draft_pick_notice is not None:
        player_id = str(player_row.get("playerID") or player_row.get("player_id") or player_name).strip()
        pick_key = f"{commit.board_size_after}:{player_id}"
        set_live_draft_pick_notice(session, "success", result["message"], pick_key=pick_key)
    if record_draft_commit_diagnostics is not None:
        record_draft_commit_diagnostics(
            session,
            pick_saved_to_room=True,
        )
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
        from draft_room_state import ACTIVE_DRAFT_SOURCE_LIVE, resolve_active_draft_source
    except ImportError:
        resolve_active_draft_source = lambda _s: "simulator"  # noqa: E731
        ACTIVE_DRAFT_SOURCE_LIVE = "live"

    if resolve_active_draft_source(session) == ACTIVE_DRAFT_SOURCE_LIVE:
        result = _draft_live(session, name, source=src)
    else:
        result = _draft_simulator(session, name, source=src)

    if result.get("ok"):
        try:
            from page_perf_phases import session_perf_phase

            with session_perf_phase(session, "draft_pick_action"):
                side = _post_draft_side_effects(session, name, st_obj=st_obj, save_reason=f"draft_player:{src}")
        except ImportError:
            side = _post_draft_side_effects(session, name, st_obj=st_obj, save_reason=f"draft_player:{src}")
        result["queue_after"] = side.get("queue_after")
        result["saved"] = side.get("saved", False)

    result["draft_context"] = draft_action_context(session)
    return result
