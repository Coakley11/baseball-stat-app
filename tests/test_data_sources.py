"""Data-source attribution: what the app ships matches what it credits, and nothing claims affiliation."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import pandas as pd

import data_sources as ds

ROOT = Path(__file__).resolve().parents[1]
NEGRO_LEAGUES = {"NNL", "NN2", "ECL", "ANL", "NAL", "NSL", "EWL"}


class AttributionTextTests(unittest.TestCase):
    def test_short_credit(self):
        self.assertEqual(ds.SHORT_CREDIT, "Baseball data: Lahman Baseball Database — Sean Lahman / SABR")

    def test_detail_names_creator_maintainer_license_and_sources(self):
        text = ds.about_data_markdown()
        for needle in ("Sean Lahman", "SABR", "Bryan Walko", "Attribution-ShareAlike 3.0", "Seamheads",
                       "MLB Stats API", "FantasyPros", "sabr.org/lahman-database", "adapted"):
            self.assertIn(needle, text)

    def test_no_endorsement_claims(self):
        text = (ds.about_data_markdown() + ds.SHORT_CREDIT).lower()
        for claim in ("official mlb", "mlb licensed", "licensed by mlb", "affiliated with sabr", "endorsed by sabr"):
            if claim in text:
                self.assertIn("not affiliated with, endorsed by or licensed by", text)
        self.assertIn("not affiliated with", text)


class ShippedDataMatchesCreditTests(unittest.TestCase):
    def test_every_credited_lahman_table_ships_and_no_other_lahman_table_is_loaded(self):
        for table in ds.LAHMAN_TABLES:
            self.assertTrue((ROOT / f"{table}.csv").is_file(), table)
        sources = "".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in ROOT.glob("*.py")
        )
        lahman = "People|Batting|Fielding|Pitching|Teams|Appearances|AllstarFull|HallOfFame|AwardsPlayers|Salaries|Managers|Schools|CollegePlaying"
        loaded = set(re.findall(r"[\"'](" + lahman + r")\.csv[\"']", sources))
        self.assertEqual(loaded, set(ds.LAHMAN_TABLES))

    def test_version_covers_the_bundled_seasons_and_negro_leagues(self):
        batting = pd.read_csv(ROOT / "Batting.csv", usecols=["yearID", "lgID"])
        self.assertEqual(int(batting["yearID"].max()), 2025)
        self.assertIn("2025", ds.LAHMAN_VERSION)
        self.assertTrue(NEGRO_LEAGUES & set(batting["lgID"].dropna()), "Seamheads credit needs Negro Leagues rows")

    def test_attribution_is_rendered_on_every_page(self):
        app = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("render_data_attribution(st)", app)
        self.assertLess(app.index("render_data_attribution(st)"), app.index('if active_page == "__ENTITLEMENT_LOADING__"'))


if __name__ == "__main__":
    unittest.main()
