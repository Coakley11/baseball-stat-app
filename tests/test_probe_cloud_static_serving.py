"""Tests for repo-backed Cloud static serving probe."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_r3_observability_classify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
    classify_s3_with_observability,
)
from stage1_s3_r2_subclassify import BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED  # noqa: E402
from stage1_s3_static_serving_probe import (  # noqa: E402
    REPO_STATIC_PROBE_RELATIVE_PATH,
    S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED,
    S3_STATIC_SERVING_REPO_CONTROL_PASS,
    build_repo_static_probe_url,
    classify_repo_static_probe_result,
    fetch_repo_static_probe_via_page,
)


class RepoStaticServingProbeTests(unittest.TestCase):
    def test_control_path_uses_app_static_convention(self) -> None:
        self.assertEqual(REPO_STATIC_PROBE_RELATIVE_PATH, "/app/static/s3_oob/__repo_static_probe_v1.json")
        url = build_repo_static_probe_url("https://example.test", cache_bust=False)
        self.assertTrue(url.endswith(REPO_STATIC_PROBE_RELATIVE_PATH))

    def test_cache_bust_query_param(self) -> None:
        url = build_repo_static_probe_url("https://example.test", cache_bust=True)
        self.assertIn("?cb=", url)

    def test_http_200_json_sentinel_pass(self) -> None:
        class FakeResponse:
            status = 200

            @property
            def headers(self):
                return {"content-type": "application/json"}

            @staticmethod
            def text():
                return json.dumps(
                    {
                        "ok": True,
                        "probe": "s3_oob_repo_static_probe_v1",
                        "source": "git_committed_static_file",
                    }
                )

        page = SimpleNamespace(
            evaluate=lambda _js: "https://example.test",
            request=SimpleNamespace(get=lambda url, timeout=0: FakeResponse()),
        )
        fetch = fetch_repo_static_probe_via_page(page)
        case, note, ok = classify_repo_static_probe_result(fetch)
        self.assertTrue(fetch["ok"])
        self.assertTrue(ok)
        self.assertEqual(case, S3_STATIC_SERVING_REPO_CONTROL_PASS)

    def test_http_200_html_not_served(self) -> None:
        class FakeResponse:
            status = 200

            @property
            def headers(self):
                return {"content-type": "text/html; charset=utf-8"}

            @staticmethod
            def text():
                return "<!doctype html><html><body>Streamlit</body></html>"

        page = SimpleNamespace(
            evaluate=lambda _js: "https://example.test",
            request=SimpleNamespace(get=lambda url, timeout=0: FakeResponse()),
        )
        fetch = fetch_repo_static_probe_via_page(page)
        case, note, ok = classify_repo_static_probe_result(fetch)
        self.assertFalse(fetch["ok"])
        self.assertFalse(ok)
        self.assertEqual(case, S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED)
        self.assertEqual(note, "repo_static_probe_returned_non_json")

    def test_wrong_sentinel_fails(self) -> None:
        fetch = {
            "ok": False,
            "http_ok": True,
            "parse_ok": True,
            "probe_marker_match": False,
            "source_marker_match": True,
        }
        case, note, ok = classify_repo_static_probe_result(fetch)
        self.assertEqual(case, S3_STATIC_SERVING_REPO_CONTROL_NOT_SERVED)
        self.assertEqual(note, "repo_static_probe_sentinel_mismatch")
        self.assertFalse(ok)

    def test_probe_script_has_no_bridge_or_auth_dependency(self) -> None:
        src = (SCRIPTS / "probe_cloud_static_serving.py").read_text(encoding="utf-8")
        self.assertIn('"uses_bridge": False', src)
        self.assertIn('"uses_auth": False', src)
        self.assertNotIn("capture_playwright", src)
        self.assertNotIn("resolve_bridge_suite_sid", src)

    def test_oob_discovery_import_fix_present(self) -> None:
        src = (SCRIPTS / "run_production_bridge_s3_server_registry_gate.py").read_text(encoding="utf-8")
        self.assertIn("run_oob_discovery_pipeline", src)
        self.assertIn(
            "from stage1_s3_oob_readback import extract_oob_freshness_from_snapshot, run_oob_discovery_pipeline",
            src,
        )

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


if __name__ == "__main__":
    unittest.main()
