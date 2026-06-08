"""Page-state restore must not overwrite a fresh cloud workspace apply."""

from __future__ import annotations

import unittest

import page_state as pg


def _norm(x: str) -> str:
    return str(x)


class TestPageStateCloudRestore(unittest.TestCase):
    def test_handle_sidebar_skips_when_cloud_workspace_applied(self) -> None:
        session = {
            "page_filter_state": {
                "Comparison Tool": {"sig_player_a_clean": "Juan Soto (NYY)"},
                "Trend Value": {"trend_players_multi": ["Aaron Judge"]},
            },
            "active_page": "Comparison Tool",
            "_page_state_last_active": "Trend Value",
            "_suite_cloud_workspace_applied": True,
            "sig_player_a_clean": "Juan Soto (NYY)",
        }
        pg.handle_sidebar_page_state(session, "Comparison Tool", _norm, None)
        self.assertEqual(session.get("_page_state_last_active"), "Comparison Tool")
        self.assertEqual(session.get("sig_player_a_clean"), "Juan Soto (NYY)")
        self.assertNotIn("_suite_cloud_workspace_applied", session)


if __name__ == "__main__":
    unittest.main()
