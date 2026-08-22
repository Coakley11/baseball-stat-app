"""Deterministic local tests for single-use refresh-token bridge handoff."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from bridge_hydration_waiter import (  # noqa: E402
    hydration_fail_fast_from_restore_exception,
    hydration_fail_fast_from_restore_exit,
)
from playwright_auth_bridge_restore_harness import (  # noqa: E402
    resolve_bridge_suite_sid_with_source,
)
from playwright_auth_capture_strict import (  # noqa: E402
    CAPTURE_FAIL_FINAL_HANDOFF,
    evaluate_strict_capture,
    metadata_has_no_secrets,
)
from suite_auth_bridge_handoff import (  # noqa: E402
    CAPTURE_FAIL_HANDOFF_FP_MISMATCH,
    CAPTURE_FAIL_POST_HANDOFF_REFRESH,
    CAPTURE_FAIL_SNAPSHOT_MISMATCH,
    CHECKPOINT_FINAL_INVARIANT,
    CHECKPOINT_FINAL_PERSIST,
    CHECKPOINT_FINAL_READBACK,
    HANDOFF_FREEZE_KEY,
    HANDOFF_NO_REFRESH_AFTER_KEY,
    PHASE_FINAL,
    PHASE_INTERMEDIATE,
    evaluate_final_handoff_eligibility,
    is_handoff_frozen,
    pair_fingerprints,
    reject_mixed_token_pair,
    replay_token_rotation_handoff,
    token_fingerprint,
)
from suite_auth_bridge_token_meta import token_fingerprint as meta_fp  # noqa: E402


def _row(checkpoint: str, **extra: object) -> dict:
    base = {
        "event": "production_stage1_auth_prestart_hydration",
        "checkpoint": checkpoint,
        "event_index": int(extra.pop("event_index", 1)),
    }
    base.update(extra)
    return base


class TokenHandoffContractTests(unittest.TestCase):
    def test_fingerprints_are_non_secret(self) -> None:
        fp = token_fingerprint("refresh-secret-value")
        self.assertEqual(len(fp), 16)
        self.assertNotIn("refresh-secret", fp)
        self.assertEqual(fp, meta_fp("refresh-secret-value"))

    def test_pair_fingerprints_and_mixed_rejection(self) -> None:
        a = {"access_token": "access-A", "refresh_token": "refresh-A"}
        b = {"access_token": "access-B", "refresh_token": "refresh-B"}
        fa = pair_fingerprints(a)
        fb = pair_fingerprints(b)
        # stale access + new refresh (relative to expected B pair)
        self.assertEqual(
            reject_mixed_token_pair(
                access_token="access-A",
                refresh_token="refresh-B",
                expected_access_fp=fb["access_fp"],
                expected_refresh_fp=fb["refresh_fp"],
            ),
            "stale_access_new_refresh_rejected",
        )
        # new access + stale refresh
        self.assertEqual(
            reject_mixed_token_pair(
                access_token="access-B",
                refresh_token="refresh-A",
                expected_access_fp=fb["access_fp"],
                expected_refresh_fp=fb["refresh_fp"],
            ),
            "new_access_stale_refresh_rejected",
        )
        self.assertEqual(
            reject_mixed_token_pair(
                access_token="access-B",
                refresh_token="refresh-B",
                expected_access_fp=fb["access_fp"],
                expected_refresh_fp=fb["refresh_fp"],
            ),
            "",
        )
        self.assertNotEqual(fa["refresh_fp"], fb["refresh_fp"])

    def test_intermediate_write_not_eligible(self) -> None:
        rows = [
            _row(
                "save_browser_auth_tokens",
                handoff_phase=PHASE_INTERMEDIATE,
                persistence_succeeded=True,
                refresh_fp="aaaabbbbccccdddd",
                event_index=10,
                suite_sid_prefix="deadbeef",
            )
        ]
        elig = evaluate_final_handoff_eligibility(rows, target_sid="deadbeef-0000")
        self.assertFalse(elig["eligible"])
        self.assertEqual(elig["failure"], CAPTURE_FAIL_FINAL_HANDOFF)

    def test_final_handoff_match_eligible(self) -> None:
        fp = "abcdef0123456789"
        rows = [
            _row(
                CHECKPOINT_FINAL_PERSIST,
                handoff_phase=PHASE_FINAL,
                persistence_succeeded=True,
                refresh_fp=fp,
                refresh_fp_prefix=fp[:16],
                session_snapshot_refresh_fp_prefix=fp[:16],
                token_generation=3,
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_READBACK,
                handoff_phase=PHASE_FINAL,
                readback_succeeded=True,
                refresh_fp_prefix=fp[:16],
                token_generation=3,
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_INVARIANT,
                final_session_snapshot_fingerprint=fp[:16],
                final_persist_token_fingerprint=fp[:16],
                final_browser_token_fingerprint=fp[:16],
                final_readback_token_fingerprint=fp[:16],
                fingerprint_match=True,
                no_auth_refresh_after_final_persist=True,
                no_auth_consumption_since_final_token_snapshot=True,
                event_index=41,
            ),
        ]
        elig = evaluate_final_handoff_eligibility(rows, target_sid="deadbeef-0000")
        self.assertTrue(elig["eligible"])
        self.assertTrue(elig["fingerprint_match"])
        self.assertTrue(elig["no_auth_refresh_after_final_persist"])

    def test_fingerprint_mismatch_blocks_reservation(self) -> None:
        rows = [
            _row(
                CHECKPOINT_FINAL_PERSIST,
                handoff_phase=PHASE_FINAL,
                persistence_succeeded=True,
                refresh_fp="aaaaaaaaaaaaaaaa",
                refresh_fp_prefix="aaaaaaaaaaaaaaaa",
                session_snapshot_refresh_fp_prefix="aaaaaaaaaaaaaaaa",
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_READBACK,
                handoff_phase=PHASE_FINAL,
                readback_succeeded=True,
                refresh_fp_prefix="bbbbbbbbbbbbbbbb",
                token_generation=2,
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_INVARIANT,
                final_session_snapshot_fingerprint="aaaaaaaaaaaaaaaa",
                final_persist_token_fingerprint="aaaaaaaaaaaaaaaa",
                final_browser_token_fingerprint="bbbbbbbbbbbbbbbb",
                final_readback_token_fingerprint="bbbbbbbbbbbbbbbb",
                fingerprint_match=False,
                no_auth_consumption_since_final_token_snapshot=True,
                event_index=41,
            ),
        ]
        elig = evaluate_final_handoff_eligibility(rows, target_sid="deadbeef-0000")
        self.assertFalse(elig["eligible"])
        self.assertEqual(elig["failure"], CAPTURE_FAIL_SNAPSHOT_MISMATCH)

    def test_rotation_after_final_blocks_eligibility(self) -> None:
        fp = "abcdef0123456789"
        rows = [
            _row(
                CHECKPOINT_FINAL_PERSIST,
                handoff_phase=PHASE_FINAL,
                persistence_succeeded=True,
                refresh_fp=fp,
                refresh_fp_prefix=fp[:16],
                session_snapshot_refresh_fp_prefix=fp[:16],
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_READBACK,
                handoff_phase=PHASE_FINAL,
                readback_succeeded=True,
                refresh_fp_prefix=fp[:16],
                token_generation=2,
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_INVARIANT,
                final_session_snapshot_fingerprint=fp[:16],
                final_persist_token_fingerprint=fp[:16],
                final_browser_token_fingerprint=fp[:16],
                final_readback_token_fingerprint=fp[:16],
                fingerprint_match=True,
                no_auth_refresh_after_final_persist=True,
                no_auth_consumption_since_final_token_snapshot=True,
                event_index=41,
            ),
            _row(
                "restore_auth_session_exit",
                skip_or_failure_reason="ok",
                event_index=50,
            ),
        ]
        elig = evaluate_final_handoff_eligibility(rows, target_sid="deadbeef-0000")
        self.assertFalse(elig["eligible"])
        self.assertEqual(elig["failure"], CAPTURE_FAIL_POST_HANDOFF_REFRESH)

    def test_already_complete_after_final_allowed(self) -> None:
        fp = "abcdef0123456789"
        rows = [
            _row(
                CHECKPOINT_FINAL_PERSIST,
                handoff_phase=PHASE_FINAL,
                persistence_succeeded=True,
                refresh_fp=fp,
                refresh_fp_prefix=fp[:16],
                session_snapshot_refresh_fp_prefix=fp[:16],
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_READBACK,
                handoff_phase=PHASE_FINAL,
                readback_succeeded=True,
                refresh_fp_prefix=fp[:16],
                token_generation=2,
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_INVARIANT,
                final_session_snapshot_fingerprint=fp[:16],
                final_persist_token_fingerprint=fp[:16],
                final_browser_token_fingerprint=fp[:16],
                final_readback_token_fingerprint=fp[:16],
                fingerprint_match=True,
                no_auth_refresh_after_final_persist=True,
                no_auth_consumption_since_final_token_snapshot=True,
                event_index=41,
            ),
            _row(
                "restore_auth_session_exit",
                skip_or_failure_reason="already_complete",
                event_index=50,
            ),
            _row(
                "restore_auth_session_exit",
                skip_or_failure_reason="handoff_frozen",
                event_index=51,
            ),
        ]
        elig = evaluate_final_handoff_eligibility(rows, target_sid="deadbeef-0000")
        self.assertTrue(elig["eligible"])

    def test_replay_fixed_path_production_once(self) -> None:
        fixed = replay_token_rotation_handoff(defect_mode=False)
        self.assertTrue(fixed["eligible"])
        self.assertTrue(fixed["production_first"]["ok"])
        self.assertFalse(fixed["production_second"]["ok"])
        self.assertEqual(fixed["production_second"]["code"], "refresh_token_already_used")
        self.assertTrue(fixed["handoff_frozen"])
        self.assertTrue(fixed["no_auth_refresh_after_final_persist"])

    def test_replay_defect_path_prevented(self) -> None:
        defect = replay_token_rotation_handoff(defect_mode=True)
        self.assertTrue(defect["prevented_stale_handoff"])
        self.assertFalse(defect["eligible"])
        self.assertEqual(defect["production"]["code"], "refresh_token_already_used")
        self.assertNotEqual(defect["persisted_refresh_fp"], defect["browser_refresh_fp"])

    def test_strict_capture_requires_final_handoff(self) -> None:
        sid = "deadbeef-0000-0000-0000-000000000001"
        rows = [
            _row(
                "save_browser_auth_tokens",
                persistence_attempted=True,
                persistence_succeeded=True,
                suite_sid_prefix="deadbeef",
                access_token_present=True,
                refresh_token_present=True,
                auth_user_id_present=True,
                bridge_record_complete=True,
                handoff_phase=PHASE_INTERMEDIATE,
            ),
            _row(
                "save_browser_auth_tokens_readback",
                readback_record_complete=True,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                "apply_authenticated_user_exit",
                authenticated_after=True,
                protected_keys={"session_flag_present": True},
            ),
        ]
        dom = {
            "streamlit_session_id": "s1",
            "diagnostic_run_id": "r1",
            "session_flag_present": True,
            "is_authenticated": True,
            "auth_session_complete": True,
            "auth_hydration_source": "already_complete",
            "current_restore_blocked_reason": "",
            "start_enabled": True,
        }
        r = evaluate_strict_capture(
            target_sid=sid,
            url_sid=sid,
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=True,
            current_auth_dom=dom,
            diagnostic_run_id="r1",
            streamlit_session_id="s1",
        )
        self.assertFalse(r["strict_auth_passed"])
        self.assertEqual(r["failure"], CAPTURE_FAIL_FINAL_HANDOFF)

    def test_strict_capture_already_complete_with_final_passes(self) -> None:
        sid = "deadbeef-0000-0000-0000-000000000001"
        fp = "abcdef0123456789"
        rows = [
            _row(
                "save_browser_auth_tokens",
                persistence_attempted=True,
                persistence_succeeded=True,
                suite_sid_prefix="deadbeef",
                access_token_present=True,
                refresh_token_present=True,
                auth_user_id_present=True,
                bridge_record_complete=True,
                handoff_phase=PHASE_INTERMEDIATE,
            ),
            _row(
                "save_browser_auth_tokens_readback",
                readback_record_complete=True,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                "apply_authenticated_user_exit",
                authenticated_after=True,
                protected_keys={"session_flag_present": True},
            ),
            _row(
                CHECKPOINT_FINAL_PERSIST,
                handoff_phase=PHASE_FINAL,
                persistence_succeeded=True,
                suite_sid_prefix="deadbeef",
                refresh_fp=fp,
                refresh_fp_prefix=fp[:16],
                session_snapshot_refresh_fp_prefix=fp[:16],
                token_generation=2,
                event_index=40,
            ),
            _row(
                CHECKPOINT_FINAL_READBACK,
                handoff_phase=PHASE_FINAL,
                readback_succeeded=True,
                refresh_fp_prefix=fp[:16],
                token_generation=2,
                event_index=40,
                suite_sid_prefix="deadbeef",
            ),
            _row(
                CHECKPOINT_FINAL_INVARIANT,
                final_session_snapshot_fingerprint=fp[:16],
                final_persist_token_fingerprint=fp[:16],
                final_browser_token_fingerprint=fp[:16],
                final_readback_token_fingerprint=fp[:16],
                fingerprint_match=True,
                no_auth_refresh_after_final_persist=True,
                no_auth_consumption_since_final_token_snapshot=True,
                event_index=41,
            ),
        ]
        dom = {
            "streamlit_session_id": "s1",
            "diagnostic_run_id": "r1",
            "session_flag_present": True,
            "is_authenticated": True,
            "auth_session_complete": True,
            "auth_hydration_source": "already_complete",
            "current_restore_blocked_reason": "",
            "start_enabled": True,
        }
        r = evaluate_strict_capture(
            target_sid=sid,
            url_sid=sid,
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=True,
            current_auth_dom=dom,
            diagnostic_run_id="r1",
            streamlit_session_id="s1",
        )
        self.assertTrue(r["strict_auth_passed"])
        self.assertTrue(r["final_handoff"]["eligible"])
        self.assertTrue(metadata_has_no_secrets({"strict_capture": r}))
        blob = json.dumps(r)
        self.assertNotIn("refresh-A", blob)
        self.assertNotIn("access-A", blob)
        self.assertNotIn("eyJ", blob)

    def test_explicit_sid_ignores_capture_bridge_flag_off(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "STAGE1_BRIDGE_SUITE_SID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "STAGE1_USE_CAPTURE_BRIDGE": "0",
                "ROOT_AUDIT_USE_CAPTURE_BRIDGE": "0",
            },
            clear=False,
        ):
            sid, src = resolve_bridge_suite_sid_with_source()
        self.assertEqual(sid, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(src, "STAGE1_BRIDGE_SUITE_SID")

    def test_capture_flag_off_only_blocks_default_discovery(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "STAGE1_USE_CAPTURE_BRIDGE": "0",
                "ROOT_AUDIT_USE_CAPTURE_BRIDGE": "0",
            },
            clear=False,
        ):
            # Ensure explicit SID env cleared for this assertion
            import os

            os.environ.pop("STAGE1_BRIDGE_SUITE_SID", None)
            os.environ.pop("ROOT_AUDIT_BRIDGE_SUITE_SID", None)
            sid, src = resolve_bridge_suite_sid_with_source()
        self.assertEqual(sid, "")
        self.assertEqual(src, "none")

    def test_waiter_fail_fast_refresh_already_used(self) -> None:
        exc = {
            "exception_class": "AuthApiError",
            "auth_code": "refresh_token_already_used",
            "message_sanitized": "Invalid Refresh Token: Already Used",
        }
        reason = hydration_fail_fast_from_restore_exception(exc)
        self.assertIn("refresh_token_already_used", reason)
        self.assertIn("AuthApiError", reason)
        # exit reason auth_hydrate_3b_final alone is not AuthApiError fail-fast
        self.assertEqual(
            hydration_fail_fast_from_restore_exit({"skip_or_failure_reason": "auth_hydrate_3b_final"}),
            "",
        )

    def test_freeze_flag_helpers(self) -> None:
        session: dict = {}
        self.assertFalse(is_handoff_frozen(session))
        session[HANDOFF_FREEZE_KEY] = True
        session[HANDOFF_NO_REFRESH_AFTER_KEY] = True
        self.assertTrue(is_handoff_frozen(session))

    def test_no_retry_same_refresh_in_replay(self) -> None:
        fixed = replay_token_rotation_handoff(defect_mode=False)
        self.assertTrue(fixed["production_first"]["ok"])
        self.assertFalse(fixed["production_second"]["ok"])


if __name__ == "__main__":
    unittest.main()
