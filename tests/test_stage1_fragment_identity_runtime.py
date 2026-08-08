"""Fragment identity runtime snapshot tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity


class FragmentIdentityRuntimeTests(unittest.TestCase):
    def test_snapshot_includes_phase_and_impl_rev(self) -> None:
        with patch(
            "live_draft_stage1_fragment_identity_runtime._thread_state_fields",
            return_value={"thread_state_fragment_id": "abc"},
        ):
            with patch("streamlit.runtime.scriptrunner.get_script_run_ctx", return_value=None):
                row = snapshot_fragment_identity(phase="render", widget_user_key="wk1")
        self.assertEqual(row["phase"], "render")
        self.assertEqual(row["thread_state_fragment_id"], "abc")
        self.assertEqual(row["widget_user_key"], "wk1")


if __name__ == "__main__":
    unittest.main()
