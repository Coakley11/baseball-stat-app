"""Boundary instrumentation for timer-zero → auto-pick → advance."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_PROBE = Path(__file__).resolve().parent / "data" / "tb_probe" / "timer_zero_lifecycle.jsonl"


def note_timer_zero_lifecycle(
    session: dict[str, Any] | None,
    boundary: str,
    *,
    room: dict[str, Any] | None = None,
    expiration_token: str = "",
    **extra: Any,
) -> None:
    """Append one JSONL lifecycle event (best-effort; never raises)."""
    try:
        room = room if isinstance(room, dict) else {}
        payload: dict[str, Any] = {
            "ts": time.time(),
            "boundary": str(boundary or ""),
            "expiration_token": str(expiration_token or "")[:120],
            "status": str(room.get("status") or ""),
            "pick_index": int(room.get("current_pick_index") or 0),
            "board_len": len(room.get("draft_board") or []),
            "timer_deadline": room.get("timer_deadline"),
        }
        try:
            from live_draft_timer_logic import live_draft_seconds_remaining

            payload["seconds_remaining"] = int(live_draft_seconds_remaining(room))
        except Exception:
            payload["seconds_remaining"] = None
        for k, v in extra.items():
            if k not in payload:
                try:
                    json.dumps(v)
                    payload[k] = v
                except Exception:
                    payload[k] = str(v)[:200]
        if isinstance(session, dict):
            hist = session.setdefault("_timer_zero_lifecycle", [])
            if isinstance(hist, list):
                hist.append(payload)
                del hist[:-40]
        _PROBE.parent.mkdir(parents=True, exist_ok=True)
        with _PROBE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
