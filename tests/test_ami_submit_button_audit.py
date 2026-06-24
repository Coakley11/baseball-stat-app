"""Repo audit: baseball-facing AMI submit must not use Send to Command Center label."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEND_CC = "Send to Command Center"

SCAN_IGNORE = (
    "/tests/",
    "/docs/",
    "test_",
    "Oldstreamlit_app.py",
    "suite_analytical_question.py",  # generic fallback for investment app only
)


class AmiSubmitButtonPathAuditTests(unittest.TestCase):
    def test_baseball_module_exists_and_hardcodes_label(self) -> None:
        path = ROOT / "baseball_ami_sidebar.py"
        self.assertTrue(path.is_file(), "baseball_ami_sidebar.py must exist")
        text = path.read_text(encoding="utf-8")
        self.assertIn("⚾ Baseball Insight", text)
        self.assertIn("_render_ami_submit_debug_panel", text)
        self.assertIn("_ami_debug_visible", text)
        self.assertIn("st.sidebar.button", text)
        self.assertNotIn(f'st.sidebar.button(\n        "{SEND_CC}"', text)

    def test_streamlit_entrypoint_uses_baseball_module(self) -> None:
        text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("render_baseball_insight_sidebar", text)
        self.assertIn('["_suite_runtime_app_id"] = "baseball"', text)

    def test_no_st_button_send_to_command_center_in_python_ui(self) -> None:
        pattern = re.compile(
            r"st\.(?:sidebar\.)?button\s*\(\s*[\"']Send to Command Center[\"']",
            re.MULTILINE,
        )
        hits: list[str] = []
        for path in ROOT.rglob("*.py"):
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if any(x in rel for x in SCAN_IGNORE):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                hits.append(rel)
        self.assertEqual(hits, [], f"Unexpected st.button('Send to Command Center') in: {hits}")

    def test_deploy_marker_resolves_commit_dynamically(self) -> None:
        import suite_deploy_marker as marker

        text = (ROOT / "suite_deploy_marker.py").read_text(encoding="utf-8")
        self.assertNotIn('GIT_COMMIT_SHORT = "6842410"', text)
        self.assertIn("resolve_git_commit_short", text)
        commit = marker.resolve_git_commit_short()
        self.assertNotEqual(commit, "6842410")
        self.assertIn("streamlit_app.py", marker.format_deploy_caption())


if __name__ == "__main__":
    unittest.main()
