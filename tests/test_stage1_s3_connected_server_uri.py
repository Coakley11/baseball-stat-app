"""Tests for connected Streamlit server URI capture and OOB URL construction."""

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

from stage1_s3_connected_server_uri import (  # noqa: E402
    SOURCE_HEALTH,
    SOURCE_HOST_CONFIG,
    SOURCE_WEBSOCKET_STREAM,
    connected_server_uri_from_stcore_url,
    join_connected_server_static_url,
    resolve_connected_server_uri,
)
from stage1_s3_oob_readback import (  # noqa: E402
    fetch_oob_snapshot_via_page,
    run_oob_discovery_pipeline,
    validate_oob_snapshot_identity,
)
from stage1_s3_r2_subclassify import BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED  # noqa: E402
from stage1_s3_r3_observability_classify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
    BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_UNAVAILABLE,
    classify_oob_channel_unavailable,
    classify_s3_with_observability,
)

SID = "session-abc"
TOKEN = "abc123"
PATH = f"/app/static/s3_oob/{TOKEN}.json"


class ConnectedServerUriExtractionTests(unittest.TestCase):
    def test_root_websocket_to_root_http(self) -> None:
        self.assertEqual(
            connected_server_uri_from_stcore_url("wss://example.test/_stcore/stream"),
            "https://example.test",
        )

    def test_tilde_plus_prefix_preserved(self) -> None:
        self.assertEqual(
            connected_server_uri_from_stcore_url(
                "wss://example.test/~/+/_stcore/stream"
            ),
            "https://example.test/~/+",
        )

    def test_arbitrary_prefix_preserved(self) -> None:
        self.assertEqual(
            connected_server_uri_from_stcore_url(
                "wss://example.test/custom/prefix/_stcore/stream"
            ),
            "https://example.test/custom/prefix",
        )

    def test_ws_to_http(self) -> None:
        self.assertEqual(
            connected_server_uri_from_stcore_url("ws://localhost:8501/_stcore/stream"),
            "http://localhost:8501",
        )

    def test_wss_to_https(self) -> None:
        self.assertEqual(
            connected_server_uri_from_stcore_url(
                "wss://baseball-stat-app.example/~/+/_stcore/stream"
            ),
            "https://baseball-stat-app.example/~/+",
        )

    def test_health_fallback(self) -> None:
        resolved = resolve_connected_server_uri(
            health_endpoints=[
                {
                    "url": "https://example.test/~/+/_stcore/health",
                    "status": 200,
                    "content_type": "text/plain",
                }
            ]
        )
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["uri"], "https://example.test/~/+")
        self.assertEqual(resolved["source"], SOURCE_HEALTH)

    def test_host_config_fallback(self) -> None:
        resolved = resolve_connected_server_uri(
            host_config_endpoints=[
                {
                    "url": "https://example.test/~/+/_stcore/host-config",
                    "status": 200,
                    "content_type": "application/json",
                }
            ]
        )
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["uri"], "https://example.test/~/+")
        self.assertEqual(resolved["source"], SOURCE_HOST_CONFIG)

    def test_websocket_outranks_http_candidates(self) -> None:
        resolved = resolve_connected_server_uri(
            websocket_urls=["wss://example.test/~/+/_stcore/stream"],
            health_endpoints=[
                {"url": "https://example.test/_stcore/health", "status": 200}
            ],
            host_config_endpoints=[
                {"url": "https://example.test/_stcore/host-config", "status": 200}
            ],
        )
        self.assertEqual(resolved["source"], SOURCE_WEBSOCKET_STREAM)
        self.assertEqual(resolved["uri"], "https://example.test/~/+")


class OobUrlConstructionTests(unittest.TestCase):
    def test_join_connected_base_and_static_path(self) -> None:
        url = join_connected_server_static_url(
            "https://example.test/~/+",
            "/app/static/s3_oob/abc123.json",
        )
        self.assertEqual(
            url,
            "https://example.test/~/+/app/static/s3_oob/abc123.json",
        )

    def test_join_does_not_use_bare_origin_path(self) -> None:
        url = join_connected_server_static_url(
            "https://example.test/~/+",
            "/app/static/s3_oob/abc123.json",
        )
        self.assertNotEqual(url, "https://example.test/app/static/s3_oob/abc123.json")
        self.assertNotIn("//app/", url.replace("https://", ""))

    def test_fetch_uses_connected_server_uri(self) -> None:
        captured: dict[str, str] = {}

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
                captured["url"] = url
                return FakeResponse()

        page = SimpleNamespace(
            evaluate=lambda _js: (_ for _ in ()).throw(AssertionError("origin fallback forbidden")),
            request=FakeRequest(),
        )
        out = fetch_oob_snapshot_via_page(
            page,
            PATH,
            connected_server_uri="https://example.test/~/+",
            require_connected_server_uri=True,
            cache_bust=False,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(
            captured["url"],
            f"https://example.test/~/+{PATH}",
        )
        self.assertEqual(out["url_base_source"], "connected_server_uri")


class ProductionSafetyTests(unittest.TestCase):
    def test_missing_connected_uri_does_not_http(self) -> None:
        calls: list[str] = []

        class FakeRequest:
            @staticmethod
            def get(url, timeout=0):
                calls.append(url)
                raise AssertionError("should not fetch")

        page = SimpleNamespace(
            evaluate=lambda _js: "https://example.test",
            request=FakeRequest(),
        )
        out = fetch_oob_snapshot_via_page(
            page,
            PATH,
            connected_server_uri=None,
            require_connected_server_uri=True,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "oob_connected_server_uri_unresolved")
        self.assertFalse(out.get("http_request_attempted"))
        self.assertEqual(calls, [])

    def test_unresolved_note_preserved_in_snapshot_validation(self) -> None:
        ok, note = validate_oob_snapshot_identity(
            None,
            expected_streamlit_sid=SID,
            expected_token=TOKEN,
            fetch={
                "ok": False,
                "reason": "oob_connected_server_uri_unresolved",
                "http_ok": False,
                "parse_ok": False,
                "http_request_attempted": False,
            },
        )
        self.assertFalse(ok)
        self.assertEqual(note, "oob_connected_server_uri_unresolved")

    def test_pipeline_require_uri_stops_before_fetch(self) -> None:
        readiness = {
            "candidates": [
                {
                    "dom_index": 0,
                    "parse_ok": True,
                    "payload": {
                        "streamlit_session_id": SID,
                        "oob_channel": {
                            "registered": True,
                            "published": True,
                            "diagnostic_token": TOKEN,
                            "static_url_path": PATH,
                            "snapshot_generation": 1,
                        },
                    },
                }
            ]
        }
        calls: list[str] = []

        def fake_fetch(*_a, **_k):
            calls.append("fetched")
            raise AssertionError("must not fetch")

        out = run_oob_discovery_pipeline(
            readiness_scrape=readiness,
            ledger_scrape={},
            expected_streamlit_sid=SID,
            page=object(),
            fetch_fn=fake_fetch,
            connected_server_uri="",
            require_connected_server_uri=True,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["snapshot_validation_note"], "oob_connected_server_uri_unresolved")
        self.assertEqual(calls, [])
        self.assertFalse(out["initial_fetch"].get("http_request_attempted"))

    def test_unavailable_classifier_keeps_precise_note(self) -> None:
        case, note, _ = classify_oob_channel_unavailable(
            channel={"registered": True, "static_url_path": PATH},
            initial_fetch={
                "ok": False,
                "reason": "oob_connected_server_uri_unresolved",
                "http_request_attempted": False,
            },
            note="oob_connected_server_uri_unresolved",
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_UNAVAILABLE)
        self.assertEqual(note, "oob_connected_server_uri_unresolved")
        self.assertNotEqual(note, "oob_static_fetch_not_json")

    def test_production_gate_installs_capture_before_goto(self) -> None:
        gate_src = (SCRIPTS / "run_production_bridge_s3_server_registry_gate.py").read_text(
            encoding="utf-8"
        )
        attach_idx = gate_src.find("connected_uri_capture.attach(page)")
        goto_idx = gate_src.find("goto_and_wake(page, url")
        self.assertGreater(attach_idx, 0)
        self.assertGreater(goto_idx, attach_idx)
        self.assertIn("require_connected_server_uri=True", gate_src)
        self.assertIn("streamlit_connected_server_uri", gate_src)
        # Production must not construct OOB URLs from bare location.origin.
        self.assertNotIn('evaluate("() => location.origin")', gate_src)

    def test_publisher_path_unchanged(self) -> None:
        from live_draft_stage1_s3_oob_snapshot import static_url_path_for_token

        self.assertEqual(static_url_path_for_token("tok"), "/app/static/s3_oob/tok.json")

    def test_deploy_pin_unchanged(self) -> None:
        pin = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(pin.startswith("b39782a"))


class RegressionClassifierTests(unittest.TestCase):
    def test_oob_static_fetch_not_json_still_classified(self) -> None:
        ok, note = validate_oob_snapshot_identity(
            None,
            expected_streamlit_sid=SID,
            expected_token=TOKEN,
            fetch={"ok": False, "http_ok": True, "parse_ok": False},
        )
        self.assertFalse(ok)
        self.assertEqual(note, "oob_static_fetch_not_json")

    def test_r3_classifier_unchanged(self) -> None:
        rows = [
            {"phase": "RUNTIME_BACKMSG_ENTRY", "pause_present": True},
            {"phase": "APPSESSION_BACKMSG_ENTRY", "pause_present": True},
            {"phase": "APPSESSION_REQUEST_RERUN_ENTRY", "pause_present": True},
            {"phase": "SAFE_SESSIONSTATE_RECEIVE_ENTRY", "pause_present": True},
            {"phase": "SERVER_RECEIVE_ENTRY", "pause_present": True},
            {
                "phase": "SERVER_STATE_APPLIED",
                "pause_present": True,
                "pause_trigger_from_deserialized": True,
            },
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


if __name__ == "__main__":
    unittest.main()
