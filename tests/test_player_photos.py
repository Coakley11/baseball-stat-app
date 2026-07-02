"""Tests for shared player photo infrastructure."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from player_photos import (
    compact_fantasy_stat_line,
    get_player_photo_info,
    load_people_photo_lookup,
    mlb_headshot_url,
    resolve_mlbam_id,
)


class PlayerPhotosTests(unittest.TestCase):
    def test_mlb_headshot_url_formats(self) -> None:
        url = mlb_headshot_url(545361)
        self.assertIsNotNone(url)
        assert url is not None
        self.assertIn("545361", url)
        self.assertIn("headshot", url)
        self.assertIsNone(mlb_headshot_url(None))
        self.assertIsNone(mlb_headshot_url(0))

    def test_load_people_photo_lookup_reads_bbref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            people = pd.DataFrame(
                [
                    {
                        "playerID": "troutmi01",
                        "nameFirst": "Mike",
                        "nameLast": "Trout",
                        "birthYear": 1991,
                        "bbrefID": "troutmi01",
                    }
                ]
            )
            people.to_csv(base / "People.csv", index=False)
            df = load_people_photo_lookup(base)
            self.assertEqual(len(df), 1)
            self.assertEqual(str(df.iloc[0]["fullName"]).strip(), "Mike Trout")

    def test_resolve_mlbam_uses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cache_dir = base / "data"
            cache_dir.mkdir(parents=True)
            (cache_dir / "player_mlbam_cache.json").write_text(
                json.dumps({"obscure01": 999001}),
                encoding="utf-8",
            )
            found, source = resolve_mlbam_id(player_id="obscure01", base_dir=base, use_api=False)
            self.assertEqual(found, 999001)
            self.assertEqual(source, "cache")

    @patch("player_photos._search_mlbam_via_api", return_value=592450)
    def test_resolve_mlbam_api_lookup_persists_cache(self, _mock_api) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            people = pd.DataFrame(
                [
                    {
                        "playerID": "obscure02",
                        "nameFirst": "Test",
                        "nameLast": "Player",
                        "birthYear": 1990,
                    }
                ]
            )
            people.to_csv(base / "People.csv", index=False)
            found, source = resolve_mlbam_id(
                player_id="obscure02",
                full_name="Test Player",
                base_dir=base,
                use_api=True,
            )
            self.assertEqual(found, 592450)
            self.assertEqual(source, "api_lookup")
            cache = json.loads((base / "data" / "player_mlbam_cache.json").read_text(encoding="utf-8"))
            self.assertEqual(cache["obscure02"], 592450)

    def test_get_player_photo_info_from_row_mlbam_column(self) -> None:
        row = pd.Series({"fullName": "Mike Trout", "playerID": "troutmi01", "MLBAM ID": 545361})
        info = get_player_photo_info(row=row, use_api=False)
        self.assertEqual(info["mlbam_id"], 545361)
        self.assertTrue(info["has_photo"])
        self.assertIn("545361", str(info["headshot_url"]))

    def test_harper_seed_map_resolves_headshot_without_api(self) -> None:
        info = get_player_photo_info(player_id="harpebr03", full_name="Bryce Harper", use_api=False)
        self.assertEqual(info["mlbam_id"], 547180)
        self.assertTrue(info["has_photo"])
        self.assertIn("547180", str(info["headshot_url"]))
        self.assertEqual(info["resolve_source"], "seed_map")

    def test_freeman_name_only_seed_map(self) -> None:
        info = get_player_photo_info(full_name="Freddie Freeman", use_api=False)
        self.assertEqual(info["mlbam_id"], 518692)
        self.assertEqual(info["resolve_source"], "seed_map")

    def test_compact_fantasy_stat_line(self) -> None:
        row = pd.Series({"HR": 45, "RBI": 104, "R": 98, "SB": 12, "BA": 0.291})
        line = compact_fantasy_stat_line(row)
        self.assertIn("HR 45", line)
        self.assertIn("RBI 104", line)
        self.assertIn("BA 0.291", line)


if __name__ == "__main__":
    unittest.main()
