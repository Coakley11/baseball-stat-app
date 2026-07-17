"""Optional system messages for Live Draft chat — disabled for ordinary draft activity."""

from __future__ import annotations

from typing import Any


def maybe_post_draft_system_message(
    session: dict[str, Any],
    event: str,
    *,
    detail: str = "",
    pick_index: int | None = None,
    team: str = "",
) -> None:
    """No-op: automatic draft-event chat clutter is disabled.

    Kept as a stable import surface so callers do not break. Ordinary pick / clock /
    pause / resume events must not flood the shared chat transcript.
    """
    _ = (session, event, detail, pick_index, team)
    return
