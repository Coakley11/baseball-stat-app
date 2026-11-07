"""Stabilization fixes from the 2026-11-07 two-account QA (release candidate after 1290465).

1. The Auto Pick notice says what really happens: the room's auto-pick rule, never a queue.
2. The selected strategy survives reruns, navigation, refresh/reconnect (workspace restore) and is
   one account's own.
3. Research notes (and pins) reach the workspace right away instead of waiting for the throttled
   routine autosave, and never carry into another account.
4. The Draft Strategy panel keeps one identity (constant label) so it stays open on changes.
5. Roster-aware reasons use the league's real roster slots and never invent a positional need.
"""

from __future__ import annotations

import json
import re
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

import draft_queue_modes as dqm
import draft_queue_panel
import draft_strategy_in_draft as sid
from draft_strategy_in_draft import APPROACH_KEY

ROOT = Path(__file__).resolve().parents[1]


class _SS(dict):
    """A session_state stand-in with attribute access, as Streamlit's has."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        self[k] = v


def _st(**state):
    return types.SimpleNamespace(session_state=_SS(state))


# ---------------------------------------------------------------------------------------------
# 1. Auto Pick notice
# ---------------------------------------------------------------------------------------------
class AutoPickNoticeTests(unittest.TestCase):
    def test_notice_names_the_room_rule_and_never_claims_the_queue(self) -> None:
        text = draft_queue_panel.auto_pick_notice({"config": {"auto_pick_rule": "best market rank"}})
        self.assertIn("Auto Pick doesn't use your queue", text)
        self.assertIn("this room's auto-pick rule (best market rank)", text)
        self.assertIn("not your Fixed queue", text)
        self.assertIn("never makes a pick", text)
        self.assertNotRegex(text, r"(?i)uses your fixed queue|first available player in your fixed")
        self.assertIn("this room's auto-pick rule picks", draft_queue_panel.auto_pick_notice({}))

    def test_the_notice_matches_the_code_no_live_path_picks_from_a_queue(self) -> None:
        # The notice is only true while no expiry/auto-pick path drafts from a manager's queue.
        callers = []
        for path in ROOT.glob("live_draft_*.py"):
            src = path.read_text(encoding="utf-8")
            callers += [path.name for line in src.splitlines()
                        if "_try_queue_auto_pick(" in line and not line.lstrip().startswith("def ")]
        self.assertEqual(callers, [], "Auto Pick now reads a queue: update draft_queue_panel.auto_pick_notice")

    def test_no_screen_text_claims_auto_pick_uses_the_queue(self) -> None:
        bad = re.compile(r"Auto Pick still uses your Fixed queue|first available player in your Fixed order")
        hits = [p.name for p in ROOT.glob("*.py") if bad.search(p.read_text(encoding="utf-8", errors="ignore"))]
        self.assertEqual(hits, [])


# ---------------------------------------------------------------------------------------------
# 2 + 3. Strategy and research-note persistence
# ---------------------------------------------------------------------------------------------
class PersistenceTests(unittest.TestCase):
    def test_strategy_mode_and_notes_round_trip_through_the_workspace(self) -> None:
        import baseball_persistent_state as bps

        self.assertIn(APPROACH_KEY, bps._WORKFLOW_KEYS)
        st = _st(draft_queue=["A", "B"], draft_queue_mode="adaptive", draft_strategy_approach="roster_aware",
                 draft_queue_plan={"pins": ["A"], "notes": {"b": "QA note"}, "moves": []})
        blob = json.loads(json.dumps(bps.build_baseball_disk_state(st), default=str))
        fresh = _st()  # a refresh / reconnect: a new Streamlit session restores the workspace
        bps.apply_baseball_disk_state(fresh, blob)
        r = fresh.session_state
        self.assertEqual(r.get(APPROACH_KEY), "roster_aware")
        self.assertEqual(r.get("draft_queue_mode"), "adaptive")
        self.assertEqual(r.get("draft_queue_plan", {}).get("notes"), {"b": "QA note"})
        self.assertEqual(r.get("draft_queue_plan", {}).get("pins"), ["A"])

    def test_root_cause_routine_autosave_is_throttled_but_a_draft_edit_is_not(self) -> None:
        # During a Shared Draft the routine autosave writes at most every 90 s, so a note saved and
        # refreshed within that window was lost. The panel's explicit save uses "draft_edit".
        from suite_egress_policy import cloud_autosave_allowed

        st = _st(_suite_last_cloud_autosave_ts=time.time())
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            self.assertFalse(cloud_autosave_allowed(st, "baseball", save_reason="autosave")[0])
            self.assertTrue(cloud_autosave_allowed(st, "baseball", save_reason="draft_edit")[0])

    def test_notes_pins_and_mode_changes_are_saved_at_the_end_of_the_run(self) -> None:
        s = {}
        dqm.set_note(s, "Nick Kurtz", "QA note")
        self.assertTrue(s.get(dqm.SAVE_PENDING_KEY))
        s.pop(dqm.SAVE_PENDING_KEY)
        dqm.set_pins(s, ["Nick Kurtz"])
        self.assertTrue(s.get(dqm.SAVE_PENDING_KEY))
        st = _st(**s)
        with mock.patch("baseball_persistent_state.force_save_baseball_state", return_value=True) as save:
            self.assertTrue(dqm.flush_personal_changes(st))
            self.assertFalse(dqm.flush_personal_changes(st))  # once per change
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs.get("reason"), "draft_edit")

    def test_strategy_selector_change_is_saved(self) -> None:
        s = {}
        sid.strategy_changed(s)
        self.assertTrue(s.get(dqm.SAVE_PENDING_KEY))

    def test_the_app_flushes_before_the_routine_autosave(self) -> None:
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertLess(src.index("flush_personal_changes(st)"), src.index("autosave_baseball_state(st)\n"))

    def test_account_change_clears_strategy_notes_and_pending_save(self) -> None:
        from draft_queue_contract import clear_queue_for_account_change

        s = {APPROACH_KEY: "value_based", dqm.PLAN_KEY: {"notes": {"x": "secret research"}},
             dqm.SAVE_PENDING_KEY: True, "draft_queue": ["X"]}
        clear_queue_for_account_change(s)
        for key in (APPROACH_KEY, dqm.PLAN_KEY, dqm.SAVE_PENDING_KEY, "draft_queue"):
            self.assertNotIn(key, s)

    def test_two_managers_keep_their_own_strategy_and_notes(self) -> None:
        a, b = {}, {}
        a[APPROACH_KEY], b[APPROACH_KEY] = "roster_aware", "value_based"
        dqm.set_note(a, "Nick Kurtz", "A only")
        dqm.set_note(b, "Matt Olson", "B only")
        self.assertEqual(dqm.notes_for(a), {"nick kurtz": "A only"})
        self.assertEqual(dqm.notes_for(b), {"matt olson": "B only"})
        self.assertEqual((sid.current_approach(a), sid.current_approach(b)), ("roster_aware", "value_based"))


def _nav_script() -> None:
    import streamlit as st

    import draft_queue_modes as dqm
    from draft_strategy_in_draft import render_strategy_selector

    dqm.keep_personal_choices(st.session_state)
    if st.session_state.get("page", "draft") == "draft":
        render_strategy_selector(st, st.session_state, key_prefix="t", cards=True)


class RerunAndNavigationTests(unittest.TestCase):
    def test_strategy_survives_reruns_and_another_page(self) -> None:
        with mock.patch("draft_strategy_store.list_strategies", return_value=[]):
            at = AppTest.from_function(_nav_script, default_timeout=30)
            at.run()
            at.selectbox(key=APPROACH_KEY).select("roster_aware").run()
            self.assertTrue(at.session_state[dqm.SAVE_PENDING_KEY])
            at.run()
            self.assertEqual(at.session_state[APPROACH_KEY], "roster_aware")
            at.session_state["page"] = "home"
            at.run()
            at.session_state["page"] = "draft"
            at.run()
            self.assertEqual(at.selectbox(key=APPROACH_KEY).value, "roster_aware")


# ---------------------------------------------------------------------------------------------
# 4. Panel stability
# ---------------------------------------------------------------------------------------------
def _panel_script() -> None:
    import streamlit as st

    import draft_queue_panel
    from tests.test_draft_queue_modes import _room, _session

    ss = st.session_state
    if "live_draft_room" not in ss:
        for k, v in _session(_room()).items():
            ss[k] = v
    draft_queue_panel.render_draft_strategy_panel(st, ss, ss["live_draft_room"], viewer_team="Team A")


def _labels(at) -> list[str]:
    return [str(e.label) for e in list(at.expander) + list(at.status)]


class PanelStabilityTests(unittest.TestCase):
    def test_the_panel_keeps_one_label_through_strategy_and_mode_changes(self) -> None:
        with mock.patch("draft_strategy_store.list_strategies", return_value=[]):
            at = AppTest.from_function(_panel_script, default_timeout=60)
            at.run()
            first = _labels(at)
            self.assertIn(draft_queue_panel.PANEL_LABEL, first)
            at.selectbox(key=APPROACH_KEY).select("roster_aware").run()
            at.radio(key=dqm.MODE_KEY).set_value("adaptive").run()
            self.assertFalse(at.exception)
            self.assertEqual(_labels(at), first)  # same expander identity, so it stays open
            self.assertTrue(any("Roster-aware strategy · Adaptive queue" in str(c.value) for c in at.caption))
            self.assertEqual(at.session_state["draft_queue"][0], "Speed One")  # the queue is untouched

    def test_label_has_no_changing_settings(self) -> None:
        self.assertEqual(draft_queue_panel.PANEL_LABEL, "Draft Strategy")
        self.assertFalse(hasattr(draft_queue_panel, "_label"))


# ---------------------------------------------------------------------------------------------
# 5. Positional reasons from the league's real roster
# ---------------------------------------------------------------------------------------------
def _pool() -> pd.DataFrame:
    rows = [("Outfield Star", "OF", 100.0, 9.0), ("First Base Bat", "1B", 90.0, 8.0), ("Catcher", "C", 70.0, 2.0),
            ("Second Bat", "1B", 60.0, 1.0)]
    return pd.DataFrame([{"fullName": n, "Primary Position": p, "Expected Fantasy Value": v, "Positional Fit": f}
                         for n, p, v, f in rows])


def _room(slots, roster=()) -> dict:
    return {"config": {"slots": slots, "num_teams": 2}, "rosters": {"Team A": [dict(r) for r in roster]},
            "pick_order": [{"Team": "Team A"}, {"Team": "Team B"}], "current_pick_index": 0, "draft_board": []}


class RosterReasonTests(unittest.TestCase):
    def _reasons(self, room, team="Team A"):
        ranked = sid.rank_pool(_pool(), "roster_aware", room=room, open_slots=sid.open_slots_for(room, team))
        return dict(zip(ranked["fullName"], ranked["Strategy Reason"])), list(ranked["fullName"])

    def test_no_outfield_need_is_claimed_in_a_league_without_outfield(self) -> None:
        room = _room({"C": 1, "1B": 1, "BN": 1}, roster=[{"fullName": "Catcher Kept", "Primary Position": "C"}])
        reasons, order = self._reasons(room)
        self.assertEqual(reasons["Outfield Star"], "Roster-aware: this league has no OF slot (bench only)")
        self.assertNotIn("OF need", " ".join(reasons.values()))
        self.assertEqual(reasons["Catcher"], "Roster-aware: your C slots are filled (bench only)")
        self.assertIn("open 1B slot", reasons["First Base Bat"])
        # Fit only counts where a slot is open: the 1B bat now ranks first, not the outfielder.
        self.assertEqual(order[0], "First Base Bat")

    def test_missing_roster_settings_are_said_plainly(self) -> None:
        room = {"config": {}, "rosters": {}}
        self.assertIsNone(sid.open_slots_for(room, "Team A"))
        ranked = sid.rank_pool(_pool(), "roster_aware", room=room, open_slots=None)
        self.assertTrue(all("roster settings aren't available" in r for r in ranked["Strategy Reason"]))

    def test_utility_slot_counts_for_any_hitter(self) -> None:
        room = _room({"C": 1, "1B": 1, "DH / UTIL": 1}, roster=[{"Primary Position": "C"}, {"Primary Position": "1B"}])
        self.assertEqual(sid.open_slots_for(room, "Team A"), {"C": 0, "1B": 0, "UTIL": 1})
        reasons, _ = self._reasons(room)
        self.assertEqual(reasons["Outfield Star"], "Roster-aware: fits your open utility slot (OF)")

    def test_cards_use_the_on_clock_team(self) -> None:
        room = _room({"OF": 1})
        room["pick_order"] = [{"Team": "Team B"}]
        self.assertEqual(sid.on_clock_team(room), "Team B")

    def test_engine_uses_real_slots_and_skips_the_generic_fallback(self) -> None:
        from tests.test_draft_queue_modes import _room as roto_room

        room = roto_room()
        needs = dqm.team_needs(room, "Team A", room["pool"], "5x5 Roto")
        self.assertEqual(needs["strategy_open_slots"], sid.open_slots_for(room, "Team A"))
        room["config"]["slots_assumed"] = True
        self.assertIsNone(dqm.team_needs(room, "Team A", room["pool"], "5x5 Roto")["strategy_open_slots"])


if __name__ == "__main__":
    unittest.main()
