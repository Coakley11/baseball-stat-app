"""Smoke tests for Sleepers filter defaults and streamlit import wiring."""

from __future__ import annotations

import ast
import py_compile
import unittest
from pathlib import Path

from fantasy_state import prepare_fantasy_sleepers_filters, prepare_fantasy_sleepers_page
from sleepers_filter_defaults import (
    default_sleepers_age_range,
    read_sleepers_canonical_filters,
    resolve_sleepers_position_age_defaults,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


class SleepersFilterDefaultsTests(unittest.TestCase):
    def test_read_and_age_defaults(self) -> None:
        session = {
            "fantasy_state": {
                "sleepers": {
                    "filters": {
                        "fantasy_market_age_range": (22, 38),
                        "fantasy_market_positions": ["OF", "SS"],
                    }
                }
            }
        }
        prepare_fantasy_sleepers_page(session)
        prepare_fantasy_sleepers_filters(session)
        resolved = resolve_sleepers_position_age_defaults(session, age_hi=50)
        self.assertEqual(resolved["default_age_range"], (22, 38))
        self.assertEqual(resolved["default_positions"], ["OF", "SS"])
        self.assertEqual(default_sleepers_age_range(session, age_hi=50), (22, 38))
        self.assertEqual(read_sleepers_canonical_filters({}), {})

    def test_streamlit_sleepers_imports_do_not_require_new_fantasy_state_symbols(self) -> None:
        text = (_REPO_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        marker = 'if active_page == "Fantasy Sleepers & Busts":'
        start = text.find(marker)
        self.assertNotEqual(start, -1)
        chunk = text[start : start + 1200]
        self.assertIn("from sleepers_filter_defaults import", chunk)
        self.assertNotIn("read_sleepers_canonical_filters,\n        render_fantasy_state_debug", chunk)

        tree = ast.parse(text)
        fantasy_import_names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "fantasy_state":
                continue
            if getattr(node, "lineno", 0) < start or getattr(node, "lineno", 0) > start + 1200:
                continue
            for alias in node.names:
                fantasy_import_names.add(alias.name)
        self.assertNotIn("default_sleepers_age_range", fantasy_import_names)
        self.assertNotIn("read_sleepers_canonical_filters", fantasy_import_names)

    def test_modules_compile(self) -> None:
        for rel in (
            "streamlit_app.py",
            "fantasy_state.py",
            "sleepers_filter_defaults.py",
            "fantasy_position_sync.py",
            "shared_draft_context.py",
            "canonical_projections.py",
        ):
            py_compile.compile(str(_REPO_ROOT / rel), doraise=True)


if __name__ == "__main__":
    unittest.main()
