"""Roster-position and waiver rules across Live Draft, Simulator, and Uploaded Drafts."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from fantasy_roster_validation import (
    LIVE_DRAFT_SETUP_ERROR,
    WAIVER_CORRECTION_MODE_KEY,
    WAIVER_CORRECTION_POSITION_KEY,
    activate_waiver_position_correction,
    clear_waiver_position_correction,
    ensure_bench_slots_for_extra_picks,
    evaluate_team_roster,
    is_waiver_position_correction_active,
    missing_position_message,
    no_expansion_draft_allowed,
    open_waiver_button_label,
    validate_commissioner_lineup_slot_count,
    validate_live_draft_setup,
)
from live_draft_roster_enforcement import compute_required_position_enforcement
from live_draft_roster_slots import assign_roster_to_slot_instances, freeze_slot_instances_on_config


def _five_starter_slots() -> dict[str, int]:
    return {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 0, "DH": 0, "P": 0, "BN": 0}


def _player(name: str, pos: str) -> dict[str, object]:
    return {
        "fullName": name,
        "Player": name,
        "Primary Position": pos,
        "Expected Fantasy Value": 10.0,
    }


class LiveDraftSetupValidationTests(unittest.TestCase):
    def test_cannot_start_when_picks_fewer_than_required(self) -> None:
        slots = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 1, "DH": 1, "P": 1, "BN": 0}
        result = validate_live_draft_setup(picks_per_team=5, slots=slots)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], LIVE_DRAFT_SETUP_ERROR)
        self.assertEqual(result["required_positions"], 8)

    def test_can_start_when_picks_equal_required(self) -> None:
        result = validate_live_draft_setup(picks_per_team=5, slots=_five_starter_slots())
        self.assertTrue(result["ok"])
        self.assertEqual(result["extra_picks"], 0)

    def test_can_start_when_picks_exceed_required(self) -> None:
        result = validate_live_draft_setup(picks_per_team=8, slots=_five_starter_slots())
        self.assertTrue(result["ok"])
        self.assertEqual(result["extra_picks"], 3)


class ExtraPicksToBenchTests(unittest.TestCase):
    def test_extra_live_draft_picks_go_to_bench(self) -> None:
        slots = ensure_bench_slots_for_extra_picks(_five_starter_slots(), picks_per_team=8)
        self.assertEqual(slots["BN"], 3)
        self.assertEqual(slots["C"], 1)

    def test_extra_drafted_players_never_discarded(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {"slots": ensure_bench_slots_for_extra_picks(_five_starter_slots(), 8)}
        )
        roster = pd.DataFrame(
            [
                _player("C Guy", "C"),
                _player("1B Guy", "1B"),
                _player("2B Guy", "2B"),
                _player("3B Guy", "3B"),
                _player("SS Guy", "SS"),
                _player("Bench A", "OF"),
                _player("Bench B", "OF"),
                _player("Bench C", "OF"),
            ]
        )
        assigned = assign_roster_to_slot_instances(roster, cfg)
        self.assertEqual(assigned["filled"], 8)
        self.assertEqual(assigned["target"], 8)
        self.assertEqual(assigned["gaps"], [])
        # All eight players remain on the roster dataframe — none discarded.
        self.assertEqual(len(roster), 8)


class LiveDraftEnforcementTests(unittest.TestCase):
    def test_enforcement_fills_required_positions(self) -> None:
        cfg = freeze_slot_instances_on_config({"slots": _five_starter_slots()})
        roster = pd.DataFrame(
            [
                _player("C Guy", "C"),
                _player("1B Guy", "1B"),
                _player("2B Guy", "2B"),
            ]
        )
        active, required = compute_required_position_enforcement(roster, cfg, picks_remaining=2)
        self.assertTrue(active)
        self.assertIn("3B", required)
        self.assertIn("SS", required)


class MissingPositionWaiverButtonTests(unittest.TestCase):
    def test_missing_live_draft_position_creates_position_specific_button(self) -> None:
        cfg = freeze_slot_instances_on_config({"slots": _five_starter_slots()})
        # Avoid 1B/3B corner cross-eligibility: leave first base uncovered with OF depth.
        roster = pd.DataFrame(
            [
                _player("C Guy", "C"),
                _player("2B Guy", "2B"),
                _player("SS Guy", "SS"),
                _player("OF Guy", "OF"),
                _player("OF Guy 2", "OF"),
            ]
        )
        coverage = evaluate_team_roster(roster_df=roster, config=cfg, max_roster_count=5)
        self.assertIn("1B", coverage["missing_positions"])
        prompts = coverage["missing_prompts"]
        self.assertTrue(any(p["text"] == "Missing first baseman" for p in prompts))
        self.assertTrue(any("First Basemen" in p["button_label"] for p in prompts))
        self.assertEqual(missing_position_message("1B"), "Missing first baseman")
        self.assertEqual(open_waiver_button_label("1B"), "Open Waiver Wire for First Basemen")


class SimulatorUploadedIsolationTests(unittest.TestCase):
    def test_draft_simulator_does_not_use_live_draft_setup_validation(self) -> None:
        from pathlib import Path

        src = Path("streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("validate_live_draft_setup(", src)
        start = src.find("def simulate_draft_lab")
        lab_region = src[start : start + 2500]
        self.assertNotIn("validate_live_draft_setup", lab_region)

    def test_uploaded_draft_does_not_use_live_draft_setup_validation(self) -> None:
        from pathlib import Path

        import draft_import_pipeline

        src = Path(draft_import_pipeline.__file__).read_text(encoding="utf-8")
        self.assertNotIn("validate_live_draft_setup", src)


class CommissionerPostDraftStructureTests(unittest.TestCase):
    def test_commissioner_can_define_post_draft_position_structure(self) -> None:
        check = validate_commissioner_lineup_slot_count(starter_count=5, drafted_roster_size=5)
        self.assertTrue(check["ok"])
        self.assertEqual(check["bench_spots"], 0)

    def test_cannot_define_more_starters_than_drafted(self) -> None:
        check = validate_commissioner_lineup_slot_count(starter_count=8, drafted_roster_size=5)
        self.assertFalse(check["ok"])


class WaiverCorrectionModeTests(unittest.TestCase):
    def test_missing_first_base_opens_filtered_correction_mode(self) -> None:
        session: dict = {}
        filt = activate_waiver_position_correction(session, "1B")
        self.assertEqual(filt, "1B")
        self.assertTrue(is_waiver_position_correction_active(session))
        self.assertEqual(session[WAIVER_CORRECTION_POSITION_KEY], "1B")

    def test_ordinary_waiver_navigation_does_not_activate_correction_mode(self) -> None:
        session: dict = {}
        self.assertFalse(is_waiver_position_correction_active(session))
        # Visiting waiver without activate leaves mode off.
        clear_waiver_position_correction(session)
        self.assertFalse(session.get(WAIVER_CORRECTION_MODE_KEY))

    def test_correction_mode_tied_to_selected_missing_position(self) -> None:
        session: dict = {}
        activate_waiver_position_correction(session, "1B")
        self.assertEqual(session[WAIVER_CORRECTION_POSITION_KEY], "1B")
        activate_waiver_position_correction(session, "3B")
        self.assertEqual(session[WAIVER_CORRECTION_POSITION_KEY], "3B")


class AddDropCapacityTests(unittest.TestCase):
    def test_full_roster_requires_add_drop(self) -> None:
        cfg = freeze_slot_instances_on_config({"slots": _five_starter_slots()})
        players = [
            _player("C Guy", "C"),
            _player("OF A", "OF"),
            _player("OF B", "OF"),
            _player("OF C", "OF"),
            _player("OF D", "OF"),
        ]
        coverage = evaluate_team_roster(players=players, config=cfg, max_roster_count=5)
        self.assertTrue(coverage["add_drop_required"])
        self.assertFalse(coverage["add_only_allowed"])

    def test_under_capacity_permits_add_only(self) -> None:
        cfg = freeze_slot_instances_on_config({"slots": _five_starter_slots()})
        players = [
            _player("C Guy", "C"),
            _player("2B Guy", "2B"),
            _player("3B Guy", "3B"),
            _player("SS Guy", "SS"),
        ]
        coverage = evaluate_team_roster(players=players, config=cfg, max_roster_count=5)
        self.assertTrue(coverage["add_only_allowed"])
        self.assertFalse(coverage["add_drop_required"])


class CascadingMissingPositionTests(unittest.TestCase):
    def test_dropping_only_player_at_required_position_creates_new_warning(self) -> None:
        cfg = freeze_slot_instances_on_config({"slots": _five_starter_slots()})
        before = [
            _player("C Guy", "C"),
            _player("1B Guy", "1B"),
            _player("2B Guy", "2B"),
            _player("3B Guy", "3B"),
            _player("SS Guy", "SS"),
        ]
        ok = evaluate_team_roster(players=before, config=cfg, max_roster_count=5)
        self.assertTrue(ok["roster_valid"])

        # Drop only SS (no cross-eligibility with OF), add another OF — SS becomes missing.
        after = [
            _player("C Guy", "C"),
            _player("1B Guy", "1B"),
            _player("2B Guy", "2B"),
            _player("3B Guy", "3B"),
            _player("New OF", "OF"),
        ]
        coverage = evaluate_team_roster(players=after, config=cfg, max_roster_count=5)
        self.assertIn("SS", coverage["missing_positions"])
        self.assertFalse(coverage["roster_valid"])

    def test_roster_remains_invalid_until_all_required_positions_filled(self) -> None:
        cfg = freeze_slot_instances_on_config({"slots": _five_starter_slots()})
        partial = [
            _player("C Guy", "C"),
            _player("1B Guy", "1B"),
            _player("2B Guy", "2B"),
            _player("3B Guy", "3B"),
            _player("OF Guy", "OF"),
        ]
        coverage = evaluate_team_roster(players=partial, config=cfg, max_roster_count=5)
        self.assertFalse(coverage["roster_valid"])
        self.assertIn("SS", coverage["missing_positions"])


class SharedLeagueAndPersistenceTests(unittest.TestCase):
    def test_shared_league_users_see_same_required_position_structure(self) -> None:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE
        from fantasy_league_lineup_format import CONFIG_SOURCE_UPLOADED, apply_lineup_format_to_context

        base = {
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "league_context_id": "lg1",
            "my_team_name": "Daniel",
            "league_rosters": {
                "Daniel": {"players": [_player("C Guy", "C")]},
                "Coakley11": {"players": [_player("C Guy 2", "C")]},
            },
        }
        updated = apply_lineup_format_to_context(
            base,
            lineup_slots=["C", "1B", "2B", "3B", "SS"],
            roster_capacity=5,
            configured_by="commissioner",
            configuration_source=CONFIG_SOURCE_UPLOADED,
            league_id="lg1",
        )
        slots = (updated.get("roster_settings") or {}).get("lineup_format", {}).get("lineup_slots")
        self.assertEqual(slots, ["C", "1B", "2B", "3B", "SS"])
        # Both teams evaluate against the same structure.
        for team in ("Daniel", "Coakley11"):
            players = updated["league_rosters"][team]["players"]
            coverage = evaluate_team_roster(
                players=players,
                context=updated,
                max_roster_count=5,
            )
            self.assertEqual(coverage["required_count"], 5)

    def test_roster_corrections_persist_after_refresh(self) -> None:
        from fantasy_league_context import get_active_league_context, upsert_league_context
        from fantasy_league_lineup_format import CONFIG_SOURCE_SIMULATOR, apply_lineup_format_to_context
        from fantasy_league_context import save_simulator_league_context

        session: dict = {}
        board = pd.DataFrame(
            [
                {"Pick": 1, "Team": "Team A", "Player": "C Guy", "Primary Position": "C"},
                {"Pick": 2, "Team": "Team A", "Player": "1B Guy", "Primary Position": "1B"},
                {"Pick": 3, "Team": "Team A", "Player": "2B Guy", "Primary Position": "2B"},
                {"Pick": 4, "Team": "Team A", "Player": "3B Guy", "Primary Position": "3B"},
                {"Pick": 5, "Team": "Team A", "Player": "SS Guy", "Primary Position": "SS"},
            ]
        )
        _, context = save_simulator_league_context(session, board, my_team_name="Team A")
        context = apply_lineup_format_to_context(
            context,
            lineup_slots=["C", "1B", "2B", "3B", "SS"],
            roster_capacity=5,
            configured_by="commissioner",
            configuration_source=CONFIG_SOURCE_SIMULATOR,
        )
        upsert_league_context(session, context)
        reloaded = get_active_league_context(session)
        assert reloaded is not None
        players = (reloaded.get("league_rosters") or {}).get("Team A", {}).get("players") or []
        coverage = evaluate_team_roster(
            players=players,
            context=reloaded,
            max_roster_count=5,
        )
        self.assertTrue(coverage["roster_valid"])
        # Format survives a second session read.
        block = (reloaded.get("roster_settings") or {}).get("lineup_format") or {}
        self.assertEqual(block.get("lineup_slots"), ["C", "1B", "2B", "3B", "SS"])

    def test_no_second_or_expansion_draft_after_position_configuration(self) -> None:
        rule = no_expansion_draft_allowed({"context_type": "mock_draft_simulation"})
        self.assertFalse(rule["allowed"])
        self.assertIn("Waiver Wire", rule["reason"])


class LiveDraftSkipsPostDraftSetupTests(unittest.TestCase):
    def test_live_draft_skips_commissioner_lineup_setup_when_slots_present(self) -> None:
        from fantasy_league_context import CONTEXT_TYPE_LIVE_DRAFT_RESULT
        from fantasy_league_lineup_format import needs_lineup_format_setup

        context = {
            "context_type": CONTEXT_TYPE_LIVE_DRAFT_RESULT,
            "roster_settings": {
                "roster_slots": _five_starter_slots(),
                "slot_instances": freeze_slot_instances_on_config({"slots": _five_starter_slots()})[
                    "slot_instances"
                ],
            },
        }
        self.assertFalse(needs_lineup_format_setup(context))


if __name__ == "__main__":
    unittest.main()
