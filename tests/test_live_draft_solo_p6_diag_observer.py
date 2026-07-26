"""Tests for P6 diagnostic observer page."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from live_draft_solo_p6_diag_observer import OBSERVER_ELEMENT_ID, build_observer_payload


class P6DiagObserverTests(unittest.TestCase):
    def test_build_observer_payload_empty_run(self) -> None:
        payload = build_observer_payload("missing-run-id")
        self.assertEqual(payload.get("diagnostic_run_id"), "missing-run-id")
        self.assertEqual(payload.get("ledger_rows"), [])

    def test_observer_element_id(self) -> None:
        self.assertEqual(OBSERVER_ELEMENT_ID, "solo-p6-diag-observer")


if __name__ == "__main__":
    unittest.main()
