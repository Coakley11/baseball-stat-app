"""Regression tests for bridge durability verification harness (no Cloud)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load_verify_module():
    path = SCRIPTS / "verify_playwright_auth_bridge_durability.py"
    spec = importlib.util.spec_from_file_location("verify_playwright_auth_bridge_durability", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class BridgeDurabilityHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_verify_module()

    def _ctx(self, *, start_enabled: bool) -> dict:
        sha = self.mod.EXPECTED_SHA[:7]
        return {
            "deployment_sha": sha,
            "url_suite_sid_matches": True,
            "start_enabled": start_enabled,
            "bridge_ledger": {
                "load_browser_tokens_loaded": True,
                "apply_exit_observed": True,
                "apply_authenticated_after": True,
            },
            "bound_current_auth": {
                "session_flag_present": True,
                "is_authenticated": True,
                "auth_session_complete": True,
                "current_restore_blocked_reason": "",
                "apply_authenticated_user_ok": True,
            },
        }

    def test_durability_pass_requires_start_enabled_populated(self) -> None:
        self.assertFalse(self.mod.bridge_durability_session_pass(self._ctx(start_enabled=False)))
        self.assertTrue(self.mod.bridge_durability_session_pass(self._ctx(start_enabled=True)))

    def test_classify_fails_when_durability_pass_false_despite_bound_pass(self) -> None:
        ctx_a = {"bridge_record_found": True, "bridge_record_complete": True}
        ctx_b = {
            "deployment_sha": self.mod.EXPECTED_SHA[:7],
            "url_suite_sid_matches": True,
            "bridge_ledger": {
                "load_invoked": True,
                "load_browser_tokens_loaded": True,
                "apply_exit_observed": True,
                "apply_authenticated_after": True,
            },
            "bound_pass": True,
            "bridge_durability_pass": False,
            "session_binding_failure": "",
            "rotation_restore": {"refresh_token_already_used": False, "bridge_invalidate_count": 0},
        }
        ctx_c = {**ctx_b, "streamlit_session_id": "c-other"}
        ctx_b["streamlit_session_id"] = "b-one"
        code, _detail = self.mod.classify_durability(
            ctx_a, ctx_b, ctx_c, expected_sha=self.mod.EXPECTED_SHA[:7]
        )
        self.assertEqual(code, self.mod.AUTH_BRIDGE6)

    def test_classify_rotation_resolved_when_b_and_c_pass_independently(self) -> None:
        sha = self.mod.EXPECTED_SHA[:7]
        ctx_a = {"bridge_record_found": True, "bridge_record_complete": True}
        base = {
            "deployment_sha": sha,
            "url_suite_sid_matches": True,
            "bridge_ledger": {
                "load_invoked": True,
                "load_browser_tokens_loaded": True,
                "apply_exit_observed": True,
                "apply_authenticated_after": True,
            },
            "bound_pass": True,
            "bridge_durability_pass": True,
            "session_binding_failure": "",
            "rotation_restore": {
                "refresh_token_already_used": False,
                "auth_hydrate_3b": False,
                "bridge_invalidate_count": 0,
            },
        }
        ctx_b = {**base, "streamlit_session_id": "streamlit-b-uuid"}
        ctx_c = {**base, "streamlit_session_id": "streamlit-c-uuid"}
        code, detail = self.mod.classify_durability(ctx_a, ctx_b, ctx_c, expected_sha=sha)
        self.assertEqual(code, self.mod.AUTH_BRIDGE_ROTATION_DURABILITY_RESOLVED)
        self.assertIn("both_fresh_contexts", detail)

    def test_classify_auth_hydrate3b_when_refresh_already_used(self) -> None:
        ctx_a = {"bridge_record_found": True, "bridge_record_complete": True}
        ctx_b = {
            "deployment_sha": self.mod.EXPECTED_SHA[:7],
            "url_suite_sid_matches": True,
            "bridge_ledger": {
                "load_invoked": True,
                "load_browser_tokens_loaded": True,
                "apply_exit_observed": True,
                "apply_authenticated_after": True,
            },
            "bound_pass": True,
            "bridge_durability_pass": True,
            "session_binding_failure": "",
            "rotation_restore": {"refresh_token_already_used": True, "bridge_invalidate_count": 0},
            "streamlit_session_id": "b-one",
        }
        ctx_c = {**ctx_b, "streamlit_session_id": "c-two", "rotation_restore": {"refresh_token_already_used": False, "bridge_invalidate_count": 0}}
        code, _detail = self.mod.classify_durability(
            ctx_a, ctx_b, ctx_c, expected_sha=self.mod.EXPECTED_SHA[:7]
        )
        self.assertEqual(code, "AUTH_HYDRATE3B")

    def test_classify_fails_on_bridge_invalidation_during_restore(self) -> None:
        ctx_a = {"bridge_record_found": True, "bridge_record_complete": True}
        ctx_b = {
            "deployment_sha": self.mod.EXPECTED_SHA[:7],
            "url_suite_sid_matches": True,
            "bridge_ledger": {
                "load_invoked": True,
                "load_browser_tokens_loaded": True,
                "apply_exit_observed": True,
                "apply_authenticated_after": True,
            },
            "bound_pass": True,
            "bridge_durability_pass": True,
            "session_binding_failure": "",
            "rotation_restore": {"refresh_token_already_used": False, "bridge_invalidate_count": 1},
            "streamlit_session_id": "b-one",
        }
        ctx_c = {**ctx_b, "streamlit_session_id": "c-two", "rotation_restore": {"bridge_invalidate_count": 0}}
        code, _detail = self.mod.classify_durability(
            ctx_a, ctx_b, ctx_c, expected_sha=self.mod.EXPECTED_SHA[:7]
        )
        self.assertEqual(code, self.mod.AUTH_BRIDGE4)

    def test_rotation_metrics_monotonic_generation_and_no_already_used(self) -> None:
        ledger = [
            {
                "checkpoint": "bridge_restore_rotation_persist",
                "prior_generation": 6,
                "result_generation": 7,
                "refresh_fp_prefix": "abc123",
            },
            {
                "checkpoint": "restore_auth_session_exit",
                "skip_or_failure_reason": "ok",
                "authenticated_after": True,
            },
        ]
        metrics = self.mod._rotation_restore_metrics(ledger)
        self.assertFalse(metrics["refresh_token_already_used"])
        self.assertEqual(metrics["rotation_persist_count"], 1)
        self.assertEqual(metrics["token_generation_observed"], [6, 7])
        self.assertEqual(metrics["refresh_fp_prefixes_observed"], ["abc123"])


if __name__ == "__main__":
    unittest.main()
