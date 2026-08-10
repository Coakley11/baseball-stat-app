"""Harness setup localization tests for S3 production gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_setup_localize import (  # noqa: E402
    ABORTED_S3_CONTROL_CENTER_NOT_READY,
    ABORTED_S3_DIAG_BINDING_NOT_READY,
    ABORTED_S3_LEDGER_EMIT_MISSING,
    ABORTED_S3_POST_REGISTRATION_NOT_READY,
    ABORTED_S3_SIBLING_BUTTON_CALL_NOT_RETURNED,
    ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED,
    ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED,
    ABORTED_S3_SIBLING_DIAG_DISABLED,
    ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED,
    ABORTED_S3_SIBLING_IMPORT_FAILED,
    ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING,
    ABORTED_S3_SIBLING_PROBE_NOT_RENDERED,
    build_setup_readiness_table,
    classify_setup_failure,
    classify_setup_failure_legacy_probe,
    r3_classification_allowed,
    setup_ready_for_sibling_click,
)


def _s3_scrape(*, post: dict | None = None, binding: dict | None = None, found: bool = True) -> dict:
    return {
        "found": found,
        "parse_ok": True,
        "payload": {
            "post_registration": post if post is not None else {"registered_widget_id": "$$ID-abc"},
            "s3_diag_binding": binding
            if binding is not None
            else {"sessionstate_binding_ok": True, "server_wrapper_integrity_ok": True},
        },
    }


def _layers(**kw: object) -> dict:
    base = {
        "sibling_callsite_found": True,
        "sibling_import_ok": True,
        "sibling_import_ok_direct": True,
        "import_effective_ok": True,
        "import_evidence_consistent": True,
        "sibling_entry_found": True,
        "sibling_diag_enabled": True,
        "sibling_button_found": True,
        "sibling_ledger_found": True,
        "sibling_declaration_reached": True,
        "sibling_pre_button_reached": True,
        "sibling_post_button_return_reached": True,
        "sibling_button_call_returned_reached": True,
        "sibling_post_registration_returned_reached": True,
        "sibling_setup_export_complete_reached": True,
    }
    base.update(kw)
    return base


class SetupLocalizeTests(unittest.TestCase):
    def test_pause_not_ready(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": False},
            sibling_layers=_layers(),
            s3_ledger_scrape={"found": True},
            post_registration={"registered_widget_id": "$$ID-x"},
            binding={"sessionstate_binding_ok": True},
        )
        self.assertEqual(case, ABORTED_S3_CONTROL_CENTER_NOT_READY)

    def test_callsite_not_reached(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(sibling_callsite_found=False),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED)

    def test_import_failed(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(
                sibling_import_ok_direct=False,
                import_effective_ok=False,
                sibling_import_ok=False,
                sibling_entry_found=False,
            ),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_IMPORT_FAILED)

    def test_function_not_entered(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(sibling_entry_found=False),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED)

    def test_diag_disabled(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(sibling_diag_enabled=False),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_DIAG_DISABLED)

    def test_button_not_mounted(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(
                sibling_button_found=False,
                sibling_button_call_returned_reached=False,
                sibling_post_registration_returned_reached=False,
                sibling_post_button_return_reached=False,
            ),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_BUTTON_CALL_NOT_RETURNED)

    def test_sibling_ledger_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(sibling_ledger_found=False),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING)

    def test_s3_ledger_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_LEDGER_EMIT_MISSING)

    def test_post_reg_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(),
            s3_ledger_scrape=_s3_scrape(post={}),
            post_registration={},
            binding={"sessionstate_binding_ok": True},
        )
        self.assertEqual(case, ABORTED_S3_POST_REGISTRATION_NOT_READY)

    def test_binding_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=_layers(),
            s3_ledger_scrape=_s3_scrape(binding={"sessionstate_binding_ok": False}),
            post_registration={"registered_widget_id": "$$ID-abc"},
            binding={"sessionstate_binding_ok": False},
        )
        self.assertEqual(case, ABORTED_S3_DIAG_BINDING_NOT_READY)

    def test_setup_pass_allows_click(self) -> None:
        layers = _layers()
        table = build_setup_readiness_table(
            runtime_sha="abc1234",
            auth_restored=True,
            start_latch_pass=True,
            room_id="ROOM01",
            streamlit_session_id="sid-1",
            pause_control_ready=True,
            sibling_layers=layers,
            s3_ledger_found=True,
            post_registration_ready=True,
            binding_ok=True,
            server_wrapper_integrity_ok=True,
        )
        self.assertTrue(setup_ready_for_sibling_click(table))
        case, note = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=layers,
            s3_ledger_scrape=_s3_scrape(),
            post_registration={"registered_widget_id": "$$ID-abc"},
            binding={"sessionstate_binding_ok": True, "server_wrapper_integrity_ok": True},
        )
        self.assertIsNone(case)
        self.assertEqual(note, "setup_pass")

    def test_legacy_coarse_probe_label(self) -> None:
        case, _ = classify_setup_failure_legacy_probe(
            pause_ready={"ready": True},
            sibling_scrape={"probe_found": False},
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_PROBE_NOT_RENDERED)

    def test_r3_blocked_before_setup_pass(self) -> None:
        for label in (
            ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED,
            ABORTED_S3_SIBLING_DIAG_DISABLED,
            ABORTED_S3_LEDGER_EMIT_MISSING,
            "ABORTED_START_LATCH",
        ):
            self.assertFalse(r3_classification_allowed(label))
        self.assertTrue(r3_classification_allowed("BUTTON_DISPATCH_S3_R3A_DROPPED_IN_APPSESSION_BACKMSG_PATH"))


if __name__ == "__main__":
    unittest.main()
