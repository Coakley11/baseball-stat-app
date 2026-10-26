"""WEB-PREP2 parity: what the API returns equals what the Streamlit pages show.

Runs the real app with ``AppTest`` (clean workspace, deep link to the page), reads the table the
page renders and the page's own range / sort / limit from session state, then asks the API
service for the same thing and compares row for row. Slow (two full app runs)."""

import html
import io
import json
import os
import re
import shutil
import unittest
from pathlib import Path

import pandas as pd

os.environ.setdefault("BASEBALL_API_PRELOAD", "0")

from baseball_api import services as svc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WS_ID = "guest"  # a preset workspace id (arbitrary ids are clamped)
WS_FILE = ROOT / "data" / "workspaces" / WS_ID / "baseball_user_state.json"


def _run_page(page: str, **selects):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=900)
    at.query_params["active_page"] = page
    at.query_params["suite_workspace"] = WS_ID
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    for key, value in selects.items():
        at.selectbox(key=key).set_value(value).run()
        assert not at.exception, [e.value for e in at.exception]
    return at


def _html_text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _answer_card(at):
    """The page's answer card (ui_hierarchy.answer_card), tiles and chips as plain text."""
    out = {"kicker": "", "headline": "", "body": "", "tiles": [], "chips": []}
    for m in at.markdown:
        v = m.value
        if 'class="u1-answer' in v:
            for part in ("kicker", "headline"):
                found = re.search(rf'class="u1-{part}">(.*?)</div>', v, re.S)
                out[part] = _html_text(found.group(1)) if found else ""
            found = re.search(r'class="u1-body">(.*?)</p>', v, re.S)
            out["body"] = _html_text(found.group(1)) if found else ""
        elif 'class="u1-tiles"' in v and not out["tiles"]:
            out["tiles"] = [(_html_text(a), _html_text(b)) for a, b in
                            re.findall(r'class="u1-l">(.*?)</div><div class="u1-v">(.*?)</div>', v, re.S)]
        elif 'class="u1-chips"' in v:
            out["chips"] += [_html_text(c) for c in re.findall(r'class="u1-chip[^"]*">(.*?)</span>', v, re.S)]
    return out


def _metric_value(at, label):
    return next(m.value for m in at.metric if m.label == label)


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


    # ---- WEB-M2: answers (R2/R3), qualification chips (R4), CSV export (R6)

    def _he_query(self, at):
        start, end = at.session_state["historical_year_range_filter"]
        metric = at.session_state["historical_sort_stat_filter"]
        order = "asc" if at.session_state["historical_sort_order_filter"] == "Ascending" else "desc"
        return dict(start=start, end=end, metric=metric, order=order)

    def _check_he_answer(self, at):
        card = _answer_card(at)
        q = self._he_query(at)
        api = svc.season_leaders(limit=1, **q)
        self.assertEqual((api.answer.headline, api.answer.body, api.answer.context),
                         (card["headline"], card["body"], card["kicker"]))
        self.assertEqual([svc.u1a.TILE_LABELS.get(k, k) for k in api.answer.tile_metrics], [t[0] for t in card["tiles"]])
        top = api.rows[0].stats.model_dump(by_alias=True)
        self.assertEqual([svc.u1a.fmt_stat(k, top[k]) for k in api.answer.tile_metrics], [t[1] for t in card["tiles"]])
        self.assertEqual([api.qualification.summary] if api.qualification.summary else [], card["chips"])
        return api

    def test_historical_explorer_answer_chip_and_csv(self):
        at = _run_page("Historical Explorer")
        api = self._check_he_answer(at)
        csv = svc.season_leaders_csv(**self._he_query(at))
        page = at.dataframe[0].value
        lines = csv.splitlines()
        self.assertEqual(lines[: len(page) + 1], page.to_csv(index=False).splitlines(), "CSV = the page's table, row for row")
        self.assertEqual(len(lines) - 1, int(_metric_value(at, "Rows Returned")))
        self.assertEqual(len(lines) - 1, api.total_rows)

    def test_historical_explorer_rate_stat_answer_and_chip(self):
        at = _run_page("Historical Explorer", historical_sort_stat_filter="OPS")
        api = self._check_he_answer(at)
        self.assertTrue(api.qualification.summary.startswith("Qualified seasons · at least "))

    def _check_board(self, at):
        start, end = at.session_state["leaders_year_range_filter"]
        metric = at.session_state["leaders_sort_stat_filter"]
        limit = int(at.session_state["leaders_top_n_filter"])
        card = _answer_card(at)
        api = svc.leaderboard(start=start, end=end, metric=metric, limit=limit)
        self.assertEqual(api.answer.headline, card["headline"])
        self.assertEqual(api.answer.context, card["kicker"])
        page_body = card["body"].replace(" Change the weights under Explore more.", "")
        self.assertEqual(api.answer.body, page_body)
        self.assertEqual([api.qualification.summary] if api.qualification.summary else [], card["chips"])
        csv = svc.leaderboard_csv(start=start, end=end, metric=metric, limit=limit)
        self.assertEqual(csv.splitlines(), at.dataframe[0].value.to_csv(index=False).splitlines())
        return api, card

    def test_leaderboards_answer_and_csv(self):
        at = _run_page("Leaderboards")
        api, card = self._check_board(at)
        self.assertEqual(api.metric.key, "score")
        self.assertIn("Change the weights under Explore more.", card["body"], "the page keeps its own hint")

    def test_leaderboards_rate_stat_answer_and_chip(self):
        at = _run_page("Leaderboards", leaders_sort_stat_filter="OBP")
        api, _card = self._check_board(at)
        self.assertTrue(api.qualification.summary.startswith("Qualified hitters · at least "))


if __name__ == "__main__":
    unittest.main()
