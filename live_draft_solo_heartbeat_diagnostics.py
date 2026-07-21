"""Per-tick Solo heartbeat diagnostics for Cloud acceptance and expire debugging."""

from __future__ import annotations

import time
from typing import Any

SOLO_HEARTBEAT_TICK_LOG_KEY = "_solo_heartbeat_tick_log"
SOLO_HEARTBEAT_LAST_TICK_AT_KEY = "_solo_heartbeat_last_tick_at"
SOLO_HEARTBEAT_LAST_ERROR_KEY = "_solo_heartbeat_last_error"
MAX_TICK_LOG = 240


def _room_board_len(room: dict[str, Any] | None) -> int:
    if not isinstance(room, dict):
        return 0
    board = room.get("draft_board") or []
    return len(board) if isinstance(board, list) else 0


def log_solo_heartbeat_tick(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    phase: str,
    remaining: int | None = None,
    deadline: float | None = None,
    expiration_claimed: str = "",
    auto_pick_attempted: bool = False,
    auto_pick_result: str = "",
    commit_confirmed: bool = False,
    new_deadline: float | None = None,
    snapshot_rebuilt: bool = False,
    rerender_requested: bool = False,
    rerender_completed: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = time.time()
    session[SOLO_HEARTBEAT_LAST_TICK_AT_KEY] = now
    live = room if isinstance(room, dict) else None
    row: dict[str, Any] = {
        "ts": now,
        "server_time": now,
        "phase": str(phase),
        "timer_deadline": deadline if deadline is not None else (live.get("timer_deadline") if live else None),
        "remaining_seconds": remaining,
        "draft_status": str(live.get("status") or "") if live else "",
        "pick_index": int(live.get("current_pick_index") or 0) if live else 0,
        "board_length": _room_board_len(live),
        "expiration_claimed": expiration_claimed or str(live.get("_solo_expire_applied") or "") if live else "",
        "auto_pick_attempted": bool(auto_pick_attempted),
        "auto_pick_result": str(auto_pick_result or "")[:240],
        "commit_confirmed": bool(commit_confirmed),
        "new_deadline": new_deadline,
        "snapshot_rebuilt": bool(snapshot_rebuilt),
        "rerender_requested": bool(rerender_requested),
        "rerender_completed": bool(rerender_completed),
        "tick": int(session.get("_solo_live_draft_heartbeat_tick") or 0),
    }
    if extra:
        row.update(extra)
    log = list(session.get(SOLO_HEARTBEAT_TICK_LOG_KEY) or [])
    log.append(row)
    session[SOLO_HEARTBEAT_TICK_LOG_KEY] = log[-MAX_TICK_LOG:]
    return row


def note_solo_heartbeat_error(session: dict[str, Any], exc: BaseException) -> None:
    session[SOLO_HEARTBEAT_LAST_ERROR_KEY] = {
        "ts": time.time(),
        "type": type(exc).__name__,
        "message": str(exc)[:400],
    }


def solo_heartbeat_recent(session: dict[str, Any], *, max_age_sec: float = 3.0) -> bool:
    last = float(session.get(SOLO_HEARTBEAT_LAST_TICK_AT_KEY) or 0.0)
    if not last:
        return False
    return (time.time() - last) < float(max_age_sec)


def last_heartbeat_tick_summary(session: dict[str, Any]) -> dict[str, Any]:
    log = list(session.get(SOLO_HEARTBEAT_TICK_LOG_KEY) or [])
    err = session.get(SOLO_HEARTBEAT_LAST_ERROR_KEY)
    return {
        "last_tick_at": session.get(SOLO_HEARTBEAT_LAST_TICK_AT_KEY),
        "recent": solo_heartbeat_recent(session),
        "last_row": log[-1] if log else {},
        "error": err if isinstance(err, dict) else None,
        "rows": len(log),
    }
