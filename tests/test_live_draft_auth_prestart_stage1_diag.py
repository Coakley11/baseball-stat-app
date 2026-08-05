"""Pre-Start auth hydration diagnostics."""

from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from live_draft_auth_prestart_stage1_diag import (  # noqa: E402
    EVENT_AUTH_BEFORE_START,
    emit_auth_state_before_start_control,
)
from queueui_auth_snapshot_classify import classify_auth_snapshot_root  # noqa: E402


@contextmanager
def auth_enabled():
    with mock.patch("live_draft_auth_snapshot_stage1_diag.is_auth_enabled", return_value=True), mock.patch(
        "suite_auth.is_auth_enabled", return_value=True
    ):
        yield


def _session(**extra: object) -> dict:
    base: dict = {"_solo_component_diag_enabled": True, "_solo_stage1_run_id": "pre01", "_solo_stage1_script_run_seq": 2}
    base.update(extra)
    return base


class AuthPrestartDiagTests(unittest.TestCase):
    def test_before_control_always_emits_when_disabled(self) -> None:
        session = _session()
        with auth_enabled():
            emit_auth_state_before_start_control(session, st=mock.Mock(), start_button_enabled=False)
        rows = session.get("_solo_stage1_production_ledger_merged") or []
        ev = [r for r in rows if r.get("event") == EVENT_AUTH_BEFORE_START]
        self.assertEqual(len(ev), 1)
        self.assertFalse(ev[0].get("start_button_enabled"))

    def test_classifier_auth_snapshot1_on_unauthenticated_capture(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_snapshot_capture",
                "capture_attempted": True,
                "capture_accepted": False,
                "is_authenticated": False,
                "auth_session_complete": False,
                "rejection_reason": "session_flag_missing",
            }
        ]
        out = classify_auth_snapshot_root(ledger_rows=rows, auth_preflight_authenticated=True)
        self.assertIn("AUTH_SNAPSHOT1", out["classification"])
        self.assertEqual(out["detail"], "session_flag_missing")

    def test_apply_authenticated_user_sets_is_authenticated(self) -> None:
        from suite_auth import AUTH_SESSION_KEY, AUTH_TOKENS_KEY, AUTH_USER_ID_KEY, _apply_authenticated_user, is_authenticated

        session = _session()
        with auth_enabled():
            _apply_authenticated_user(session, {"email": "a@b.com", "id": "u1"}, tokens={"access_token": "a", "refresh_token": "r"})
        self.assertTrue(session.get(AUTH_SESSION_KEY))
        self.assertTrue(is_authenticated(session))


if __name__ == "__main__":
    unittest.main()
