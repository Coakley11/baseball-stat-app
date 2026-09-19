"""Regression: completed roster recap must not crash on duplicate columns."""

from __future__ import annotations

import unittest

import pandas as pd

from player_photos import _scalar_row_value, get_player_photo_info


class CompletedRosterPhotoTests(unittest.TestCase):
    def test_duplicate_fullname_columns_do_not_raise(self) -> None:
        # Shape that previously crashed: rename Player→fullName and MLB Team→Team
        # while fantasy Team already existed → duplicate labels → Series ambiguity.
        df = pd.DataFrame(
            [
                {
                    "Player": "Aaron Judge",
                    "fullName": "Aaron Judge",
                    "Team": "Team A",
                    "MLB Team": "NYY",
                    "Primary Position": "OF",
                    "playerID": "judgea001",
                }
            ]
        )
        # Force duplicate column labels the way a bad rename would.
        bad = df.copy()
        bad["fullName"] = bad["Player"]
        bad = pd.concat([bad, bad[["fullName"]].rename(columns={"fullName": "fullName"})], axis=1)
        # Ensure duplicate fullName columns exist
        bad.columns = list(bad.columns[:-1]) + ["fullName"]
        self.assertTrue(bad.columns.duplicated().any() or list(bad.columns).count("fullName") >= 1)

        row = bad.iloc[0]
        # Scalar helper must never return a Series
        name = _scalar_row_value(row, "fullName", "Player")
        self.assertIsInstance(name, (str, type(None)))
        if name is not None:
            self.assertNotIsInstance(name, pd.Series)

        info = get_player_photo_info(row=row, use_api=False)
        self.assertTrue(info.get("full_name") is None or isinstance(info.get("full_name"), str))

    def test_clean_recap_rename_shape(self) -> None:
        roster_df = pd.DataFrame(
            [
                {
                    "Fantasy Team": "Team A",
                    "Player": "Juan Soto",
                    "MLB Team": "NYM",
                    "Team": "Team A",
                    "Primary Position": "OF",
                    "playerID": "sotoj001",
                }
            ]
        )
        team_recap = roster_df[roster_df["Fantasy Team"].astype(str).eq("Team A")].copy()
        if "Player" in team_recap.columns and "fullName" not in team_recap.columns:
            team_recap["fullName"] = team_recap["Player"]
        if team_recap.columns.duplicated().any():
            team_recap = team_recap.loc[:, ~team_recap.columns.duplicated()].copy()
        row = team_recap.iloc[0]
        info = get_player_photo_info(row=row, use_api=False)
        self.assertEqual(info.get("full_name"), "Juan Soto")


if __name__ == "__main__":
    unittest.main()
