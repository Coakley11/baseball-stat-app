"""Live Draft active-surface chrome — keep recommendation cards in the first viewport."""

from __future__ import annotations

from typing import Any

__all__ = ("live_draft_suppress_page_intro",)


def live_draft_suppress_page_intro(session: dict[str, Any] | None) -> bool:
    """True when Quick Guide / tutorial chrome should hide so cards stay on-screen.

    Human Solo Start lands on room_body with hero + tutorial + Quick Guide above the
    board/recs columns. On a normal laptop viewport those cards end up below the fold
    even when pool/top_rec/Add-to-Queue are already painted. Suppress intro chrome for
    active / lobby drafts only — setup keeps the full guide.

    Important: Streamlit ``st.session_state`` is Mapping-like but **not** a ``dict``
    subclass. Never coerce unknown session objects to ``{}`` — that wiped the live
    room and left intro chrome on for every human Solo path.
    """
    if session is None:
        return False
    try:
        room = session.get("live_draft_room")
    except Exception:
        return False
    if isinstance(room, dict):
        status = str(room.get("status") or "").strip().lower()
        # Prefer the room stamp over lifecycle edge cases — if a live/lobby room is
        # bound, intro chrome must not push recommendation cards below the fold.
        if status in {"in_progress", "paused", "not_started"}:
            return True
    try:
        from live_draft_completion import (
            LIFECYCLE_ACTIVE_DRAFT,
            LIFECYCLE_WAITING_SHARED_LOBBY,
            resolve_live_draft_lifecycle,
        )

        life = str(resolve_live_draft_lifecycle(session) or "").strip()
        return life in {LIFECYCLE_ACTIVE_DRAFT, LIFECYCLE_WAITING_SHARED_LOBBY}
    except ImportError:
        return False
