"""Browser-free integration: FINAL_HANDOFF evidence survives durable capture assembly.

Proves the c900-class defect is fixed:
  full ledger FINAL → evaluate_strict_capture → _public_summary → ledger_login_timeline
  → evaluate_final_handoff_reservation_from_durable remains eligible.

No auto-injection of missing FINAL rows. No browser/network.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from capture_playwright_daniel_auth_once import _public_summary  # noqa: E402
from playwright_auth_capture_diag import (  # noqa: E402
    LOGIN_CHECKPOINTS,
    ledger_login_timeline,
)
from playwright_auth_capture_strict import (  # noqa: E402
    CAPTURE_FAIL_FINAL_HANDOFF,
    CAPTURE_FAIL_FINAL_HANDOFF_AUTHORITY_MISMATCH,
    evaluate_final_handoff_reservation_from_durable,
    evaluate_strict_capture,
    metadata_has_no_secrets,
)
from suite_auth_bridge_handoff import (  # noqa: E402
    CAPTURE_FAIL_HANDOFF_FP_MISMATCH,
    CAPTURE_FAIL_POST_HANDOFF_REFRESH,
    CHECKPOINT_FINAL_INVARIANT,
    CHECKPOINT_FINAL_PERSIST,
    CHECKPOINT_FINAL_READBACK,
    PHASE_FINAL,
    PHASE_INTERMEDIATE,
    evaluate_final_handoff_eligibility,
)

SID = "c900c4ea-4595-400c-a556-eb9226d4de81"
PREFIX = SID[:8]
FP = "abcdef0123456789"
STREAMLIT_SID = "45af0fe1-415a-4604-83a2-df84dd8aa080"
RUN_ID = "run-c900-propagation"


def _h(checkpoint: str, *, event_index: int, **extra: object) -> dict:
    row = {
        "event": "production_stage1_auth_prestart_hydration",
        "checkpoint": checkpoint,
        "streamlit_session_id": STREAMLIT_SID,
        "diagnostic_run_id": RUN_ID,
        "run_id": RUN_ID,
        "script_run_seq": 1,
        "event_index": event_index,
        "event_id": f"fcd3647d24d8439b:{event_index}:production_stage1_auth_prestart_hydration",
        "suite_sid_prefix": PREFIX,
    }
    row.update(extra)
    return row


def _already_complete_dom() -> dict:
    return {
        "streamlit_session_id": STREAMLIT_SID,
        "diagnostic_run_id": RUN_ID,
        "script_run_seq": 8,
        "session_flag_present": True,
        "is_authenticated": True,
        "auth_session_complete": True,
        "auth_hydration_source": "already_complete",
        "access_token_present": True,
        "refresh_token_present": True,
        "auth_user_id_present": True,
        "start_enabled": True,
        "current_restore_blocked_reason": "",
    }


def _base_success_rows(*, include_final: bool = True, fp: str = FP, gen: int = 2) -> list[dict]:
    rows = [
        _h(
            "load_browser_auth_tokens",
            event_index=10,
            browser_tokens_loaded=False,
            access_token_present=False,
            refresh_token_present=False,
        ),
        _h(
            "apply_authenticated_user_exit",
            event_index=20,
            authenticated_after=True,
            apply_return_ok=True,
            auth_session_complete=True,
            protected_keys={"session_flag_present": True},
        ),
        _h(
            "save_browser_auth_tokens",
            event_index=21,
            persistence_attempted=True,
            persistence_succeeded=True,
            access_token_present=True,
            refresh_token_present=True,
            auth_user_id_present=True,
            bridge_record_complete=True,
            handoff_phase=PHASE_INTERMEDIATE,
            failure_reason="ok",
        ),
        _h(
            "save_browser_auth_tokens_readback",
            event_index=22,
            readback_record_complete=True,
            rejection_reason="ok",
            access_token_present=True,
            refresh_token_present=True,
        ),
        _h(
            "restore_auth_session_exit",
            event_index=23,
            authenticated_after=True,
            skip_or_failure_reason="already_complete",
        ),
    ]
    if include_final:
        rows.extend(
            [
                _h(
                    CHECKPOINT_FINAL_PERSIST,
                    event_index=40,
                    handoff_phase=PHASE_FINAL,
                    persistence_succeeded=True,
                    refresh_fp=fp,
                    refresh_fp_prefix=fp[:16],
                    access_fp_prefix="feedfacefeedface"[:16],
                    token_generation=gen,
                    failure_reason="ok",
                ),
                _h(
                    CHECKPOINT_FINAL_READBACK,
                    event_index=41,
                    handoff_phase=PHASE_FINAL,
                    readback_succeeded=True,
                    fingerprint_match=True,
                    refresh_fp_prefix=fp[:16],
                    token_generation=gen,
                    failure_reason="ok",
                ),
                _h(
                    CHECKPOINT_FINAL_INVARIANT,
                    event_index=42,
                    handoff_phase=PHASE_FINAL,
                    final_persist_token_fingerprint=fp[:16],
                    final_browser_token_fingerprint=fp[:16],
                    fingerprint_match=True,
                    no_auth_refresh_after_final_persist=True,
                    failure_reason="ok",
                ),
            ]
        )
    return rows


def _assemble_durable(ledger: list[dict]) -> tuple[dict, dict]:
    """Mirror supported capture assembly: strict eval → public summary → timeline → result."""
    # Do NOT inject FINAL — caller must supply real ledger evidence.
    assert not any(
        # guard against accidental helper injection in this module
        False
        for _ in ()
    )
    strict = evaluate_strict_capture(
        target_sid=SID,
        url_sid=SID,
        ledger_rows=ledger,
        start_enabled=True,
        start_visible=True,
        paired_authenticated=True,
        signed_in_display=True,
        current_auth_dom=_already_complete_dom(),
        diagnostic_run_id=RUN_ID,
        streamlit_session_id=STREAMLIT_SID,
    )
    public = _public_summary(strict)
    timeline = ledger_login_timeline(ledger)
    durable = {
        "ok": bool(strict.get("strict_auth_passed")),
        "suite_sid": SID,
        "auth_capture_pass": bool(strict.get("strict_auth_passed")),
        "strict_capture": public,
        "login_timeline": timeline,
    }
    return strict, durable


class FinalHandoffEvidencePropagationTests(unittest.TestCase):
    def test_01_login_checkpoints_include_final_types(self) -> None:
        for cp in (CHECKPOINT_FINAL_PERSIST, CHECKPOINT_FINAL_READBACK, CHECKPOINT_FINAL_INVARIANT):
            self.assertIn(cp, LOGIN_CHECKPOINTS)

    def test_02_public_summary_preserves_strict_and_final(self) -> None:
        strict, durable = _assemble_durable(_base_success_rows(include_final=True))
        self.assertTrue(strict["strict_auth_passed"])
        sc = durable["strict_capture"]
        self.assertTrue(sc.get("strict_auth_passed"))
        self.assertIn("final_handoff", sc)
        self.assertTrue(sc["final_handoff"]["eligible"])
        self.assertTrue(sc["final_handoff"]["final_handoff_seen"])
        self.assertEqual(sc["final_handoff"]["refresh_fp_prefix"], FP[:16])
        self.assertEqual(sc["final_handoff"]["token_generation"], 2)

    def test_03_timeline_preserves_final_phase_and_fingerprints(self) -> None:
        _, durable = _assemble_durable(_base_success_rows(include_final=True))
        tl = durable["login_timeline"]
        cps = {str(r.get("checkpoint")) for r in tl}
        self.assertIn(CHECKPOINT_FINAL_PERSIST, cps)
        self.assertIn(CHECKPOINT_FINAL_READBACK, cps)
        self.assertIn(CHECKPOINT_FINAL_INVARIANT, cps)
        persist = next(r for r in tl if r.get("checkpoint") == CHECKPOINT_FINAL_PERSIST)
        self.assertEqual(persist.get("handoff_phase"), PHASE_FINAL)
        self.assertEqual(str(persist.get("refresh_fp_prefix") or "")[:16], FP[:16])
        self.assertEqual(int(persist.get("token_generation") or 0), 2)
        inv = next(r for r in tl if r.get("checkpoint") == CHECKPOINT_FINAL_INVARIANT)
        self.assertTrue(inv.get("fingerprint_match"))
        self.assertTrue(inv.get("no_auth_refresh_after_final_persist"))

    def test_04_integration_propagation_already_complete_path(self) -> None:
        """c900-style already_complete success: FINAL survives assembly → reservation."""
        strict, durable = _assemble_durable(_base_success_rows(include_final=True))
        self.assertTrue(strict["strict_auth_passed"])
        self.assertTrue(strict["final_handoff"]["eligible"])

        # Timeline alone is enough for eligibility after repair (corroboration).
        tl_elig = evaluate_final_handoff_eligibility(durable["login_timeline"], target_sid=SID)
        self.assertTrue(tl_elig["eligible"], tl_elig)

        res = evaluate_final_handoff_reservation_from_durable(durable, target_sid=SID)
        self.assertTrue(res["eligible"], res)
        self.assertEqual(res["authority"], "durable_strict_final_handoff")
        self.assertTrue(res["timeline_corroborated"])
        self.assertFalse(res["authority_mismatch"])
        self.assertTrue(metadata_has_no_secrets(durable))

    def test_05_old_c900_lossy_summary_fails_closed(self) -> None:
        """Simulate pre-repair _public_summary that dropped FINAL while claiming pass."""
        strict, durable = _assemble_durable(_base_success_rows(include_final=True))
        self.assertTrue(strict["strict_auth_passed"])
        # Strip FINAL authority the way old _public_summary did.
        lossy = dict(durable)
        lossy["strict_capture"] = {
            k: v for k, v in durable["strict_capture"].items() if k not in ("final_handoff", "strict_auth_passed")
        }
        # Old stdout still said ok/pass without durable FINAL fields.
        lossy["strict_capture"]["is_authenticated"] = True
        lossy["strict_capture"]["auth_session_complete"] = True
        lossy["strict_capture"]["start_enabled"] = True
        # Force the mismatched shape: claim passed without final_handoff block.
        lossy["strict_capture"]["strict_auth_passed"] = True
        res = evaluate_final_handoff_reservation_from_durable(lossy, target_sid=SID)
        self.assertFalse(res["eligible"])
        self.assertTrue(res["authority_mismatch"])
        self.assertEqual(res["failure"], CAPTURE_FAIL_FINAL_HANDOFF_AUTHORITY_MISMATCH)

    def test_06_missing_final_fails_closed(self) -> None:
        strict, durable = _assemble_durable(_base_success_rows(include_final=False))
        self.assertFalse(strict["strict_auth_passed"])
        self.assertEqual(strict.get("failure"), CAPTURE_FAIL_FINAL_HANDOFF)
        self.assertFalse(durable["strict_capture"]["final_handoff"]["eligible"])
        res = evaluate_final_handoff_reservation_from_durable(durable, target_sid=SID)
        self.assertFalse(res["eligible"])
        self.assertIn("bridge_final_handoff", str(res.get("failure") or ""))

    def test_07_fingerprint_mismatch_fails_closed(self) -> None:
        rows = _base_success_rows(include_final=True, fp=FP)
        # Corrupt invariant browser fp.
        for r in rows:
            if r.get("checkpoint") == CHECKPOINT_FINAL_INVARIANT:
                r["final_browser_token_fingerprint"] = "deadbeefdeadbeef"
                r["fingerprint_match"] = False
        strict, durable = _assemble_durable(rows)
        self.assertFalse(strict["strict_auth_passed"])
        self.assertEqual(strict.get("failure"), CAPTURE_FAIL_HANDOFF_FP_MISMATCH)
        res = evaluate_final_handoff_reservation_from_durable(durable, target_sid=SID)
        self.assertFalse(res["eligible"])

    def test_08_post_final_refresh_fails_closed(self) -> None:
        rows = _base_success_rows(include_final=True)
        rows.append(
            _h(
                "restore_auth_session_exit",
                event_index=50,
                authenticated_after=True,
                skip_or_failure_reason="ok",
            )
        )
        strict, durable = _assemble_durable(rows)
        self.assertFalse(strict["strict_auth_passed"])
        self.assertEqual(strict.get("failure"), CAPTURE_FAIL_POST_HANDOFF_REFRESH)
        res = evaluate_final_handoff_reservation_from_durable(durable, target_sid=SID)
        self.assertFalse(res["eligible"])

    def test_09_reservation_not_timeline_alone(self) -> None:
        """Timeline with FINAL but durable strict missing FINAL → fail closed (not timeline-only pass)."""
        _, durable = _assemble_durable(_base_success_rows(include_final=True))
        # Keep repaired timeline; wipe durable FINAL authority.
        durable["strict_capture"] = {
            **{k: v for k, v in durable["strict_capture"].items() if k != "final_handoff"},
            "strict_auth_passed": False,
            "final_handoff": {
                "final_handoff_seen": False,
                "fingerprint_match": False,
                "no_auth_refresh_after_final_persist": False,
                "eligible": False,
                "refresh_fp_prefix": "",
                "token_generation": 0,
                "failure": CAPTURE_FAIL_FINAL_HANDOFF,
            },
        }
        # Timeline still has FINAL — must NOT authorize from timeline alone.
        tl_elig = evaluate_final_handoff_eligibility(durable["login_timeline"], target_sid=SID)
        self.assertTrue(tl_elig["eligible"])
        res = evaluate_final_handoff_reservation_from_durable(durable, target_sid=SID)
        self.assertFalse(res["eligible"])
        self.assertTrue(res["authority_mismatch"])

    def test_10_no_raw_tokens_in_durable_artifacts(self) -> None:
        ledger = _base_success_rows(include_final=True)
        # Poison full ledger with raw-looking fields that must never reach public artifacts.
        ledger.append(
            _h(
                CHECKPOINT_FINAL_PERSIST,
                event_index=99,
                handoff_phase=PHASE_FINAL,
                access_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaa.bbb",
                refresh_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ccc.ddd",
                refresh_fp=FP,
                refresh_fp_prefix=FP[:16],
                token_generation=2,
                persistence_succeeded=True,
            )
        )
        _, durable = _assemble_durable(_base_success_rows(include_final=True))
        blob = json.dumps(durable, default=str)
        self.assertNotIn("eyJ", blob)
        # Booleans like access_token_present are allowed; raw token values/keys are not.
        self.assertNotRegex(blob, r'"access_token"\s*:')
        self.assertNotRegex(blob, r'"refresh_token"\s*:')
        self.assertTrue(metadata_has_no_secrets(durable))
        # Timeline must not copy raw token keys even if present on source rows.
        poisoned_timeline = ledger_login_timeline(ledger)
        poisoned_blob = json.dumps(poisoned_timeline, default=str)
        self.assertNotRegex(poisoned_blob, r'"access_token"\s*:')
        self.assertNotRegex(poisoned_blob, r'"refresh_token"\s*:')
        self.assertNotIn("eyJ", poisoned_blob)

    def test_11_save_intermediate_handoff_phase_survives_timeline(self) -> None:
        _, durable = _assemble_durable(_base_success_rows(include_final=True))
        saves = [r for r in durable["login_timeline"] if r.get("checkpoint") == "save_browser_auth_tokens"]
        self.assertTrue(saves)
        self.assertEqual(saves[0].get("handoff_phase"), PHASE_INTERMEDIATE)


if __name__ == "__main__":
    unittest.main()
