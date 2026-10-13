"""Regression tests for the Live Draft quality pass (ready loop, eligibility, shared rooms)."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import MutableMapping
from pathlib import Path

import pandas as pd


class _ProxySession(MutableMapping):
    """Mapping that is not a dict — like Streamlit's SessionStateProxy."""

    def __init__(self, data=None):
        self._d = dict(data or {})

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        self._d[k] = v

    def __delitem__(self, k):
        del self._d[k]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


class Pick1SnapshotReadinessTests(unittest.TestCase):
    def test_ready_snapshot_is_seen_through_a_non_dict_session(self) -> None:
        from live_draft_ready_prewarm import (
            PICK1_READY_FLAG,
            PICK1_SNAPSHOT_KEY,
            pick1_snapshot_is_ready,
        )

        room = {"draft_room_id": "R1", "current_pick_index": 0, "draft_board": []}
        session = _ProxySession(
            {PICK1_SNAPSHOT_KEY: {"ok": True, "room_id": "R1"}, PICK1_READY_FLAG: True}
        )
        # A dict-only guard returned False here, so the Ready lobby rebuilt the
        # snapshot and called st.rerun() on every run.
        self.assertTrue(pick1_snapshot_is_ready(session, room))

    def test_snapshot_for_a_started_room_is_not_ready(self) -> None:
        from live_draft_ready_prewarm import PICK1_SNAPSHOT_KEY, pick1_snapshot_is_ready

        room = {"draft_room_id": "R1", "current_pick_index": 1, "draft_board": [{}]}
        session = _ProxySession({PICK1_SNAPSHOT_KEY: {"ok": True, "room_id": "R1"}})
        self.assertFalse(pick1_snapshot_is_ready(session, room))


class SetupDefaultsTests(unittest.TestCase):
    def test_default_picks_cover_default_required_starters(self) -> None:
        from fantasy_roster_validation import validate_live_draft_setup
        from user_page_preferences import default_live_draft_setup_settings

        picks = default_live_draft_setup_settings()["live_draft_picks_per_team"]
        default_slots = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0, "BN": 5}
        self.assertTrue(validate_live_draft_setup(picks_per_team=picks, slots=default_slots)["ok"])


class OpenNeedEligibilityTests(unittest.TestCase):
    def test_flex_slot_takes_two_way_hitters(self) -> None:
        from live_draft_roster_slots import _eligible_for_draft_slot, _eligible_for_open_need_recommendation

        tokens = ["DH", "P"]  # Ohtani: DH/UTIL/P
        self.assertTrue(_eligible_for_draft_slot(tokens, "DH"))
        self.assertTrue(_eligible_for_open_need_recommendation(tokens, "UTIL"))
        self.assertFalse(_eligible_for_draft_slot(["SP"], "DH"))

    def test_player_fills_open_needs(self) -> None:
        from live_draft_roster_slots import player_fills_open_needs as fills

        # Starter gaps remain: only those positions count (BN is no escape hatch) …
        self.assertFalse(fills(["SS"], ["C", "DH", "BN"]))
        self.assertTrue(fills(["C"], ["C", "DH"]))
        # … except a DH-only hitter while DH is open.
        self.assertTrue(fills(["DH", "P"], ["C", "DH"]))
        # Only DH left: any hitter, never a pitcher.
        self.assertTrue(fills(["SS"], ["DH"]))
        self.assertFalse(fills(["SP"], ["DH"]))
        # Bench open: anyone league-legal.
        self.assertTrue(fills(["SP"], ["DH", "BN"]))

    def test_recommendation_filter_keeps_dh_only_player_while_starters_remain(self) -> None:
        from live_draft_roster_slots import filter_candidates_to_team_open_positions

        pool = pd.DataFrame(
            [
                {"fullName": "Two Way", "Primary Position": "DH", "Eligible Positions": "DH/UTIL/P"},
                {"fullName": "Short Stop", "Primary Position": "SS", "Eligible Positions": None},
                {"fullName": "Catcher", "Primary Position": "C", "Eligible Positions": None},
            ]
        )
        roster = pd.DataFrame([{"fullName": "Filled SS", "Primary Position": "SS"}])
        cfg = {"slots": {"C": 1, "SS": 1, "DH": 1, "BN": 2}}
        kept = set(filter_candidates_to_team_open_positions(pool, roster, config=cfg)["fullName"])
        self.assertEqual(kept, {"Two Way", "Catcher"})

    def test_autopick_candidate_valid_when_only_dh_is_open(self) -> None:
        from live_draft_autopick import _candidate_still_valid

        cand = {"playerID": "x1", "fullName": "Short Stop", "Primary Position": "SS", "Eligible Positions": None}
        # Text matching required a literal "DH", so this stalled the draft.
        self.assertTrue(_candidate_still_valid(cand, drafted=set(), gaps=["DH"]))
        pitcher = {"playerID": "p1", "fullName": "Arm", "Primary Position": "SP", "Eligible Positions": None}
        self.assertFalse(_candidate_still_valid(pitcher, drafted=set(), gaps=["DH"]))
        self.assertFalse(_candidate_still_valid(cand, drafted={"id:x1"}, gaps=["DH"]))


class RosterProjectionTests(unittest.TestCase):
    def test_roster_rows_gain_pool_projections(self) -> None:
        from live_draft_roster_tracker import roster_df_for_team

        pool = pd.DataFrame(
            [{"playerID": "a1", "fullName": "Slugger", "proj_HR": 40.0, "proj_SB": 5.0}]
        )
        room = {"rosters": {"Team A": [{"playerID": "a1", "fullName": "Slugger"}]}, "pool": pool}
        df = roster_df_for_team(room, "Team A")
        self.assertEqual(float(df.loc[0, "proj_HR"]), 40.0)

    def test_category_outlook_counts_rostered_projections(self) -> None:
        from live_draft_category_outlook import compute_category_outlook
        from live_draft_roster_tracker import roster_df_for_team

        pool = pd.DataFrame(
            [
                {"playerID": f"p{i}", "fullName": f"P{i}", "proj_HR": 10.0, "proj_SB": 5.0,
                 "proj_RBI": 50.0, "proj_R": 50.0, "proj_BA": 0.250}
                for i in range(10)
            ]
        )
        room = {"rosters": {"Team A": [{"playerID": "p0", "fullName": "P0"}]}, "pool": pool}
        outlook = compute_category_outlook(roster_df_for_team(room, "Team A"), pool, config={})
        hr = next(b for b in outlook["bars"] if b["category"] == "HR")
        self.assertEqual(hr["team_value"], 10.0)


class LocalSharedRoomWriteTests(unittest.TestCase):
    def test_save_is_atomic_and_leaves_no_temp_files(self) -> None:
        import draft_room_shared_state as m

        with tempfile.TemporaryDirectory() as tmp:
            store = m.LocalFileSharedRoomStore.__new__(m.LocalFileSharedRoomStore)
            store.root = Path(tmp)
            store.save({"room_code": "ABC123", "revision": 1, "filler": "x" * 5000})
            store.save({"room_code": "ABC123", "revision": 2})
            path = Path(tmp) / "ABC123.json"
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["revision"], 2)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["ABC123.json"])


class SharedPresenceLabelTests(unittest.TestCase):
    def test_guest_seat_is_not_labelled_with_the_host_name(self) -> None:
        from live_draft_presence import required_human_participant_rows

        doc = {
            "room": {"teams": ["Team A", "Team B"], "config": {"num_teams": 2}},
            "commissioner_participant_id": "workspace:host",
            "host_participant_id": "workspace:host",
            "participants": {
                "workspace:host": {"assigned_team": "Team A", "user_id": "local:default", "display_name": "workspace:host"},
                "workspace:guest": {"assigned_team": "Team B", "user_id": "local:default", "display_name": "workspace:guest"},
            },
            "joined_participants": {
                "local:default": {"display_name": "workspace:host", "team_name": "Team A", "user_id": "local:default"},
                "workspace:host": {"display_name": "workspace:host", "team_name": "Team A", "user_id": "workspace:host"},
                "workspace:guest": {"display_name": "workspace:guest", "team_name": "Team B", "user_id": "workspace:guest"},
            },
        }
        rows = required_human_participant_rows({}, doc["room"], document=doc, allow_network=False)
        names = {r["team_name"]: r["display_name"] for r in rows}
        self.assertEqual(names.get("Team B"), "workspace:guest")


class CanonicalPeekTests(unittest.TestCase):
    def test_peek_returns_the_stored_blob_without_copying(self) -> None:
        from live_draft_state import LIVE_DRAFT_STATE_KEY, has_active_live_draft, peek_canonical_live_draft

        blob = {"draft_room_id": "R9", "status": "in_progress"}
        session = {LIVE_DRAFT_STATE_KEY: blob}
        self.assertIs(peek_canonical_live_draft(session), blob)
        self.assertTrue(has_active_live_draft(session))

    def test_owned_save_pipeline_matches_copying_pipeline(self) -> None:
        from live_draft_state import LIVE_DRAFT_STATE_KEY, sanitize_state_dict_for_json

        def state():
            return {
                LIVE_DRAFT_STATE_KEY: {
                    "draft_room_id": "R9",
                    "status": "in_progress",
                    "pool_records": [{"playerID": "a"}],
                    "pool_columns": ["playerID"],
                },
                "page_filter_state": {},
            }

        a = sanitize_state_dict_for_json(state())
        b = sanitize_state_dict_for_json(state(), copy_input=False)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))


class DecisionScoreCopyTests(unittest.TestCase):
    def test_tooltip_does_not_promise_a_0_to_100_range(self) -> None:
        from draft_score_display import DISPLAY_PICK_SCORE, SCORE_TOOLTIPS

        self.assertNotIn("0–100", SCORE_TOOLTIPS[DISPLAY_PICK_SCORE])


if __name__ == "__main__":
    unittest.main()
