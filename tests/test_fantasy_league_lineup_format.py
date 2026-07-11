"""Tests for league lineup format, waiver position filters, and lineup persistence."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import pandas as pd

from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
    CONTEXT_TYPE_REAL_LEAGUE,
    create_league_context,
    get_active_league_context,
    save_simulator_league_context,
    upsert_league_context,
)
from fantasy_league_lineup_format import (
    CONFIG_SOURCE_LIVE,
    CONFIG_SOURCE_SIMULATOR,
    CONFIG_SOURCE_UPLOADED,
    apply_lineup_format_to_context,
    detect_roster_size_hint,
    is_lineup_format_commissioner,
    needs_lineup_format_setup,
    roster_capacity_from_format,
    save_league_lineup_format,
)
from fantasy_lineup_ui import build_slot_key_labels
from fantasy_weekly_lineup import (
    LINEUP_STATUS_DRAFT,
    LINEUP_STATUS_LOCKED,
    get_saved_weekly_lineup,
    is_lineup_locked,
    persist_weekly_lineup_draft,
    resolve_weekly_lineup_slots,
    save_weekly_lineup,
    validate_weekly_lineup,
)
from fantasy_weekly_lineup_ui import build_open_slot_prompts, ensure_canonical_assignments


def _three_player_board() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "Catcher One", "Pick": 1, "Primary Position": "C"},
            {"Team": "Daniel", "Player": "Corner Bat", "Pick": 2, "Primary Position": "1B"},
            {"Team": "Daniel", "Player": "Middle Man", "Pick": 3, "Primary Position": "2B"},
            {"Team": "Rival", "Player": "Other C", "Pick": 4, "Primary Position": "C"},
            {"Team": "Rival", "Player": "Other 1B", "Pick": 5, "Primary Position": "1B"},
            {"Team": "Rival", "Player": "Other 2B", "Pick": 6, "Primary Position": "2B"},
        ]
    )


def _three_player_roster() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "Catcher One", "Primary Position": "C"},
            {"Player": "Corner Bat", "Primary Position": "1B"},
            {"Player": "Middle Man", "Primary Position": "2B"},
        ]
    )


def _live_draft_context_three_slots() -> dict:
    return create_league_context(
        league_context_id="live:test",
        context_type=CONTEXT_TYPE_LIVE_DRAFT_RESULT,
        league_name="Live League",
        my_team_name="Daniel",
        league_rosters={
            "Daniel": {
                "players": [
                    {"fullName": "Catcher One", "position": "C"},
                    {"fullName": "Corner Bat", "position": "1B"},
                    {"fullName": "Middle Man", "position": "2B"},
                ]
            }
        },
        roster_settings={
            "roster_slots": {"C": 1, "1B": 1, "2B": 1},
            "slot_instances": [
                {"position": "C", "label": "Catcher", "slot_index": 0},
                {"position": "1B", "label": "First Base", "slot_index": 1},
                {"position": "2B", "label": "Second Base", "slot_index": 2},
            ],
        },
        display_name="Live Draft",
    )


class LineupFormatTests(unittest.TestCase):
    def test_live_draft_skips_setup_and_uses_configured_slots(self) -> None:
        context = _live_draft_context_three_slots()
        self.assertFalse(needs_lineup_format_setup(context))
        self.assertEqual(resolve_weekly_lineup_slots(context), ["C", "1B", "2B"])
        labels = build_slot_key_labels(resolve_weekly_lineup_slots(context))
        bases = {label.base_slot for label in labels}
        self.assertEqual(bases, {"C", "1B", "2B"})
        self.assertNotIn("UTIL", bases)
        self.assertNotIn("OF", bases)

    def test_three_player_simulator_prompts_for_format(self) -> None:
        session: dict = {}
        _, context = save_simulator_league_context(session, _three_player_board(), my_team_name="Daniel")
        self.assertTrue(needs_lineup_format_setup(context))
        suggested, counts = detect_roster_size_hint(context)
        self.assertEqual(suggested, 3)
        self.assertEqual(counts.get("Daniel"), 3)

    def test_three_player_uploaded_league_same_behavior(self) -> None:
        context = create_league_context(
            league_context_id="upload:test",
            context_type=CONTEXT_TYPE_REAL_LEAGUE,
            league_name="Uploaded",
            my_team_name="Daniel",
            league_rosters={
                "Daniel": {"players": [{"fullName": "A"}, {"fullName": "B"}, {"fullName": "C"}]},
                "Rival": {"players": [{"fullName": "X"}, {"fullName": "Y"}, {"fullName": "Z"}]},
            },
            display_name="Uploaded Draft",
        )
        self.assertTrue(needs_lineup_format_setup(context))

    def test_saved_format_visible_to_all_teams(self) -> None:
        session: dict = {}
        _, context = save_simulator_league_context(session, _three_player_board(), my_team_name="Daniel")
        updated = apply_lineup_format_to_context(
            context,
            lineup_slots=["C", "1B", "2B"],
            roster_capacity=3,
            configured_by="commissioner@test",
            configuration_source=CONFIG_SOURCE_SIMULATOR,
        )
        upsert_league_context(session, updated)
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        self.assertEqual(resolve_weekly_lineup_slots(reloaded), ["C", "1B", "2B"])
        self.assertEqual(roster_capacity_from_format(reloaded), 3)

    def test_non_commissioner_cannot_save_format(self) -> None:
        session: dict = {}
        context = create_league_context(
            league_context_id="shared:test",
            context_type=CONTEXT_TYPE_REAL_LEAGUE,
            league_name="Shared",
            my_team_name="Owner",
            league_rosters={"Owner": {"players": []}, "Daniel": {"players": []}},
            display_name="Shared League",
        )
        upsert_league_context(session, context)
        with patch("fantasy_league_invites.is_league_commissioner", return_value=False):
            self.assertFalse(is_lineup_format_commissioner(session, context))
            result = save_league_lineup_format(
                session,
                lineup_slots=["C", "1B", "2B"],
                roster_capacity=3,
            )
        self.assertFalse(result.get("ok"))

    def test_unselected_positions_not_on_board(self) -> None:
        session: dict = {}
        _, context = save_simulator_league_context(session, _three_player_board(), my_team_name="Daniel")
        updated = apply_lineup_format_to_context(
            context,
            lineup_slots=["C", "1B", "2B"],
            roster_capacity=3,
            configured_by="daniel",
            configuration_source=CONFIG_SOURCE_SIMULATOR,
        )
        labels = build_slot_key_labels(resolve_weekly_lineup_slots(updated))
        self.assertEqual([label.base_slot for label in labels], ["C", "1B", "2B"])

    def test_format_persists_in_context(self) -> None:
        session: dict = {}
        _, context = save_simulator_league_context(session, _three_player_board(), my_team_name="Daniel")
        save_league_lineup_format(
            session,
            lineup_slots=["C", "1B", "2B"],
            roster_capacity=3,
            configuration_source=CONFIG_SOURCE_UPLOADED,
        )
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        block = (reloaded.get("roster_settings") or {}).get("lineup_format") or {}
        self.assertEqual(block.get("lineup_slots"), ["C", "1B", "2B"])
        self.assertEqual(block.get("configuration_source"), CONFIG_SOURCE_UPLOADED)


class WaiverCapacityTests(unittest.TestCase):
    def test_full_three_player_roster_requires_add_drop(self) -> None:
        from fantasy_waiver_wire import WAIVER_TX_MODE_ADD_DROP, waiver_roster_transaction_mode

        session: dict = {}
        _, context = save_simulator_league_context(session, _three_player_board(), my_team_name="Daniel")
        updated = apply_lineup_format_to_context(
            context,
            lineup_slots=["C", "1B", "2B"],
            roster_capacity=3,
            configured_by="daniel",
            configuration_source=CONFIG_SOURCE_SIMULATOR,
        )
        self.assertEqual(waiver_roster_transaction_mode(updated, 3), WAIVER_TX_MODE_ADD_DROP)

    def test_two_player_roster_allows_add_only(self) -> None:
        from fantasy_waiver_wire import WAIVER_TX_MODE_ADD_ONLY, waiver_roster_transaction_mode

        session: dict = {}
        _, context = save_simulator_league_context(session, _three_player_board(), my_team_name="Daniel")
        updated = apply_lineup_format_to_context(
            context,
            lineup_slots=["C", "1B", "2B"],
            roster_capacity=3,
            configured_by="daniel",
            configuration_source=CONFIG_SOURCE_SIMULATOR,
        )
        self.assertEqual(waiver_roster_transaction_mode(updated, 2), WAIVER_TX_MODE_ADD_ONLY)


class WaiverPositionFilterTests(unittest.TestCase):
    def _filter_df(self) -> pd.DataFrame:
        from streamlit_app import enrich_lineup_roster_positions, filter_players_by_fantasy_position

        df = pd.DataFrame(
            [
                {"Player": "Real C", "Primary Position": "C"},
                {"Player": "Center Fielder", "Primary Position": "CF"},
                {"Player": "Left Fielder", "Primary Position": "LF"},
                {"Player": "First Baseman", "Primary Position": "1B"},
                {"Player": "Utility Bat", "Primary Position": "1B,3B"},
                {"Player": "Ace Pitcher", "Primary Position": "SP"},
            ]
        )
        enriched = enrich_lineup_roster_positions(df)
        return enriched, filter_players_by_fantasy_position

    def test_catcher_excludes_cf_only(self) -> None:
        enriched, filter_fn = self._filter_df()
        filtered = filter_fn(enriched, "C")
        names = set(filtered["Player"].tolist())
        self.assertIn("Real C", names)
        self.assertNotIn("Center Fielder", names)

    def test_outfield_includes_lf_cf_rf(self) -> None:
        enriched, filter_fn = self._filter_df()
        filtered = filter_fn(enriched, "OF")
        names = set(filtered["Player"].tolist())
        self.assertIn("Center Fielder", names)
        self.assertIn("Left Fielder", names)
        self.assertNotIn("Real C", names)

    def test_first_base_includes_multi_position(self) -> None:
        enriched, filter_fn = self._filter_df()
        filtered = filter_fn(enriched, "1B")
        names = set(filtered["Player"].tolist())
        self.assertIn("First Baseman", names)
        self.assertIn("Utility Bat", names)

    def test_util_excludes_pitchers(self) -> None:
        enriched, filter_fn = self._filter_df()
        filtered = filter_fn(enriched, "DH/UTIL")
        names = set(filtered["Player"].tolist())
        self.assertNotIn("Ace Pitcher", names)
        self.assertIn("Utility Bat", names)

    def test_all_positions_restores_full_pool(self) -> None:
        enriched, filter_fn = self._filter_df()
        filtered = filter_fn(enriched, "All positions")
        self.assertEqual(len(filtered), len(enriched))

    def test_recommendations_and_table_share_same_filter(self) -> None:
        from fantasy_waiver_wire_ui import _apply_waiver_position_filter

        enriched, _ = self._filter_df()
        for choice in ("C", "1B", "OF", "DH/UTIL"):
            ui_filtered = _apply_waiver_position_filter(enriched, choice)
            from streamlit_app import filter_players_by_fantasy_position

            direct = filter_players_by_fantasy_position(enriched, choice)
            self.assertEqual(
                sorted(ui_filtered["Player"].tolist()),
                sorted(direct["Player"].tolist()),
                msg=f"filter mismatch for {choice}",
            )


class LineupPersistenceTests(unittest.TestCase):
    def _session_with_format(self) -> tuple[dict, dict]:
        session: dict = {}
        _, context = save_simulator_league_context(session, _three_player_board(), my_team_name="Daniel")
        updated = apply_lineup_format_to_context(
            context,
            lineup_slots=["C", "1B", "2B"],
            roster_capacity=3,
            configured_by="daniel",
            configuration_source=CONFIG_SOURCE_SIMULATOR,
        )
        upsert_league_context(session, updated)
        return session, updated

    def test_drag_persists_as_draft(self) -> None:
        session, context = self._session_with_format()
        slots = resolve_weekly_lineup_slots(context)
        assignments = {"C": "Catcher One", "1B": "", "2B": ""}
        result = persist_weekly_lineup_draft(
            session,
            week=1,
            slots=slots,
            assignments=assignments,
            my_team="Daniel",
        )
        self.assertTrue(result.get("ok"))
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        saved = get_saved_weekly_lineup(reloaded, 1, team="Daniel", session=session)
        assert saved is not None
        self.assertEqual(saved.get("status"), LINEUP_STATUS_DRAFT)
        self.assertEqual(saved["assignments"].get("C"), "Catcher One")

    def test_session_rehydrates_draft_after_refresh(self) -> None:
        session, context = self._session_with_format()
        slots = resolve_weekly_lineup_slots(context)
        persist_weekly_lineup_draft(
            session,
            week=1,
            slots=slots,
            assignments={"C": "Catcher One", "1B": "Corner Bat", "2B": ""},
            my_team="Daniel",
        )
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        saved = get_saved_weekly_lineup(reloaded, 1, team="Daniel", session=session)
        assert saved is not None
        fresh_session: dict = {}
        upsert_league_context(fresh_session, copy.deepcopy(reloaded))
        canon = ensure_canonical_assignments(
            fresh_session,
            canon_key="weekly_lineup_canon_1",
            slot_keys=[("C", "Catcher"), ("1B", "First Base"), ("2B", "Second Base")],
            saved_assignments=dict(saved.get("assignments") or {}),
        )
        self.assertEqual(canon.get("C"), "Catcher One")
        self.assertEqual(canon.get("1B"), "Corner Bat")

    def test_save_disabled_with_empty_positions(self) -> None:
        roster = _three_player_roster()
        validation = validate_weekly_lineup(["C", "1B", "2B"], {"C": "Catcher One", "1B": "", "2B": ""}, roster)
        self.assertFalse(validation.get("ok"))

    def test_save_enabled_when_all_filled(self) -> None:
        roster = _three_player_roster()
        validation = validate_weekly_lineup(
            ["C", "1B", "2B"],
            {"C": "Catcher One", "1B": "Corner Bat", "2B": "Middle Man"},
            roster,
        )
        self.assertTrue(validation.get("ok"))

    def test_saving_locks_lineup(self) -> None:
        session, _ = self._session_with_format()
        roster = _three_player_roster()
        result = save_weekly_lineup(
            session,
            week=1,
            slots=["C", "1B", "2B"],
            assignments={"C": "Catcher One", "1B": "Corner Bat", "2B": "Middle Man"},
            my_team="Daniel",
            roster_df=roster,
        )
        self.assertTrue(result.get("ok"))
        context = get_active_league_context(session)
        assert context is not None
        self.assertTrue(is_lineup_locked(context, 1, team="Daniel", session=session))
        saved = get_saved_weekly_lineup(context, 1, team="Daniel", session=session)
        assert saved is not None
        self.assertEqual(saved.get("status"), LINEUP_STATUS_LOCKED)

    def test_locked_lineup_blocks_draft_persist(self) -> None:
        session, _ = self._session_with_format()
        roster = _three_player_roster()
        save_weekly_lineup(
            session,
            week=1,
            slots=["C", "1B", "2B"],
            assignments={"C": "Catcher One", "1B": "Corner Bat", "2B": "Middle Man"},
            my_team="Daniel",
            roster_df=roster,
        )
        result = persist_weekly_lineup_draft(
            session,
            week=1,
            slots=["C", "1B", "2B"],
            assignments={"C": "Bench", "1B": "Corner Bat", "2B": "Middle Man"},
            my_team="Daniel",
        )
        self.assertFalse(result.get("ok"))

    def test_week_isolation(self) -> None:
        session, context = self._session_with_format()
        slots = resolve_weekly_lineup_slots(context)
        persist_weekly_lineup_draft(
            session,
            week=1,
            slots=slots,
            assignments={"C": "Catcher One", "1B": "", "2B": ""},
            my_team="Daniel",
        )
        persist_weekly_lineup_draft(
            session,
            week=2,
            slots=slots,
            assignments={"C": "", "1B": "Corner Bat", "2B": ""},
            my_team="Daniel",
        )
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        week1 = get_saved_weekly_lineup(reloaded, 1, team="Daniel", session=session)
        week2 = get_saved_weekly_lineup(reloaded, 2, team="Daniel", session=session)
        assert week1 is not None and week2 is not None
        self.assertEqual(week1["assignments"].get("C"), "Catcher One")
        self.assertEqual(week2["assignments"].get("1B"), "Corner Bat")

    def test_partial_draft_not_locked(self) -> None:
        session, context = self._session_with_format()
        slots = resolve_weekly_lineup_slots(context)
        persist_weekly_lineup_draft(
            session,
            week=1,
            slots=slots,
            assignments={"C": "Catcher One", "1B": "", "2B": ""},
            my_team="Daniel",
        )
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        self.assertFalse(is_lineup_locked(reloaded, 1, team="Daniel", session=session))

    def test_open_slot_prompts_only_configured_positions(self) -> None:
        labels = build_slot_key_labels(["C", "1B", "2B"])
        rows = build_open_slot_prompts(labels, {"C": "Catcher One", "1B": "", "2B": "Middle Man"})
        texts = [row["text"] for row in rows]
        self.assertEqual(len(rows), 1)
        self.assertIn("First Base is empty", texts[0])
        self.assertEqual(rows[0]["waiver_label"], "First Base")

    def test_live_draft_configuration_source(self) -> None:
        from fantasy_league_lineup_format import configuration_source_for_context

        context = _live_draft_context_three_slots()
        self.assertEqual(configuration_source_for_context(context), CONFIG_SOURCE_LIVE)


if __name__ == "__main__":
    unittest.main()
