"""Tests for dedicated P6 diagnostic entrypoint gating."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from live_draft_solo_p6_dedicated_entrypoint import (
    p6_dedicated_auth_ready,
    p6_dedicated_entrypoint_requested,
)


class P6DedicatedEntrypointTests(unittest.TestCase):
    def test_requested_requires_p6_run_and_delivery_diag(self) -> None:
        st = MagicMock()
        session: dict = {}
        self.assertFalse(p6_dedicated_entrypoint_requested(st, session))

    def test_auth_ready_when_auth_disabled(self) -> None:
        st = MagicMock()
        st.query_params = {}
        self.assertTrue(p6_dedicated_auth_ready(st, {}))

    def test_auth_ready_with_suite_sid_query(self) -> None:
        st = MagicMock()
        st.query_params = {"suite_sid": "a38d0369-9c8f-48ed-b2be-e10237e9349b"}
        session: dict = {}
        with unittest.mock.patch("suite_auth.is_auth_enabled", return_value=True):
            with unittest.mock.patch("suite_auth.is_authenticated", return_value=False):
                with unittest.mock.patch("suite_auth.auth_session_complete", return_value=False):
                    self.assertTrue(p6_dedicated_auth_ready(st, session))


if __name__ == "__main__":
    unittest.main()
