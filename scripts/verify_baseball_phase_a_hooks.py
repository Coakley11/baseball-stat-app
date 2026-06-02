#!/usr/bin/env python3
"""Smoke-check Baseball Phase A activity hooks (no Streamlit UI)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVENTS = (
    ("log_player_comparison", ("Aaron Judge", "Juan Soto"), "player_comparison"),
    ("log_projection_report", {"style": "Balanced", "player_count": 120}, "projection_report"),
    ("log_draft_prep", {"context": "5x5 Roto", "teams": "4-team"}, "draft_prep"),
    ("log_roster_build", {"team": "Team A"}, "roster_build"),
    ("log_trade_analysis", {"give": ["Judge"], "get": ["Soto"], "verdict": "Fair"}, "trade_analysis"),
    ("log_trend_analysis", {"player": ""}, "trend_analysis"),
    ("log_breakout_analysis", {"count": 10}, "breakout_analysis"),
    ("log_sleeper_research", {"count": 15}, "sleeper_research"),
)


def main() -> int:
    recorded: list[tuple[str, str]] = []

    def capture(app: str, event: str, **kwargs) -> None:
        recorded.append((app, event))

    import baseball_activity as ba

    with patch.object(ba, "record_activity", side_effect=capture, create=True):
        with patch("suite_activity_client.record_activity", side_effect=capture):
            for fn_name, args, expected in EVENTS:
                fn = getattr(ba, fn_name)
                if isinstance(args, dict):
                    fn(**args)
                elif isinstance(args, tuple):
                    fn(*args)
                else:
                    fn()

    seen = {ev for _app, ev in recorded}
    missing = [ev for _fn, _a, ev in EVENTS if ev not in seen]
    if missing:
        print("FAIL: events not recorded:", ", ".join(missing))
        print("Recorded:", recorded)
        return 1

    print("OK: all Phase A baseball events recorded via baseball_activity")
    for _app, ev in recorded:
        print(f"  - {ev}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
