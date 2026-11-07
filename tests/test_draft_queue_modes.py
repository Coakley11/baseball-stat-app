"""Fixed and Adaptive Draft Queue modes (2026-11-07).

Synthetic leagues only: a 5x5 Roto league whose roster is short on power, a points league, a
pitching pool, and the real-app harness draft (Solo and Shared rooms).
"""

from __future__ import annotations

import copy
import json
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

import draft_queue_modes as dqm
from draft_strategy_in_draft import APPROACH_KEY

# name, pos, HR, RBI, R, SB, AVG, AB, value
HITTERS = [
    ("Power Bat", "1B", 40, 110, 85, 2, 0.265, 600, 330),
    ("Slugger Two", "3B", 36, 100, 80, 4, 0.255, 580, 320),
    ("Speed One", "OF", 6, 45, 95, 45, 0.280, 600, 335),
    ("Speed Two", "OF", 5, 40, 90, 40, 0.275, 590, 325),
    ("Speed Three", "OF", 7, 48, 88, 38, 0.270, 580, 318),
    ("Speed Four", "2B", 8, 50, 86, 35, 0.268, 570, 312),
    ("Speed Five", "SS", 9, 52, 84, 33, 0.266, 560, 308),
    ("Speed Six", "SS", 6, 44, 80, 30, 0.262, 550, 300),
    ("Contact C", "C", 12, 60, 60, 2, 0.300, 450, 280),
    ("Avg Bat", "OF", 20, 75, 75, 10, 0.260, 560, 290),
]
for i in range(20):  # league filler: the league medians come from here too
    HITTERS.append((f"Filler {i:02d}", ["C", "1B", "2B", "3B", "SS", "OF"][i % 6], 15 + i % 10, 60 + i, 65 + i,
                    8 + i % 7, 0.250 + (i % 5) * 0.004, 500, 200 - i))
# Already on Team A (drafted): three speedsters, no power.
ROSTER_A = [("Rabbit A", "OF", 4, 40, 90, 42, 0.270, 590, 300), ("Rabbit B", "2B", 5, 42, 85, 38, 0.268, 580, 296),
            ("Rabbit C", "SS", 3, 38, 82, 36, 0.265, 570, 292)]
ROSTER_B = [("Bopper X", "OF", 38, 105, 80, 3, 0.250, 590, 310)]


def _pool(rows=None) -> pd.DataFrame:
    rows = rows or (HITTERS + ROSTER_A + ROSTER_B)
    return pd.DataFrame([
        {"playerID": f"h{i:03d}", "fullName": r[0], "Primary Position": r[1], "proj_HR": r[2], "proj_RBI": r[3],
         "proj_R": r[4], "proj_SB": r[5], "proj_BA": r[6], "proj_AB": r[7], "Expected Fantasy Value": float(r[8]),
         "Decision Score": float(r[8]) / 4}
        for i, r in enumerate(rows)
    ])


def _room(fmt: str = "5x5 Roto", room_id: str = "ROTO-1") -> dict:
    pool = _pool()
    board, rosters = [], {"Team A": [], "Team B": []}
    pick = 0
    for team, players in (("Team A", ROSTER_A), ("Team B", ROSTER_B)):
        for r in players:
            pick += 1
            rec = pool[pool["fullName"] == r[0]].iloc[0].to_dict()
            rec.update({"Pick": pick, "Team": team})
            board.append(rec)
            rosters[team].append(rec)
    return {"draft_room_id": room_id, "status": "in_progress", "teams": ["Team A", "Team B"], "draft_board": board,
            "rosters": rosters, "current_pick_index": pick,
            "config": {"num_teams": 2, "fantasy_format": fmt, "your_team": "Team A",
                       "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "BN": 2}},
            "pool": pool}


QUEUE = ["Speed One", "Speed Two", "Speed Three", "Speed Four", "Speed Five", "Speed Six", "Contact C", "Power Bat"]


def _session(room: dict, queue=None, **extra) -> dict:
    s = {"live_draft_room": room, "active_page": "Live Draft Room", "main_sidebar_page": "Live Draft Room",
         "live_draft_setup_mode": "solo", "draft_queue": list(queue if queue is not None else QUEUE)}
    s.update(extra)
    return s


def _pick(room: dict, name: str, team: str) -> None:
    rec = room["pool"][room["pool"]["fullName"] == name].iloc[0].to_dict()
    rec.update({"Pick": len(room["draft_board"]) + 1, "Team": team})
    room["draft_board"].append(rec)
    room["rosters"].setdefault(team, []).append(rec)
    room["current_pick_index"] += 1


def _undo(room: dict) -> None:
    rec = room["draft_board"].pop()
    room["rosters"][rec["Team"]].remove(rec)
    room["current_pick_index"] -= 1


class SetupTests(unittest.TestCase):
    def test_the_session_is_a_live_draft(self) -> None:
        self.assertEqual(dqm.draft_source(_session(_room())), "live:ROTO-1")

    def test_fixed_is_the_default(self) -> None:
        self.assertEqual(dqm.current_mode({}), "fixed")
        self.assertEqual(dqm.current_mode({dqm.MODE_KEY: "nonsense"}), "fixed")


class FixedQueueTests(unittest.TestCase):
    def test_fixed_never_reorders_and_skips_players_drafted_here(self) -> None:
        room = _room()
        s = _session(room, **{APPROACH_KEY: "roster_aware"})
        for name, team in (("Speed Two", "Team B"), ("Avg Bat", "Team A"), ("Slugger Two", "Team B")):
            _pick(room, name, team)
            view = dqm.refresh(s, room, "Team A")
        self.assertEqual(s["draft_queue"], QUEUE)  # the saved queue is untouched
        self.assertEqual(view["fixed"], [n for n in QUEUE if n != "Speed Two"])
        self.assertEqual(view["drafted_here"], ["Speed Two"])
        self.assertEqual(view["history"], [])  # Fixed mode logs nothing


class AdaptiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room = _room()
        self.s = _session(self.room, **{dqm.MODE_KEY: "adaptive", APPROACH_KEY: "roster_aware"})

    def test_team_needs_sum_counting_stats_and_find_the_power_gap(self) -> None:
        needs = dqm.team_needs(self.room, "Team A", self.room["pool"], "5x5 Roto")
        weak = {w["label"]: w for w in needs["weak"]}
        self.assertIn("HR", weak)
        self.assertIn("RBI", weak)
        self.assertNotIn("SB", weak)
        self.assertIn("SB", needs["strong"])
        med_hr = float(self.room["pool"]["proj_HR"].median())
        self.assertAlmostEqual(weak["HR"]["expected"], round(med_hr * 3, 3))  # 3 rostered players
        self.assertEqual(weak["HR"]["team"], 12.0)  # 4 + 5 + 3
        self.assertEqual(weak["HR"]["level"], "Critical")

    def test_power_bat_moves_up_with_a_reason_from_real_projections(self) -> None:
        view = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(self.s["draft_queue"], QUEUE)  # never written
        new_rank = view["adaptive"].index("Power Bat") + 1
        self.assertLessEqual(new_rank, 6)
        event = next(h for h in view["history"] if h["player"] == "Power Bat")
        self.assertEqual(event["direction"], "up")
        self.assertEqual(event["from"], 8)
        text = " ".join(event["reasons"])
        self.assertIn("critical in HR and RBI", text)
        self.assertIn("40 HR", text)
        self.assertIn("110 RBI", text)
        self.assertIn("open 1B slot", text)
        self.assertIn("whom you ranked higher", text)

    def test_adaptive_responds_to_availability_and_roster_changes(self) -> None:
        dqm.refresh(self.s, self.room, "Team A")
        _pick(self.room, "Power Bat", "Team B")  # gone in this draft
        _pick(self.room, "Slugger Two", "Team A")  # Team A finally gets power
        view = dqm.refresh(self.s, self.room, "Team A")
        self.assertNotIn("Power Bat", view["adaptive"])
        self.assertEqual(view["drafted_here"], ["Power Bat"])
        hr_now = next(w for w in view["needs"]["weak"] if w["label"] == "HR")
        self.assertEqual(hr_now["team"], 48.0)  # 12 + Slugger Two's 36
        # 12 of an expected 54 (3 players) before; 48 of 72 (4 players) now: the gap is closing.
        self.assertGreater(hr_now["team"] / hr_now["expected"], 12.0 / 54.0)

    def test_strategy_switch_changes_the_adaptive_order(self) -> None:
        roster = dqm.refresh(self.s, self.room, "Team A")["adaptive"]
        self.s[APPROACH_KEY] = "best_available"
        bpa = dqm.refresh(self.s, self.room, "Team A")
        self.assertNotEqual(roster, bpa["adaptive"])
        self.assertTrue(any(h["trigger"] == "strategy" for h in bpa["history"]))

    def test_pinned_players_keep_their_fixed_place(self) -> None:
        dqm.set_pins(self.s, ["Speed Six"])
        view = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(view["adaptive"].index("Speed Six"), QUEUE.index("Speed Six"))

    def test_small_score_differences_do_not_reshuffle(self) -> None:
        names = ["A", "B", "C"]
        scores = {"a": {"score": 0.50}, "b": {"score": 0.52}, "c": {"score": 0.53}}
        self.assertEqual(dqm.adaptive_order(names, scores, []), names)
        scores["c"]["score"] = 0.60
        self.assertEqual(dqm.adaptive_order(names, scores, []), ["C", "A", "B"])

    def test_deterministic_for_the_same_state(self) -> None:
        a = dqm.refresh(copy.deepcopy(self.s), copy.deepcopy(self.room), "Team A")
        b = dqm.refresh(copy.deepcopy(self.s), copy.deepcopy(self.room), "Team A")
        self.assertEqual(a["adaptive"], b["adaptive"])

    def test_never_picks_and_never_touches_the_room(self) -> None:
        before = copy.deepcopy({k: v for k, v in self.room.items() if k != "pool"})
        for approach in ("balanced", "best_available", "value_based", "positional_scarcity", "roster_aware"):
            self.s[APPROACH_KEY] = approach
            dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual({k: v for k, v in self.room.items() if k != "pool"}, before)

    def test_auto_pick_reads_the_fixed_queue_not_the_adaptive_order(self) -> None:
        import inspect

        import live_draft_autopick

        source = inspect.getsource(live_draft_autopick)
        for key in (dqm.ADAPTIVE_KEY, dqm.MODE_KEY, "draft_queue_modes"):
            self.assertNotIn(key, source)

    def test_suggests_strong_players_outside_the_queue_with_reasons(self) -> None:
        view = dqm.refresh(self.s, self.room, "Team A")
        self.assertLessEqual(len(view["suggestions"]), dqm.MAX_SUGGESTIONS)
        self.assertEqual(self.s["draft_queue"], QUEUE)  # nothing added automatically
        for s in view["suggestions"]:
            self.assertNotIn(s["player"], QUEUE)
            self.assertTrue(s["reasons"])


class RateStatTests(unittest.TestCase):
    def test_avg_is_volume_weighted_not_summed(self) -> None:
        rows = [("Full Time", "OF", 10, 60, 60, 5, 0.300, 600, 250), ("Part Time", "OF", 3, 20, 20, 1, 0.320, 150, 150)]
        rows += [(f"F{i}", "OF", 10, 50, 50, 5, 0.260, 500, 100) for i in range(8)]
        pool = _pool(rows)
        impact = dqm._category_impact(pool, [{"label": "AVG", "col": "proj_BA", "kind": "rate", "level": "Low"}], pool)
        full, part = (float(impact["AVG"][pool.index[pool["fullName"] == n][0]]) for n in ("Full Time", "Part Time"))
        self.assertGreater(full, part)  # (.300-.260)*600 = 24 hits > (.320-.260)*150 = 9

    def test_era_is_lower_is_better(self) -> None:
        pitchers = pd.DataFrame([
            {"fullName": f"P{i}", "Primary Position": "SP", "proj_ERA": era, "proj_K": k, "proj_IP": 170.0,
             "Expected Fantasy Value": 100.0 + i}
            for i, (era, k) in enumerate([(3.0, 210), (3.4, 190), (3.8, 180), (4.0, 170), (4.2, 160), (4.6, 150),
                                          (5.2, 120), (5.4, 110)])
        ])
        rec = lambda n: {**pitchers[pitchers["fullName"] == n].iloc[0].to_dict(), "Team": "Team A"}  # noqa: E731
        room = {"draft_board": [rec("P6"), rec("P7")], "rosters": {"Team A": [rec("P6"), rec("P7")]},
                "config": {"fantasy_format": "5x5 Roto", "slots": {"SP": 4}}, "pool": pitchers}
        needs = dqm.team_needs(room, "Team A", pitchers, "5x5 Roto")
        era = next(w for w in needs["weak"] if w["label"] == "ERA")
        self.assertEqual(era["kind"], "rate_low")
        impact = dqm._category_impact(pitchers, [era], pitchers)["ERA"]
        self.assertGreater(float(impact[0]), float(impact[5]))  # 3.00 ERA helps more than 4.60


class PointsLeagueTests(unittest.TestCase):
    def test_points_league_has_no_category_deficits(self) -> None:
        room = _room("Points League")
        s = _session(room, **{dqm.MODE_KEY: "adaptive", APPROACH_KEY: "roster_aware"})
        view = dqm.refresh(s, room, "Team A")
        self.assertTrue(view["needs"]["points"])
        self.assertEqual(view["needs"]["weak"], [])
        for h in view["history"]:
            self.assertFalse(any("projected team is" in r for r in h["reasons"]))


class ExplanationHonestyTests(unittest.TestCase):
    def test_without_research_history_it_says_so_and_invents_nothing(self) -> None:
        room = _room()
        s = _session(room, **{dqm.MODE_KEY: "adaptive", APPROACH_KEY: "roster_aware"})
        view = dqm.refresh(s, room, "Team A")
        limits = " ".join(dqm.research_limitations(s, view["snapshot"]))
        self.assertIn("No saved strategy was loaded", limits)
        self.assertIn("No research notes were recorded", limits)
        for h in view["history"]:
            self.assertFalse(any(r.startswith(("Your note", "You moved him")) for r in h["reasons"]))
            self.assertIn("No saved strategy was recorded", h["alignment"])

    def test_recorded_notes_moves_and_saved_strategy_are_quoted_exactly(self) -> None:
        room = _room()
        s = _session(room, **{dqm.MODE_KEY: "adaptive", APPROACH_KEY: "roster_aware"})
        s[dqm.LOADED_STRATEGY_KEY] = {"id": "x1", "name": "Power later", "approach": "roster_aware", "notes": {}}
        dqm.set_note(s, "Power Bat", "Elite exit velocity; wait on him")
        dqm.note_manual_moves(s, ["Power Bat", "Speed One"], ["Speed One", "Power Bat"])
        view = dqm.refresh(s, room, "Team A")
        event = next(h for h in view["history"] if h["player"] == "Power Bat")
        self.assertIn("Your note: “Elite exit velocity; wait on him”.", event["reasons"])
        self.assertIn("You moved him down yourself (#1 → #2).", event["reasons"])
        self.assertTrue(event["follows_strategy"])
        self.assertIn("Power later", event["alignment"])
        s[APPROACH_KEY] = "best_available"
        later = dqm.refresh(s, room, "Team A")
        if later["history"][-1]["trigger"] == "strategy":
            self.assertFalse(later["history"][-1]["follows_strategy"])

    def test_manual_reorder_through_the_queue_write_path_is_recorded(self) -> None:
        from draft_state import sync_draft_queue

        s = _session(_room())
        sync_draft_queue(s, ["Speed Two", "Speed One"] + QUEUE[2:], reason="move_queue_up")
        self.assertTrue(dqm.moves_for(s, "Speed Two"))
        sync_draft_queue(s, QUEUE[:3], reason="remove_from_queue")  # not a reorder
        self.assertEqual(len(dqm.plan(s)["moves"]), 2)


class SnapshotAndHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room = _room()
        self.s = _session(self.room, **{dqm.MODE_KEY: "adaptive", APPROACH_KEY: "roster_aware"})

    def test_snapshot_survives_adaptations_and_edits_and_restores(self) -> None:
        from draft_state import sync_draft_queue

        dqm.refresh(self.s, self.room, "Team A")
        for name, team in (("Avg Bat", "Team B"), ("Contact C", "Team A"), ("Slugger Two", "Team B")):
            _pick(self.room, name, team)
            dqm.refresh(self.s, self.room, "Team A")
        sync_draft_queue(self.s, ["Speed Six"], reason="queue_change")
        view = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(view["snapshot"]["players"], QUEUE)
        with self.assertRaises(ValueError):
            dqm.restore_snapshot_to_queue(self.s, confirmed=False)
        dqm.restore_snapshot_to_queue(self.s, confirmed=True)
        self.assertEqual(self.s["draft_queue"], QUEUE)

    def test_mode_switch_restores_the_fixed_view(self) -> None:
        adaptive = dqm.refresh(self.s, self.room, "Team A")
        self.s[dqm.MODE_KEY] = "fixed"
        fixed = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(fixed["fixed"], QUEUE)
        self.assertNotEqual(adaptive["adaptive"], QUEUE)
        self.s[dqm.MODE_KEY] = "adaptive"
        again = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(again["adaptive"], adaptive["adaptive"])

    def test_undo_recalculates_safely(self) -> None:
        at_start = dqm.refresh(self.s, self.room, "Team A")["adaptive"]
        _pick(self.room, "Speed One", "Team B")
        dqm.refresh(self.s, self.room, "Team A")
        _pick(self.room, "Slugger Two", "Team A")
        after = dqm.refresh(self.s, self.room, "Team A")
        self.assertIn("6", self.s[dqm.ADAPTIVE_KEY]["live:ROTO-1"]["orders"])
        self.assertNotIn("Speed One", after["adaptive"])
        _undo(self.room)
        _undo(self.room)
        back = dqm.refresh(self.s, self.room, "Team A")
        self.assertEqual(back["adaptive"], at_start)
        self.assertTrue(all(int(h["pick"]) <= 4 for h in back["history"]))

    def test_state_survives_a_workspace_round_trip_without_duplicate_history(self) -> None:
        first = dqm.refresh(self.s, self.room, "Team A")
        restored = json.loads(json.dumps({k: self.s[k] for k in (dqm.MODE_KEY, dqm.PLAN_KEY, dqm.ADAPTIVE_KEY)}))
        s2 = _session(self.room, **restored, **{APPROACH_KEY: "roster_aware"})
        again = dqm.refresh(s2, self.room, "Team A")
        self.assertEqual(again["adaptive"], first["adaptive"])
        self.assertEqual(len(again["history"]), len(first["history"]))

    def test_persisted_with_the_workspace_and_cleared_on_sign_out(self) -> None:
        import baseball_persistent_state as bps
        from draft_queue_contract import clear_queue_for_account_change

        for key in (dqm.MODE_KEY, dqm.PLAN_KEY, dqm.ADAPTIVE_KEY, dqm.LOADED_STRATEGY_KEY):
            self.assertIn(key, bps._WORKFLOW_KEYS)
        dqm.refresh(self.s, self.room, "Team A")
        clear_queue_for_account_change(self.s)
        for key in (dqm.PLAN_KEY, dqm.ADAPTIVE_KEY, dqm.LOADED_STRATEGY_KEY, "draft_queue"):
            self.assertNotIn(key, self.s)

    def test_comparison_highlights_only_meaningful_moves(self) -> None:
        view = dqm.refresh(self.s, self.room, "Team A")
        rows = dqm.comparison_rows(view)
        self.assertEqual(len(rows), len(QUEUE))
        moved = [r for r in rows if r["Move"]]
        self.assertTrue(moved)
        for r in rows:
            if not r["Move"]:
                self.assertNotIn("↑", r["Adaptive Queue"])
                self.assertNotIn("↓", r["Adaptive Queue"])
        top = dqm.significant_changes(view)
        self.assertTrue(all(abs(h["net"]) >= dqm.MEANINGFUL_MOVE for h in top))

    def test_moves_are_listed_with_their_reasons_for_narrow_screens(self) -> None:
        view = dqm.refresh(self.s, self.room, "Team A")
        rows, moves = dqm.comparison_rows(view), dqm.comparison_moves(view)
        self.assertEqual(len(moves), len([r for r in rows if r["Move"]]))
        for m in moves:
            self.assertEqual(view["adaptive"][m["adaptive"] - 1], m["player"])
            self.assertEqual(view["fixed"][m["fixed"] - 1], m["player"])
            self.assertEqual(m["direction"], "up" if m["fixed"] > m["adaptive"] else "down")
            self.assertTrue(m["reason"])


class PerDraftPrivacyTests(unittest.TestCase):
    def test_drafted_players_are_unavailable_only_in_that_draft(self) -> None:
        room1, room2 = _room(room_id="MOCK-1"), _room(room_id="LEAGUE-2")
        s = _session(room1, **{dqm.MODE_KEY: "adaptive", APPROACH_KEY: "roster_aware"})
        _pick(room1, "Power Bat", "Team B")
        v1 = dqm.refresh(s, room1, "Team A")
        s["live_draft_room"] = room2
        v2 = dqm.refresh(s, room2, "Team A")
        self.assertNotIn("Power Bat", v1["adaptive"])
        self.assertIn("Power Bat", v2["adaptive"])
        self.assertEqual(set(s[dqm.ADAPTIVE_KEY]), {"live:MOCK-1", "live:LEAGUE-2"})
        # Moving on in draft 1 never reorders draft 2.
        s["live_draft_room"] = room1
        _pick(room1, "Slugger Two", "Team A")
        dqm.refresh(s, room1, "Team A")
        self.assertEqual(s[dqm.ADAPTIVE_KEY]["live:LEAGUE-2"]["orders"], {str(len(room2["draft_board"])): v2["adaptive"]})

    def test_personal_keys_never_reach_a_shared_room_document(self) -> None:
        from draft_room_shared_state import sanitize_shared_room_document, shared_room_document_private_leaks

        doc = {"draft_room_id": "R", dqm.MODE_KEY: "adaptive", dqm.PLAN_KEY: {"notes": {"x": "y"}},
               dqm.ADAPTIVE_KEY: {"live:R": {}}, APPROACH_KEY: "value_based", dqm.LOADED_STRATEGY_KEY: {"name": "n"}}
        self.assertEqual(len(shared_room_document_private_leaks(doc)), 5)
        clean = sanitize_shared_room_document(dict(doc))
        self.assertEqual(shared_room_document_private_leaks(clean), [])


def _two_managers():
    from tests import live_draft_real_app_harness as h

    h.isolate_environment()
    code, host, guest = h.shared_seeds()
    return code, host, guest


class TwoManagerTests(unittest.TestCase):
    def test_two_managers_keep_private_queues_strategies_and_histories(self) -> None:
        code, host, guest = _two_managers()
        room_h, room_g = host["live_draft_room"], guest["live_draft_room"]
        host.update({"draft_queue": ["Player 010", "Player 040", "Player 020"], dqm.MODE_KEY: "adaptive",
                     APPROACH_KEY: "best_available"})
        guest.update({"draft_queue": ["Player 030", "Player 015"], dqm.MODE_KEY: "fixed", APPROACH_KEY: "roster_aware"})
        before = copy.deepcopy({k: v for k, v in room_h.items() if k != "pool"})
        vh = dqm.refresh(host, room_h, "Team A")
        vg = dqm.refresh(guest, room_g, "Team B")
        self.assertEqual(set(vh["fixed"]), {"Player 010", "Player 040", "Player 020"})
        self.assertEqual(vg["fixed"], ["Player 030", "Player 015"])
        self.assertEqual(vg["history"], [])
        self.assertEqual(host[APPROACH_KEY], "best_available")
        self.assertEqual(guest[APPROACH_KEY], "roster_aware")
        self.assertEqual({k: v for k, v in room_h.items() if k != "pool"}, before)
        from draft_room_shared_state import shared_room_document_private_leaks

        self.assertEqual(shared_room_document_private_leaks({k: v for k, v in room_h.items() if k != "pool"}), [])
        # Each manager's adaptive state lives only in their own session.
        self.assertIsNot(host[dqm.ADAPTIVE_KEY], guest.get(dqm.ADAPTIVE_KEY))
        self.assertNotIn("Player 010", json.dumps(guest.get(dqm.ADAPTIVE_KEY) or {}))
        self.assertNotIn("Player 030", json.dumps(host.get(dqm.ADAPTIVE_KEY) or {}))


def _panel_script() -> None:
    import streamlit as st

    import draft_queue_panel
    from tests.test_draft_queue_modes import _room, _session

    ss = st.session_state
    if "live_draft_room" not in ss:
        for k, v in _session(_room()).items():
            ss[k] = v
    draft_queue_panel.render_draft_strategy_panel(st, ss, ss["live_draft_room"], viewer_team="Team A")


def _panel_labels(at) -> list[str]:
    # An expander with an icon is listed by AppTest as a "status" element.
    return [str(e.label) for e in list(at.expander) + list(at.status)]


class PanelTests(unittest.TestCase):
    def test_panel_opens_switches_modes_and_leaves_draft_state_alone(self) -> None:
        at = AppTest.from_function(_panel_script, default_timeout=60)
        at.run()
        self.assertFalse(at.exception)
        self.assertIn("Draft Strategy", _panel_labels(at))
        self.assertTrue(any("Balanced strategy · Fixed queue" in str(c.value) for c in at.caption))
        self.assertFalse(any("Auto Pick" in str(i.value) for i in at.info))
        self.assertTrue(any("Auto Pick doesn't use your queue" in str(c.value) for c in at.caption))
        room_before = copy.deepcopy({k: v for k, v in at.session_state["live_draft_room"].items() if k != "pool"})
        at.radio(key=dqm.MODE_KEY).set_value("adaptive").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state[dqm.MODE_KEY], "adaptive")
        self.assertIn("Draft Strategy", _panel_labels(at))  # same expander: it stays open
        self.assertTrue(any("Balanced strategy · Adaptive queue" in str(c.value) for c in at.caption))
        self.assertTrue(any("Auto Pick doesn't use your queue" in str(i.value) for i in at.info))
        self.assertFalse(any("uses your Fixed queue" in str(i.value) for i in at.info))
        at.run()  # a rerun keeps the mode
        self.assertEqual(at.session_state[dqm.MODE_KEY], "adaptive")
        self.assertEqual(at.session_state["draft_queue"], QUEUE)
        self.assertEqual({k: v for k, v in at.session_state["live_draft_room"].items() if k != "pool"}, room_before)
        tabs = [t.label for t in at.tabs]
        for label in ("Fixed vs Adaptive", "What changed and why?", "Team needs", "Original plan", "Pins & notes"):
            self.assertIn(label, tabs)
        self.assertTrue(any("moved up" in str(m.value) for m in at.markdown))
        # The comparison table keeps three short columns; the reasons are stacked below it (390 px phones).
        self.assertTrue(any(list(df.value.columns) == ["Fixed Queue", "Adaptive Queue", "Move"] for df in at.dataframe))
        self.assertFalse(any("Why" in df.value.columns for df in at.dataframe))
        self.assertTrue(any("Why they moved" in str(m.value) for m in at.markdown))
        self.assertTrue(any("Fixed #" in str(m.value) and "Adaptive #" in str(m.value) for m in at.markdown))


def _navigation_script() -> None:
    import streamlit as st

    import draft_queue_modes as dqm

    dqm.keep_personal_choices(st.session_state)  # as streamlit_app does before any widget
    if st.session_state.get("page", "draft") == "draft":
        st.radio("Draft Queue mode", list(dqm.MODES), key=dqm.MODE_KEY)
        st.selectbox("Draft strategy", ["balanced", "value_based"], key="draft_strategy_approach")


class NavigationPersistenceTests(unittest.TestCase):
    def test_mode_and_strategy_survive_visiting_another_page(self) -> None:
        at = AppTest.from_function(_navigation_script, default_timeout=30)
        at.run()
        at.radio(key=dqm.MODE_KEY).set_value("adaptive").run()
        at.selectbox(key="draft_strategy_approach").select("value_based").run()
        at.session_state["page"] = "home"
        at.run()
        self.assertEqual(at.session_state[dqm.MODE_KEY], "adaptive")  # kept for the workspace save
        self.assertEqual(at.session_state["draft_strategy_approach"], "value_based")
        at.session_state["page"] = "draft"
        at.run()
        self.assertEqual(at.radio(key=dqm.MODE_KEY).value, "adaptive")
        self.assertEqual(at.selectbox(key="draft_strategy_approach").value, "value_based")

    def test_the_app_keeps_them_before_any_widget(self) -> None:
        from pathlib import Path

        src = Path(__file__).resolve().parents[1].joinpath("streamlit_app.py").read_text(encoding="utf-8")
        keep = src.index("keep_personal_choices(st.session_state)")
        self.assertLess(src.index("st.set_page_config("), keep)
        self.assertLess(keep, src.index("st.radio("))
        self.assertLess(keep, src.index("st.selectbox("))


if __name__ == "__main__":
    unittest.main()
