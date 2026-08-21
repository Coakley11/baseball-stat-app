"""Local synthetic tests for already-authenticated Context A bridge bootstrap.

No browser. No network. Does not execute capture main().
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from capture_playwright_daniel_auth_once import (  # noqa: E402
    ALREADY_AUTH_BRIDGE_MISSING,
    BOOTSTRAP_MAX_ATTEMPTS,
    FRANCISCO_LATCH_PARAM,
    already_authenticated_bridge_missing,
    apply_authenticated_user_observed_from_ledger,
    build_already_authenticated_bridge_bootstrap_message,
    capture_query_string_for_bridge_bootstrap,
    current_suite_bridge_authority_ok,
    decide_already_authenticated_bridge_bootstrap,
    enforce_current_suite_bridge_authority,
    invoke_already_authenticated_bridge_bootstrap,
    select_streamlit_guest_frame_index,
)
from playwright_auth_capture_diag import login_transition_state  # noqa: E402
from playwright_auth_capture_strict import (  # noqa: E402
    CAPTURE_FAIL_BRIDGE_PERSIST,
    CAPTURE_FAIL_BRIDGE_PERSIST_SID,
    CAPTURE_FAIL_SIGNED_IN_ONLY,
    evaluate_strict_capture,
)
from playwright_auth_preflight_strict import PREFLIGHT_FAIL_NO_TOKEN_ROW  # noqa: E402

SID_6B = "6b0e3dde-6173-4fe9-a20e-8267ac8933df"
SID_AEFA = "aefa77f2-bc00-45f1-a378-9d5a7ee71551"
SID_FRESH = "abcd1234-0000-0000-0000-000000000001"


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
        protected_keys={"session_flag_present": True},
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


def _final_handoff_ok(*, prefix: str, event_index: int = 30, fp: str = "abcdef0123456789") -> list[dict]:
    return [
        _h(
            "bridge_final_handoff_persist",
            handoff_phase="FINAL_HANDOFF",
            persistence_succeeded=True,
            suite_sid_prefix=prefix,
            refresh_fp=fp,
            refresh_fp_prefix=fp[:16],
            token_generation=2,
            failure_reason="ok",
            event_index=event_index,
        ),
        _h(
            "bridge_final_handoff_invariant",
            final_persist_token_fingerprint=fp[:16],
            final_browser_token_fingerprint=fp[:16],
            fingerprint_match=True,
            no_auth_refresh_after_final_persist=True,
            failure_reason="ok",
            event_index=event_index + 1,
        ),
    ]


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


def _eval(sid: str, rows: list[dict], *, signed_in: bool = True, dom: dict | None = None) -> dict:
    ledger = list(rows)
    if not any(
        str(r.get("checkpoint") or "") in ("bridge_final_handoff_persist", "bridge_final_handoff_invariant")
        or str(r.get("handoff_phase") or "") == "FINAL_HANDOFF"
        for r in ledger
    ):
        ledger.extend(_final_handoff_ok(prefix=sid[:8], event_index=9000))
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


class AlreadyAuthenticatedBridgeBootstrapTests(unittest.TestCase):
    def test_01_normal_fresh_login_success(self) -> None:
        rows = [
            _h(
                "load_browser_auth_tokens",
                browser_tokens_loaded=True,
                access_token_present=True,
                refresh_token_present=True,
                suite_sid_prefix=SID_FRESH[:8],
                event_index=1,
            ),
            _apply_ok(event_index=2),
            _save_ok(prefix=SID_FRESH[:8], event_index=3),
            _readback_ok(prefix=SID_FRESH[:8], event_index=4),
        ]
        ev = _eval(SID_FRESH, rows, signed_in=True, dom=_dom())
        self.assertTrue(ev["strict_auth_passed"])
        self.assertTrue(ev["apply_authenticated_user_observed"])
        self.assertTrue(current_suite_bridge_authority_ok(ev["bridge_persistence"]))

    def test_02_accepted_already_authenticated_pattern(self) -> None:
        rows = [
            _missing_load(prefix=SID_6B[:8], event_index=10),
            _apply_ok(event_index=20),
            _save_ok(prefix=SID_6B[:8], event_index=21),
            _readback_ok(prefix=SID_6B[:8], event_index=22),
        ]
        ev = _eval(SID_6B, rows, signed_in=True, dom=_dom())
        self.assertTrue(ev["strict_auth_passed"])
        self.assertTrue(ev["bridge_persistence"]["persistence_succeeded"])
        self.assertTrue(ev["bridge_persistence"]["readback_succeeded"])
        self.assertTrue(ev["bridge_persistence"]["bridge_record_complete"])

    def test_03_aefa_failure_pattern(self) -> None:
        rows = [_missing_load(prefix=SID_AEFA[:8], event_index=737)]
        ev = _eval(SID_AEFA, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["strict_auth_passed"])
        self.assertEqual(ev["failure"], PREFLIGHT_FAIL_NO_TOKEN_ROW)
        self.assertFalse(ev["apply_authenticated_user_observed"])
        eligible = already_authenticated_bridge_missing(
            is_authenticated=True,
            auth_session_complete=True,
            signed_in_display=True,
            token_record_missing=str(ev.get("bridge_lookup") or "") == "record_missing",
            persistence_succeeded=bool((ev.get("bridge_persistence") or {}).get("persistence_succeeded")),
            readback_succeeded=bool((ev.get("bridge_persistence") or {}).get("readback_succeeded")),
            bridge_record_complete=bool((ev.get("bridge_persistence") or {}).get("bridge_record_complete")),
        )
        self.assertTrue(eligible)

    def test_04_bootstrap_eligible_when_auth_complete_and_bridge_missing(self) -> None:
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
        decision = decide_already_authenticated_bridge_bootstrap(eligible=True, attempted_count=0)
        self.assertTrue(decision["invoke"])
        self.assertEqual(decision["reason"], ALREADY_AUTH_BRIDGE_MISSING)

    def test_05_not_authenticated_not_eligible(self) -> None:
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
        decision = decide_already_authenticated_bridge_bootstrap(eligible=False, attempted_count=0)
        self.assertFalse(decision["invoke"])
        self.assertEqual(decision["reason"], "not_eligible")

    def test_06_existing_bridge_complete_bootstrap_not_needed(self) -> None:
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

    def test_07_wrong_suite_sid_save_does_not_satisfy(self) -> None:
        rows = [
            _missing_load(prefix=SID_FRESH[:8], event_index=10),
            _apply_ok(event_index=20),
            _save_ok(prefix="ffffffff", event_index=21),
            _readback_ok(prefix="ffffffff", event_index=22),
        ]
        ev = _eval(SID_FRESH, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["strict_auth_passed"])
        self.assertEqual(ev["failure"], CAPTURE_FAIL_BRIDGE_PERSIST_SID)
        self.assertFalse(current_suite_bridge_authority_ok(ev["bridge_persistence"]))

    def test_08_save_without_readback_fails(self) -> None:
        rows = [
            _h(
                "load_browser_auth_tokens",
                browser_tokens_loaded=True,
                access_token_present=True,
                refresh_token_present=True,
                suite_sid_prefix=SID_FRESH[:8],
                event_index=1,
            ),
            _apply_ok(event_index=2),
            _save_ok(prefix=SID_FRESH[:8], event_index=3),
        ]
        ev = _eval(SID_FRESH, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["strict_auth_passed"])
        self.assertFalse(ev["bridge_persistence"]["readback_succeeded"])
        self.assertIn(ev["failure"], (CAPTURE_FAIL_BRIDGE_PERSIST, PREFLIGHT_FAIL_NO_TOKEN_ROW))

    def test_09_readback_incomplete_fails(self) -> None:
        rows = [
            _h(
                "load_browser_auth_tokens",
                browser_tokens_loaded=True,
                access_token_present=True,
                refresh_token_present=True,
                suite_sid_prefix=SID_FRESH[:8],
                event_index=1,
            ),
            _apply_ok(event_index=2),
            _save_ok(prefix=SID_FRESH[:8], event_index=3),
            _readback_ok(prefix=SID_FRESH[:8], event_index=4, complete=False),
        ]
        ev = _eval(SID_FRESH, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["strict_auth_passed"])
        self.assertFalse(ev["bridge_persistence"]["readback_succeeded"])

    def test_10_persistence_failure_fails(self) -> None:
        rows = [
            _h(
                "load_browser_auth_tokens",
                browser_tokens_loaded=True,
                access_token_present=True,
                refresh_token_present=True,
                suite_sid_prefix=SID_FRESH[:8],
                event_index=1,
            ),
            _apply_ok(event_index=2),
            _h(
                "save_browser_auth_tokens",
                persistence_attempted=True,
                persistence_succeeded=False,
                suite_sid_prefix=SID_FRESH[:8],
                bridge_record_complete=False,
                failure_reason="save_error:APIError",
                event_index=3,
            ),
        ]
        ev = _eval(SID_FRESH, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["strict_auth_passed"])
        self.assertFalse(ev["bridge_persistence"]["persistence_succeeded"])

    def test_11_apply_not_observed_but_save_readback_complete(self) -> None:
        rows = [
            _h(
                "load_browser_auth_tokens",
                browser_tokens_loaded=True,
                access_token_present=True,
                refresh_token_present=True,
                suite_sid_prefix=SID_FRESH[:8],
                event_index=1,
            ),
            _save_ok(prefix=SID_FRESH[:8], event_index=3),
            _readback_ok(prefix=SID_FRESH[:8], event_index=4),
        ]
        ev = _eval(SID_FRESH, rows, signed_in=True, dom=_dom())
        self.assertFalse(ev["apply_authenticated_user_observed"])
        self.assertTrue(ev["strict_auth_passed"])
        self.assertTrue(current_suite_bridge_authority_ok(ev["bridge_persistence"]))

    def test_12_login_initiated_false_still_passes_with_bridge_proof(self) -> None:
        rows = [
            _missing_load(prefix=SID_6B[:8], event_index=10),
            _apply_ok(event_index=20),
            _save_ok(prefix=SID_6B[:8], event_index=21),
            _readback_ok(prefix=SID_6B[:8], event_index=22),
        ]
        ev = _eval(SID_6B, rows, signed_in=True, dom=_dom())
        self.assertTrue(ev["strict_auth_passed"])
        login = login_transition_state(
            target_sid=SID_6B,
            url_sid=SID_6B,
            provider_seen=False,
            oauth_callback_seen=False,
            returned_to_app=True,
            storage={
                "access_token_value_present": False,
                "refresh_token_value_present": False,
                "supabase_storage_key_present": False,
            },
            signed_in_display=True,
            ledger_rows=rows,
            strict_failure="",
            sign_in_initiated=False,
        )
        self.assertFalse(login["steps"]["1_sign_in_initiated"])
        self.assertEqual(login["first_missing_transition"], "1_sign_in_initiated")

    def test_13_bootstrap_attempt_once_no_loop(self) -> None:
        self.assertEqual(BOOTSTRAP_MAX_ATTEMPTS, 1)
        first = decide_already_authenticated_bridge_bootstrap(eligible=True, attempted_count=0)
        self.assertTrue(first["invoke"])
        second = decide_already_authenticated_bridge_bootstrap(eligible=True, attempted_count=1)
        self.assertFalse(second["invoke"])
        self.assertEqual(second["reason"], "bootstrap_already_attempted")
        third = decide_already_authenticated_bridge_bootstrap(eligible=True, attempted_count=99)
        self.assertFalse(third["invoke"])

    def test_14_signed_in_ui_only_fails(self) -> None:
        ev = evaluate_strict_capture(
            target_sid=SID_AEFA,
            url_sid=SID_AEFA,
            ledger_rows=[],
            start_enabled=True,
            start_visible=True,
            paired_authenticated=None,
            signed_in_display=True,
        )
        ev = enforce_current_suite_bridge_authority(ev)
        self.assertFalse(ev["strict_auth_passed"])
        self.assertEqual(ev["failure"], CAPTURE_FAIL_SIGNED_IN_ONLY)
        self.assertFalse(
            already_authenticated_bridge_missing(
                is_authenticated=ev.get("is_authenticated"),
                auth_session_complete=ev.get("auth_session_complete"),
                signed_in_display=True,
                token_record_missing=str(ev.get("bridge_lookup") or "") == "record_missing",
                persistence_succeeded=False,
                readback_succeeded=False,
                bridge_record_complete=False,
            )
        )

    def test_15_existing_6b0e3dde_style_ledger_remains_accepted(self) -> None:
        rows = [
            _h(
                "load_browser_auth_tokens_lookup",
                rejection_reason="token_record_missing",
                browser_tokens_loaded=False,
                suite_sid_prefix=SID_6B[:8],
                event_index=4443,
            ),
            _missing_load(prefix=SID_6B[:8], event_index=4444),
            _h(
                "restore_auth_session_exit",
                authenticated_after=False,
                event_index=4445,
            ),
            _apply_ok(event_index=4539),
            _save_ok(prefix=SID_6B[:8], event_index=4540),
            _readback_ok(prefix=SID_6B[:8], event_index=4541),
        ]
        ev = _eval(SID_6B, rows, signed_in=True, dom=_dom())
        self.assertTrue(ev["strict_auth_passed"])
        self.assertTrue(ev["apply_authenticated_user_observed"])
        self.assertTrue(ev["bridge_persistence"]["suite_sid_prefix_match"])

    def test_bootstrap_message_is_existing_query_host_contract(self) -> None:
        url = (
            "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
            f"?active_page=Live+Draft+Room&solo_component_diag=1"
            f"&solo_stage1_parent_boundary=1&suite_sid={SID_AEFA}"
            f"&{FRANCISCO_LATCH_PARAM}=1"
        )
        qs = capture_query_string_for_bridge_bootstrap(url, suite_sid=SID_AEFA)
        self.assertNotIn(FRANCISCO_LATCH_PARAM, qs)
        self.assertIn(f"suite_sid={SID_AEFA}", qs)
        msg = build_already_authenticated_bridge_bootstrap_message(qs)
        self.assertEqual(list(msg.keys()), ["stCommVersion", "type", "queryParams"])
        self.assertEqual(msg["stCommVersion"], 1)
        self.assertEqual(msg["type"], "UPDATE_FROM_QUERY_PARAMS")
        self.assertEqual(msg["queryParams"], qs)
        calls: list[tuple[int, dict]] = []

        def _evaluate(index: int, payload: dict) -> dict:
            calls.append((index, payload))
            return {"origin": "https://example", "search": "?" + qs}

        out = invoke_already_authenticated_bridge_bootstrap(
            query_string=qs,
            frame_urls=[
                "https://example/",
                f"https://example/~/+/?suite_sid={SID_AEFA}",
            ],
            evaluate_fn=_evaluate,
        )
        self.assertTrue(out["dispatched"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 1)
        self.assertEqual(select_streamlit_guest_frame_index(calls and [
            "https://example/",
            f"https://example/~/+/?suite_sid={SID_AEFA}",
        ])["kind"], "streamlit_guest_iframe")


if __name__ == "__main__":
    unittest.main()
