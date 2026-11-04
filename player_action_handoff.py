"""Preserve Compare / Trend handoffs when a button callback cannot resolve a label."""

from __future__ import annotations

from typing import Any

WAIVER_ACTION_PLAYER_KEY = "waiver_action_player"
WAIVER_ACTION_KIND_KEY = "waiver_action_kind"
WAIVER_ACTION_NOTICE_KEY = "waiver_action_notice"
TREND_UNAVAILABLE_KEY = "trend_unavailable_notice"
COMPARE_UNAVAILABLE_KEY = "compare_unavailable_notice"


def remember_player_action(session: dict[str, Any], player: str, action: str) -> None:
    session[WAIVER_ACTION_PLAYER_KEY] = str(player or "").strip()
    session[WAIVER_ACTION_KIND_KEY] = str(action or "").strip()


def queue_unresolved_trend(session: dict[str, Any], player: str, message: str) -> str:
    name = str(player or "").strip() or "That player"
    session["pending_trend_player"] = name
    session[TREND_UNAVAILABLE_KEY] = message or (
        f"{name} does not have enough recent seasons for a trend chart."
    )
    session[WAIVER_ACTION_NOTICE_KEY] = session[TREND_UNAVAILABLE_KEY]
    return "Trend Value"


def queue_unresolved_compare(session: dict[str, Any], player: str, message: str) -> str:
    name = str(player or "").strip()
    session["pending_compare_players"] = [name] if name else []
    session[COMPARE_UNAVAILABLE_KEY] = message or (
        f"Could not match {name or 'that player'} in the comparison database."
    )
    session[WAIVER_ACTION_NOTICE_KEY] = session[COMPARE_UNAVAILABLE_KEY]
    return "Comparison Tool"
