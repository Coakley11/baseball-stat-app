"""Trade / Acquire session constants — import-safe (no app dependencies)."""

from __future__ import annotations

TRADE_FLOW_SESSION_KEY = "_player_trade_acquire_flow"
TRADE_ACTION_ACQUIRE = "acquire"
TRADE_ACTION_TRADE_AWAY = "trade_away"
WAIVER_ACTION_PLAN_ADD = "plan_add"
WAIVER_ACTION_PLAN_DROP = "plan_drop"

__all__ = (
    "TRADE_FLOW_SESSION_KEY",
    "TRADE_ACTION_ACQUIRE",
    "TRADE_ACTION_TRADE_AWAY",
    "WAIVER_ACTION_PLAN_ADD",
    "WAIVER_ACTION_PLAN_DROP",
)
