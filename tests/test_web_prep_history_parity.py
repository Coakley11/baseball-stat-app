"""WEB-PREP1 parity: the historical layer moved to baseball_history.py produces exactly what the
original streamlit_app.py code produced.

The originals are rebuilt from the U2/U3 checkpoint (git show 4bc3d30:streamlit_app.py) by AST
span and run with a pass-through ``st`` stub, then compared frame-for-frame with the new module
on the real Lahman files. A negative control proves the comparison can fail."""

import ast
import subprocess
import types
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import baseball_history as bh

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "4bc3d30"
NAMES = ["team_id_mapping", "team_id_to_name", "team_id_to_historical_name", "AL_TEAMS", "NL_TEAMS", "TEAM_PARK_FACTOR",
         "normalize_team_id", "safe_int_year", "team_league", "historical_team_name", "safe_round_rate_stats",
         "build_clean_player_label_map", "add_missing_numeric_columns", "add_rate_stats", "read_required_csv",
         "aggregate_player_year_team", "aggregate_player_year_primary_team", "load_data"]


class _StubSt:
    @staticmethod
    def cache_data(*_a, **_k):
        return lambda fn: fn

    @staticmethod
    def error(msg):
        raise RuntimeError(msg)

    @staticmethod
    def stop():
        raise RuntimeError("stop")


def _original():
    try:
        src = subprocess.run(["git", "show", f"{BASE_COMMIT}:streamlit_app.py"], cwd=ROOT, capture_output=True,
                             check=True).stdout.decode("utf-8")
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise unittest.SkipTest("checkpoint source not available")
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    picked = {}
    for node in tree.body:
        name = getattr(node, "name", None) or next((t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)), None)
        if name in NAMES:
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            picked[name] = "".join(lines[start - 1:node.end_lineno])
    ns = {"st": _StubSt(), "pd": pd, "np": np, "Path": Path, "BASE_DIR": ROOT, "__name__": "original"}
    exec(compile("\n".join(picked[n] for n in NAMES), "original_streamlit_app", "exec"), ns)  # noqa: S102

    # The original Historical Explorer page block, as a function of the same inputs.
    start = src.index('    hist_source = batting_df[(batting_df["yearID"] >= hist_year_range[0])')
    end_marker = '''    else:
        hist["displayPosition"] = ""
'''
    end = src.index(end_marker, start) + len(end_marker)
    block = src[start:end]
    fn_src = ("def page_rows(batting_df, hist_year_range, hist_bats, hist_pos, hist_position_source_col, hist_teams,"
              " combine_split_seasons):\n" + block +
              "    return hist, team_col_for_display, team_sort_col, hist_note\n")
    exec(compile(fn_src, "original_page_block", "exec"), ns)  # noqa: S102

    old_mask = src[src.index("    mask = pd.Series(True, index=df.index)\n    for stat, min_val in mins.items():"):]
    old_mask = old_mask[:old_mask.index("    return df.loc[mask].copy()\n") + len("    return df.loc[mask].copy()\n")]
    exec(compile("def mask(df, mins):\n" + old_mask, "original_mask", "exec"), ns)  # noqa: S102
    old_score = src[src.index('    leaderboard["score"] = 0.0\n'):]
    old_score = old_score[:old_score.index("\n\n")]
    exec(compile("def score(leaderboard, weight_values, RATE_STATS=" + repr(bh.RATE_STATS) + "):\n" + old_score +
                 "\n    return leaderboard\n", "original_score", "exec"), ns)  # noqa: S102
    return types.SimpleNamespace(**ns)


class HistoryParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = _original()
        cls.old_frames = cls.old.load_data(0.0)
        cls.new_frames = bh.load_history_frames(ROOT)

    def test_load_is_identical(self):
        for old, new, label in zip(self.old_frames, self.new_frames, ("batting", "yearly", "people")):
            with self.subTest(frame=label):
                pd.testing.assert_frame_equal(old, new)

    def test_aggregations_and_labels_are_identical(self):
        batting = self.new_frames[0]
        sample = batting[(batting["yearID"] >= 2018) & (batting["yearID"] <= 2020)]
        pd.testing.assert_frame_equal(self.old.aggregate_player_year_team(sample), bh.aggregate_player_year_team(sample))
        pd.testing.assert_frame_equal(self.old.aggregate_player_year_primary_team(sample),
                                      bh.aggregate_player_year_primary_team(sample))
        yearly = self.new_frames[1]
        self.assertEqual(self.old.build_clean_player_label_map(yearly), bh.build_clean_player_label_map(yearly))

    def test_historical_explorer_rows_are_identical(self):
        batting = self.new_frames[0]
        cases = [
            ((2019, 2021), [], [], "primaryPos", ["All Teams"], False),
            ((2019, 2021), [], [], "primaryPos", ["All Teams"], True),
            ((1995, 2000), ["L"], ["SS", "2B"], "careerPrimaryPos", ["American League"], False),
            ((1995, 2000), ["R", "B"], [], "primaryPos", ["National League", "New York Yankees"], True),
        ]
        for rng, bats, pos, src_col, teams, combine in cases:
            with self.subTest(range=rng, combine=combine, teams=teams):
                old = self.old.page_rows(batting, rng, bats, pos, src_col, teams, combine)
                new = bh.historical_rows(batting, year_range=rng, bats=bats, positions=pos, position_source_col=src_col,
                                         teams=teams, combine_split_seasons=combine)
                pd.testing.assert_frame_equal(old[0], new[0])
                self.assertEqual(old[1:], new[1:])

    def test_minimums_and_score_are_identical(self):
        yearly = self.new_frames[1]
        rows = yearly[yearly["yearID"] == 2024].copy()
        mins = {"AB": 300, "HR": 10, "OPS": 0.75, "SB": 0}
        pd.testing.assert_frame_equal(self.old.mask(rows, mins), bh.apply_stat_minimums(rows, mins))
        weights = {"HR": 1.0, "RBI": 1.0, "SB": 1.0, "OPS": 2.0}
        pd.testing.assert_frame_equal(self.old.score(rows.copy(), weights), bh.add_leaderboard_score(rows.copy(), weights))

    def test_negative_control(self):
        batting = self.new_frames[0]
        old = self.old.page_rows(batting, (2019, 2021), [], [], "primaryPos", ["All Teams"], False)[0]
        new = bh.historical_rows(batting, year_range=(2019, 2021), combine_split_seasons=True)[0]
        with self.assertRaises(AssertionError):
            pd.testing.assert_frame_equal(old, new)


if __name__ == "__main__":
    unittest.main()
