"""Work every rerun repeated for nothing (profile of page navigation, 2026-10-26).

- Historical Explorer, Career Totals and League Standings force a full save on every render;
  unchanged content now skips the disk write and the cloud read + write.
- Waiver position weights derived a player's positions once per weighted position.
- The sidebar Build stamp ran two git subprocesses per rerun.
"""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd


class _St:
    def __init__(self) -> None:
        self.session_state: dict = {}


class RenderSnapshotSaveTests(unittest.TestCase):
    def _save(self, st, reason: str, state: dict) -> bool:
        import suite_user_persistence as sup

        return sup.force_autosave(st, "baseball", build_state=lambda _st: dict(state), reason=reason)

    def test_unchanged_render_snapshot_is_not_rewritten(self) -> None:
        st = _St()
        with mock.patch("suite_user_persistence.save_user_state", return_value=True) as disk, \
                mock.patch("suite_cloud_state.save_cloud_full_session", return_value=False):
            self.assertTrue(self._save(st, "historical_edit", {"active_page": "Historical Explorer", "x": 1}))
            self.assertEqual(disk.call_count, 1)
            self.assertTrue(self._save(st, "historical_edit", {"active_page": "Historical Explorer", "x": 1}))
            self.assertEqual(disk.call_count, 1)
            self.assertEqual(st.session_state["_suite_force_save_skipped_unchanged"], "historical_edit")

    def test_changed_render_snapshot_is_saved(self) -> None:
        st = _St()
        with mock.patch("suite_user_persistence.save_user_state", return_value=True) as disk, \
                mock.patch("suite_cloud_state.save_cloud_full_session", return_value=False):
            self._save(st, "fantasy_in_season_snapshot", {"x": 1})
            self._save(st, "fantasy_in_season_snapshot", {"x": 2})
            self.assertEqual(disk.call_count, 2)

    def test_explicit_saves_always_write(self) -> None:
        st = _St()
        with mock.patch("suite_user_persistence.save_user_state", return_value=True) as disk, \
                mock.patch("suite_cloud_state.save_cloud_full_session", return_value=False):
            self._save(st, "comparison_edit", {"x": 1})
            self._save(st, "comparison_edit", {"x": 1})
            self.assertEqual(disk.call_count, 2)


class WaiverPositionWeightTests(unittest.TestCase):
    def test_matches_per_position_eligibility(self) -> None:
        import fantasy_waiver_wire as ww

        weights = {"C": 3.0, "SS": 2.0, "OF": 1.5, "UTIL": 0.5, "2B": 1.0}
        rows = [
            pd.Series({"Player": "A", "Primary Position": "C"}),
            pd.Series({"Player": "B", "Primary Position": "SS", "positions": "SS/2B"}),
            pd.Series({"Player": "C", "Primary Position": "OF"}),
            pd.Series({"Player": "D", "Primary Position": "DH"}),
            pd.Series({"Player": "E"}),
        ]
        for row in rows:
            expected = max([w for p, w in weights.items() if ww._player_eligible_at(row, p)], default=0.0)
            self.assertEqual(ww._player_position_weight(row, weights), expected, row.get("Player"))


class BuildStampTests(unittest.TestCase):
    def test_git_runs_once_per_minute(self) -> None:
        import build_stamp

        build_stamp._cache.clear()
        with mock.patch("build_stamp.subprocess.check_output", side_effect=["abc1234\n", "", "zzz\n", ""]) as run:
            self.assertEqual(build_stamp.build_stamp("C:/repo"), "abc1234")
            self.assertEqual(build_stamp.build_stamp("C:/repo"), "abc1234")
            self.assertEqual(run.call_count, 2)
            (stamped_at, _head), = build_stamp._cache.values()
            with mock.patch("build_stamp.time.monotonic", return_value=stamped_at + 61):
                self.assertEqual(build_stamp.build_stamp("C:/repo"), "zzz")
        build_stamp._cache.clear()


if __name__ == "__main__":
    unittest.main()
