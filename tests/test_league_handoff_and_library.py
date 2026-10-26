"""Leagues after the draft: a Live/Shared Draft league (slot config, no saved lineup format)
counts its bench in roster capacity so waiver moves work, and renaming a saved league in the
library renames it on every fantasy page."""

from __future__ import annotations

import unittest

from fantasy_league_lineup_format import roster_capacity_from_format
from fantasy_waiver_wire import waiver_roster_transaction_mode

LIVE_SLOTS = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0, "BN": 3}


def _live_league() -> dict:
    return {"league_context_id": "archive:qa", "context_type": "real_league",
            "roster_settings": {"roster_slots": dict(LIVE_SLOTS), "slot_instances": []}}


class LiveDraftLeagueCapacityTests(unittest.TestCase):
    def test_capacity_is_starters_plus_bench(self):
        self.assertEqual(roster_capacity_from_format(_live_league()), 12)

    def test_full_drafted_roster_can_make_moves(self):
        ctx = _live_league()
        self.assertEqual(waiver_roster_transaction_mode(ctx, 12), "add_drop")  # was cleanup_required
        self.assertEqual(waiver_roster_transaction_mode(ctx, 11), "add_only")
        self.assertEqual(waiver_roster_transaction_mode(ctx, 13), "cleanup_required")

    def test_saved_format_capacity_still_wins(self):
        ctx = _live_league()
        ctx["roster_settings"]["lineup_format"] = {"lineup_slots": ["C"], "roster_capacity": 15}
        self.assertEqual(roster_capacity_from_format(ctx), 15)


class TradeBuilderFirstVisitTests(unittest.TestCase):
    def test_first_visit_gets_no_reset_notice(self):
        from fantasy_trade_builder_state import BUILDER_FLASH_SUFFIX, maybe_migrate_builder_schema

        session: dict = {}
        _state, migrated = maybe_migrate_builder_schema(session, "scope", {})
        self.assertTrue(migrated)
        self.assertNotIn(f"scope|{BUILDER_FLASH_SUFFIX}", session)

    def test_reset_of_a_saved_builder_is_announced(self):
        from fantasy_trade_builder_state import BUILDER_FLASH_SUFFIX, maybe_migrate_builder_schema

        session: dict = {}
        maybe_migrate_builder_schema(session, "scope", {"give_players": ["A"]})
        self.assertIn("fresh editable state", session[f"scope|{BUILDER_FLASH_SUFFIX}"])


class LibraryRenameTests(unittest.TestCase):
    def test_rename_reaches_the_fantasy_page_heading(self):
        import pandas as pd

        from draft_archive_ui import _rename_archive_entry
        from fantasy_context_source import resolve_fantasy_workflow_source_descriptor
        from fantasy_league_context import activate_archive_league_context, save_imported_league_context

        session: dict = {}
        board = pd.DataFrame([{"Pick": 1, "Round": 1, "Team": "Team 1", "Player": "A"},
                              {"Pick": 2, "Round": 1, "Team": "Team 2", "Player": "B"}])
        entry, _ = save_imported_league_context(session, board, my_team_name="Team 1", draft_name="Old Name",
                                                league_name="Old Name", save_only=True, assign_team=True)
        activate_archive_league_context(session, entry["draft_id"])
        self.assertEqual(resolve_fantasy_workflow_source_descriptor(session)["display_name"], "Old Name")
        st = type("St", (), {"session_state": session})()
        self.assertTrue(_rename_archive_entry(st, session, entry["draft_id"], "QA Renamed League"))
        self.assertEqual(resolve_fantasy_workflow_source_descriptor(session)["display_name"], "QA Renamed League")


if __name__ == "__main__":
    unittest.main()
