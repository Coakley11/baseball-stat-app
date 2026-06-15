"""Start Live Draft simulator promotion — player name matching."""

from __future__ import annotations

import re
import unicodedata
import unittest

import pandas as pd


def normalize_player_name_for_merge(name):
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    text = str(name)
    text = text.replace("(Batter)", "").replace("(Pitcher)", "")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def find_live_pool_row(available, player_name: str):
    if available is None or getattr(available, "empty", True):
        return None
    col = "fullName" if "fullName" in available.columns else "Player"
    target = str(player_name or "").strip()
    target_norm = normalize_player_name_for_merge(target)
    for _, row in available.iterrows():
        full = str(row.get(col) or "").strip()
        if not full:
            continue
        if full.lower() == target.lower() or full == target:
            return row
        if target_norm and normalize_player_name_for_merge(full) == target_norm:
            return row
    return None


class TestFindLivePoolRow(unittest.TestCase):
    def test_normalized_name_match(self) -> None:
        pool = pd.DataFrame(
            [
                {"fullName": "Ronald Acuna Jr.", "playerID": "1"},
                {"fullName": "Mike Trout", "playerID": "2"},
            ]
        )
        row = find_live_pool_row(pool, "Ronald Acuña Jr.")
        self.assertIsNotNone(row)
        self.assertEqual(str(row.get("playerID")), "1")
