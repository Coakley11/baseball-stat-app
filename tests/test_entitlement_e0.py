"""E0: one trusted membership snapshot per run, an off/preview/on switch, and the gate helpers.

Nothing is enforced: READY_FEATURES is empty and the switch defaults to "off".
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

import baseball_monetization as bm
import baseball_monetization_ui as ui

ROOT = Path(__file__).resolve().parents[1]
FREE = bm.EntitlementSnapshot(plan=bm.Plan.FREE, ready=True, status=bm.SubscriptionStatus.AUTHENTICATED_FREE, user_id="u1")
PRO = bm.EntitlementSnapshot(plan=bm.Plan.PRO, ready=True, status=bm.SubscriptionStatus.ACTIVE, user_id="u1")
LOADING = bm.EntitlementSnapshot(ready=False, status=bm.SubscriptionStatus.UNKNOWN, user_id="u1")
CAP = "draft_strategy_library"


class SwitchTests(unittest.TestCase):
    def test_default_is_off_and_nothing_is_enforced(self):
        self.assertIs(bm.enforcement_mode({}), bm.EnforcementMode.OFF)
        self.assertEqual(bm.READY_FEATURES, frozenset({bm.FeatureId.DRAFT_STRATEGIES}))  # E1 built, not active
        self.assertEqual(bm.enforced_features({}), frozenset())

    def test_values(self):
        env = bm.ENFORCEMENT_ENV
        self.assertIs(bm.enforcement_mode({env: " On "}), bm.EnforcementMode.ON)
        self.assertIs(bm.enforcement_mode({env: "preview"}), bm.EnforcementMode.PREVIEW)
        self.assertIs(bm.enforcement_mode({env: "yes please"}), bm.EnforcementMode.OFF, "unknown = off")

    def test_a_ready_feature_is_enforced_only_while_the_switch_is_on(self):
        with mock.patch.object(bm, "READY_FEATURES", frozenset({bm.FeatureId.DRAFT_STRATEGIES})):
            for mode in ("off", "preview", ""):
                with mock.patch.dict("os.environ", {bm.ENFORCEMENT_ENV: mode}):
                    self.assertTrue(bm.allows(FREE, CAP), mode)
            with mock.patch.dict("os.environ", {bm.ENFORCEMENT_ENV: "on"}):
                self.assertFalse(bm.allows(FREE, CAP))
                self.assertTrue(bm.allows(PRO, CAP))
                self.assertTrue(bm.allows(FREE, "draft_recommendations"), "only the ready feature")
        with mock.patch.object(bm, "READY_FEATURES", frozenset()), mock.patch.dict("os.environ", {bm.ENFORCEMENT_ENV: "on"}):
            self.assertTrue(bm.allows(FREE, CAP), "switch on but no feature ready: nothing enforced")


class HelperTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(bm, "ENFORCED_FEATURES", frozenset({bm.FeatureId.DRAFT_STRATEGIES}))
        p.start(); self.addCleanup(p.stop)

    def test_require_raises_a_typed_refusal(self):
        bm.require(PRO, CAP)
        with self.assertRaises(bm.ProFeatureRequired) as e:
            bm.require(FREE, CAP)
        self.assertIs(e.exception.feature_id, bm.FeatureId.DRAFT_STRATEGIES)
        self.assertFalse(e.exception.loading)
        self.assertIn("included with Baseball Explorer Pro", str(e.exception))
        with self.assertRaises(bm.ProFeatureRequired) as e:
            bm.require(LOADING, CAP)
        self.assertTrue(e.exception.loading, "unready is 'checking', never a grant")

    def test_effective_keeps_the_saved_value_but_applies_the_default(self):
        self.assertEqual(bm.effective(PRO, CAP, "mine", "default"), "mine")
        self.assertEqual(bm.effective(FREE, CAP, "mine", "default"), "default")

    def test_pro_states(self):
        for status, grants in ((bm.SubscriptionStatus.ACTIVE, True), (bm.SubscriptionStatus.TRIALING, True),
                               (bm.SubscriptionStatus.CANCELED_PERIOD_END, True), (bm.SubscriptionStatus.PAST_DUE, False),
                               (bm.SubscriptionStatus.CANCELED, False), (bm.SubscriptionStatus.EXPIRED, False)):
            snap = bm.EntitlementSnapshot(plan=bm.Plan.PRO, ready=True, status=status)
            self.assertIs(bm.allows(snap, CAP), grants, status)


class RunSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.answer = FREE
        self.user = "u1"

        def resolve(session, environ=None):
            self.calls.append(self.user)
            return self.answer

        for p in (mock.patch.object(ui, "resolve_trusted_entitlement", side_effect=resolve),
                  mock.patch("baseball_monetization.authenticated_subject", side_effect=lambda s: (self.user, bool(self.user), "t"))):
            p.start(); self.addCleanup(p.stop)

    def test_one_resolve_per_ttl_per_account(self):
        s = {}
        self.assertIs(ui.run_entitlement(s, now=100.0), FREE)
        ui.run_entitlement(s, now=130.0)
        self.assertEqual(len(self.calls), 1, "cached within the TTL")
        self.assertIs(s[ui.RUN_SNAPSHOT_KEY], FREE)
        ui.run_entitlement(s, now=100.0 + ui.SNAPSHOT_TTL_S + 1)
        self.assertEqual(len(self.calls), 2, "re-resolved after the TTL")

    def test_a_different_account_never_sees_the_cached_snapshot(self):
        s = {}
        ui.run_entitlement(s, now=100.0)
        self.user, self.answer = "u2", PRO
        self.assertIs(ui.run_entitlement(s, now=101.0), PRO)
        self.assertEqual(self.calls, ["u1", "u2"])
        self.user, self.answer = "", bm.EntitlementSnapshot()
        self.assertEqual(ui.run_entitlement(s, now=102.0).plan, bm.Plan.FREE, "signed out re-resolves")

    def test_unready_is_never_cached_and_refresh_forgets(self):
        s = {}
        self.answer = LOADING
        ui.run_entitlement(s, now=1.0)
        self.assertNotIn(ui.SNAPSHOT_CACHE_KEY, s)
        self.answer = PRO
        self.assertIs(ui.run_entitlement(s, now=2.0), PRO)
        ui.refresh_entitlement(s)
        ui.run_entitlement(s, now=3.0)
        self.assertEqual(len(self.calls), 3)

    def test_snapshot_for_run_reads_this_run(self):
        s = {ui.RUN_SNAPSHOT_KEY: PRO}
        self.assertIs(ui.snapshot_for_run(s), PRO)


class WiringTests(unittest.TestCase):
    def test_the_app_resolves_once_per_run_and_every_gate_reads_that_snapshot(self):
        app = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("_monetization_snapshot = run_entitlement(", app)
        self.assertIn("refresh_entitlement(st.session_state)", app)
        for name in ("draft_strategy_store.py", "draft_strategy_ui.py"):
            src = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("snapshot_for_run(session)", src, name)
            self.assertNotIn("current_entitlement(", src, name)
        offenders = [p.name for p in ROOT.glob("*.py")
                     if p.name != "baseball_monetization_ui.py"
                     and re.search(r"\bcurrent_entitlement\(", p.read_text(encoding="utf-8", errors="ignore"))]
        self.assertEqual(offenders, [], "resolve through run_entitlement / snapshot_for_run only")


if __name__ == "__main__":
    unittest.main()
