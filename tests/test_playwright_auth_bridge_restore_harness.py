"""Tests for shared bridge-restore harness helpers."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from playwright_auth_bridge_restore_harness import (  # noqa: E402
    bridge_preflight_rejects_stale_session,
    resolve_bridge_suite_sid,
    resolve_real_accounts_wake,
)


class BridgeRestoreHarnessTests(unittest.TestCase):
    def test_resolve_from_env_overrides_capture(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cap = Path(td) / "cap.json"
            cap.write_text(
                json.dumps(
                    {
                        "suite_sid": "from-capture",
                        "strict_capture": {"bridge_persistence": {"persistence_succeeded": True}},
                    }
                ),
                encoding="utf-8",
            )
            import os

            os.environ["ROOT_AUDIT_BRIDGE_SUITE_SID"] = "from-env"
            try:
                self.assertEqual(resolve_bridge_suite_sid(capture_path=cap), "from-env")
            finally:
                os.environ.pop("ROOT_AUDIT_BRIDGE_SUITE_SID", None)

    def test_resolve_from_capture_when_persistence_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cap = Path(td) / "cap.json"
            cap.write_text(
                json.dumps(
                    {
                        "suite_sid": "b2cdeae3-c863-4b11-b1dd-ac72d3b3d701",
                        "strict_capture": {
                            "bridge_persistence": {
                                "persistence_succeeded": True,
                                "readback_succeeded": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            import os

            os.environ.pop("ROOT_AUDIT_BRIDGE_SUITE_SID", None)
            os.environ["ROOT_AUDIT_USE_CAPTURE_BRIDGE"] = "1"
            sid = resolve_bridge_suite_sid(capture_path=cap)
            self.assertEqual(sid, "b2cdeae3-c863-4b11-b1dd-ac72d3b3d701")

    def test_stale_session_rejected(self) -> None:
        self.assertEqual(
            bridge_preflight_rejects_stale_session(
                bridge_sid="aaa", url_sid="bbb", authenticated=True
            ),
            "url_suite_sid_mismatch",
        )
        self.assertEqual(
            bridge_preflight_rejects_stale_session(
                bridge_sid="aaa", url_sid="aaa", authenticated=False
            ),
            "authenticated_session_not_bound",
        )
        self.assertEqual(
            bridge_preflight_rejects_stale_session(
                bridge_sid="aaa", url_sid="aaa", authenticated=True
            ),
            "",
        )


    def test_real_accounts_wake_bridge_default_off(self) -> None:
        import os

        os.environ.pop("BRIDGE_RESTORE_REAL_ACCOUNTS_WAKE", None)
        self.assertFalse(resolve_real_accounts_wake(bridge_restore_mode=True))


if __name__ == "__main__":
    unittest.main()
