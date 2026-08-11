"""Tests for cloud_runtime_fs_probe wiring and classification."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from cloud_runtime_fs_probe import (  # noqa: E402
    PROBE_ELEMENT_ID,
    PROBE_QUERY_PARAM,
    collect_cloud_runtime_fs_probe,
    maybe_render_cloud_runtime_fs_probe,
    parse_deploy_pin,
    payload_excludes_secrets,
    render_cloud_runtime_fs_probe,
    solo_cloud_fs_probe_enabled,
)
from stage1_s3_cloud_fs_probe_classify import (  # noqa: E402
    CLOUD_FS_PROBE_CHECKOUT_AND_STATIC_CONFIG_PRESENT,
    CLOUD_FS_PROBE_CHECKOUT_STALE_OR_ASSET_MISSING,
    CLOUD_FS_PROBE_STATIC_CONFIG_NOT_EFFECTIVE,
    CLOUD_FS_PROBE_UNAVAILABLE,
    classify_cloud_fs_probe_scrape,
)
from stage1_s3_r2_subclassify import BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED  # noqa: E402
from stage1_s3_r3_observability_classify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
    classify_s3_with_observability,
)


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


class CloudRuntimeFsProbeTests(unittest.TestCase):
    def test_collect_returns_required_fields(self) -> None:
        payload = collect_cloud_runtime_fs_probe()
        required = (
            "git_head",
            "git_head_short",
            "git_branch",
            "cwd",
            "streamlit_app_abspath",
            "streamlit_version",
            "config_path",
            "config_exists",
            "effective_enable_static_serving",
            "static_dir_abspath",
            "static_dir_exists",
            "repo_static_probe_abspath",
            "repo_static_probe_exists",
            "repo_static_probe_size_bytes",
            "repo_static_probe_sentinel_ok",
            "deploy_commit_exists",
            "deploy_commit_raw",
            "deploy_pin",
            "app_runtime_deploy_marker",
        )
        for key in required:
            self.assertIn(key, payload, msg=key)
        self.assertEqual(PROBE_ELEMENT_ID, "solo-cloud-fs-probe")
        self.assertTrue(payload["git_head"])
        self.assertEqual(len(payload["git_head_short"]), 7)

    def test_git_head_capture_matches_rev_parse(self) -> None:
        payload = collect_cloud_runtime_fs_probe()
        self.assertEqual(payload["git_head"], _git_head())

    def test_branch_capture(self) -> None:
        payload = collect_cloud_runtime_fs_probe()
        self.assertIn("git_branch", payload)
        self.assertTrue(payload["git_branch"] or payload["git_branch"].startswith("error:"))

    def test_effective_static_serving_from_streamlit_option(self) -> None:
        st = SimpleNamespace(
            get_option=lambda name: True if name == "server.enableStaticServing" else None
        )
        payload = collect_cloud_runtime_fs_probe(st=st)
        self.assertTrue(payload["effective_enable_static_serving"])

    def test_committed_static_probe_exists_with_sentinel(self) -> None:
        payload = collect_cloud_runtime_fs_probe()
        probe_path = ROOT / "static" / "s3_oob" / "__repo_static_probe_v1.json"
        self.assertTrue(probe_path.is_file())
        self.assertTrue(payload["repo_static_probe_exists"])
        self.assertGreater(payload["repo_static_probe_size_bytes"], 0)
        self.assertTrue(payload["repo_static_probe_sentinel_ok"])

    def test_deploy_pin_separate_from_git_head(self) -> None:
        payload = collect_cloud_runtime_fs_probe()
        deploy_raw = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8")
        expected_pin = parse_deploy_pin(deploy_raw)
        self.assertEqual(payload["deploy_pin"], expected_pin)
        self.assertEqual(payload["app_runtime_deploy_marker"], expected_pin)
        self.assertEqual(expected_pin, "b39782a")
        self.assertNotEqual(payload["deploy_pin"], payload["git_head"][:7])

    def test_parse_deploy_pin_truncates_comment(self) -> None:
        self.assertEqual(parse_deploy_pin("b39782a  # auto-generated\n"), "b39782a")

    def test_payload_excludes_secrets(self) -> None:
        payload = collect_cloud_runtime_fs_probe()
        payload["deploy_commit_reads"] = {"safe": "b39782a"}
        self.assertTrue(payload_excludes_secrets(payload))

    def test_collect_not_cached_between_calls(self) -> None:
        a = collect_cloud_runtime_fs_probe()
        b = collect_cloud_runtime_fs_probe()
        self.assertEqual(a["git_head"], b["git_head"])

    def test_solo_cloud_fs_probe_query_param_gating(self) -> None:
        off = SimpleNamespace(query_params={PROBE_QUERY_PARAM: "0"})
        on = SimpleNamespace(query_params={PROBE_QUERY_PARAM: "1"})
        self.assertFalse(solo_cloud_fs_probe_enabled(off))
        self.assertTrue(solo_cloud_fs_probe_enabled(on))

    def test_maybe_render_skips_without_query_param(self) -> None:
        st = SimpleNamespace(query_params={}, markdown=mock.Mock())
        self.assertFalse(maybe_render_cloud_runtime_fs_probe(st))
        st.markdown.assert_not_called()

    def test_render_uses_markdown_only_no_widget_fragment_timer(self) -> None:
        st = SimpleNamespace(
            query_params={PROBE_QUERY_PARAM: "1"},
            markdown=mock.Mock(),
            get_option=lambda name: True if name == "server.enableStaticServing" else None,
        )
        st.button = mock.Mock()
        st.fragment = mock.Mock()
        st.rerun = mock.Mock()
        render_cloud_runtime_fs_probe(st)
        st.markdown.assert_called_once()
        html = st.markdown.call_args[0][0]
        self.assertIn(f'id="{PROBE_ELEMENT_ID}"', html)
        self.assertIn("data-git-head=", html)
        self.assertIn("data-deploy-pin=", html)
        st.button.assert_not_called()
        st.fragment.assert_not_called()
        st.rerun.assert_not_called()

    def test_classify_case_a_checkout_and_static_present(self) -> None:
        payload = {
            "git_head": "6394eb6abc1234567890abcdef1234567890abcd",
            "git_head_short": "6394eb6",
            "git_head_contains_probe_asset": True,
            "repo_static_probe_exists": True,
            "repo_static_probe_sentinel_ok": True,
            "effective_enable_static_serving": True,
            "deploy_pin": "b39782a",
        }
        scrape = {
            "found": True,
            "data-json": json.dumps(payload),
        }
        case, note, evidence = classify_cloud_fs_probe_scrape(scrape)
        self.assertEqual(case, CLOUD_FS_PROBE_CHECKOUT_AND_STATIC_CONFIG_PRESENT)
        self.assertEqual(note, "checkout_asset_and_static_config_present")
        self.assertEqual(evidence["deploy_pin"], "b39782a")

    def test_classify_case_b_stale_or_asset_missing(self) -> None:
        payload = {
            "git_head": "5575fe2abc1234567890abcdef1234567890abcd",
            "git_head_short": "5575fe2",
            "git_head_contains_probe_asset": False,
            "repo_static_probe_exists": False,
            "effective_enable_static_serving": True,
        }
        scrape = {"found": True, "payload": payload}
        case, note, _ = classify_cloud_fs_probe_scrape(scrape)
        self.assertEqual(case, CLOUD_FS_PROBE_CHECKOUT_STALE_OR_ASSET_MISSING)
        self.assertEqual(note, "checkout_stale_or_repo_static_probe_missing")

    def test_classify_case_c_static_config_not_effective(self) -> None:
        payload = {
            "git_head_contains_probe_asset": True,
            "repo_static_probe_exists": True,
            "effective_enable_static_serving": False,
        }
        scrape = {"found": True, "payload": payload}
        case, note, _ = classify_cloud_fs_probe_scrape(scrape)
        self.assertEqual(case, CLOUD_FS_PROBE_STATIC_CONFIG_NOT_EFFECTIVE)
        self.assertEqual(note, "enable_static_serving_not_effective")

    def test_classify_case_d_unavailable(self) -> None:
        case, note, _ = classify_cloud_fs_probe_scrape({"found": False})
        self.assertEqual(case, CLOUD_FS_PROBE_UNAVAILABLE)
        self.assertEqual(note, "fs_probe_marker_not_mounted")

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

    def test_bootstrap_hook_imports_maybe_render(self) -> None:
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("maybe_render_cloud_runtime_fs_probe", src)
        self.assertIn("from cloud_runtime_fs_probe import maybe_render_cloud_runtime_fs_probe", src)


if __name__ == "__main__":
    unittest.main()
