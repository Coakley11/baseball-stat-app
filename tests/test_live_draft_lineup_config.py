"""Tests for Live Draft lineup configuration persistence and repair."""

from __future__ import annotations

import unittest

from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CREATION_ORIGIN_LIVE_DRAFT_ROOM,
    context_has_roster_slots,
    resolve_context_lineup_slots,
    upsert_league_context,
)
from fantasy_league_lineup_format import needs_lineup_format_setup
from live_draft_lineup_config import (
    KNOWN_ROBINS_DRAFT_ID,
    STANDARD_10_HITTER_SLOTS,
    build_live_draft_slot_config,
    is_live_draft_league_context,
    live_draft_skips_lineup_format_setup,
    repair_live_draft_lineup_config_for_context,
)

class LiveDraftLineupConfigTests(unittest.TestCase):
    def _robins_context_without_slots(self) -> dict:
        return {
            "league_context_id": "archive:c6810611c73e",
            "context_type": CONTEXT_TYPE_LIVE_DRAFT_RESULT,
            "metadata": {
                "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
                "source_draft_id": KNOWN_ROBINS_DRAFT_ID,
            },
            "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
            "league_rosters": {
                "Donny": [{"name": f"P{i}"} for i in range(10)],
                "Team B": [{"name": f"B{i}"} for i in range(10)],
            },
            "roster_settings": {},
        }

    def test_completed_live_draft_gets_nine_starter_slots(self) -> None:
        session: dict = {"draft_archive_teams": [], "fantasy_league_context_state": {"contexts": {}}}
        ctx = self._robins_context_without_slots()
        upsert_league_context(session, ctx, mark_persist_authoritative=True)
        trace = repair_live_draft_lineup_config_for_context(
            session,
            draft_id=KNOWN_ROBINS_DRAFT_ID,
            allow_standard_fallback=True,
        )
        self.assertTrue(trace.get("repaired"))
        from fantasy_league_context import get_league_context

        repaired = get_league_context(session, "archive:c6810611c73e")
        self.assertTrue(context_has_roster_slots(repaired))
        slots = resolve_context_lineup_slots(repaired)
        self.assertIsNotNone(slots)
        assert slots is not None
        self.assertEqual(len(slots), 9)

    def test_lineup_assistant_skips_position_setup_for_live_draft(self) -> None:
        session: dict = {"draft_archive_teams": [], "fantasy_league_context_state": {"contexts": {}}}
        ctx = self._robins_context_without_slots()
        upsert_league_context(session, ctx, mark_persist_authoritative=True)
        repair_live_draft_lineup_config_for_context(
            session,
            draft_id=KNOWN_ROBINS_DRAFT_ID,
            allow_standard_fallback=True,
        )
        from fantasy_league_context import get_league_context

        repaired = get_league_context(session, "archive:c6810611c73e")
        self.assertFalse(needs_lineup_format_setup(repaired))
        self.assertTrue(live_draft_skips_lineup_format_setup(repaired))

    def test_standard_fallback_matches_robins_ten_player_format(self) -> None:
        cfg = build_live_draft_slot_config(roster_size=10, slots=STANDARD_10_HITTER_SLOTS)
        slots = dict(cfg.get("slots") or {})
        starters = sum(int(v or 0) for k, v in slots.items() if k != "BN")
        self.assertEqual(starters, 9)
        self.assertEqual(int(slots.get("BN") or 0), 1)

    def test_imported_league_may_still_need_setup(self) -> None:
        ctx = {
            "context_type": "mock_draft_simulation",
            "metadata": {"creation_origin": "draft_simulator"},
            "roster_settings": {},
        }
        self.assertTrue(needs_lineup_format_setup(ctx))
        self.assertFalse(is_live_draft_league_context(ctx))

    def test_bench_derived_from_roster_minus_starters(self) -> None:
        session: dict = {"draft_archive_teams": [], "fantasy_league_context_state": {"contexts": {}}}
        ctx = self._robins_context_without_slots()
        upsert_league_context(session, ctx, mark_persist_authoritative=False)
        repair_live_draft_lineup_config_for_context(
            session,
            draft_id=KNOWN_ROBINS_DRAFT_ID,
            allow_standard_fallback=True,
        )
        from fantasy_league_context import get_league_context, resolve_context_draft_slot_config

        repaired = get_league_context(session, "archive:c6810611c73e")
        slot_cfg = resolve_context_draft_slot_config(repaired)
        meta = dict((repaired.get("roster_settings") or {}).get("live_draft_lineup_config") or {})
        self.assertEqual(int(meta.get("starter_count") or 0), 9)
        self.assertEqual(int(meta.get("bench_count") or 0), 1)
        self.assertEqual(int(meta.get("roster_size") or 0), 10)
        self.assertTrue(slot_cfg.get("slots"))


if __name__ == "__main__":
    unittest.main()
