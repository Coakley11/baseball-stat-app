"""Tests for canonical league format propagation."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from baseball_persistent_state import build_baseball_disk_state
from global_fantasy_settings_state import (
    CANONICAL_POINTS,
    CANONICAL_ROTO,
    LIVE_SCORING_POINTS,
    LIVE_SCORING_ROTO,
    mirror_canonical_to_all_aliases,
    normalize_league_format,
    on_alias_format_changed,
    on_live_draft_scoring_changed,
    write_canonical_global_fantasy_settings,
)


class TestNormalizeLeagueFormat(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertEqual(normalize_league_format("Points"), CANONICAL_POINTS)
        self.assertEqual(normalize_league_format("Points League"), CANONICAL_POINTS)
        self.assertEqual(normalize_league_format("Roto (5x5)"), CANONICAL_ROTO)
        self.assertEqual(normalize_league_format("5x5 Roto"), CANONICAL_ROTO)


class TestFormatPropagation(unittest.TestCase):
    def test_write_canonical_mirrors_aliases_and_live_scoring(self) -> None:
        session: dict = {}
        write_canonical_global_fantasy_settings(session, format_="Points League", reason="test")
        self.assertEqual(session["room_format"], CANONICAL_POINTS)
        self.assertEqual(session["draft_lab_scoring_type"], CANONICAL_POINTS)
        self.assertEqual(session["fantasy_market_format"], CANONICAL_POINTS)
        self.assertEqual(session["live_draft_scoring"], LIVE_SCORING_POINTS)

    def test_on_alias_format_changed_from_draft_lab(self) -> None:
        session = {"draft_lab_scoring_type": "Points League"}
        on_alias_format_changed(session, "draft_lab_scoring_type")
        self.assertEqual(session["room_format"], CANONICAL_POINTS)
        self.assertEqual(session["draft_format"], CANONICAL_POINTS)
        self.assertEqual(session["live_draft_scoring"], LIVE_SCORING_POINTS)

    def test_live_draft_scoring_promotes_to_canonical(self) -> None:
        session = {"live_draft_scoring": LIVE_SCORING_ROTO}
        on_live_draft_scoring_changed(session)
        self.assertEqual(session["room_format"], CANONICAL_ROTO)
        self.assertEqual(session["draft_lab_scoring_type"], CANONICAL_ROTO)

    def test_mirror_after_restore(self) -> None:
        session = {
            "room_format": CANONICAL_POINTS,
            "draft_lab_scoring_type": CANONICAL_ROTO,
            "live_draft_scoring": LIVE_SCORING_ROTO,
        }
        mirror_canonical_to_all_aliases(session)
        self.assertEqual(session["draft_lab_scoring_type"], CANONICAL_POINTS)
        self.assertEqual(session["live_draft_scoring"], LIVE_SCORING_POINTS)


class TestNanCloudSave(unittest.TestCase):
    def test_build_disk_state_json_serializable_with_nan(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Draft Room Simulator",
            "page_filter_state": {},
            "room_format": CANONICAL_ROTO,
            "draft_lab_results": {
                "draft": [{"HR": float("nan"), "Player": "Test"}],
            },
        }
        blob = build_baseball_disk_state(st)
        json.dumps(blob)


if __name__ == "__main__":
    unittest.main()
