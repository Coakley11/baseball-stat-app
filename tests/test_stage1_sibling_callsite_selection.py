"""Callsite candidate selection and import-evidence consistency tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_sibling_setup_scrape import (  # noqa: E402
    finalize_sibling_import_evidence,
    merge_layers_from_dom_dict,
    select_authoritative_callsite,
)
from stage1_s3_setup_localize import (  # noqa: E402
    ABORTED_S3_SETUP_EVIDENCE_CONTRADICTION,
    ABORTED_S3_SIBLING_IMPORT_FAILED,
    classify_setup_failure,
    setup_ready_for_sibling_click,
    build_setup_readiness_table,
)


def _cand(dom_index: int, *, attempted: bool, ok: bool | None, ts: float) -> dict:
    return {
        "dom_index": dom_index,
        "import_attempted_attr": "1" if attempted else "0",
        "import_ok_attr": "" if ok is None else ("1" if ok else "0"),
        "json": {
            "import_attempted": attempted,
            "import_ok": ok,
            "ts": ts,
            "room_id": "7E43FBC9",
            "streamlit_session_id": "fd064582-d931-48c4-aebf-12452d9422ca",
            "full_app_run_seq": 12,
            "thread_fragment_id": "frag1",
        },
    }


class CallsiteSelectionTests(unittest.TestCase):
    def test_pre_then_post_success_selects_post(self) -> None:
        sel = select_authoritative_callsite([_cand(0, attempted=False, ok=None, ts=1.0), _cand(1, attempted=True, ok=True, ts=2.0)])
        self.assertEqual(sel["selected_callsite_index"], 1)
        self.assertTrue(sel["sibling_import_ok_direct"])

    def test_newest_post_import_ts(self) -> None:
        sel = select_authoritative_callsite(
            [
                _cand(0, attempted=True, ok=True, ts=1.0),
                _cand(1, attempted=True, ok=False, ts=3.0),
                _cand(2, attempted=True, ok=True, ts=3.0),
            ]
        )
        self.assertIn(sel["selected_callsite_index"], (1, 2))
        self.assertEqual(sel["selected_callsite_index"], 2)

    def test_ts_tie_prefers_last_dom(self) -> None:
        sel = select_authoritative_callsite([_cand(0, attempted=True, ok=True, ts=5.0), _cand(1, attempted=True, ok=True, ts=5.0)])
        self.assertEqual(sel["selected_callsite_index"], 1)

    def test_pre_import_only_unknown(self) -> None:
        sel = select_authoritative_callsite([_cand(0, attempted=False, ok=None, ts=1.0)])
        self.assertIsNone(sel["sibling_import_ok_direct"])


class ImportEvidenceTests(unittest.TestCase):
    def test_explicit_import_false_fails_without_entry(self) -> None:
        layers = {
            "sibling_callsite_found": True,
            "sibling_import_ok_direct": False,
            "import_effective_ok": False,
            "sibling_entry_found": False,
            "import_evidence_consistent": True,
        }
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=layers,
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_IMPORT_FAILED)

    def test_import_null_entry_true_effective_success(self) -> None:
        raw = {
            "callsite_count": 2,
            "callsite_candidates_raw": [_cand(0, attempted=False, ok=None, ts=1.0), _cand(1, attempted=True, ok=True, ts=2.0)],
            "sibling_callsite_found": True,
            "sibling_entry_found": True,
            "sibling_button_found": True,
            "sibling_ledger_found": True,
            "entry_json": {"solo_diag_enabled_final": True},
            "declaration_candidates": [
                {
                    "dom_index": 0,
                    "data_event": "SIBLING_BUTTON_DECLARATION_ENTRY",
                    "declaration_reached": "1",
                    "json": {"event": "SIBLING_BUTTON_DECLARATION_ENTRY", "declaration_reached": True, "ts": 1.0},
                },
                {
                    "dom_index": 1,
                    "data_event": "SIBLING_BUTTON_DECLARATION_RESULT",
                    "declaration_reached": "1",
                    "json": {
                        "event": "SIBLING_BUTTON_DECLARATION_RESULT",
                        "declaration_reached": True,
                        "returned_value": False,
                        "ts": 2.0,
                    },
                },
            ],
            "setup_checkpoint_candidates": [
                {
                    "dom_index": 0,
                    "data_event": "SIBLING_BUTTON_CALL_RETURNED",
                    "json": {"event": "SIBLING_BUTTON_CALL_RETURNED", "ts": 2.1},
                },
                {
                    "dom_index": 1,
                    "data_event": "SIBLING_POST_REGISTRATION_RETURNED",
                    "json": {"event": "SIBLING_POST_REGISTRATION_RETURNED", "ts": 2.2},
                },
                {
                    "dom_index": 2,
                    "data_event": "SIBLING_SETUP_EXPORT_COMPLETE",
                    "json": {"event": "SIBLING_SETUP_EXPORT_COMPLETE", "ts": 2.3},
                },
            ],
        }
        layers = merge_layers_from_dom_dict(raw)
        layers = finalize_sibling_import_evidence(layers, s3_ledger_found=True, post_registration_ready=True, binding_ok=True)
        self.assertTrue(layers["import_effective_ok"])
        case, note = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=layers,
            s3_ledger_scrape={
                "found": True,
                "parse_ok": True,
                "payload": {
                    "post_registration": {"registered_widget_id": "$$ID-abc"},
                    "s3_diag_binding": {"sessionstate_binding_ok": True, "server_wrapper_integrity_ok": True},
                },
            },
            post_registration={"registered_widget_id": "$$ID-abc"},
            binding={"sessionstate_binding_ok": True, "server_wrapper_integrity_ok": True},
        )
        self.assertIsNone(case)
        self.assertEqual(note, "setup_pass")

    def test_import_false_with_entry_contradiction(self) -> None:
        layers = finalize_sibling_import_evidence(
            {
                "sibling_callsite_found": True,
                "sibling_import_ok_direct": False,
                "sibling_entry_found": True,
                "sibling_button_found": True,
                "sibling_ledger_found": True,
                "sibling_diag_enabled": True,
            },
            s3_ledger_found=True,
            post_registration_ready=True,
            binding_ok=True,
        )
        self.assertFalse(layers["import_evidence_consistent"])
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=layers,
            s3_ledger_scrape={"found": True},
            post_registration={"registered_widget_id": "$$ID-x"},
            binding={"sessionstate_binding_ok": True},
        )
        self.assertEqual(case, ABORTED_S3_SETUP_EVIDENCE_CONTRADICTION)

    def test_production_false_abort_shape_now_passes_setup(self) -> None:
        """Room 7E43FBC9 shape: pre-import first node + full downstream surfaces."""
        raw = {
            "callsite_count": 2,
            "callsite_candidates_raw": [
                _cand(0, attempted=False, ok=None, ts=1786327538.515),
                _cand(1, attempted=True, ok=True, ts=1786327538.52),
            ],
            "sibling_callsite_found": True,
            "sibling_entry_found": True,
            "sibling_button_found": True,
            "sibling_ledger_found": True,
            "entry_json": {"solo_diag_enabled_final": True, "solo_component_diag_raw": "1"},
            "declaration_candidates": [
                {
                    "dom_index": 0,
                    "data_event": "SIBLING_BUTTON_DECLARATION_ENTRY",
                    "declaration_reached": "1",
                    "json": {"event": "SIBLING_BUTTON_DECLARATION_ENTRY", "declaration_reached": True, "ts": 1.0},
                },
                {
                    "dom_index": 1,
                    "data_event": "SIBLING_BUTTON_DECLARATION_RESULT",
                    "declaration_reached": "1",
                    "json": {
                        "event": "SIBLING_BUTTON_DECLARATION_RESULT",
                        "declaration_reached": True,
                        "returned_value": False,
                        "ts": 2.0,
                    },
                },
            ],
            "setup_checkpoint_candidates": [
                {
                    "dom_index": 0,
                    "data_event": "SIBLING_BUTTON_CALL_RETURNED",
                    "json": {"event": "SIBLING_BUTTON_CALL_RETURNED", "ts": 2.1},
                },
                {
                    "dom_index": 1,
                    "data_event": "SIBLING_POST_REGISTRATION_RETURNED",
                    "json": {"event": "SIBLING_POST_REGISTRATION_RETURNED", "ts": 2.2},
                },
                {
                    "dom_index": 2,
                    "data_event": "SIBLING_SETUP_EXPORT_COMPLETE",
                    "json": {"event": "SIBLING_SETUP_EXPORT_COMPLETE", "ts": 2.3},
                },
            ],
        }
        layers = finalize_sibling_import_evidence(
            merge_layers_from_dom_dict(raw),
            s3_ledger_found=True,
            post_registration_ready=True,
            binding_ok=True,
        )
        table = build_setup_readiness_table(
            runtime_sha="dd04cd8",
            auth_restored=True,
            start_latch_pass=True,
            room_id="7E43FBC9",
            streamlit_session_id="fd064582-d931-48c4-aebf-12452d9422ca",
            pause_control_ready=True,
            sibling_layers=layers,
            s3_ledger_found=True,
            post_registration_ready=True,
            binding_ok=True,
            server_wrapper_integrity_ok=True,
        )
        self.assertTrue(setup_ready_for_sibling_click(table))


if __name__ == "__main__":
    unittest.main()
