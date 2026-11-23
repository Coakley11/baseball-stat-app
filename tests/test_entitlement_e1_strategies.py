"""E1: Saved Draft Strategies (+ AMI strategy coaching) enforcement — built, NOT active.

Enforced only when BASEBALL_ENTITLEMENT_ENFORCEMENT=on (READY_FEATURES has DRAFT_STRATEGIES). These
tests switch it on inside the test only. They cover every entry point: the store (page, in-draft
plans, AMI), the in-draft panel, AMI A1/A2 tools, live-draft copies, downgrade, and every
subscription state.
"""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import baseball_monetization as bm
import baseball_monetization_ui as ui
import draft_plan_source as dps
import draft_strategy_store as dss
import draft_strategy_v2 as v2
from draft_state import DRAFT_QUEUE_KEY
from tests.test_draft_strategy_v2 import _Backend, _v1

TYPES = (v2.ITEM_TYPE, v2.BACKUP_ITEM_TYPE, v2.RESEARCH_ITEM_TYPE, v2.TRASH_ITEM_TYPE)
FREE = bm.EntitlementSnapshot(plan=bm.Plan.FREE, ready=True, status=bm.SubscriptionStatus.AUTHENTICATED_FREE)
PRO = bm.EntitlementSnapshot(plan=bm.Plan.PRO, ready=True, status=bm.SubscriptionStatus.ACTIVE)
LOADING = bm.EntitlementSnapshot(ready=False, status=bm.SubscriptionStatus.UNKNOWN)
ON = {bm.ENFORCEMENT_ENV: "on"}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.backends = {t: _Backend() for t in TYPES}
        for p in (mock.patch("draft_strategy_store._backend", side_effect=lambda t=v2.ITEM_TYPE: self.backends[t]),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False)):
            p.start(); self.addCleanup(p.stop)
        self.rows = self.backends[v2.ITEM_TYPE].rows
        self.rows["A"] = _v1("A", "Alpha", [("Aaron Judge", "power"), ("Juan Soto", "")])
        self.s = {DRAFT_QUEUE_KEY: ["Global One", "Global Two"],
                  "draft_queue_plan": {"pins": [], "notes": {}, "moves": []},
                  "draft_queue_adaptive": {"live:ROOM1": {}}}

    def as_(self, snap):
        self.s[ui.RUN_SNAPSHOT_KEY] = snap

    def calls(self):
        a = v2.upgrade(self.rows["A"])
        return {"list": lambda: dss.list_strategies(self.s),
                "get": lambda: v2.get_strategy_v2(self.s, "A"),
                "save": lambda: v2.save_strategy_v2(self.s, v2.move(a, "Juan Soto", 0), 0),
                "load into queue": lambda: dss.load_strategy(self.s, "A", confirm_replace=True),
                "research": lambda: v2.append_research(self.s, "A", "x"),
                "in-draft plan": lambda: dps._copy_of(self.s, "A")}


class SwitchOffTests(_Base):
    def test_nothing_changes_while_the_switch_is_off(self):
        self.as_(FREE)
        with mock.patch.dict("os.environ", {bm.ENFORCEMENT_ENV: "off"}):
            for name, call in self.calls().items():
                call()  # no refusal


class EnforcedStoreTests(_Base):
    def test_free_is_refused_at_every_entry_point_and_nothing_is_written_or_lost(self):
        self.as_(FREE)
        before = copy.deepcopy(self.rows)
        with mock.patch.dict("os.environ", ON):
            for name, call in self.calls().items():
                with self.subTest(name), self.assertRaises(dss.StrategyError) as e:
                    call()
                self.assertIn("Pro feature", str(e.exception))
        self.assertEqual(self.rows, before, "downgrade keeps every saved strategy")
        self.assertEqual(self.s[DRAFT_QUEUE_KEY], ["Global One", "Global Two"], "Global Queue untouched")
        self.assertEqual(self.backends[v2.RESEARCH_ITEM_TYPE].puts, [])

    def test_loading_membership_is_never_decided(self):
        self.as_(LOADING)
        with mock.patch.dict("os.environ", ON), self.assertRaises(dss.StrategyError) as e:
            dss.list_strategies(self.s)
        self.assertIn("Checking your membership", str(e.exception))

    def test_subscription_states(self):
        with mock.patch.dict("os.environ", ON):
            for status, allowed in ((bm.SubscriptionStatus.ACTIVE, True), (bm.SubscriptionStatus.TRIALING, True),
                                    (bm.SubscriptionStatus.CANCELED_PERIOD_END, True),
                                    (bm.SubscriptionStatus.PAST_DUE, False), (bm.SubscriptionStatus.CANCELED, False),
                                    (bm.SubscriptionStatus.EXPIRED, False)):
                self.as_(bm.EntitlementSnapshot(plan=bm.Plan.PRO, ready=True, status=status))
                with self.subTest(status.value):
                    if allowed:
                        self.assertEqual([s["id"] for s in dss.list_strategies(self.s)], ["A"])
                    else:
                        with self.assertRaises(dss.StrategyError):
                            dss.list_strategies(self.s)

    def test_upgrade_brings_everything_back(self):
        with mock.patch.dict("os.environ", ON):
            self.as_(FREE)
            with self.assertRaises(dss.StrategyError):
                dss.list_strategies(self.s)
            self.as_(PRO)
            self.assertEqual(dss.list_strategies(self.s)[0]["name"], "Alpha")


class LiveDraftTests(_Base):
    def test_a_strategy_already_chosen_for_a_draft_keeps_working_after_a_lapse(self):
        self.as_(PRO)
        with mock.patch.dict("os.environ", ON):
            dps.choose(self.s, "live:ROOM1", "A")
            self.as_(FREE)  # Pro lapses mid-draft
            self.assertEqual(dps.plan_queue(self.s, "live:ROOM1"), ["Aaron Judge", "Juan Soto"])
            self.assertEqual(dps.current(self.s, "live:ROOM1")["name"], "Alpha")
            self.assertIn("Global Queue", dps.choose(self.s, "live:ROOM1", "global"), "switching to Global is Free")
            with self.assertRaises(dss.StrategyError):
                dps.choose(self.s, "live:ROOM1", "A")  # picking a saved strategy again needs Pro

    def test_the_panel_offers_only_the_global_queue_and_a_quiet_pro_note(self):
        import draft_queue_panel as panel

        self.as_(FREE)
        with mock.patch.dict("os.environ", ON):
            self.assertEqual(panel._plan_options(self.s), {"global": "Global Queue"})
            self.assertTrue(panel._strategies_locked(self.s))
            shown = []

            class _St:
                def caption(self, text): shown.append(text)
                def checkbox(self, *a, **k): raise AssertionError("save-back controls must not render")
                def button(self, *a, **k): raise AssertionError("save-back controls must not render")
                def success(self, *a, **k): pass
                def warning(self, *a, **k): pass

            panel._render_save_back(_St(), self.s, "live:ROOM1", {"name": "Alpha"}, "kp")
            self.assertTrue(any("PRO" in t and "Saving back" in t for t in shown))
        self.as_(LOADING)
        with mock.patch.dict("os.environ", ON):
            self.assertFalse(panel._strategies_locked(self.s), "loading is not 'locked'")
        self.as_(FREE)
        with mock.patch.dict("os.environ", ON), mock.patch("suite_auth.is_anonymous_guest", return_value=True):
            self.assertFalse(panel._strategies_locked(self.s), "guests see the sign-in path instead")
        with mock.patch.dict("os.environ", {bm.ENFORCEMENT_ENV: "off"}):
            self.assertFalse(panel._strategies_locked(self.s))


class AmiTests(_Base):
    TOOLS = ("list_my_strategies", "get_my_strategy", "compare_strategy_to_global",
             "strategy_membership", "strategy_top_at_position")

    def test_every_strategy_tool_follows_the_same_gate(self):
        import ami_assistant.tools  # noqa: F401  (registers)
        from ami_assistant.tools import registry as codes
        from ami_assistant.tools.registry import REGISTRY

        for name in self.TOOLS:
            self.assertEqual(REGISTRY.get(name).plan_capability, "draft_strategy_library", name)
        # In the app AMI gets the same run snapshot the store reads (run_entitlement), so set both.
        with mock.patch.dict("os.environ", ON):
            self.as_(FREE)
            for name in self.TOOLS:
                res = REGISTRY.call(name, {}, session=self.s, entitlement=FREE)
                self.assertEqual(res.error_code, codes.NOT_ENTITLED, name)
            self.as_(PRO)
            res = REGISTRY.call("list_my_strategies", {}, session=self.s, entitlement=PRO)
            self.assertTrue(res.ok, res.error_code)
            self.assertIsNone(REGISTRY.get("get_global_list").plan_capability or None, "Global Queue answers stay Free")


if __name__ == "__main__":
    unittest.main()
