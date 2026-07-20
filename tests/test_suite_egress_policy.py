"""Tests for Supabase egress reduction policy."""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from suite_egress_policy import (
    LOW_EGRESS_SESSION_KEY,
    cloud_autosave_allowed,
    low_egress_mode,
    poll_sync_defer_active,
    set_low_egress_mode,
    shared_draft_poll_interval_sec,
    workspace_cloud_fetch_needed,
)


class _FakeSt:
    def __init__(self) -> None:
        self.session_state: dict = {}


class SuiteEgressPolicyTests(unittest.TestCase):
    def test_low_egress_mode_env(self) -> None:
        with patch.dict(os.environ, {"SUITE_LOW_EGRESS": "1"}):
            self.assertTrue(low_egress_mode({}))

    def test_low_egress_mode_st_secrets(self) -> None:
        class _Secrets(dict):
            pass

        secrets = _Secrets(SUITE_LOW_EGRESS="1")
        with patch.dict(os.environ, {"SUITE_LOW_EGRESS": ""}, clear=False):
            with patch("streamlit.secrets", secrets, create=True):
                # Import path uses `import streamlit as st` then st.secrets
                import streamlit as st

                with patch.object(st, "secrets", secrets, create=True):
                    self.assertTrue(low_egress_mode({}))

    def test_low_egress_mode_session(self) -> None:
        session: dict = {}
        self.assertFalse(low_egress_mode(session))
        set_low_egress_mode(session, True)
        self.assertTrue(low_egress_mode(session))
        self.assertTrue(session.get(LOW_EGRESS_SESSION_KEY))

    def test_shared_draft_poll_interval_respects_low_egress(self) -> None:
        session: dict = {}
        normal = shared_draft_poll_interval_sec(session)
        set_low_egress_mode(session, True)
        self.assertGreater(shared_draft_poll_interval_sec(session), normal)

    def test_workspace_cloud_fetch_skipped_when_synced_in_low_egress(self) -> None:
        st = _FakeSt()
        st.session_state["_suite_workspace_synced::baseball"] = True
        set_low_egress_mode(st.session_state, True)
        self.assertFalse(workspace_cloud_fetch_needed(st, "baseball"))

    def test_cloud_autosave_throttled_for_autosave(self) -> None:
        st = _FakeSt()
        st.session_state["_suite_last_cloud_autosave_ts"] = time.time()
        allowed, reason = cloud_autosave_allowed(st, "baseball", save_reason="autosave")
        self.assertFalse(allowed)
        self.assertEqual(reason, "autosave_throttled")

    def test_poll_sync_defer_active(self) -> None:
        session: dict = {"_suite_defer_cloud_autosave_until": time.time() + 30}
        self.assertTrue(poll_sync_defer_active(session))


if __name__ == "__main__":
    unittest.main()
