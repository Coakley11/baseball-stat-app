"""Tests for sibling setup stabilization waiter (harness-only)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_setup_localize import (  # noqa: E402
    ABORTED_S3_LEDGER_EMIT_MISSING,
    ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION,
    ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING,
    classify_setup_failure,
)
from stage1_sibling_setup_scrape import SIBLING_BUTTON_LABEL  # noqa: E402
from stage1_sibling_setup_stable import (  # noqa: E402
    _poll_setup_once,
    _room_aligned,
    wait_for_sibling_setup_stable,
)


def _pass_layers(**kw: object) -> dict:
    base = {
        "sibling_callsite_found": True,
        "sibling_import_ok": True,
        "import_effective_ok": True,
        "import_evidence_consistent": True,
        "sibling_entry_found": True,
        "sibling_diag_enabled": True,
        "sibling_button_found": True,
        "sibling_ledger_found": True,
        "sibling_pre_button_reached": True,
        "sibling_post_button_return_reached": True,
        "sibling_button_call_returned_reached": True,
        "sibling_post_registration_returned_reached": True,
        "sibling_setup_export_complete_reached": True,
        "declaration_post_json": {"room_id": "ROOM01", "full_app_run_seq": 9},
    }
    base.update(kw)
    return base


def _snap(*, layers: dict, s3_found: bool = True, post_id: str = "$$ID-abc", binding_ok: bool = True) -> dict:
    return {
        "atomic_presence": {
            "pre_declaration_present": True,
            "post_declaration_present": True,
            "sibling_button_present": True,
            "sibling_ledger_present": layers.get("sibling_ledger_found", False),
            "s3_ledger_present": s3_found,
            "room_id": "ROOM01",
            "full_app_run_seq": 9,
        },
        "sibling_setup_layers": layers,
        "sibling_probe_scrape": {"streamlit_session_id": "sid-1"},
        "s3_ledger_scrape": {"found": s3_found, "payload": {}},
        "post_registration": {"registered_widget_id": post_id},
        "s3_diag_binding": {"sessionstate_binding_ok": binding_ok, "server_wrapper_integrity_ok": True},
        "pre_declaration": {},
        "post_registration_ready": post_id.startswith("$$ID-"),
        "binding_ok": binding_ok,
        "streamlit_session_id": "sid-1",
        "full_app_run_seq": 9,
        "room_aligned": True,
    }


class SiblingSetupStableTests(unittest.TestCase):
    def test_first_poll_missing_ledgers_second_poll_pass(self) -> None:
        page = MagicMock()
        miss = _snap(layers=_pass_layers(sibling_ledger_found=False), s3_found=False, post_id="", binding_ok=False)
        miss["post_registration_ready"] = False
        miss["binding_ok"] = False
        hit = _snap(layers=_pass_layers())
        with patch("stage1_sibling_setup_stable._poll_setup_once", side_effect=[miss, hit]):
            with patch("stage1_sibling_setup_stable.resolve_streamlit_app_frame", return_value=MagicMock()):
                out = wait_for_sibling_setup_stable(
                    page,
                    room_id="ROOM01",
                    pause_ready={"ready": True},
                    runtime_sha="5bb568b",
                    auth_restored=True,
                    start_latch_pass=True,
                    max_wait_s=5.0,
                    poll_interval_ms=1,
                )
        self.assertTrue(out["ok"])
        self.assertEqual(out["poll_count"], 2)
        page.wait_for_timeout.assert_called()

    def test_transient_missing_then_coherent_no_abort(self) -> None:
        page = MagicMock()
        transient = _snap(layers=_pass_layers(sibling_ledger_found=False), s3_found=False)
        transient["s3_ledger_scrape"] = {"found": False}
        ok = _snap(layers=_pass_layers())
        with patch("stage1_sibling_setup_stable._poll_setup_once", side_effect=[transient, transient, ok]):
            with patch("stage1_sibling_setup_stable.resolve_streamlit_app_frame", return_value=MagicMock()):
                out = wait_for_sibling_setup_stable(
                    page,
                    room_id="ROOM01",
                    pause_ready={"ready": True},
                    runtime_sha="5bb568b",
                    auth_restored=True,
                    start_latch_pass=True,
                    max_wait_s=5.0,
                    poll_interval_ms=1,
                )
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["poll_count"], 3)

    def test_ledger_missing_through_timeout_sibling_abort(self) -> None:
        page = MagicMock()
        stuck = _snap(
            layers=_pass_layers(sibling_ledger_found=False, sibling_post_button_return_reached=True),
            s3_found=False,
            post_id="",
            binding_ok=False,
        )
        stuck["post_registration_ready"] = False
        with patch("stage1_sibling_setup_stable._poll_setup_once", return_value=stuck):
            with patch("stage1_sibling_setup_stable.resolve_streamlit_app_frame", return_value=MagicMock()):
                with patch("stage1_sibling_setup_stable.time") as tmock:
                    tmock.time.side_effect = [0.0, 0.5, 46.0] * 20
                    out = wait_for_sibling_setup_stable(
                        page,
                        room_id="ROOM01",
                        pause_ready={"ready": True},
                        runtime_sha="5bb568b",
                        auth_restored=True,
                        start_latch_pass=True,
                        max_wait_s=45.0,
                        poll_interval_ms=1,
                    )
        self.assertFalse(out["ok"])
        self.assertTrue(out["timed_out"])
        self.assertEqual(out["setup_abort"], ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING)
        self.assertEqual(
            out["setup_note"],
            "sibling_hidden_ledger_persistently_missing_after_setup_stabilization",
        )

    def test_sibling_ledger_present_s3_missing_timeout(self) -> None:
        page = MagicMock()
        stuck = _snap(layers=_pass_layers(sibling_ledger_found=True), s3_found=False, post_id="$$ID-x")
        with patch("stage1_sibling_setup_stable._poll_setup_once", return_value=stuck):
            with patch("stage1_sibling_setup_stable.resolve_streamlit_app_frame", return_value=MagicMock()):
                with patch("stage1_sibling_setup_stable.time") as tmock:
                    tmock.time.side_effect = [0.0, 0.5, 46.0] * 20
                    out = wait_for_sibling_setup_stable(
                        page,
                        room_id="ROOM01",
                        pause_ready={"ready": True},
                        runtime_sha="5bb568b",
                        auth_restored=True,
                        start_latch_pass=True,
                        max_wait_s=45.0,
                        poll_interval_ms=1,
                    )
        self.assertEqual(out["setup_abort"], ABORTED_S3_LEDGER_EMIT_MISSING)
        self.assertEqual(out["setup_note"], "s3_ledger_persistently_missing_after_setup_stabilization")

    def test_room_mismatch_not_coherent(self) -> None:
        layers = _pass_layers(declaration_post_json={"room_id": "OTHER", "full_app_run_seq": 9})
        self.assertFalse(_room_aligned("ROOM01", layers, {"room_id": "OTHER"}))

    def test_different_run_sequences_in_history_not_merged(self) -> None:
        page = MagicMock()
        seq8 = _snap(
            layers=_pass_layers(
                sibling_ledger_found=False,
                declaration_post_json={"room_id": "ROOM01", "full_app_run_seq": 8},
            ),
            s3_found=False,
            post_id="",
            binding_ok=False,
        )
        seq8["full_app_run_seq"] = 8
        seq8["post_registration_ready"] = False
        seq9 = _snap(layers=_pass_layers(declaration_post_json={"room_id": "ROOM01", "full_app_run_seq": 9}))
        seq9["full_app_run_seq"] = 9
        with patch("stage1_sibling_setup_stable._poll_setup_once", side_effect=[seq8, seq9]):
            with patch("stage1_sibling_setup_stable.resolve_streamlit_app_frame", return_value=MagicMock()):
                out = wait_for_sibling_setup_stable(
                    page,
                    room_id="ROOM01",
                    pause_ready={"ready": True},
                    runtime_sha="5bb568b",
                    auth_restored=True,
                    start_latch_pass=True,
                    max_wait_s=5.0,
                    poll_interval_ms=1,
                )
        self.assertTrue(out["ok"])
        seqs = [r.get("full_app_run_seq") for r in out["poll_history"]]
        self.assertEqual(seqs, [8, 9])

    def test_button_exception_immediate_abort(self) -> None:
        page = MagicMock()
        bad = _snap(
            layers=_pass_layers(
                checkpoint_sibling_button_call_exception={"event": "SIBLING_BUTTON_CALL_EXCEPTION"},
            )
        )
        with patch("stage1_sibling_setup_stable._poll_setup_once", return_value=bad):
            with patch("stage1_sibling_setup_stable.resolve_streamlit_app_frame", return_value=MagicMock()):
                out = wait_for_sibling_setup_stable(
                    page,
                    room_id="ROOM01",
                    pause_ready={"ready": True},
                    runtime_sha="5bb568b",
                    auth_restored=True,
                    start_latch_pass=True,
                    max_wait_s=45.0,
                    poll_interval_ms=1,
                )
        self.assertTrue(out["early_abort"])
        self.assertEqual(out["setup_abort"], ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION)
        self.assertEqual(out["poll_count"], 1)

    def test_exact_button_label_constant(self) -> None:
        self.assertEqual(SIBLING_BUTTON_LABEL, "Stage1 Pause-Sibling Return Probe")

    def test_no_click_during_polling(self) -> None:
        page = MagicMock()
        ok = _snap(layers=_pass_layers())
        with patch("stage1_sibling_setup_stable._poll_setup_once", return_value=ok):
            with patch("stage1_sibling_setup_stable.resolve_streamlit_app_frame", return_value=MagicMock()):
                wait_for_sibling_setup_stable(
                    page,
                    room_id="ROOM01",
                    pause_ready={"ready": True},
                    runtime_sha="5bb568b",
                    auth_restored=True,
                    start_latch_pass=True,
                    max_wait_s=1.0,
                    poll_interval_ms=1,
                )
        self.assertFalse(page.click.called)

    def test_gate_imports_same_stabilization_helper(self) -> None:
        gate_path = SCRIPTS / "run_production_bridge_s3_server_registry_gate.py"
        text = gate_path.read_text(encoding="utf-8")
        self.assertIn("wait_for_sibling_setup_stable", text)
        self.assertNotIn("scrape_sibling_setup_layers(page, frame=frame)", text)

    def test_classify_after_stabilization_note_distinct_from_single_scrape(self) -> None:
        layers = _pass_layers(sibling_ledger_found=False)
        case, note = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=layers,
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
            after_stabilization=True,
        )
        self.assertEqual(case, ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING)
        self.assertIn("persistently_missing", note)
        _, immediate = classify_setup_failure(
            pause_ready={"ready": True},
            sibling_layers=layers,
            s3_ledger_scrape={"found": False},
            post_registration={},
            binding={},
            after_stabilization=False,
        )
        self.assertIn("after_post_declaration", immediate)


if __name__ == "__main__":
    unittest.main()
