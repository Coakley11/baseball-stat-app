"""E2 (built, NOT active): Draft Lab runs/results, Draft Lab grading of a completed Live draft, and
Simulate Draft Pick. Enforced only when BASEBALL_ENTITLEMENT_ENFORCEMENT=on (tests switch it on locally).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

import baseball_monetization as bm
import baseball_monetization_ui as ui

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
ARCHIVE = (ROOT / "draft_archive_ui.py").read_text(encoding="utf-8")
FREE = bm.EntitlementSnapshot(plan=bm.Plan.FREE, ready=True, status=bm.SubscriptionStatus.AUTHENTICATED_FREE, user_id="u1")
PRO = bm.EntitlementSnapshot(plan=bm.Plan.PRO, ready=True, status=bm.SubscriptionStatus.ACTIVE, user_id="u1")
E2 = ("draft_lab_simulation", "draft_lab_live_analysis", "draft_pick_simulation")
ON = {bm.ENFORCEMENT_ENV: "on", bm.GROUPS_ENV: "draft_lab,simulate_pick"}


class SwitchTests(unittest.TestCase):
    def test_off_by_default_and_only_the_e2_capabilities_when_on(self):
        for cap in E2:
            self.assertFalse(bm.capability_enforced(cap, {}), cap)
            self.assertTrue(bm.capability_enforced(cap, ON), cap)
        for cap in ("draft_recommendations", "ml_predictions", "trade_ideas", "advanced_analytics"):
            self.assertFalse(bm.capability_enforced(cap, ON), f"{cap} belongs to a later phase")
        self.assertFalse(bm.is_enforced(bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE), "only Simulate, not the feature")
        self.assertIs(bm.CAPABILITY_FEATURES["draft_pick_simulation"], bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE)

    def test_labels_follow_the_capability(self):
        with mock.patch.dict("os.environ", ON):
            self.assertEqual(ui.pro_state(FREE, bm.FeatureId.DRAFT_LAB, "draft_lab_simulation"), "locked")
            self.assertEqual(ui.pro_state(PRO, bm.FeatureId.DRAFT_LAB, "draft_lab_simulation"), "included")
            self.assertEqual(ui.pro_state(FREE, bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE), "preview",
                             "other draft-intelligence labels stay preview")
        self.assertEqual(ui.pro_state(FREE, bm.FeatureId.DRAFT_LAB, "draft_lab_simulation"), "preview")

    def test_a_locked_label_tells_the_caller_not_to_render_the_tool(self):
        shown = []

        class _St:
            def caption(self, t): shown.append(("caption", t))
            def container(self, **k):
                import contextlib
                return contextlib.nullcontext()
            def markdown(self, t): shown.append(("markdown", t))
            def write(self, t): shown.append(("write", t))
            def button(self, *a, **k): return False

        s = {ui.RUN_SNAPSHOT_KEY: FREE}
        with mock.patch.dict("os.environ", ON):
            self.assertFalse(ui.render_pro_note(_St(), s, "draft_lab", key="k", capability="draft_lab_simulation"))
        self.assertIn(("write", ui.LOCKED_SENTENCE), shown)
        self.assertTrue(ui.render_pro_note(_St(), s, "draft_lab", key="k", capability="draft_lab_simulation"))


class FreshCheckTests(unittest.TestCase):
    def test_allowed_now(self):
        s = {ui.RUN_SNAPSHOT_KEY: FREE}
        self.assertTrue(ui.allowed_now(s, "draft_pick_simulation"), "switch off: open to everyone")
        with mock.patch.dict("os.environ", ON):
            self.assertFalse(ui.allowed_now(s, "draft_pick_simulation"))
            s[ui.RUN_SNAPSHOT_KEY] = PRO
            self.assertTrue(ui.allowed_now(s, "draft_pick_simulation"))

    def test_fresh_rereads_membership_only_when_enforced(self):
        s = {ui.RUN_SNAPSHOT_KEY: PRO, ui.SNAPSHOT_CACHE_KEY: {"user_id": "u1", "at": 0.0, "snapshot": PRO}}
        with mock.patch.object(ui, "run_entitlement", return_value=FREE) as rerun:
            self.assertTrue(ui.allowed_now(s, "draft_lab_simulation", fresh=True))
            rerun.assert_not_called()  # switch off: no extra billing reads
            with mock.patch.dict("os.environ", ON):
                self.assertFalse(ui.allowed_now(s, "draft_lab_simulation", fresh=True), "Pro just ended: not served from cache")
            rerun.assert_called_once()
        self.assertNotIn(ui.SNAPSHOT_CACHE_KEY, s, "the stale cached answer was dropped")

    def test_simulated_developer_plan_is_not_refreshed(self):
        dev = bm.development_entitlement("pro")
        s = {ui.RUN_SNAPSHOT_KEY: dev}
        with mock.patch.object(ui, "run_entitlement") as rerun, mock.patch.dict("os.environ", ON):
            self.assertTrue(ui.allowed_now(s, "draft_lab_simulation", fresh=True))
            rerun.assert_not_called()

    def test_errors_fail_closed_only_when_enforced(self):
        with mock.patch.object(ui, "snapshot_for_run", side_effect=RuntimeError("billing down")):
            self.assertTrue(ui.allowed_now({}, "draft_lab_simulation"))
            with mock.patch.dict("os.environ", ON):
                self.assertFalse(ui.allowed_now({}, "draft_lab_simulation"))


class LiveDraftGradingTests(unittest.TestCase):
    def _click(self, snap):
        import draft_archive_ui as dau

        session = {ui.RUN_SNAPSHOT_KEY: snap}
        fake_st = mock.MagicMock(); fake_st.session_state = session
        # The fresh re-read returns the account's real answer (here: the same snapshot).
        with mock.patch.dict("sys.modules", {"streamlit": fake_st}), \
                mock.patch.object(ui, "run_entitlement", return_value=snap), \
                mock.patch("draft_lab_handoff.push_completed_live_draft_to_lab") as push:
            dau._on_analyze_draft_click()
        return session.get(dau._DRAFT_ANALYZE_UI_FLASH_KEY) or {}, push

    def test_free_gets_an_explanation_and_nothing_is_computed(self):
        with mock.patch.dict("os.environ", ON):
            flash, push = self._click(FREE)
        self.assertIn("included with Baseball Explorer Pro", flash.get("message", ""))
        self.assertIn("exports stay available", flash.get("message", ""))
        push.assert_not_called()

    def test_pro_and_switch_off_pass_the_gate(self):
        for env, snap in (({}, FREE), (ON, PRO)):
            with mock.patch.dict("os.environ", env):
                flash, _ = self._click(snap)
            self.assertNotIn("Pro", flash.get("message", ""), env)  # it reaches the normal checks (no room here)


class WiringTests(unittest.TestCase):
    def test_draft_lab_run_and_results_are_gated(self):
        self.assertIn('_lab_allowed = render_pro_note(st, st.session_state, "draft_lab"', APP)
        self.assertIn('capability="draft_lab_simulation")', APP)
        self.assertIn("run_lab = _lab_allowed and st.button(", APP)
        self.assertIn('run_lab = _pro_allowed_now(st.session_state, "draft_lab_simulation", fresh=True)', APP)
        self.assertRegex(APP, r"if not _lab_allowed:\n\s+pass  # E2: Pro results are withheld")
        self.assertNotIn('st.session_state.pop("draft_lab_results"', APP[APP.index("_lab_allowed = render_pro_note"):][:20000],
                         "locked results are hidden, never cleared")

    def test_every_simulate_entry_point_uses_the_one_capability(self):
        self.assertIn('if not _pro_allowed_now(st.session_state, "draft_pick_simulation", fresh=True):', APP)
        notes = re.findall(r'label="Simulate Draft Pick \(roster impact\)"(?:, capability="(\w+)")?', APP)
        self.assertEqual(len(notes), 3)
        self.assertEqual(set(notes), {"draft_pick_simulation"})

    def test_live_draft_grading_is_gated_in_the_handler_and_the_button(self):
        self.assertIn('allowed_now(session, "draft_lab_live_analysis", fresh=True)', ARCHIVE)
        self.assertIn('capability="draft_lab_live_analysis"', ARCHIVE)

    def test_no_gate_inside_live_draft_pick_flows(self):
        for name in ("live_draft_room_ui.py", "draft_ui.py", "draft_actions.py"):
            src = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("allowed_now(", src, name)
            self.assertNotIn("require_capability(", src, name)


if __name__ == "__main__":
    unittest.main()
