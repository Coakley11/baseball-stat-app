#!/usr/bin/env python3
"""Fantasy Lineup Assistant performance baseline — cold/warm phase timings.

Run from repo root:
  python scripts/profile_lineup_assistant_baseline.py
"""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fresh_session() -> dict:
    from fantasy_league_context import (
        CONTEXT_TYPE_REAL_LEAGUE,
        create_league_context,
        set_active_league_context,
        upsert_league_context,
    )
    from fantasy_league_lineup_format import apply_lineup_format_to_context, CONFIG_SOURCE_UPLOADED

    session: dict = {"_page_perf_ns": {"started_at": time.perf_counter(), "page": "Fantasy Lineup Assistant", "timings": {}}}
    board = pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "Corner Bat", "Pick": 1, "Primary Position": "1B"},
            {"Team": "Daniel", "Player": "Middle Man", "Pick": 2, "Primary Position": "SS"},
            {"Team": "Daniel", "Player": "Fly Ball", "Pick": 3, "Primary Position": "OF"},
        ]
    )
    ctx = create_league_context(
        league_context_id="live:perf",
        context_type=CONTEXT_TYPE_REAL_LEAGUE,
        league_name="Perf League",
        my_team_name="Daniel",
        league_rosters={"Daniel": board.to_dict("records")},
        display_name="Perf League",
    )
    ctx = apply_lineup_format_to_context(
        ctx,
        lineup_slots=["1B", "SS", "OF"],
        roster_capacity=3,
        configured_by="daniel",
        configuration_source=CONFIG_SOURCE_UPLOADED,
    )
    upsert_league_context(session, ctx)
    set_active_league_context(session, "live:perf")
    return session


def _roster_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "Corner Bat", "Primary Position": "1B", "Team": "Daniel"},
            {"Player": "Middle Man", "Primary Position": "SS", "Team": "Daniel"},
            {"Player": "Fly Ball", "Primary Position": "OF", "Team": "Daniel"},
        ]
    )


def _timed(label: str, fn) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000.0


def profile_lineup(*, warm: bool) -> dict[str, float]:
    from fantasy_league_lineup_format import resolve_lineup_page_context
    from fantasy_lineup_interactive_board import build_interactive_board_payload
    from fantasy_lineup_ui import build_slot_key_labels, slot_key_labels_as_tuples
    from fantasy_weekly_lineup import get_saved_weekly_lineup, persist_weekly_lineup_draft
    from fantasy_weekly_lineup_ui import ensure_canonical_assignments

    session = _fresh_session()
    if warm:
        resolve_lineup_page_context(session)

    times: dict[str, float] = {}
    times["1_active_context_load_ms"] = _timed(
        "ctx",
        lambda: resolve_lineup_page_context(session),
    )
    context = resolve_lineup_page_context(session)
    assert context is not None

    times["6_weekly_lineup_read_ms"] = _timed(
        "read",
        lambda: get_saved_weekly_lineup(context, 1, team="Daniel", session=session),
    )

    slot_labels = build_slot_key_labels(["1B", "SS", "OF"])
    slot_keys = slot_key_labels_as_tuples(slot_labels)
    roster = _roster_df()
    assignments = ensure_canonical_assignments(
        session,
        canon_key="weekly_lineup_canon_1",
        slot_keys=slot_keys,
        saved_assignments={},
    )

    times["7_board_payload_ms"] = _timed(
        "payload",
        lambda: build_interactive_board_payload(
            slot_labels,
            assignments,
            roster,
            editable=True,
            session=session,
        ),
    )

    with patch("baseball_persistent_state.force_save_baseball_state"):
        times["8_draft_persist_ms"] = _timed(
            "persist",
            lambda: persist_weekly_lineup_draft(
                session,
                week=1,
                slots=["1B", "SS", "OF"],
                assignments={"1B": "Corner Bat", "SS": "", "OF": ""},
                my_team="Daniel",
                roster_df=roster,
            ),
        )
        times["8_draft_persist_repeat_ms"] = _timed(
            "persist_repeat",
            lambda: persist_weekly_lineup_draft(
                session,
                week=1,
                slots=["1B", "SS", "OF"],
                assignments={"1B": "Corner Bat", "SS": "", "OF": ""},
                my_team="Daniel",
                roster_df=roster,
            ),
        )

    times["7_board_payload_warm_ms"] = _timed(
        "payload_warm",
        lambda: build_interactive_board_payload(
            slot_labels,
            assignments,
            roster,
            editable=True,
            session=session,
        ),
    )

    times["page_wall_clock_ms"] = sum(
        v for k, v in times.items() if k.endswith("_ms") and "repeat" not in k and "warm" not in k
    )
    return times


def main() -> int:
    with patch("page_perf_phases.dev_perf_enabled", return_value=True):
        print("=== Fantasy Lineup Assistant baseline ===\n")
        cold = profile_lineup(warm=False)
        warm = profile_lineup(warm=True)
        print("Cold path:")
        for k, v in sorted(cold.items()):
            print(f"  {k}: {v:.1f} ms")
        print("\nWarm/cached path:")
        for k, v in sorted(warm.items()):
            print(f"  {k}: {v:.1f} ms")
        print(
            "\nNotes: shared sync/hydrate are no-ops without shared store in this fixture; "
            "persist_repeat measures skip-save when assignments unchanged."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
