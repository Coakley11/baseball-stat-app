"""WEB-PREP2 parity: what the API returns equals what the Streamlit pages show.

Runs the real app with ``AppTest`` (clean workspace, deep link to the page), reads the table the
page renders and the page's own range / sort / limit from session state, then asks the API
service for the same thing and compares row for row. Slow (two full app runs)."""

import json
import os
import shutil
import unittest
from pathlib import Path

import pandas as pd

os.environ.setdefault("BASEBALL_API_PRELOAD", "0")

from baseball_api import services as svc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WS_ID = "guest"  # a preset workspace id (arbitrary ids are clamped)
WS_FILE = ROOT / "data" / "workspaces" / WS_ID / "baseball_user_state.json"


def _run_page(page: str):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=900)
    at.query_params["active_page"] = page
    at.query_params["suite_workspace"] = WS_ID
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _num(series):
    return pd.to_numeric(series, errors="coerce").round(3).tolist()


class ApiMatchesStreamlitPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._backup = WS_FILE.read_bytes() if WS_FILE.is_file() else None
        cls._dir_created = not WS_FILE.parent.exists()
        WS_FILE.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls._backup is not None:
            WS_FILE.write_bytes(cls._backup)
        elif WS_FILE.is_file():
            WS_FILE.unlink()
        if cls._dir_created and WS_FILE.parent.exists():
            shutil.rmtree(WS_FILE.parent, ignore_errors=True)

    def setUp(self):
        WS_FILE.write_text(json.dumps({"version": 1, "app": "baseball", "saved_at": "2026-01-01T00:00:00+00:00",
                                       "state": {}}), encoding="utf-8")

    def test_leaderboards(self):
        at = _run_page("Leaderboards")
        page = at.dataframe[0].value
        start, end = at.session_state["leaders_year_range_filter"]
        metric = at.session_state["leaders_sort_stat_filter"]
        limit = int(at.session_state["leaders_top_n_filter"])
        api = svc.leaderboard(start=start, end=end, metric=metric, limit=limit)
        self.assertEqual([r.player.name for r in api.rows], page["Player"].tolist())
        rows = pd.DataFrame([{**r.stats.model_dump(by_alias=True), "Score": r.score} for r in api.rows])
        for col in ("R", "AB", "H", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS", "Score"):
            with self.subTest(column=col):
                self.assertEqual(_num(rows[col]), _num(page[col]))

    def test_historical_explorer(self):
        at = _run_page("Historical Explorer")
        page = at.dataframe[0].value
        start, end = at.session_state["historical_year_range_filter"]
        metric = at.session_state["historical_sort_stat_filter"]
        order = "asc" if at.session_state["historical_sort_order_filter"] == "Ascending" else "desc"
        try:  # AppTest's session state has no .get
            combine = bool(at.session_state["historical_combine_split_seasons_filter"])
        except (KeyError, AttributeError):
            combine = False
        shown = len(page)
        page = page.head(min(shown, svc.MAX_LIMIT))  # the API caps a page of results at 200
        api = svc.season_leaders(start=start, end=end, metric=metric, order=order, limit=len(page), combine=combine)
        self.assertGreaterEqual(api.total_rows, shown)
        self.assertEqual([(r.year, r.player.name) for r in api.rows], list(zip(page["Year"].astype(int), page["Player"])))
        rows = pd.DataFrame([r.stats.model_dump(by_alias=True) for r in api.rows])
        for col in ("R", "AB", "H", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"):
            with self.subTest(column=col):
                self.assertEqual(_num(rows[col]), _num(page[col]))
        self.assertEqual([r.team.season_name if r.team else None for r in api.rows], page["Team"].tolist())


if __name__ == "__main__":
    unittest.main()
