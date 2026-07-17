"""Optional system messages for Live Draft chat events (deduped, non-flooding)."""

from __future__ import annotations

from typing import Any

from live_draft_chat import append_live_draft_chat_message


def maybe_post_draft_system_message(
    session: dict[str, Any],
    event: str,
    *,
    detail: str = "",
    pick_index: int | None = None,
    team: str = "",
) -> None:
    """Post a system chat line for important draft events. Safe no-op on failure."""
    try:
        from draft_room_context import is_multiplayer_draft_active

        if not is_multiplayer_draft_active(session):
            return
    except ImportError:
        return

    event_key = str(event or "").strip().lower()
    text = ""
    system_key = ""
    if event_key == "draft_started":
        text = "Draft started."
        system_key = "draft_started"
    elif event_key == "draft_paused":
        text = "Draft paused."
        system_key = f"draft_paused:{pick_index}"
    elif event_key == "draft_resumed":
        text = "Draft resumed."
        system_key = f"draft_resumed:{pick_index}"
    elif event_key in ("on_the_clock", "team_on_clock"):
        team_name = str(team or "").strip() or "A team"
        text = f"{team_name} is on the clock."
        # One on-the-clock notice per pick index — never flood.
        system_key = f"on_clock:{int(pick_index if pick_index is not None else -1)}"
    elif event_key in ("manual_pick", "pick"):
        text = str(detail or "A manual pick was made.").strip()
        system_key = f"manual_pick:{int(pick_index if pick_index is not None else -1)}:{text[:40]}"
    elif event_key in ("auto_pick", "autopick"):
        text = str(detail or "An auto-pick was made.").strip()
        system_key = f"auto_pick:{int(pick_index if pick_index is not None else -1)}:{text[:40]}"
    elif event_key in ("team_joined", "team_claimed"):
        team_name = str(team or detail or "A manager").strip()
        text = f"{team_name} joined the draft."
        system_key = f"joined:{team_name.lower()}"
    elif event_key in ("draft_completed", "draft_complete"):
        text = "Draft completed."
        system_key = "draft_completed"
    else:
        return

    if not text:
        return
    try:
        append_live_draft_chat_message(
            session,
            text,
            message_type="system",
            system_key=system_key,
        )
    except Exception:
        pass
