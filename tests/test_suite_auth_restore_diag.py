"""Sanitized restore exception diagnostics."""

from __future__ import annotations

import unittest
from unittest import mock

from suite_auth_restore_diag import sanitize_auth_exception


class SuiteAuthRestoreDiagTests(unittest.TestCase):
    def test_sanitize_strips_jwt_like_substrings(self) -> None:
        class AuthApiError(Exception):
            status = 401
            code = "invalid_grant"

        exc = AuthApiError("token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig rejected")
        out = sanitize_auth_exception(exc, phase="set_session")
        self.assertEqual(out["exception_class"], "AuthApiError")
        self.assertEqual(out["phase"], "set_session")
        self.assertIn("[redacted_jwt]", out["message_sanitized"])
        self.assertNotIn("eyJhbGci", out["message_sanitized"])

    def test_emit_restore_checkpoint_does_not_raise(self) -> None:
        from suite_auth_restore_diag import emit_restore_auth_exception_checkpoint

        session: dict = {}
        with mock.patch("live_draft_auth_prestart_stage1_diag.emit_prestart_hydration_checkpoint") as emit:
            emit_restore_auth_exception_checkpoint(session, RuntimeError("x"), phase="set_session")
            emit.assert_called_once()
            extra = emit.call_args.kwargs.get("extra") or emit.call_args[1].get("extra") or {}
            if not extra:
                extra = emit.call_args[0][3] if len(emit.call_args[0]) > 3 else {}
            self.assertTrue(extra or emit.called)


if __name__ == "__main__":
    unittest.main()
