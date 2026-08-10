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
    ABORTED_S3_SIBLING_PROBE_NOT_RENDERED,
    build_setup_readiness_table,
    classify_setup_failure,
    r3_classification_allowed,
    setup_ready_for_sibling_click,
)


class SetupLocalizeTests(unittest.TestCase):
    def test_pause_not_ready(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": False},
            sibling_scrape={"probe_found": True},
            s3_ledger_scrape={"found": True},
            post_registration={"registered_widget_id": "$$ID-x"},
            binding={"sessionstate_binding_ok": True},
        )
        self.assertEqual(case, ABORTED_S3_CONTROL_CENTER_NOT_READY)

    def test_sibling_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_scrape={"probe_found": False},
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_PROBE_NOT_RENDERED)

    def test_ledger_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_scrape={"probe_found": True},
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_LEDGER_EMIT_MISSING)

    def test_post_reg_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_scrape={"probe_found": True},
            s3_ledger_scrape={"found": True},
            post_registration={},
            binding={"sessionstate_binding_ok": True},
        )
        self.assertEqual(case, ABORTED_S3_POST_REGISTRATION_NOT_READY)

    def test_binding_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_scrape={"probe_found": True},
            s3_ledger_scrape={"found": True},
            post_registration={"registered_widget_id": "$$ID-abc"},
            binding={"sessionstate_binding_ok": False},
        )
        self.assertEqual(case, ABORTED_S3_DIAG_BINDING_NOT_READY)

    def test_setup_pass_allows_click(self) -> None:
        table = build_setup_readiness_table(
            runtime_sha="405b0fa",
            auth_restored=True,
            start_latch_pass=True,
            room_id="ROOM01",
            streamlit_session_id="sid-1",
            pause_control_ready=True,
            sibling_probe_found=True,
            s3_ledger_found=True,
            post_registration_ready=True,
            binding_ok=True,
        )
        self.assertTrue(setup_ready_for_sibling_click(table))
        case, note = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_scrape={"probe_found": True},
            s3_ledger_scrape={"found": True},
            post_registration={"registered_widget_id": "$$ID-abc"},
            binding={"sessionstate_binding_ok": True},
        )
        self.assertIsNone(case)
        self.assertEqual(note, "setup_pass")

    def test_r3_blocked_on_aborted(self) -> None:
        self.assertFalse(r3_classification_allowed("ABORTED_S3_LEDGER_EMIT_MISSING"))
        self.assertTrue(r3_classification_allowed("BUTTON_DISPATCH_S3_R3A_DROPPED_IN_APPSESSION_BACKMSG_PATH"))


if __name__ == "__main__":
    unittest.main()
