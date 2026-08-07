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
        }
        ctx_c = {**ctx_b, "streamlit_session_id": "c-other"}
        ctx_b["streamlit_session_id"] = "b-one"
        code, _detail = self.mod.classify_durability(
            ctx_a, ctx_b, ctx_c, expected_sha=self.mod.EXPECTED_SHA[:7]
        )
        self.assertEqual(code, self.mod.AUTH_BRIDGE6)


if __name__ == "__main__":
    unittest.main()
