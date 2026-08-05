"""Stage-1 Start-arm auth snapshot diagnostics (ledger only)."""

from __future__ import annotations

import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from live_draft_auth_snapshot_stage1_diag import (  # noqa: E402
    EVENT_AUTH_MUTATION,
    EVENT_SNAPSHOT_CAPTURE,
    auth_session_complete_breakdown,
    emit_auth_snapshot_before_rerun,
    emit_auth_snapshot_restore_attempt,
    record_auth_snapshot_capture,
)
from suite_auth import (  # noqa: E402
    AUTH_SESSION_KEY,
    AUTH_START_RERUN_SNAPSHOT_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    ensure_authenticated_session_hydrated,
    is_authenticated,
    snapshot_auth_for_start_draft_rerun,
)

SNAPSHOT_SOURCE_SID_KEY = "_solo_auth_snapshot_source_streamlit_session_id"
TRACE_MUTATIONS_KEY = "_solo_auth_diag_trace_mutations"


@contextmanager
def auth_enabled():
    with mock.patch("live_draft_auth_snapshot_stage1_diag.is_auth_enabled", return_value=True), mock.patch(
        "suite_auth.is_auth_enabled", return_value=True
    ):
        yield


def _ledger(session: dict) -> list[dict]:
    return list(session.get("_solo_stage1_production_ledger_merged") or [])


def _session(**extra: object) -> dict:
    base: dict = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_run_id": "authsnap01",
        "_solo_stage1_script_run_seq": 3,
    }
    base.update(extra)
    return base


def _complete_auth(**overrides: object) -> dict:
    return _session(
        **{
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uid-test-001",
            AUTH_USER_EMAIL_KEY: "test@example.com",
            AUTH_TOKENS_KEY: {"access_token": "acc", "refresh_token": "ref"},
            **overrides,
        }
    )


class AuthSnapshotStage1DiagTests(unittest.TestCase):
    def test_complete_session_produces_valid_snapshot(self) -> None:
        session = _complete_auth()
        with auth_enabled():
            record_auth_snapshot_capture(session, st=mock.Mock())
        self.assertIn(AUTH_START_RERUN_SNAPSHOT_KEY, session)
        rows = [r for r in _ledger(session) if r.get("event") == EVENT_SNAPSHOT_CAPTURE]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("capture_accepted"))

    def test_incomplete_auth_rejects_with_reason(self) -> None:
        session = _session(**{AUTH_SESSION_KEY: True, AUTH_USER_ID_KEY: "u1"})
        with auth_enabled():
            record_auth_snapshot_capture(session, st=mock.Mock())
        self.assertNotIn(AUTH_START_RERUN_SNAPSHOT_KEY, session)
        row = next(r for r in _ledger(session) if r.get("event") == EVENT_SNAPSHOT_CAPTURE)
        self.assertFalse(row.get("capture_accepted"))
        self.assertEqual(row.get("rejection_reason"), "access_token_missing")

    def test_snapshot_present_through_callback_exit(self) -> None:
        session = _complete_auth()
        with auth_enabled():
            record_auth_snapshot_capture(session, st=mock.Mock())
            emit_auth_snapshot_before_rerun(session, st=mock.Mock())
        row = [r for r in _ledger(session) if r.get("event") == "production_stage1_auth_snapshot_before_rerun"][-1]
        self.assertTrue(row.get("snapshot_key_present"))

    def test_snapshot_restores_before_predicate(self) -> None:
        session = _complete_auth()
        session.pop(AUTH_SESSION_KEY, None)
        session.pop(AUTH_TOKENS_KEY, None)
        snap = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uid-test-001",
            AUTH_USER_EMAIL_KEY: "test@example.com",
            AUTH_TOKENS_KEY: {"access_token": "acc", "refresh_token": "ref"},
        }
        session[AUTH_START_RERUN_SNAPSHOT_KEY] = snap
        session[SNAPSHOT_SOURCE_SID_KEY] = "sid-a"
        session[TRACE_MUTATIONS_KEY] = True
        with auth_enabled(), mock.patch(
            "live_draft_auth_snapshot_stage1_diag._streamlit_session_id", return_value="sid-a"
        ):
            out = emit_auth_snapshot_restore_attempt(session, st=mock.Mock())
        self.assertTrue(out.get("restore_accepted"))
        self.assertTrue(is_authenticated(session))

    def test_session_id_mismatch_reported_but_restore_still_attempted(self) -> None:
        session = _complete_auth()
        session.pop(AUTH_TOKENS_KEY, None)
        session[AUTH_START_RERUN_SNAPSHOT_KEY] = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uid-test-001",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
        }
        session[SNAPSHOT_SOURCE_SID_KEY] = "sid-old"
        with auth_enabled(), mock.patch(
            "live_draft_auth_snapshot_stage1_diag._streamlit_session_id", return_value="sid-new"
        ):
            out = emit_auth_snapshot_restore_attempt(session, st=mock.Mock())
        self.assertFalse(out.get("same_streamlit_session_id"))
        self.assertTrue(out.get("restore_accepted"))

    def test_restored_auth_makes_is_authenticated_true(self) -> None:
        session = _session()
        session[AUTH_START_RERUN_SNAPSHOT_KEY] = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "u",
            AUTH_TOKENS_KEY: {"access_token": "x", "refresh_token": "y"},
        }
        with auth_enabled():
            ensure_authenticated_session_hydrated(session, st=mock.Mock())
        self.assertTrue(is_authenticated(session))

    def test_warm_workspace_still_calls_hydrate(self) -> None:
        src = (ROOT / "baseball_persistent_state.py").read_text(encoding="utf-8")
        idx = src.index("def prepare_baseball_workspace")
        hydrate = src.index("ensure_authenticated_session_hydrated", idx)
        reconcile = src.index("reconcile_live_draft_auth_restore_block", hydrate)
        self.assertLess(hydrate, reconcile)

    def test_apply_disk_state_hydrates_before_live_draft_gates(self) -> None:
        src = (ROOT / "baseball_persistent_state.py").read_text(encoding="utf-8")
        idx = src.index("def apply_baseball_disk_state")
        hydrate = src.index("ensure_authenticated_session_hydrated", idx)
        reconcile = src.index("reconcile_live_draft_auth_restore_block", hydrate)
        self.assertLess(hydrate, reconcile)

    def test_signed_out_blocked(self) -> None:
        session = _session()
        with auth_enabled():
            record_auth_snapshot_capture(session, st=mock.Mock())
        row = next(r for r in _ledger(session) if r.get("event") == EVENT_SNAPSHOT_CAPTURE)
        self.assertFalse(row.get("capture_accepted"))

    def test_diagnostics_never_contain_raw_tokens(self) -> None:
        session = _complete_auth(
            **{
                AUTH_TOKENS_KEY: {
                    "access_token": "tok_access_7f3a9c",
                    "refresh_token": "tok_refresh_8e2b1d",
                }
            }
        )
        with auth_enabled():
            snapshot_auth_for_start_draft_rerun(session, st=mock.Mock())
            emit_auth_snapshot_restore_attempt(session, st=mock.Mock())
        blob = json.dumps(_ledger(session))
        self.assertNotIn("tok_access_7f3a9c", blob)
        self.assertNotIn("tok_refresh_8e2b1d", blob)

    def test_mutation_trace_after_start_arm(self) -> None:
        session = _complete_auth()
        with auth_enabled():
            record_auth_snapshot_capture(session, st=mock.Mock())
        muts = [r for r in _ledger(session) if r.get("event") == EVENT_AUTH_MUTATION]
        self.assertTrue(any(r.get("key") == AUTH_START_RERUN_SNAPSHOT_KEY for r in muts))

    def test_auth_breakdown_fields(self) -> None:
        with auth_enabled():
            bd = auth_session_complete_breakdown(_complete_auth())
        self.assertTrue(bd.get("access_token_present"))
        self.assertTrue(bd.get("auth_session_complete"))


if __name__ == "__main__":
    unittest.main()
