"""Sibling declaration scrape selection and setup localization boundaries."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_sibling_setup_scrape import (  # noqa: E402
    DECL_POST_EVENT,
    DECL_PRE_EVENT,
    merge_layers_from_dom_dict,
    select_authoritative_declaration,
)
from stage1_s3_setup_localize import (  # noqa: E402
    ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION,
    ABORTED_S3_SIBLING_BUTTON_CALL_NOT_RETURNED,
    ABORTED_S3_SIBLING_BUTTON_DOM_MISMATCH,
    ABORTED_S3_SIBLING_POST_REGISTRATION_NOT_REACHED,
    classify_setup_failure,
)


def _decl(dom_index: int, event: str, *, ts: float, extra: dict | None = None) -> dict:
    payload = {
        "event": event,
        "ts": ts,
        "room_id": "36851FAF",
        "widget_key": "stage1_pause_sibling_return_36851FAF_diag",
        "declaration_reached": True,
    }
    if extra:
        payload.update(extra)
    return {
        "dom_index": dom_index,
        "data_event": event,
        "declaration_reached": "1",
        "json": payload,
    }


class DeclarationScrapeTests(unittest.TestCase):
    def test_duplicate_pre_post_both_selected_by_event(self) -> None:
        raw = [
            _decl(0, DECL_PRE_EVENT, ts=1.0),
            _decl(1, DECL_POST_EVENT, ts=2.0, extra={"returned_value": False, "registered_widget_id": "$$ID-x"}),
        ]
        pre = select_authoritative_declaration(raw, event=DECL_PRE_EVENT)
        post = select_authoritative_declaration(raw, event=DECL_POST_EVENT)
        self.assertEqual(pre.get("dom_index"), 0)
        self.assertEqual(post.get("dom_index"), 1)
        layers = merge_layers_from_dom_dict(
            {
                "callsite_candidates_raw": [],
                "callsite_count": 0,
                "declaration_candidates": raw,
                "setup_checkpoint_candidates": [],
                "button_inventory": [],
                "sibling_entry_found": True,
                "sibling_diag_enabled_attr": "1",
                "sibling_button_found": False,
                "sibling_ledger_found": False,
                "sibling_callsite_found": True,
            }
        )
        self.assertTrue(layers["sibling_pre_button_reached"])
        self.assertTrue(layers["sibling_post_button_return_reached"])
        self.assertIs(layers["sibling_post_button_return_value"], False)
        self.assertEqual(layers["declaration_json"]["event"], DECL_PRE_EVENT)
        self.assertEqual(layers["declaration_post_json"]["event"], DECL_POST_EVENT)

    def test_pre_only_not_post(self) -> None:
        raw = [_decl(0, DECL_PRE_EVENT, ts=1.0)]
        layers = merge_layers_from_dom_dict(
            {
                "callsite_candidates_raw": [],
                "callsite_count": 0,
                "declaration_candidates": raw,
                "setup_checkpoint_candidates": [],
                "button_inventory": [],
                "sibling_entry_found": True,
                "sibling_diag_enabled_attr": "1",
                "sibling_button_found": False,
                "sibling_callsite_found": True,
            }
        )
        self.assertTrue(layers["sibling_pre_button_reached"])
        self.assertFalse(layers["sibling_post_button_return_reached"])

    def test_pre_post_use_distinct_dom_id_selectors(self) -> None:
        from live_draft_stage1_pause_sibling_probe import (
            PAUSE_SIBLING_DECL_POST_DOM_ID,
            PAUSE_SIBLING_DECL_PRE_DOM_ID,
        )

        src = (
            Path(__file__).resolve().parent.parent.joinpath("live_draft_stage1_pause_sibling_probe.py").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(PAUSE_SIBLING_DECL_PRE_DOM_ID, src)
        self.assertIn(PAUSE_SIBLING_DECL_POST_DOM_ID, src)
        self.assertIn("PAUSE_SIBLING_DECL_PRE_DOM_ID", src)
        self.assertIn("PAUSE_SIBLING_DECL_POST_DOM_ID", src)

    def test_button_inventory_candidates(self) -> None:
        inv = [
            {"index": 0, "normalized_text": "Pause", "exact_label_match": False, "contains_pause_sibling": False},
            {
                "index": 1,
                "normalized_text": "Stage1 Pause-Sibling Return Probe",
                "exact_label_match": True,
                "contains_pause_sibling": True,
                "contains_stage1": True,
            },
        ]
        layers = merge_layers_from_dom_dict(
            {
                "callsite_candidates_raw": [],
                "callsite_count": 0,
                "declaration_candidates": [],
                "setup_checkpoint_candidates": [],
                "button_inventory": inv,
                "sibling_entry_found": True,
                "sibling_diag_enabled_attr": "1",
                "sibling_button_found": True,
                "sibling_callsite_found": True,
            }
        )
        self.assertEqual(len(layers["button_candidates_exact"]), 1)
        self.assertEqual(len(layers["button_candidates_contains_pause_sibling"]), 1)


class SetupSubclassTests(unittest.TestCase):
    def _base_layers(self, **kw: object) -> dict:
        base = {
            "sibling_callsite_found": True,
            "sibling_import_ok": True,
            "sibling_import_ok_direct": True,
            "import_effective_ok": True,
            "import_evidence_consistent": True,
            "sibling_entry_found": True,
            "sibling_diag_enabled": True,
            "sibling_pre_button_reached": True,
            "sibling_button_found": False,
            "sibling_ledger_found": False,
            "sibling_declaration_reached": True,
        }
        base.update(kw)
        return base

    def test_pre_no_button_return_checkpoint(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=self._base_layers(sibling_button_call_returned_reached=False),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_BUTTON_CALL_NOT_RETURNED)

    def test_button_call_exception(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=self._base_layers(
                checkpoint_sibling_button_call_exception={"exception_type": "StreamlitAPIException"}
            ),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION)

    def test_post_registration_missing(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=self._base_layers(
                sibling_button_call_returned_reached=True,
                sibling_post_registration_returned_reached=False,
            ),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_POST_REGISTRATION_NOT_REACHED)

    def test_dom_mismatch_after_post_registration(self) -> None:
        case, _ = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=self._base_layers(
                sibling_button_call_returned_reached=True,
                sibling_post_registration_returned_reached=True,
                sibling_post_button_return_reached=True,
            ),
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_BUTTON_DOM_MISMATCH)


if __name__ == "__main__":
    unittest.main()
