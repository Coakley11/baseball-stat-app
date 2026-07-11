#!/usr/bin/env python3
"""Fast startup import smoke — avoids full streamlit_app.py import."""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODULES = (
    "player_trade_constants",
    "player_actions",
    "player_trade_context",
    "player_trade_bridge",
    "fantasy_weekly_hitter_scoring",
)


def main() -> int:
    failed = 0
    for name in MODULES:
        t0 = time.perf_counter()
        try:
            importlib.import_module(name)
            elapsed = time.perf_counter() - t0
            print(f"PASS {name} ({elapsed:.2f}s)")
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"FAIL {name} ({elapsed:.2f}s): {type(exc).__name__}: {exc}")
            failed += 1

    from player_trade_bridge import (
        TRADE_ACTION_ACQUIRE,
        complete_trade_acquire_flow,
        format_roster_context_label,
        player_trade_shortcut_eligible,
        start_trade_acquire_flow,
    )

    assert TRADE_ACTION_ACQUIRE == "acquire"
    for fn in (
        complete_trade_acquire_flow,
        format_roster_context_label,
        player_trade_shortcut_eligible,
        start_trade_acquire_flow,
    ):
        assert callable(fn)
    print("PASS streamlit_app trade import contract (via bridge)")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
