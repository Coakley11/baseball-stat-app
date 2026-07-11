"""Startup-safe bridge for player trade helpers (defers heavy import chain)."""

from __future__ import annotations

from typing import Any, Callable

from player_trade_constants import (
    TRADE_ACTION_ACQUIRE,
    TRADE_ACTION_TRADE_AWAY,
    TRADE_FLOW_SESSION_KEY,
)

_MODULE: Any = None
_IMPORT_ERROR: BaseException | None = None


def trade_import_error_message() -> str:
    """Human-readable import failure for developer diagnostics."""
    if _IMPORT_ERROR is None:
        return ""
    return f"{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}"


def _load() -> Any:
    global _MODULE, _IMPORT_ERROR
    if _MODULE is not None:
        return _MODULE
    if _IMPORT_ERROR is not None:
        raise _IMPORT_ERROR
    try:
        import player_trade_context as module

        _MODULE = module
        return module
    except BaseException as exc:
        _IMPORT_ERROR = exc
        raise


def complete_trade_acquire_flow(
    session: dict[str, Any],
    *,
    mode: str | None = None,
    context_id: str | None = None,
) -> str:
    try:
        return _load().complete_trade_acquire_flow(session, mode=mode, context_id=context_id)
    except Exception as exc:
        return f"Trade / Acquire unavailable: {type(exc).__name__}: {exc}"


def format_roster_context_label(ctx: dict[str, Any]) -> str:
    return _load().format_roster_context_label(ctx)


def player_trade_shortcut_eligible(session: dict[str, Any], player_name: str) -> tuple[bool, str]:
    try:
        return _load().player_trade_shortcut_eligible(session, player_name)
    except Exception as exc:
        return False, f"Trade shortcuts unavailable: {type(exc).__name__}: {exc}"


def start_trade_acquire_flow(
    session: dict[str, Any],
    *,
    player_name: str,
    key_prefix: str,
) -> str | None:
    try:
        return _load().start_trade_acquire_flow(
            session,
            player_name=player_name,
            key_prefix=key_prefix,
        )
    except Exception as exc:
        return f"Trade / Acquire unavailable: {type(exc).__name__}: {exc}"


__all__ = (
    "TRADE_ACTION_ACQUIRE",
    "TRADE_ACTION_TRADE_AWAY",
    "TRADE_FLOW_SESSION_KEY",
    "complete_trade_acquire_flow",
    "format_roster_context_label",
    "player_trade_shortcut_eligible",
    "start_trade_acquire_flow",
    "trade_import_error_message",
)
