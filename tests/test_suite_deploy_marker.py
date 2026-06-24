"""Deploy marker resolves commit from deploy_commit.txt / env, not stale hardcodes."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class SuiteDeployMarkerTests(unittest.TestCase):
    def test_resolves_commit_from_deploy_commit_file(self) -> None:
        import suite_deploy_marker as marker

        marker.resolve_git_commit_short.cache_clear()
        marker.resolve_commit_source.cache_clear()
        with mock.patch.dict(os.environ, {}, clear=True):
            marker.resolve_git_commit_short.cache_clear()
            marker.resolve_commit_source.cache_clear()
            commit = marker.resolve_git_commit_short()
            self.assertNotEqual(commit, "6842410")
            self.assertNotEqual(commit, "unknown")
            self.assertGreaterEqual(len(commit), 7)

    def test_runtime_feature_verification_includes_mp_generation(self) -> None:
        import suite_deploy_marker as marker

        flags = marker.runtime_feature_verification()
        self.assertEqual(flags["mp_draft_code_generation"], marker.MP_DRAFT_CODE_GENERATION)
        self.assertEqual(flags["leave_room_fix"], "present")
        self.assertEqual(flags["leave_shared_draft_room"], "present")
        self.assertEqual(flags["runtime_diagnostics"], "present")

    def test_format_deploy_caption_uses_streamlit_entrypoint(self) -> None:
        import suite_deploy_marker as marker

        caption = marker.format_deploy_caption()
        self.assertIn("streamlit_app.py", caption)
        self.assertNotIn("6842410", caption)


if __name__ == "__main__":
    unittest.main()
