"""clean_ui_columns must drop duplicate display columns (Arrow/Streamlit crash)."""

from __future__ import annotations

import unittest

import pandas as pd


class CleanUiColumnsDedupeTests(unittest.TestCase):
    def test_duplicate_player_columns_are_removed(self) -> None:
        # Import after path is app root (unittest discovery cwd).
        import streamlit_app as app

        df = pd.DataFrame(
            [
                {
                    "Player": "A",
                    "fullName": "A",
                    "Primary Position": "SS",
                    "MLB Team": "NYY",
                    "Expected Fantasy Value": 12.0,
                    "Fantasy Edge": 1.0,
                    "Model Rank": 1,
                    "Market Rank": 2,
                }
            ]
        )
        # Force a duplicate Player label the way merges sometimes do.
        df = pd.concat([df, df[["Player"]]], axis=1)
        self.assertFalse(bool(df.columns.is_unique))
        out = app.clean_ui_columns(df)
        self.assertTrue(bool(out.columns.is_unique))
        self.assertEqual(list(out.columns).count("Player"), 1)


if __name__ == "__main__":
    unittest.main()
