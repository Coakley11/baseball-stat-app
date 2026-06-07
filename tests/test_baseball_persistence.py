"""Tests for Baseball cross-device persistence snapshot."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from baseball_persistent_state import build_baseball_disk_state


class TestBaseballPersistence(unittest.TestCase):
    def test_build_disk_state_snapshots_active_page_filters(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Comparison Tool",
            "page_filter_state": {},
            "sig_player_a_clean": "Juan Soto (NYY)",
            "sig_player_b_clean": "Aaron Judge (NYY)",
            "compare_players": ["Juan Soto (NYY)", "Aaron Judge (NYY)"],
            "compare_stat": "OPS",
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob.get("active_page"), "Comparison Tool")
        pf = blob.get("page_filter_state") or {}
        cmp = pf.get("Comparison Tool") or {}
        self.assertEqual(cmp.get("sig_player_a_clean"), "Juan Soto (NYY)")
        self.assertEqual(cmp.get("compare_players"), ["Juan Soto (NYY)", "Aaron Judge (NYY)"])


if __name__ == "__main__":
    unittest.main()
