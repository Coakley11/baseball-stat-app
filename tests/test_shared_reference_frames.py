"""Shared read-only reference tables (memory fix, 2026-11-22).

One process-wide copy of Lahman batting / yearly / people replaces a copy per script run. Sharing is only safe
if nothing can change the shared object, so every in-place change must raise and leave it untouched, while
everything derived from it stays an ordinary writable DataFrame.
"""

from __future__ import annotations

import pickle
import re
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from shared_reference_frames import SharedReadOnlyError, freeze, is_shared

ROOT = Path(__file__).resolve().parents[1]


def _base() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"], "c": [1.5, 2.5, np.nan]})


MUTATIONS = {
    "set new column": lambda s: s.__setitem__("d", 1),
    "set existing column": lambda s: s.__setitem__("a", 0),
    "loc value": lambda s: s.loc.__setitem__((0, "a"), 9),
    "loc new column": lambda s: s.loc.__setitem__((slice(None), "d"), 1),
    "iloc value": lambda s: s.iloc.__setitem__((0, 0), 9),
    "at value": lambda s: s.at.__setitem__((0, "a"), 9),
    "columns assign": lambda s: setattr(s, "columns", ["x", "y", "z"]),
    "index assign": lambda s: setattr(s, "index", [7, 8, 9]),
    "del column": lambda s: s.__delitem__("a"),
    "insert": lambda s: s.insert(0, "n", 1),
    "pop": lambda s: s.pop("a"),
    "update": lambda s: s.update(pd.DataFrame({"a": [9.0, 9.0, 9.0]})),
    "fillna inplace": lambda s: s.fillna(0, inplace=True),
    "sort_values inplace": lambda s: s.sort_values("a", ascending=False, inplace=True),
    "drop inplace": lambda s: s.drop(columns=["a"], inplace=True),
    "rename inplace": lambda s: s.rename(columns={"a": "z"}, inplace=True),
    "reset_index inplace": lambda s: s.reset_index(inplace=True),
    "set_index inplace": lambda s: s.set_index("a", inplace=True),
    "drop_duplicates inplace": lambda s: s.drop_duplicates(inplace=True),
    "replace inplace": lambda s: s.replace(1, 5, inplace=True),
    "dropna inplace": lambda s: s.dropna(inplace=True),
    "sort_index inplace": lambda s: s.sort_index(ascending=False, inplace=True),
}


class SharedFramesAreReadOnly(unittest.TestCase):
    def test_every_in_place_change_raises_and_leaves_the_table_untouched(self) -> None:
        for label, mutate in MUTATIONS.items():
            with self.subTest(label):
                shared, ref = freeze(_base()), _base()
                with self.assertRaises((SharedReadOnlyError, ValueError)):
                    mutate(shared)
                self.assertTrue(pd.DataFrame(shared).equals(ref))
                self.assertEqual(list(shared.columns), list(ref.columns))
                self.assertEqual(list(shared.index), list(ref.index))

    def test_derived_results_are_ordinary_writable_frames(self) -> None:
        shared = freeze(_base())
        derived = [shared.copy(), shared[shared["a"] > 1], shared[["a", "c"]], shared.merge(_base(), on="a"),
                   shared.rename(columns={"a": "z"}), shared.set_index("a"), shared.sort_values("a"),
                   shared.assign(d=1), shared.fillna(0)]
        for d in derived:
            self.assertFalse(is_shared(d))
            self.assertIsInstance(d, pd.DataFrame)
        edited = shared.copy()
        edited["d"] = 1
        edited.loc[0, "a"] = 9
        self.assertEqual(shared["a"].tolist(), [1, 2, 3])
        self.assertNotIn("d", shared.columns)

    def test_no_data_copy_and_pickles_as_a_plain_frame(self) -> None:
        base = _base()
        shared = freeze(base)
        self.assertTrue(np.shares_memory(shared["a"].to_numpy(), base["a"].to_numpy()))
        self.assertIs(type(pickle.loads(pickle.dumps(shared))), pd.DataFrame)
        self.assertIsNone(freeze(None))

    def test_the_app_loads_the_reference_tables_once_shared_and_frozen(self) -> None:
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        block = src[src.index("def load_data(") - 80: src.index("def load_data(") + 1400]
        self.assertRegex(block, r"@st\.cache_resource\(show_spinner=False, max_entries=2\)\s*\ndef load_data\(")
        self.assertIn("freeze(df) for df in _history.load_history_frames", block)
        self.assertTrue(re.search(r"^batting_df, yearly_df, people_df = load_data\(HOF_CACHE_KEY\)", src, re.M))


if __name__ == "__main__":
    unittest.main()
