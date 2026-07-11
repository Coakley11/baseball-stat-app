"""Integration tests for Fantasy Lineup state sync and shared format."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    create_league_context,
    get_active_league_context,
    save_imported_league_context,
    upsert_league_context,
)
from fantasy_league_lineup_format import (
    CONFIG_SOURCE_UPLOADED,
    apply_lineup_format_to_context,
    hydrate_lineup_format_from_shared,
    resolve_lineup_page_context,
    save_league_lineup_format,
)
from fantasy_lineup_interactive_board import apply_drop_event, parse_board_drop_result
from fantasy_shared_league_store import (
    LocalFileSharedLeagueStore,
    load_shared_league,
    push_league_context_to_shared,
    set_shared_league_store,
    sync_context_with_shared_store,
)
from fantasy_weekly_lineup import get_saved_weekly_lineup, persist_weekly_lineup_draft
from fantasy_weekly_lineup_ui import (
    build_open_slot_prompts,
    ensure_canonical_assignments,
    reconcile_editor_assignments,
)


def _three_player_roster() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "Catcher One", "Primary Position": "C", "Team": "Daniel"},
            {"Player": "Corner Bat", "Primary Position": "1B", "Team": "Daniel"},
            {"Player": "Middle Man", "Primary Position": "2B", "Team": "Daniel"},
        ]
    )


class ComponentDropEventTests(unittest.TestCase):
    def test_parse_component_returns_dict(self) -> None:
        event = {"player": "Corner Bat", "target": "1B", "assignments": {"1B": "Corner Bat"}}
        self.assertEqual(parse_board_drop_result(event), event)

    def test_apply_drop_event_updates_canonical_assignments(self) -> None:
        roster = _three_player_roster()
        slot_keys = [("C", "Catcher"), ("1B", "First Base"), ("2B", "Second Base")]
        event = {
            "player": "Corner Bat",
            "target": "1B",
            "assignments": {"C": "", "1B": "Corner Bat", "2B": ""},
        }
        result = apply_drop_event({}, slot_keys, event, roster_df=roster)
        assert result is not None
        self.assertEqual(result["1B"], "Corner Bat")

    def test_drop_event_flow_persists_and_rehydrates(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Catcher One", "Pick": 1, "Primary Position": "C"},
                {"Team": "Daniel", "Player": "Corner Bat", "Pick": 2, "Primary Position": "1B"},
                {"Team": "Daniel", "Player": "Middle Man", "Pick": 3, "Primary Position": "2B"},
            ]
        )
        from fantasy_league_context import save_simulator_league_context

        _, context = save_simulator_league_context(session, board, my_team_name="Daniel")
        context = apply_lineup_format_to_context(
            context,
            lineup_slots=["C", "1B", "2B"],
            roster_capacity=3,
            configured_by="daniel",
            configuration_source=CONFIG_SOURCE_UPLOADED,
        )
        upsert_league_context(session, context)

        roster = _three_player_roster()
        slot_keys = [("C", "Catcher"), ("1B", "First Base"), ("2B", "Second Base")]
        canon_key = "weekly_lineup_canon_1"
        assignments = ensure_canonical_assignments(
            session, canon_key=canon_key, slot_keys=slot_keys, saved_assignments={}
        )
        event = {
            "player": "Corner Bat",
            "target": "1B",
            "assignments": {"C": "", "1B": "Corner Bat", "2B": ""},
        }
        new_assignments = apply_drop_event(assignments, slot_keys, event, roster_df=roster)
        assert new_assignments is not None
        self.assertTrue(
            reconcile_editor_assignments(
                session,
                canon_key=canon_key,
                slot_keys=slot_keys,
                new_assignments=new_assignments,
            )
        )
        persist_weekly_lineup_draft(
            session,
            week=1,
            slots=["C", "1B", "2B"],
            assignments=new_assignments,
            my_team="Daniel",
            roster_df=roster,
        )

        fresh_session: dict = {}
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        upsert_league_context(fresh_session, copy.deepcopy(reloaded))
        saved = get_saved_weekly_lineup(reloaded, 1, team="Daniel", session=session)
        assert saved is not None
        restored = ensure_canonical_assignments(
            fresh_session,
            canon_key=canon_key,
            slot_keys=slot_keys,
            saved_assignments=dict(saved.get("assignments") or {}),
        )
        self.assertEqual(restored["1B"], "Corner Bat")


class DynamicUiSyncTests(unittest.TestCase):
    def test_open_slot_rows_shrink_as_positions_fill(self) -> None:
        from fantasy_lineup_ui import build_slot_key_labels

        labels = build_slot_key_labels(["C", "1B", "2B"])
        rows = build_open_slot_prompts(labels, {"C": "", "1B": "", "2B": ""})
        self.assertEqual(len(rows), 3)
        rows = build_open_slot_prompts(labels, {"C": "Catcher One", "1B": "", "2B": ""})
        self.assertEqual(len(rows), 2)
        rows = build_open_slot_prompts(labels, {"C": "Catcher One", "1B": "Corner Bat", "2B": "Middle Man"})
        self.assertEqual(rows, [])

    def test_stale_empty_session_rehydrates_from_saved_draft(self) -> None:
        slot_keys = [("C", "Catcher"), ("1B", "First Base")]
        session = {"weekly_lineup_canon_1": {"C": "", "1B": ""}}
        saved = {"C": "Catcher One", "1B": "Corner Bat"}
        restored = ensure_canonical_assignments(
            session,
            canon_key="weekly_lineup_canon_1",
            slot_keys=slot_keys,
            saved_assignments=saved,
        )
        self.assertEqual(restored["1B"], "Corner Bat")


class SharedFormatSyncTests(unittest.TestCase):
    def test_commissioner_format_visible_to_second_account(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            set_shared_league_store(LocalFileSharedLeagueStore(root=Path(tmp)))
            session_a: dict = {}
            session_b: dict = {}
            board = pd.DataFrame(
                [
                    {"Team": "Daniel", "Player": "Player A", "Pick": 1},
                    {"Team": "Team 2", "Player": "Player B", "Pick": 2},
                ]
            )
            context_a, _ = save_imported_league_context(
                session_a,
                board,
                my_team_name="Daniel",
                league_name="Shared Test League",
            )
            context_a = apply_lineup_format_to_context(
                context_a,
                lineup_slots=["C", "1B", "SS"],
                roster_capacity=3,
                configured_by="daniel",
                configuration_source=CONFIG_SOURCE_UPLOADED,
            )
            upsert_league_context(session_a, context_a)
            push_league_context_to_shared(session_a, context_a)

            from fantasy_league_identity import resolve_canonical_league_id

            league_id = resolve_canonical_league_id(context_a)
            assert league_id
            shared = load_shared_league(league_id)
            assert shared is not None
            self.assertEqual(
                ((shared.get("roster_settings") or {}).get("lineup_format") or {}).get("lineup_slots"),
                ["C", "1B", "SS"],
            )

            context_b = create_league_context(
                league_context_id="ctx:team2",
                context_type=CONTEXT_TYPE_REAL_LEAGUE,
                league_name="Shared Test League",
                my_team_name="Team 2",
                league_rosters=copy.deepcopy(context_a.get("league_rosters") or {}),
                display_name="Team 2 view",
            )
            meta_b = copy.deepcopy(context_a.get("metadata") or {})
            meta_b["league_id"] = league_id
            context_b["metadata"] = meta_b
            context_b["league_id"] = league_id
            upsert_league_context(session_b, context_b)
            from fantasy_league_context import get_league_context, set_active_league_context

            set_active_league_context(session_b, "ctx:team2")
            resolved = resolve_lineup_page_context(session_b)

            assert resolved is not None
            from fantasy_league_lineup_format import needs_lineup_format_setup
            from fantasy_weekly_lineup import resolve_weekly_lineup_slots

            self.assertFalse(needs_lineup_format_setup(resolved))
            self.assertEqual(resolve_weekly_lineup_slots(resolved), ["C", "1B", "SS"])


if __name__ == "__main__":
    unittest.main()
