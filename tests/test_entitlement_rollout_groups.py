"""Staged activation: the master switch plus a named list of rollout groups.

Owner requirement (2026-11-23): enabling one feature's restrictions must never lock every other
prepared feature. A gate is enforced only when BASEBALL_ENTITLEMENT_ENFORCEMENT=on AND its group is in
BASEBALL_ENTITLEMENT_GROUPS; everything else fails safe (nothing restricted).
"""

from __future__ import annotations

import unittest
from unittest import mock

import baseball_monetization as bm

E, G = bm.ENFORCEMENT_ENV, bm.GROUPS_ENV
CAPS = {"strategies": "draft_strategy_library", "draft_lab": "draft_lab_simulation", "simulate_pick": "draft_pick_simulation"}
FREE = bm.EntitlementSnapshot(plan=bm.Plan.FREE, ready=True, status=bm.SubscriptionStatus.AUTHENTICATED_FREE)


def enforced(env):
    return {name for name, cap in CAPS.items() if bm.capability_enforced(cap, env)}


class RolloutGroupTests(unittest.TestCase):
    def test_fail_safe_defaults(self):
        for env in ({}, {E: "off", G: "strategies,draft_lab,simulate_pick"}, {E: "preview", G: "strategies"},
                    {E: "on"}, {E: "on", G: ""}, {E: "on", G: "  ,  "}, {E: "on", G: "everything,all,typo"},
                    {E: "maybe", G: "strategies"}):
            with self.subTest(env=env):
                self.assertEqual(enforced(env), set())
                self.assertEqual(bm.active_groups(env), frozenset())
                self.assertEqual(bm.enforced_features(env), frozenset())

    def test_each_group_activates_alone(self):
        for name in CAPS:
            with self.subTest(name):
                self.assertEqual(enforced({E: "on", G: name}), {name}, "no other prepared feature is locked")

    def test_names_are_case_and_space_tolerant_and_combine(self):
        self.assertEqual(enforced({E: "ON", G: " Strategies , DRAFT_LAB "}), {"strategies", "draft_lab"})
        self.assertEqual(enforced({E: "on", G: "draft_lab,strategy"}), {"draft_lab"}, "a typo never widens")

    def test_draft_lab_group_covers_both_draft_lab_capabilities_only(self):
        env = {E: "on", G: "draft_lab"}
        self.assertTrue(bm.capability_enforced("draft_lab_live_analysis", env))
        self.assertFalse(bm.capability_enforced("draft_recommendations", env))
        self.assertNotIn(bm.FeatureId.DRAFT_LAB, bm.enforced_features(env), "capabilities, not the whole feature")

    def test_the_strategies_group_enforces_the_whole_feature(self):
        env = {E: "on", G: "strategies"}
        self.assertEqual(bm.enforced_features(env), frozenset({bm.FeatureId.DRAFT_STRATEGIES}))
        with mock.patch.dict("os.environ", env):
            self.assertFalse(bm.allows(FREE, "draft_strategy_library"))
            self.assertTrue(bm.allows(FREE, "draft_pick_simulation"))

    def test_every_group_is_built_from_registered_features_and_capabilities(self):
        for g in bm.ROLLOUT_GROUPS.values():
            for f in g.features:
                self.assertIn(f, bm.FEATURE_REGISTRY)
            for c in g.capabilities:
                self.assertIn(c, bm.CAPABILITY_FEATURES, c)
        self.assertEqual(bm.READY_FEATURES, frozenset({bm.FeatureId.DRAFT_STRATEGIES}))

    def test_summary_names_the_effective_state(self):
        self.assertEqual(bm.enforcement_summary({}), "entitlement enforcement: off; active groups: none")
        self.assertIn("active groups: draft_lab, strategies", bm.enforcement_summary({E: "on", G: "strategies,draft_lab"}))


if __name__ == "__main__":
    unittest.main()
