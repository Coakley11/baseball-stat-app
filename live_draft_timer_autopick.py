"""Timer auto-pick orchestration — delegates to expired-pick state machine."""

from __future__ import annotations

from typing import Any

from live_draft_expired_pick import EXPIRED_PICK_PENDING_KEY, handle_expired_pick_on_page

# Backward-compatible alias
LIVE_DRAFT_TIMER_EXPIRED_KEY = EXPIRED_PICK_PENDING_KEY


def maybe_timer_autopick(session: dict[str, Any], room: dict[str, Any], *, source: str) -> tuple[bool, str]:
    """Legacy entry point — use handle_expired_pick_on_page in new code."""
    result = handle_expired_pick_on_page(session, room, source=source)
    if result.ok:
        return True, result.message
    if result.error:
        return False, result.error
    return False, ""
