"""The indexed active-player check answers exactly like the per-call table scan."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from player_actions import (
    build_active_player_index,
    is_active_current_player,
    is_active_current_player_indexed,
)

ROOT = Path(__file__).resolve().parents[1]


def _seasons() -> pd.DataFrame:
    batting = pd.read_csv(ROOT / "Batting.csv", usecols=["playerID", "yearID"], low_memory=False)
    people = pd.read_csv(ROOT / "People.csv", usecols=["playerID", "nameFirst", "nameLast"], low_memory=False)
    df = batting[batting["yearID"] >= 2018].merge(people, on="playerID", how="left")
    df["fullName"] = (df["nameFirst"].fillna("") + " " + df["nameLast"].fillna("")).str.strip()
    return df[["playerID", "fullName", "yearID"]].drop_duplicates()


class ActivePlayerIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = _seasons()
        cls.index = build_active_player_index(cls.df)

    def _same(self, player):
        self.assertEqual(
            is_active_current_player_indexed(player, self.index),
            is_active_current_player(player, self.df),
            player,
        )

    def test_by_name_matches_scan(self):
        names = self.df["fullName"].drop_duplicates().sample(40, random_state=3).tolist()
        for name in names + ["Shohei Ohtani (Batter)", "Ronald Acuña Jr.", "Nobody Atall", ""]:
            self._same(name)

    def test_by_id_and_dict_inputs_match_scan(self):
        rows = self.df.drop_duplicates("playerID").sample(25, random_state=5)
        for _, row in rows.iterrows():
            self._same({"playerID": row["playerID"], "fullName": row["fullName"]})
            self._same(pd.Series({"Player": row["fullName"]}))
        self._same({"playerID": "nosuchid01", "fullName": "Aaron Judge"})

    def test_empty_table(self):
        self.assertFalse(is_active_current_player_indexed("Aaron Judge", build_active_player_index(pd.DataFrame())))


if __name__ == "__main__":
    unittest.main()
