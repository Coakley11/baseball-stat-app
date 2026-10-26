"""Players with an unknown birth date or batting hand must stay in season/career aggregations.

pandas groupby drops rows whose keys are NaN by default; the yearly table, Career Totals and
window totals group by bio columns, which silently removed ~3,000 early and Negro Leagues
players (e.g. Jack Burdock, 1,231 hits).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BIO_KEYS = ["bats", "throws", "birthYear", "birthMonth", "birthDay", "birthCountry"]


class UnknownBioPlayersTests(unittest.TestCase):
    def test_the_data_really_has_such_players(self):
        people = pd.read_csv(ROOT / "People.csv", low_memory=False)
        burdock = people[people["playerID"] == "burdoja01"]
        self.assertEqual(len(burdock), 1)
        self.assertTrue(burdock[BIO_KEYS].isna().any(axis=1).iloc[0])

    def test_grouping_keeps_nan_keys(self):
        rows = pd.DataFrame({"playerID": ["a", "a", "b"], "bats": ["R", "R", None], "H": [1, 2, 5]})
        dropped = rows.groupby(["playerID", "bats"], as_index=False)["H"].sum()
        kept = rows.groupby(["playerID", "bats"], as_index=False, dropna=False)["H"].sum()
        self.assertEqual(dropped["playerID"].tolist(), ["a"])
        self.assertEqual(kept["playerID"].tolist(), ["a", "b"])

    def test_app_aggregations_keep_unknown_bio_players(self):
        app = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        # The season (yearly) table is built in baseball_history, which load_data delegates to.
        src = app + (ROOT / "baseball_history.py").read_text(encoding="utf-8")
        grouped_by_bio = re.findall(r"\.groupby\(\[[^\]]*\"bats\"[^\]]*\][^)]*\)", src)
        self.assertGreaterEqual(len(grouped_by_bio), 2)
        for call in grouped_by_bio:
            self.assertIn("dropna=False", call, call)
        body = app[app.index("def aggregate_recent_player_totals"):app.index("def apply_stat_min_filters")]
        self.assertIn("dropna=False", body)


if __name__ == "__main__":
    unittest.main()
