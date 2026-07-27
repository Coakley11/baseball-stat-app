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
        self.assertTrue(p6_dedicated_auth_ready({}))


if __name__ == "__main__":
    unittest.main()
