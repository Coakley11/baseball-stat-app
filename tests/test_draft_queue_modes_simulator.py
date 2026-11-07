"""Draft Room Simulator: the same Fixed/Adaptive engine on a manual mock board (2026-11-07).

The user drafts for their own team and assigns players to opponents; after each simulated pick the
Adaptive Queue re-evaluates. No recommendation cards, no clock, no automatic picks.
"""

from __future__ import annotations

import copy
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

import draft_queue_modes as dqm
from draft_strategy_in_draft import APPROACH_KEY
from tests.test_draft_queue_modes import QUEUE, _pool

TEAMS = ["Daniel", "Team 2"]


def _board(rounds: int = 8) -> pd.DataFrame:
    rows, n = [], 1
    for rnd in range(1, rounds + 1):
        for team in TEAMS if rnd % 2 else list(reversed(TEAMS)):
            rows.append({"Round": rnd, "Pick": n, "Team": team, "Player": ""})
            n += 1
    return pd.DataFrame(rows)


def _session(**extra) -> dict:
    s = {"draft_room_table": _board(), "_simulator_board_epoch": 3, "draft_queue": list(QUEUE),
         "room_your_team": "Daniel", "room_format": "5x5 Roto", dqm.MODE_KEY: "adaptive", APPROACH_KEY: "roster_aware"}
    s.update(extra)
    return s


def _assign(s: dict, pick: int, player: str) -> None:
    df = s["draft_room_table"]
    df.loc[df["Pick"] == pick, "Player"] = player


def _view(s: dict, pool: pd.DataFrame) -> dict:
    room = dqm.simulator_room(s, pool, teams=TEAMS, your_team="Daniel", fmt=str(s.get("room_format")))
    return dqm.refresh(s, room, "Daniel", source=dqm.simulator_source(s))


class SimulatorAdapterTests(unittest.TestCase):
    def test_board_becomes_rosters_with_projections_and_never_changes(self) -> None:
        s, pool = _session(), _pool()
        _assign(s, 1, "Rabbit A")
        _assign(s, 2, "Bopper X")
        before = s["draft_room_table"].copy()
        room = dqm.simulator_room(s, pool, teams=TEAMS, your_team="Daniel", fmt="5x5 Roto")
        self.assertEqual([r["fullName"] for r in room["rosters"]["Daniel"]], ["Rabbit A"])
        self.assertEqual(room["rosters"]["Team 2"][0]["proj_HR"], 38)
        self.assertTrue(room["config"]["slots_assumed"])
        pd.testing.assert_frame_equal(s["draft_room_table"], before)
        self.assertEqual(dqm.simulator_source(s), "sim:3")


class SimulatorRosterSlotTests(unittest.TestCase):
    def test_active_league_roster_settings_are_used_and_named(self) -> None:
        from unittest import mock

        import fantasy_league_context

        ctx = {"league_name": "Danny League", "roster_settings": {"roster_slots": {"C": 2, "1B": 1, "OF": 5, "BN": 3}}}
        with mock.patch.object(fantasy_league_context, "get_active_league_context", return_value=ctx):
            room = dqm.simulator_room(_session(), _pool(), teams=TEAMS, your_team="Daniel", fmt="5x5 Roto")
        self.assertEqual(room["config"]["slots"].get("C"), 2)
        self.assertEqual(room["config"]["slots"].get("OF"), 5)
        self.assertFalse(room["config"]["slots_assumed"])
        self.assertIn("Danny League", room["config"]["slots_source"])
        needs = dqm.team_needs(room, "Daniel", room["pool"], "5x5 Roto")
        self.assertEqual(needs["open_slots"]["OF"], 5)

    def test_shared_draft_settings_are_used_when_there_is_no_league(self) -> None:
        s = _session(draft_shared_settings={"slots": {"C": 1, "SS": 2}})
        room = dqm.simulator_room(s, _pool(), teams=TEAMS, your_team="Daniel", fmt="5x5 Roto")
        self.assertEqual(room["config"]["slots"], {"C": 1, "SS": 2})
        self.assertEqual(room["config"]["slots_source"], "your draft settings")

    def test_fallback_is_disclosed(self) -> None:
        room = dqm.simulator_room(_session(), _pool(), teams=TEAMS, your_team="Daniel", fmt="5x5 Roto")
        self.assertTrue(room["config"]["slots_assumed"])
        self.assertEqual(room["config"]["slots_source"], "")


class MissingProjectionTests(unittest.TestCase):
    def test_rostered_players_without_projections_are_not_called_strong(self) -> None:
        s = _session()
        _assign(s, 1, "Someone Not In The Pool")
        room = dqm.simulator_room(s, _pool(), teams=TEAMS, your_team="Daniel", fmt="5x5 Roto")
        needs = dqm.team_needs(room, "Daniel", room["pool"], "5x5 Roto")
        self.assertEqual((needs["roster_size"], needs["roster_projected"]), (1, 0))
        self.assertEqual(needs["weak"], [])


class StrategyTrainingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.s, self.pool = _session(), _pool()
        # The user drafts three contact/speed hitters with little power; opponents take others.
        for pick, player in ((1, "Rabbit A"), (2, "Bopper X"), (3, "Avg Bat"), (4, "Rabbit B"), (5, "Rabbit C")):
            _assign(self.s, pick, player)

    def test_power_need_moves_the_slugger_up_and_says_why(self) -> None:
        view = _view(self.s, self.pool)
        self.assertEqual(self.s["draft_queue"], QUEUE)  # the original queue order is preserved
        self.assertLess(view["adaptive"].index("Power Bat"), QUEUE.index("Power Bat") - 1)
        event = next(h for h in view["history"] if h["player"] == "Power Bat")
        self.assertIn("40 HR", " ".join(event["reasons"]))
        self.assertEqual([w["label"] for w in view["needs"]["weak"]][:2], ["HR", "RBI"])

    def test_assigning_him_to_an_opponent_makes_him_unavailable_and_finds_alternatives(self) -> None:
        _view(self.s, self.pool)
        _assign(self.s, 6, "Power Bat")  # pick 6 belongs to Team 2 in the snake
        view = _view(self.s, self.pool)
        self.assertNotIn("Power Bat", view["adaptive"])
        self.assertEqual(view["drafted_here"], ["Power Bat"])
        alt = {s["player"]: s for s in view["suggestions"]}
        self.assertIn("Slugger Two", alt)
        self.assertTrue(any("HR" in r for r in alt["Slugger Two"]["reasons"]))
        self.assertEqual(self.s["draft_queue"], QUEUE)  # never added automatically

    def test_undo_recalculates_to_the_earlier_state(self) -> None:
        before = _view(self.s, self.pool)["adaptive"]
        _assign(self.s, 6, "Power Bat")
        _view(self.s, self.pool)
        _assign(self.s, 6, "")  # undo
        after = _view(self.s, self.pool)
        self.assertEqual(after["adaptive"], before)
        self.assertTrue(all(int(h["pick"]) <= 5 for h in after["history"]))

    def test_changing_an_earlier_selection_recalculates_from_there(self) -> None:
        _view(self.s, self.pool)
        _assign(self.s, 6, "Speed Six")
        _view(self.s, self.pool)
        _assign(self.s, 4, "Slugger Two")  # the user now took power at pick 4 instead
        view = _view(self.s, self.pool)
        self.assertTrue(all(int(h["pick"]) <= 3 or int(h["pick"]) == 6 for h in view["history"]))
        hr = next(w for w in view["needs"]["weak"] if w["label"] == "HR")
        self.assertEqual(hr["team"], 4 + 36 + 3)  # Rabbit A + Slugger Two + Rabbit C

    def test_changing_the_strategy_reevaluates(self) -> None:
        roster = _view(self.s, self.pool)["adaptive"]
        self.s[APPROACH_KEY] = "best_available"
        bpa = _view(self.s, self.pool)
        self.assertNotEqual(bpa["adaptive"], roster)

    def test_switching_modes_never_loses_the_original_queue(self) -> None:
        adaptive = _view(self.s, self.pool)
        self.s[dqm.MODE_KEY] = "fixed"
        fixed = _view(self.s, self.pool)
        self.assertEqual(fixed["fixed"], QUEUE)
        self.assertEqual(adaptive["snapshot"]["players"], QUEUE)

    def test_loading_a_different_plan_keeps_this_mocks_original_snapshot(self) -> None:
        _view(self.s, self.pool)
        from draft_state import sync_draft_queue

        sync_draft_queue(self.s, ["Slugger Two", "Contact C"], reason="load_saved_strategy")
        view = _view(self.s, self.pool)
        self.assertEqual(view["fixed"], ["Slugger Two", "Contact C"])
        self.assertEqual(view["snapshot"]["players"], QUEUE)

    def test_a_mock_never_touches_another_drafts_state_or_the_live_room(self) -> None:
        from tests.test_draft_queue_modes import _room

        live = _room(room_id="LIVE-9")
        self.s["live_draft_room"] = live
        live_before = copy.deepcopy({k: v for k, v in live.items() if k != "pool"})
        self.s[dqm.ADAPTIVE_KEY] = {"live:LIVE-9": {"orders": {"4": ["Speed One"]}, "history": [], "snapshot": {}}}
        _view(self.s, self.pool)
        _assign(self.s, 6, "Speed One")
        _view(self.s, self.pool)
        self.assertEqual(self.s[dqm.ADAPTIVE_KEY]["live:LIVE-9"]["orders"], {"4": ["Speed One"]})
        self.assertEqual({k: v for k, v in live.items() if k != "pool"}, live_before)
        self.assertIn("sim:3", self.s[dqm.ADAPTIVE_KEY])

    def test_a_reset_board_is_a_new_mock(self) -> None:
        _view(self.s, self.pool)
        self.s["_simulator_board_epoch"] = 4
        self.s["draft_room_table"] = _board()
        view = _view(self.s, self.pool)
        self.assertEqual(view["drafted_here"], [])
        self.assertEqual(set(self.s[dqm.ADAPTIVE_KEY]), {"sim:3", "sim:4"})

    def test_no_picks_and_no_clock(self) -> None:
        before = self.s["draft_room_table"].copy()
        for approach in ("balanced", "best_available", "value_based", "positional_scarcity", "roster_aware"):
            self.s[APPROACH_KEY] = approach
            _view(self.s, self.pool)
        pd.testing.assert_frame_equal(self.s["draft_room_table"], before)
        self.assertFalse(any("timer" in k or "clock" in k for k in self.s))


def _sim_panel_script() -> None:
    import streamlit as st

    import draft_queue_modes as dqm
    import draft_queue_panel
    from tests.test_draft_queue_modes import _pool
    from tests.test_draft_queue_modes_simulator import TEAMS, _assign, _session

    ss = st.session_state
    if "draft_room_table" not in ss:
        for k, v in _session().items():
            ss[k] = v
        ss[dqm.MODE_KEY] = "fixed"
        for pick, player in ((1, "Rabbit A"), (2, "Bopper X"), (3, "Avg Bat"), (4, "Rabbit B"), (5, "Rabbit C")):
            _assign(ss, pick, player)
    pool = _pool()
    room = dqm.simulator_room(ss, pool, teams=TEAMS, your_team="Daniel", fmt="5x5 Roto")
    draft_queue_panel.render_draft_strategy_panel(st, ss, room, viewer_team="Daniel", key_prefix="sim",
                                                  source=dqm.simulator_source(ss), cards=False)


class SimulatorPanelTests(unittest.TestCase):
    def test_panel_in_the_simulator_has_no_cards_and_switches_modes(self) -> None:
        at = AppTest.from_function(_sim_panel_script, default_timeout=60)
        at.run()
        self.assertFalse(at.exception)
        self.assertFalse(any("Cards ranked" in str(c.value) for c in at.caption))
        at.selectbox(key=APPROACH_KEY).select("value_based").run()
        self.assertTrue(any("shapes the Adaptive Queue" in str(c.value) for c in at.caption))
        at.radio(key=dqm.MODE_KEY).set_value("adaptive").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["draft_queue"], QUEUE)
        self.assertTrue(any("standard starter slots are assumed" in str(c.value) for c in at.caption))
        # The Simulator has no timer: it says nothing about Auto Pick, only that nothing here picks.
        self.assertFalse(any("Auto Pick" in str(i.value) for i in at.info))
        self.assertTrue(any("you log every pick yourself" in str(c.value) for c in at.caption))


if __name__ == "__main__":
    unittest.main()
