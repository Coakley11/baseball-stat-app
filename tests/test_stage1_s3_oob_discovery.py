"""Harness OOB discovery repair tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_oob_readback import (  # noqa: E402
    fetch_oob_snapshot_via_page,
    resolve_oob_channel,
    run_oob_discovery_pipeline,
    select_valid_readiness_candidate,
    validate_oob_channel_identity,
    validate_oob_snapshot_identity,
)
from stage1_s3_r3_observability_classify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
    classify_s3_with_observability,
)
from stage1_s3_r2_subclassify import BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED  # noqa: E402
from stage1_s3_server_registry_scrape import scrape_s3_server_diag_readiness  # noqa: E402


SID = "f85354f6-f82d-4f3f-8450-193b44296ce7"
TOKEN = "502c4959955b4810"
PATH = f"/app/static/s3_oob/{TOKEN}.json"


def _readiness_candidate(
    *,
    dom_index: int,
    sid: str,
    registered: bool,
    token: str = "",
    path: str = "",
    parse_ok: bool = True,
) -> dict:
    payload = {
        "streamlit_session_id": sid,
        "oob_channel": {
            "registered": registered,
            "diagnostic_token": token,
            "static_url_path": path,
            "snapshot_generation": 1 if registered and token else None,
            "published": bool(registered and token),
        },
    }
    return {
        "dom_index": dom_index,
        "parse_ok": parse_ok,
        "streamlit_session_id": sid,
        "payload": payload if parse_ok else None,
        "oob_channel_registered": registered,
        "diagnostic_token": token,
        "static_url_path": path,
    }


def _ledger_event(*, sid: str = SID, token: str = TOKEN, path: str = PATH, ts: float = 2.0) -> dict:
    return {
        "event_id": f"evt-{int(ts)}",
        "phase": "S3_OOB_CHANNEL_REGISTERED",
        "streamlit_session_id": sid,
        "diagnostic_token": token,
        "static_url_path": path,
        "registered": True,
        "published": True,
        "snapshot_generation": 1,
        "publish_source": "initial_pre_click",
        "ts": ts,
    }


class OobDiscoveryRepairTests(unittest.TestCase):
    def test_first_stale_second_valid_selects_valid(self) -> None:
        candidates = [
            _readiness_candidate(dom_index=0, sid=SID, registered=False),
            _readiness_candidate(dom_index=1, sid=SID, registered=True, token=TOKEN, path=PATH),
        ]
        selected, reason = select_valid_readiness_candidate(candidates, expected_streamlit_sid=SID)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected["dom_index"], 1)
        self.assertIn("valid", reason)

    def test_multiple_valid_candidates_preserve_inventory_and_select_last(self) -> None:
        candidates = [
            _readiness_candidate(dom_index=0, sid=SID, registered=True, token="aaa", path="/app/static/s3_oob/aaa.json"),
            _readiness_candidate(dom_index=1, sid=SID, registered=True, token=TOKEN, path=PATH),
        ]
        resolution = resolve_oob_channel(
            readiness_scrape={"candidates": candidates, "candidate_count": 2},
            ledger_scrape={},
            expected_streamlit_sid=SID,
        )
        self.assertEqual(len(resolution["readiness_candidates"]), 2)
        self.assertEqual(resolution["discovery_source"], "readiness_candidate")
        self.assertEqual(resolution["resolved_channel"]["diagnostic_token"], TOKEN)

    def test_ledger_fallback_when_readiness_stale(self) -> None:
        readiness = {
            "candidate_count": 1,
            "candidates": [_readiness_candidate(dom_index=0, sid=SID, registered=False)],
        }
        ledger = {"payload": {"ledger": {"module_rows": [_ledger_event()]}}}
        resolution = resolve_oob_channel(
            readiness_scrape=readiness,
            ledger_scrape=ledger,
            expected_streamlit_sid=SID,
        )
        self.assertEqual(resolution["discovery_source"], "ledger_s3_oob_channel_registered")
        self.assertEqual(resolution["resolved_channel"]["diagnostic_token"], TOKEN)

    def test_ledger_fallback_requires_matching_sid(self) -> None:
        ledger = {"payload": {"ledger": {"rows": [_ledger_event(sid="other-sid")]}}}
        resolution = resolve_oob_channel(
            readiness_scrape={"candidates": []},
            ledger_scrape=ledger,
            expected_streamlit_sid=SID,
        )
        self.assertEqual(resolution["discovery_source"], "none")

    def test_conflicting_sid_rejected(self) -> None:
        channel = {
            "streamlit_session_id": "other-sid",
            "diagnostic_token": TOKEN,
            "static_url_path": PATH,
            "registered": True,
        }
        ok, note = validate_oob_channel_identity(channel, expected_streamlit_sid=SID)
        self.assertFalse(ok)
        self.assertEqual(note, "oob_channel_sid_mismatch")

    def test_token_path_mismatch_rejected(self) -> None:
        channel = {
            "streamlit_session_id": SID,
            "diagnostic_token": "different-token",
            "static_url_path": PATH,
            "registered": True,
        }
        ok, note = validate_oob_channel_identity(channel, expected_streamlit_sid=SID)
        self.assertFalse(ok)
        self.assertEqual(note, "oob_token_path_mismatch")

    def test_empty_path_does_not_request_http(self) -> None:
        calls: list[str] = []

        class FakeRequest:
            @staticmethod
            def get(url, timeout=0):
                calls.append(url)
                raise AssertionError("should not fetch")

        page = SimpleNamespace(evaluate=lambda _js: "https://example.test", request=FakeRequest())
        out = fetch_oob_snapshot_via_page(page, "")
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "empty_static_url_path")
        self.assertEqual(calls, [])

    def test_http_200_html_is_not_ok(self) -> None:
        class FakeResponse:
            status = 200

            @staticmethod
            def headers():
                return {"content-type": "text/html"}

            @staticmethod
            def text():
                return "<html><body>Streamlit</body></html>"

        class FakeRequest:
            @staticmethod
            def get(url, timeout=0):
                return FakeResponse()

        page = SimpleNamespace(evaluate=lambda _js: "https://example.test", request=FakeRequest())
        out = fetch_oob_snapshot_via_page(page, PATH)
        self.assertTrue(out["http_ok"])
        self.assertFalse(out["parse_ok"])
        self.assertFalse(out["ok"])

    def test_valid_http_json_is_ok(self) -> None:
        class FakeResponse:
            status = 200

            @property
            def headers(self):
                return {"content-type": "application/json"}

            @staticmethod
            def text():
                return json.dumps(
                    {
                        "streamlit_session_id": SID,
                        "diagnostic_token": TOKEN,
                        "snapshot_generation": 1,
                        "publish_source": "initial_pre_click",
                    }
                )

        class FakeRequest:
            @staticmethod
            def get(url, timeout=0):
                return FakeResponse()

        page = SimpleNamespace(evaluate=lambda _js: "https://example.test", request=FakeRequest())
        out = fetch_oob_snapshot_via_page(page, PATH)
        self.assertTrue(out["ok"])
        self.assertTrue(out["parse_ok"])

    def test_snapshot_sid_mismatch_rejected(self) -> None:
        fetch = {"ok": True, "http_ok": True, "parse_ok": True}
        snap = {
            "streamlit_session_id": "other-sid",
            "diagnostic_token": TOKEN,
            "snapshot_generation": 1,
            "publish_source": "initial_pre_click",
        }
        ok, note = validate_oob_snapshot_identity(
            snap, expected_streamlit_sid=SID, expected_token=TOKEN, fetch=fetch
        )
        self.assertFalse(ok)
        self.assertEqual(note, "oob_snapshot_sid_mismatch")

    def test_snapshot_token_mismatch_rejected(self) -> None:
        fetch = {"ok": True, "http_ok": True, "parse_ok": True}
        snap = {
            "streamlit_session_id": SID,
            "diagnostic_token": "other-token",
            "snapshot_generation": 1,
            "publish_source": "initial_pre_click",
        }
        ok, note = validate_oob_snapshot_identity(
            snap, expected_streamlit_sid=SID, expected_token=TOKEN, fetch=fetch
        )
        self.assertFalse(ok)
        self.assertEqual(note, "oob_snapshot_token_mismatch")

    def test_generation_one_initial_snapshot_accepted(self) -> None:
        fetch = {"ok": True, "http_ok": True, "parse_ok": True}
        snap = {
            "streamlit_session_id": SID,
            "diagnostic_token": TOKEN,
            "snapshot_generation": 1,
            "publish_source": "initial_pre_click",
        }
        ok, note = validate_oob_snapshot_identity(
            snap, expected_streamlit_sid=SID, expected_token=TOKEN, fetch=fetch
        )
        self.assertTrue(ok)
        self.assertEqual(note, "")

    def test_oob_setup_only_mode_constant_present(self) -> None:
        gate_src = (SCRIPTS / "run_production_bridge_s3_server_registry_gate.py").read_text(encoding="utf-8")
        self.assertIn("STAGE1_S3_OOB_SETUP_ONLY", gate_src)
        self.assertIn("OOB_CHANNEL_DISCOVERY_PASS", gate_src)
        self.assertIn("oob_channel_ready_for_full_s3_gate", gate_src)

    def test_r3_classifier_unchanged(self) -> None:
        rows = [
            {"phase": "RUNTIME_BACKMSG_ENTRY", "pause_present": True},
            {"phase": "APPSESSION_BACKMSG_ENTRY", "pause_present": True},
            {"phase": "APPSESSION_REQUEST_RERUN_ENTRY", "pause_present": True},
            {"phase": "SAFE_SESSIONSTATE_RECEIVE_ENTRY", "pause_present": True},
            {"phase": "SERVER_RECEIVE_ENTRY", "pause_present": True},
            {"phase": "SERVER_STATE_APPLIED", "pause_present": True, "pause_trigger_from_deserialized": True},
        ]
        case, _, _ = classify_s3_with_observability(
            module_rows=rows,
            authoritative_rows=rows,
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id="$$ID-x",
            sibling_python_effect=False,
            register_widget_result=False,
            st_button_returned=False,
            binding_ok=True,
        )
        self.assertNotEqual(case, BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT)

    def test_r2_classifier_constant_unchanged(self) -> None:
        self.assertEqual(
            BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED,
            "BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED",
        )

    def test_run_oob_discovery_pipeline_uses_ledger_fallback(self) -> None:
        readiness = {"candidates": [_readiness_candidate(dom_index=0, sid=SID, registered=False)]}
        ledger = {"payload": {"ledger": {"merged_rows": [_ledger_event()]}}}

        def fake_fetch(_page, static_url_path, cache_bust=True):
            self.assertEqual(static_url_path, PATH)
            return {
                "ok": True,
                "http_ok": True,
                "parse_ok": True,
                "snapshot_present": True,
                "snapshot": {
                    "streamlit_session_id": SID,
                    "diagnostic_token": TOKEN,
                    "snapshot_generation": 1,
                    "publish_source": "initial_pre_click",
                },
            }

        out = run_oob_discovery_pipeline(
            readiness_scrape=readiness,
            ledger_scrape=ledger,
            expected_streamlit_sid=SID,
            page=object(),
            fetch_fn=fake_fetch,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["discovery_source"], "ledger_s3_oob_channel_registered")

    @patch("stage1_s3_server_registry_scrape.resolve_streamlit_app_frame")
    def test_scrape_readiness_returns_candidate_inventory(self, frame_fn) -> None:
        frame_fn.return_value = SimpleNamespace(
            evaluate=lambda js, sel: {
                "found": True,
                "candidate_count": 2,
                "nodes": [
                    {
                        "dom_index": 0,
                        "json": json.dumps(
                            {
                                "streamlit_session_id": SID,
                                "oob_channel": {"registered": False},
                            }
                        ),
                        "streamlit_session_id": SID,
                    },
                    {
                        "dom_index": 1,
                        "json": json.dumps(
                            {
                                "streamlit_session_id": SID,
                                "oob_channel": {
                                    "registered": True,
                                    "diagnostic_token": TOKEN,
                                    "static_url_path": PATH,
                                },
                            }
                        ),
                        "streamlit_session_id": SID,
                    },
                ],
            }
        )
        page = SimpleNamespace()
        scrape = scrape_s3_server_diag_readiness(page, expected_streamlit_session_id=SID)
        self.assertEqual(scrape["candidate_count"], 2)
        self.assertEqual(len(scrape["candidates"]), 2)
        self.assertEqual(scrape["selected_candidate_index"], 1)


if __name__ == "__main__":
    unittest.main()
