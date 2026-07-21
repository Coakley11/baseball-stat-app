"""Live Draft completion → Fantasy Lineup origin preservation."""

from __future__ import annotations

import unittest
from pathlib import Path

from fantasy_league_context import CONTEXT_TYPE_LIVE_DRAFT_RESULT, CREATION_ORIGIN_LIVE_DRAFT_ROOM
from fantasy_league_lineup_format import needs_lineup_format_setup
from live_draft_lineup_config import live_draft_skips_lineup_format_setup

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "live_draft_lineup_workflow_apptest.py"


class LiveDraftLineupWorkflowTests(unittest.TestCase):
    def test_completed_live_draft_context_skips_position_setup(self) -> None:
        from fantasy_league_context import create_league_context_from_live_room
        from tests.live_draft_accelerated_harness import (
            DraftRunMetrics,
            accelerated_draft_patches,
            build_four_team_eight_round_room,
            expire_one_pick,
            seed_session,
        )

        room = build_four_team_eight_round_room(timer_seconds=5)
        session = seed_session(room)
        metrics = DraftRunMetrics()
        with accelerated_draft_patches():
            while str(room.get("status") or "") != "complete":
                expire_one_pick(session, room, metrics)
        ctx = create_league_context_from_live_room(
            session,
            room,
            my_team_name="Team A",
            league_name="Harness League",
            source_draft_id="LINEUP-HARNESS",
            persist=False,
        )
        self.assertEqual(ctx.get("context_type"), CONTEXT_TYPE_LIVE_DRAFT_RESULT)
        meta = dict(ctx.get("metadata") or {})
        self.assertEqual(meta.get("creation_origin"), CREATION_ORIGIN_LIVE_DRAFT_ROOM)
        self.assertFalse(needs_lineup_format_setup(ctx))
        self.assertTrue(live_draft_skips_lineup_format_setup(ctx))
        roster_settings = dict(ctx.get("roster_settings") or {})
        lineup_meta = dict(roster_settings.get("live_draft_lineup_config") or {})
        self.assertGreater(int(lineup_meta.get("starter_count") or 0), 0)
        self.assertIn("roster_slots", roster_settings)

    def test_lineup_workflow_apptest_skips_choose_positions(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE), default_timeout=120)
        at.run()
        self.assertFalse(at.exception)
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("Choose Lineup Positions", markdown)
        self.assertIn("FORMAT_READY=True", markdown)
        self.assertIn("NEEDS_SETUP=False", markdown)


if __name__ == "__main__":
    unittest.main()
