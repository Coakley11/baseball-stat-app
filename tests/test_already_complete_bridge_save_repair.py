"""Local repair regressions: already-complete session + missing current-suite bridge.

CAPTURE/HARNESS + AUTH-BRIDGE CONTRACT only. No browser. No network.
Preserves ensure_authenticated_session_hydrated ordinary UI early-return.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

from capture_playwright_daniel_auth_once import (  # noqa: E402
    ALREADY_AUTH_NONCONSUMING_FINALIZE,
    BOOTSTRAP_MAX_ATTEMPTS,
    already_authenticated_bridge_missing,
    apply_authenticated_user_observed_from_ledger,
    decide_already_authenticated_bridge_bootstrap,
    decide_already_authenticated_nonconsuming_finalize,
    enforce_current_suite_bridge_authority,
    current_suite_bridge_authority_ok,
)
from playwright_auth_capture_diag import (  # noqa: E402
    infer_timeout_failure_phase,
    login_transition_state,
)
from playwright_auth_capture_strict import evaluate_strict_capture  # noqa: E402
from playwright_auth_preflight_strict import PREFLIGHT_FAIL_NO_TOKEN_ROW  # noqa: E402
from suite_auth import (  # noqa: E402
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_ID_KEY,
    ensure_authenticated_session_hydrated,
)

SID_2967 = "2967c4d9-6054-46e5-a0bd-c89d00ac7f74"
SID_7155 = "71559005-eb49-48c4-ae24-cb71c8e5ea8c"
FP = "23f75e3dbb4b72ec"


def _h(checkpoint: str, **extra: object) -> dict:
    row = {
        "event": "production_stage1_auth_prestart_hydration",
        "checkpoint": checkpoint,
        "streamlit_session_id": "sess-a",
        "run_id": "run-a",
        "script_run_seq": 1,
        "event_index": extra.pop("event_index", 1),
    }
    row.update(extra)
    return row


def _dom(*, complete: bool = True) -> dict:
    return {
        "streamlit_session_id": "sess-a",
        "diagnostic_run_id": "run-a",
        "script_run_seq": 8,
        "session_flag_present": True,
        "is_authenticated": complete,
        "auth_session_complete": complete,
        "auth_hydration_source": "already_complete" if complete else "restore_failed",
        "access_token_present": complete,
        "refresh_token_present": complete,
        "auth_user_id_present": complete,
        "start_enabled": True,
        "current_restore_blocked_reason": "",
    }


def _missing_load(*, prefix: str, event_index: int = 10) -> dict:
    return _h(
        "load_browser_auth_tokens",
        browser_tokens_loaded=False,
        access_token_present=False,
        refresh_token_present=False,
        suite_sid_prefix=prefix,
        event_index=event_index,
    )


def _apply_ok(*, event_index: int = 20) -> dict:
    return _h(
        "apply_authenticated_user_exit",
        authenticated_after=True,
        apply_return_ok=True,
        auth_session_complete=True,
        event_index=event_index,
    )


def _save_ok(*, prefix: str, event_index: int = 21) -> dict:
    return _h(
        "save_browser_auth_tokens",
        persistence_attempted=True,
        persistence_succeeded=True,
        suite_sid_prefix=prefix,
        access_token_present=True,
        refresh_token_present=True,
        auth_user_id_present=True,
        bridge_record_complete=True,
        failure_reason="ok",
        handoff_phase="INTERMEDIATE",
        event_index=event_index,
    )


def _readback_ok(*, prefix: str, event_index: int = 22, complete: bool = True) -> dict:
    return _h(
        "save_browser_auth_tokens_readback",
        suite_sid_prefix=prefix,
        readback_record_complete=complete,
        rejection_reason="ok" if complete else "incomplete",
        access_token_present=True,
        refresh_token_present=True,
        event_index=event_index,
    )


def _final_ok(*, prefix: str, event_index: int = 30, fp: str = FP) -> list[dict]:
    return [
        _h(
            "bridge_final_handoff_persist",
            handoff_phase="FINAL_HANDOFF",
            persistence_succeeded=True,
            suite_sid_prefix=prefix,
            refresh_fp=fp,
            refresh_fp_prefix=fp[:16],
            session_snapshot_refresh_fp_prefix=fp[:16],
            token_generation=2,
            failure_reason="ok",
            event_index=event_index,
        ),
        _h(
            "bridge_final_handoff_readback",
            handoff_phase="FINAL_HANDOFF",
            readback_succeeded=True,
            suite_sid_prefix=prefix,
            refresh_fp_prefix=fp[:16],
            token_generation=2,
            failure_reason="ok",
            event_index=event_index + 1,
        ),
        _h(
            "bridge_final_handoff_invariant",
            final_session_snapshot_fingerprint=fp[:16],
            final_persist_token_fingerprint=fp[:16],
            final_browser_token_fingerprint=fp[:16],
            final_readback_token_fingerprint=fp[:16],
            fingerprint_match=True,
            no_auth_refresh_after_final_persist=True,
            no_auth_consumption_since_final_token_snapshot=True,
            failure_reason="ok",
            event_index=event_index + 2,
        ),
    ]


def _eval(sid: str, rows: list[dict], *, signed_in: bool = True, dom: dict | None = None) -> dict:
    ledger = list(rows)
    if not any(
        str(r.get("checkpoint") or "") in ("bridge_final_handoff_persist", "bridge_final_handoff_invariant")
        or str(r.get("handoff_phase") or "") == "FINAL_HANDOFF"
        for r in ledger
    ):
        ledger.extend(_final_ok(prefix=sid[:8], event_index=9000))
    raw = evaluate_strict_capture(
        target_sid=sid,
        url_sid=sid,
        ledger_rows=ledger,
        start_enabled=True,
        start_visible=True,
        paired_authenticated=True,
        signed_in_display=signed_in,
        current_auth_dom=dom if dom is not None else _dom(),
        diagnostic_run_id="run-a",
        streamlit_session_id="sess-a",
    )
    raw["apply_authenticated_user_observed"] = apply_authenticated_user_observed_from_ledger(rows)
    return enforce_current_suite_bridge_authority(raw)


def _login_state(
    *,
    sid: str,
    rows: list[dict],
    strict_failure: str,
    sign_in_initiated: bool = False,
    signed_in_display: bool = True,
) -> dict:
    return login_transition_state(
        target_sid=sid,
        url_sid=sid,
        provider_seen=False,
        oauth_callback_seen=False,
        returned_to_app=False,
        storage={
            "access_token_value_present": False,
            "refresh_token_value_present": False,
            "supabase_storage_key_present": False,
        },
        signed_in_display=signed_in_display,
        ledger_rows=rows,
        strict_failure=strict_failure,
        sign_in_initiated=sign_in_initiated,
    )


class AlreadyCompleteBridgeSaveRepairTests(unittest.TestCase):
    def test_01_2967_shape_detects_missing_bridge_and_allows_one_shot_sync(self) -> None:
        """Historical 2967: already_complete UI + token_record_missing → bootstrap once."""
        rows = [
            _h(
                "load_browser_auth_tokens_lookup",
                rejection_reason="token_record_missing",
                browser_tokens_loaded=False,
                suite_sid_prefix=SID_2967[:8],
                event_index=1,
            ),
            _missing_load(prefix=SID_2967[:8], event_index=2),
            _h(
                "restore_auth_session_exit",
                authenticated_after=False,
                skip_or_failure_reason="token_record_missing",
                event_index=3,
            ),
        ]
        ev = _eval(SID_2967, rows, signed_in=True, dom=_dom(complete=True))
        self.assertFalse(ev["strict_auth_passed"])
        self.assertEqual(ev["failure"], PREFLIGHT_FAIL_NO_TOKEN_ROW)
        self.assertFalse(ev["bridge_persistence"]["persistence_attempted"])
        self.assertFalse((ev.get("final_handoff") or {}).get("eligible"))
        eligible = already_authenticated_bridge_missing(
            is_authenticated=True,
            auth_session_complete=True,
            signed_in_display=True,
            token_record_missing=True,
            persistence_succeeded=False,
            readback_succeeded=False,
            bridge_record_complete=False,
        )
        self.assertTrue(eligible)
        decision = decide_already_authenticated_nonconsuming_finalize(eligible=True, attempted_count=0)
        self.assertTrue(decision["invoke"])
        self.assertEqual(decision["reason"], ALREADY_AUTH_NONCONSUMING_FINALIZE)
        # Consuming UPDATE_FROM_QUERY_PARAMS bootstrap must stay disabled.
        legacy = decide_already_authenticated_bridge_bootstrap(eligible=True, attempted_count=0)
        self.assertFalse(legacy["invoke"])
        # After supported sync produces save+readback+FINAL (ledger), strict passes.
        repaired = [
            *rows,
            _apply_ok(event_index=20),
            _save_ok(prefix=SID_2967[:8], event_index=21),
            _readback_ok(prefix=SID_2967[:8], event_index=22),
        ]
        ev2 = _eval(SID_2967, repaired, signed_in=True, dom=_dom())
        self.assertTrue(ev2["strict_auth_passed"])
        self.assertTrue(current_suite_bridge_authority_ok(ev2["bridge_persistence"]))
        self.assertTrue((ev2.get("final_handoff") or {}).get("eligible") or (ev2.get("final_handoff") or {}).get("final_handoff_seen"))

    def test_02_715590_success_shape_no_redundant_bootstrap(self) -> None:
        rows = [
            _missing_load(prefix=SID_7155[:8], event_index=10),
            _apply_ok(event_index=20),
            _save_ok(prefix=SID_7155[:8], event_index=21),
            _readback_ok(prefix=SID_7155[:8], event_index=22),
            _h(
                "restore_auth_session_exit",
                authenticated_after=True,
                skip_or_failure_reason="already_complete",
                event_index=23,
            ),
        ]
        ev = _eval(SID_7155, rows, signed_in=True, dom=_dom())
        self.assertTrue(ev["strict_auth_passed"])
        self.assertTrue(ev["apply_authenticated_user_observed"])
        self.assertFalse(
            already_authenticated_bridge_missing(
                is_authenticated=True,
                auth_session_complete=True,
                signed_in_display=True,
                token_record_missing=False,
                persistence_succeeded=True,
                readback_succeeded=True,
                bridge_record_complete=True,
            )
        )
        decision = decide_already_authenticated_nonconsuming_finalize(eligible=False, attempted_count=0)
        self.assertFalse(decision["invoke"])

    def test_03_existing_current_suite_bridge_skips_bootstrap(self) -> None:
        self.assertFalse(
            already_authenticated_bridge_missing(
                is_authenticated=True,
                auth_session_complete=True,
                signed_in_display=True,
                token_record_missing=False,
                persistence_succeeded=True,
                readback_succeeded=True,
                bridge_record_complete=True,
            )
        )

    def test_04_incomplete_session_does_not_fabricate_bridge(self) -> None:
        self.assertFalse(
            already_authenticated_bridge_missing(
                is_authenticated=False,
                auth_session_complete=False,
                signed_in_display=False,
                token_record_missing=True,
                persistence_succeeded=False,
                readback_succeeded=False,
                bridge_record_complete=False,
            )
        )
        rows = [_missing_load(prefix=SID_2967[:8])]
        ev = evaluate_strict_capture(
            target_sid=SID_2967,
            url_sid=SID_2967,
            ledger_rows=rows,
            start_enabled=False,
            start_visible=True,
            paired_authenticated=None,
            signed_in_display=False,
            current_auth_dom=_dom(complete=False),
        )
        self.assertFalse(ev["strict_auth_passed"])
        self.assertFalse(ev["bridge_persistence"]["persistence_attempted"])

    def test_05_save_failure_fail_closed(self) -> None:
        rows = [
            _missing_load(prefix=SID_2967[:8], event_index=1),
            _apply_ok(event_index=2),
            _h(
                "save_browser_auth_tokens",
                persistence_attempted=True,
                persistence_succeeded=False,
                suite_sid_prefix=SID_2967[:8],
                bridge_record_complete=False,
                failure_reason="save_error:APIError",
                event_index=3,
            ),
        ]
        ev = _eval(SID_2967, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["strict_auth_passed"])
        self.assertFalse(ev["bridge_persistence"]["persistence_succeeded"])
        self.assertFalse((ev.get("final_handoff") or {}).get("eligible") and ev["bridge_persistence"]["persistence_succeeded"])

    def test_06_readback_failure_fail_closed(self) -> None:
        rows = [
            _missing_load(prefix=SID_2967[:8], event_index=1),
            _apply_ok(event_index=2),
            _save_ok(prefix=SID_2967[:8], event_index=3),
            _readback_ok(prefix=SID_2967[:8], event_index=4, complete=False),
        ]
        ev = _eval(SID_2967, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["strict_auth_passed"])
        self.assertFalse(ev["bridge_persistence"]["readback_succeeded"])

    def test_07_identity_mismatch_fail_closed(self) -> None:
        rows = [
            _missing_load(prefix=SID_2967[:8], event_index=1),
            _apply_ok(event_index=2),
            _save_ok(prefix="ffffffff", event_index=3),
            _readback_ok(prefix="ffffffff", event_index=4),
        ]
        ev = _eval(SID_2967, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["strict_auth_passed"])
        self.assertFalse(current_suite_bridge_authority_ok(ev["bridge_persistence"]))

    def test_08_sign_in_initiated_false_still_allows_nonconsuming_finalize(self) -> None:
        self.assertTrue(
            already_authenticated_bridge_missing(
                is_authenticated=True,
                auth_session_complete=True,
                signed_in_display=True,
                token_record_missing=True,
                persistence_succeeded=False,
                readback_succeeded=False,
                bridge_record_complete=False,
            )
        )
        decision = decide_already_authenticated_nonconsuming_finalize(eligible=True, attempted_count=0)
        self.assertTrue(decision["invoke"])
        self.assertEqual(decision["reason"], ALREADY_AUTH_NONCONSUMING_FINALIZE)
        legacy = decide_already_authenticated_bridge_bootstrap(eligible=True, attempted_count=0)
        self.assertFalse(legacy["invoke"])
        self.assertEqual(BOOTSTRAP_MAX_ATTEMPTS, 1)

    def test_09_timeout_bridge_save_when_ui_authenticated_bridge_missing(self) -> None:
        rows = [
            _missing_load(prefix=SID_2967[:8], event_index=1),
            _h(
                "restore_auth_session_exit",
                authenticated_after=False,
                skip_or_failure_reason="token_record_missing",
                event_index=2,
            ),
        ]
        st = _login_state(
            sid=SID_2967,
            rows=rows,
            strict_failure=PREFLIGHT_FAIL_NO_TOKEN_ROW,
            sign_in_initiated=False,
            signed_in_display=True,
        )
        self.assertFalse(st["steps"]["1_sign_in_initiated"])
        self.assertTrue(st["steps"]["8_load_browser_auth_tokens_invoked"])
        self.assertFalse(st["bridge_save_attempted"])
        phase = infer_timeout_failure_phase(st, strict_failure=PREFLIGHT_FAIL_NO_TOKEN_ROW)
        self.assertEqual(phase, "timeout_bridge_save_never_invoked")
        self.assertNotEqual(phase, "timeout_login_never_initiated")

    def test_10_genuine_login_never_initiated_preserved(self) -> None:
        st = _login_state(
            sid=SID_2967,
            rows=[],
            strict_failure="",
            sign_in_initiated=False,
            signed_in_display=False,
        )
        self.assertEqual(st["first_missing_transition"], "1_sign_in_initiated")
        phase = infer_timeout_failure_phase(st, strict_failure="")
        self.assertEqual(phase, "timeout_login_never_initiated")
        # Incomplete session + missing bridge must NOT become bootstrap-eligible.
        self.assertFalse(
            already_authenticated_bridge_missing(
                is_authenticated=False,
                auth_session_complete=False,
                signed_in_display=False,
                token_record_missing=True,
                persistence_succeeded=False,
                readback_succeeded=False,
                bridge_record_complete=False,
            )
        )

    def test_11_ensure_hydrated_ordinary_ui_early_return_unchanged(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-daniel",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.restore_auth_session"
        ) as restore:
            self.assertTrue(ensure_authenticated_session_hydrated(session))
            restore.assert_not_called()
            self.assertEqual(session.get("_suite_auth_last_hydration_source"), "already_complete")

    def test_12_ui_already_complete_does_not_imply_strict_bridge_ready(self) -> None:
        rows = [_missing_load(prefix=SID_2967[:8], event_index=1)]
        ev = evaluate_strict_capture(
            target_sid=SID_2967,
            url_sid=SID_2967,
            ledger_rows=rows,
            start_enabled=True,
            start_visible=True,
            paired_authenticated=True,
            signed_in_display=True,
            current_auth_dom=_dom(complete=True),
            diagnostic_run_id="run-a",
            streamlit_session_id="sess-a",
        )
        ev = enforce_current_suite_bridge_authority(ev)
        self.assertTrue(ev.get("is_authenticated"))
        self.assertTrue(ev.get("auth_session_complete"))
        self.assertEqual(ev["failure"], PREFLIGHT_FAIL_NO_TOKEN_ROW)
        self.assertFalse(ev["strict_auth_passed"])
        self.assertFalse((ev.get("final_handoff") or {}).get("eligible"))

    def test_13_nonconsuming_finalize_at_most_once(self) -> None:
        first = decide_already_authenticated_nonconsuming_finalize(eligible=True, attempted_count=0)
        second = decide_already_authenticated_nonconsuming_finalize(eligible=True, attempted_count=1)
        self.assertTrue(first["invoke"])
        self.assertFalse(second["invoke"])
        self.assertEqual(second["reason"], "finalize_already_attempted")
        # Legacy consuming bootstrap never invokes.
        legacy = decide_already_authenticated_bridge_bootstrap(eligible=True, attempted_count=0)
        self.assertFalse(legacy["invoke"])


if __name__ == "__main__":
    unittest.main()
