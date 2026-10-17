"""WEB-M2 API contracts (R1–R8 of the web handoff) on the real Lahman data: catalog, answers,
plain-text qualification, stat names, paging and CSV, one-player rankings, and
the optional player summary / 503 while loading. Parity with the running Streamlit pages is in
``test_web_prep_api_parity.py``."""

import ast
import io
import os
import re
import unittest
from pathlib import Path

import pandas as pd

os.environ.setdefault("BASEBALL_API_PRELOAD", "0")

from starlette.testclient import TestClient  # noqa: E402

import rate_stat_qualification as rsq  # noqa: E402
import u1_answers as u1a  # noqa: E402
from baseball_api import schemas as s  # noqa: E402
from baseball_api import services as svc  # noqa: E402
from baseball_api.app import app  # noqa: E402
from baseball_api.openapi import build_openapi  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
CLIENT = TestClient(app)


def get(path, **params):
    r = CLIENT.get("/api/v1" + path, params=params)
    assert r.status_code == 200, r.text
    return r


def page_literal(pattern):
    """A literal from the Streamlit page source (the control's own option list)."""
    m = re.search(pattern, APP_SRC, re.S)
    assert m, pattern
    return ast.literal_eval(m.group(1))


class CatalogTests(unittest.TestCase):  # R1
    @classmethod
    def setUpClass(cls):
        cls.cat = s.Catalog.model_validate(get("/catalog").json())
        cls.data = svc.STORE.get()

    def test_option_lists_are_the_streamlit_controls(self):
        c = self.cat
        self.assertEqual(c.historical.metrics, page_literal(r"sort_options_hist = (\[.*?\])"))
        self.assertEqual(c.leaderboards.metrics, page_literal(r"leaders_sort_options = (\[.*?\])"))
        self.assertEqual(c.leaderboards.weight_stats, page_literal(r"\n    weight_stats = (\[.*?\])"))
        self.assertEqual(c.leaderboards.defaults.weights, page_literal(r"_default_weights = (\{.*?\})"))
        lo, hi = re.search(r'"Show Top N Players",\s*min_value=(\d+),\s*max_value=(\d+)', APP_SRC).groups()
        self.assertEqual(c.leaderboards.limit_bounds, [int(lo), int(hi)])
        self.assertEqual(c.leaderboards.defaults.limit, int(re.search(r'init_state_once\("leaders_top_n_filter", (\d+)\)', APP_SRC).group(1)))
        wlo, whi, step = re.search(r'f"Weight for \{stat\}",\s*min_value=([\d.]+),\s*max_value=([\d.]+),\s*step=([\d.]+)', APP_SRC).groups()
        self.assertEqual((c.leaderboards.weight_bounds, c.leaderboards.weight_step), ([float(wlo), float(whi)], float(step)))
        self.assertEqual([o.label for o in c.historical.filters.position_sources],
                         page_literal(r'validate_state_option\(\s*"historical_position_filter_mode",\s*(\[.*?\])'))
        # the page's own builders, verbatim
        b = self.data.batting
        self.assertEqual([o.value for o in c.historical.filters.bats],
                         sorted([x for x in b["bats"].dropna().unique() if str(x).strip() != ""]))
        for source, col in (("season", "primaryPos"), ("career", "careerPrimaryPos")):
            self.assertEqual(c.historical.filters.positions_by_source[source],
                             sorted(x for x in b[col].dropna().unique() if str(x).strip() != "" and x not in ("PH", "PR")))
        self.assertIn('hist_team_options = ["All Teams", "American League", "National League"] + actual_team_names', APP_SRC)
        franchises = sorted(set(b["teamName"].dropna().astype(str)).intersection(set(svc.bh.team_id_to_name.values())))
        self.assertEqual([o.value for o in c.historical.filters.teams], ["All Teams", "American League", "National League", *franchises])

    def test_defaults_are_what_the_endpoints_use(self):
        d = self.cat.historical.defaults
        self.assertIn('validate_state_option("historical_sort_stat_filter", sort_options_hist, "HR")', APP_SRC)
        self.assertIn('validate_state_option("leaders_sort_stat_filter", leaders_sort_options, "score")', APP_SRC)
        self.assertIn("default_start_hist = max(year_min, 2010)", APP_SRC)
        self.assertIn("default_start_leaders = max(year_min, 2020)", APP_SRC)
        plain = get("/seasons").json()
        explicit = get("/seasons", start=d.start, end=d.end, metric=d.metric, order=d.order, combine=d.split == "combined",
                       bats=",".join(d.bats), positions=",".join(d.positions), position_source=d.position_source,
                       teams=",".join(d.teams), limit=self.cat.leaderboards.defaults.limit).json()
        self.assertEqual((plain["start"], plain["end"], plain["metric"]["key"], plain["order"], plain["split_mode"]),
                         (d.start, d.end, d.metric, d.order, d.split))
        self.assertEqual(plain["rows"], explicit["rows"])
        self.assertEqual(plain["total_rows"], explicit["total_rows"])
        ld = self.cat.leaderboards.defaults
        board = get("/leaderboards").json()
        self.assertEqual((board["start"], board["end"], board["metric"]["key"], board["weights"], len(board["rows"])),
                         (ld.start, ld.end, ld.metric, ld.weights, ld.limit))
        self.assertEqual((self.cat.seasons.first, self.cat.seasons.last), self.data.years)

    def test_columns_are_the_page_tables_and_resolve_in_rows(self):
        def resolve(row, field):
            for part in field.split("."):
                row = row[part]
            return row

        for name, path in (("historical", "/seasons"), ("leaderboards", "/leaderboards")):
            with self.subTest(page=name):
                cols = getattr(self.cat, name).columns
                csv_header = CLIENT.get("/api/v1" + path, params={"format": "csv", "limit": 1}).text.splitlines()[0]
                self.assertEqual([c.label for c in cols], csv_header.split(","), "same headers as the page / CSV")
                row = get(path, limit=1).json()["rows"][0]
                for c in cols:
                    resolve(row, c.field)  # every field exists in a real row
                    if c.metric:
                        self.assertIn(c.metric, {m.key for m in self.cat.metrics})

    def test_every_team_value_is_accepted(self):
        for opt in self.cat.historical.filters.teams:
            with self.subTest(team=opt.value):
                r = CLIENT.get("/api/v1/seasons", params={"teams": opt.value, "limit": 1})
                self.assertEqual(r.status_code, 200)
                self.assertGreater(r.json()["total_rows"], 0, "a team option that matches no season")

    def test_metric_names_are_plain_language(self):  # R5
        names = {m.key: m.name for m in self.cat.metrics}
        for key, name in u1a.STAT_NAMES.items():
            self.assertEqual(names[key], name)
        self.assertEqual((names["HR"], names["BA"], names["score"], names["G"], names["yearID"]),
                         ("home runs", "batting average", "score", "games", "season"))
        keys = set(names)
        self.assertTrue(set(self.cat.historical.metrics) <= keys and set(self.cat.leaderboards.metrics) <= keys)
        self.assertEqual(get("/seasons", metric="BA", limit=1).json()["metric"]["name"], "batting average")


class AnswerTests(unittest.TestCase):  # R2, R3
    def test_season_answer_is_the_page_answer_for_the_same_rows(self):
        for metric, order in (("HR", "desc"), ("OPS", "desc"), ("SB", "asc")):
            with self.subTest(metric=metric):
                r = s.SeasonLeadersResult.model_validate(get("/seasons", metric=metric, order=order).json())
                q = svc._season_query(metric=metric, order=order)
                page = u1a.season_answer(svc._hist_display(q), metric, q.years, ascending=order == "asc",
                                         team_col=q.team_col, qualification=r.qualification.summary)
                self.assertEqual((r.answer.headline, r.answer.body, r.answer.context),
                                 (page["headline"], page["body"], page["context"]))
                self.assertEqual(r.headline, r.answer.headline)
                self.assertEqual([u1a.TILE_LABELS.get(k, k) for k in r.answer.tile_metrics], [t[0] for t in page["tiles"]])
                top = r.rows[0].stats.model_dump(by_alias=True)
                self.assertEqual([u1a.fmt_stat(k, top[k]) for k in r.answer.tile_metrics], [t[1] for t in page["tiles"]])

    def test_leaderboard_answer_has_no_page_control_wording(self):
        for metric, weights in (("score", None), ("score", "HR:2,OPS:1"), ("OBP", None), ("HR", None)):
            with self.subTest(metric=metric, weights=weights):
                params = {"metric": metric, **({"weights": weights} if weights else {})}
                a = get("/leaderboards", **params).json()["answer"]
                text = a["headline"] + " " + a["body"]
                for words in ("Explore more", "Change the", "under ", "slider", "expander", "click"):
                    self.assertNotIn(words, text)
                parsed = {k: float(v) for k, v in (part.split(":") for part in weights.split(","))} if weights else None
                _d, years, w, qual, board = svc._board(metric=metric, weights=parsed)
                page = u1a.leaderboard_answer(board, metric, years, weights=w, qualification=qual.summary)
                self.assertEqual(a["headline"], page["headline"])
                expected = page["body"].replace(" Change the weights under Explore more.", "")
                self.assertEqual(a["body"], expected)
                self.assertEqual(a["context"], f"Ranked by {u1a.stat_name(metric)}")

    def test_empty_result_has_no_answer(self):
        r = get("/seasons", start=2024, end=2024, metric="OPS", min_ab=900).json()
        self.assertEqual((r["total_rows"], r["answer"], r["headline"]), (0, None, None))


class QualificationTextTests(unittest.TestCase):  # R4
    CASES = [
        ("/seasons", {"metric": "OPS"}), ("/seasons", {"metric": "BA", "min_ab": 300}),
        ("/seasons", {"metric": "OBP", "qualified": "false"}), ("/seasons", {"metric": "SLG", "start": 2019, "end": 2021}),
        ("/leaderboards", {"metric": "OBP"}), ("/leaderboards", {"metric": "OPS", "start": 1990, "end": 2025}),
        ("/leaderboards", {"metric": "BA", "min_ab": 1000}), ("/seasons", {"metric": "HR"}), ("/leaderboards", {}),
    ]

    def test_summary_is_the_page_chip_and_nothing_is_markdown(self):
        for path, params in self.CASES:
            with self.subTest(path=path, **params):
                r = get(path, **params).json()
                q = r["qualification"]
                metric = r["metric"]["key"]
                session = {rsq.ab_min_key("p"): q["min_ab"]}
                if q["mode"] == "manual":
                    rsq.mark_manual(session, "p")
                page_chip = u1a.qualification_text(session, "p", metric, (r["start"], r["end"]), per_season=path == "/seasons")
                self.assertEqual(q["summary"], page_chip)
                for text in (q["summary"], q["explanation"] or ""):
                    for mark in ("**", "*", "_", "`", "Stat minimum filters", "Change it"):
                        self.assertNotIn(mark, text)
                if metric in u1a.RATE_STATS:
                    self.assertTrue(q["summary"] and q["explanation"])
                    if q["min_ab"]:
                        self.assertIn(f"{q['min_ab']:,} AB", q["explanation"])
                else:
                    self.assertEqual((q["summary"], q["explanation"]), ("", None))

    def test_examples_from_the_handoff(self):
        q = get("/leaderboards", metric="OBP", start=2020, end=2025).json()["qualification"]
        self.assertEqual(q["summary"], f"Qualified hitters · at least {q['min_ab']:,} AB over 2020–2025")
        q = get("/seasons", metric="OPS", start=2023, end=2023).json()["qualification"]
        self.assertEqual(q["summary"], "Qualified seasons · at least 437 AB in the season")
        q = get("/seasons", metric="OPS", min_ab=200).json()["qualification"]
        self.assertEqual(q["summary"], "Minimum you set · at least 200 AB in the season")
        q = get("/seasons", metric="OPS", qualified="false").json()["qualification"]
        self.assertEqual(q["summary"], "No at-bat minimum · part-time players can lead this list")
        self.assertIn("players with very few at-bats", q["explanation"])

    def test_streamlit_caption_is_unchanged(self):
        info = rsq.qualified_ab({2020: 60, 2021: 162}, (2020, 2021), span=False)
        self.assertEqual(rsq.qualification_caption({"rate": True, "mode": "auto", "value": 437}, info, "BA"),
                         "**Qualified hitters only:** ranking by BA requires at least **437 AB** (about 2.7 AB per team "
                         "game of a full season, close to MLB's batting-title rule). Change it under *Stat minimum "
                         "filters*. Shortened seasons in range (2020) need a lower minimum to appear.")
        self.assertEqual(rsq.qualification_explanation({"rate": True, "mode": "auto", "value": 437}, info, "batting average"),
                         "Qualified hitters only: ranking by batting average requires at least 437 AB (about 2.7 AB per "
                         "team game of a full season, close to MLB's batting-title rule). Shortened seasons in range "
                         "(2020) need a lower minimum to appear.")


class PagingAndCsvTests(unittest.TestCase):  # R6
    def test_offset_pages_tile_the_full_ranking(self):
        for path, params in (("/seasons", {"metric": "OPS"}), ("/leaderboards", {"metric": "HR"})):
            with self.subTest(path=path):
                whole = get(path, limit=150, **params).json()
                pages = [get(path, limit=50, offset=o, **params).json() for o in (0, 50, 100)]
                self.assertEqual([r for p in pages for r in p["rows"]], whole["rows"])
                self.assertEqual([p["offset"] for p in pages], [0, 50, 100])
                self.assertEqual([r["rank"] for r in pages[2]["rows"]][:2], [101, 102])
                past = get(path, offset=whole["total_rows"], **params).json()
                self.assertEqual(past["rows"], [])
                self.assertEqual(past["answer"], whole["answer"], "the answer describes the whole ranking, not a page")
        r = CLIENT.get("/api/v1/seasons", params={"offset": -1})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "invalid_parameter"))

    def test_historical_csv_is_every_ranked_row_in_page_columns(self):
        r = CLIENT.get("/api/v1/seasons", params={"metric": "OPS", "format": "csv"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/csv"))
        self.assertIn('filename="historical_explorer.csv"', r.headers["content-disposition"])
        df = pd.read_csv(io.StringIO(r.text))
        self.assertEqual(list(df.columns), ["Year", "Player", "Bats", "Primary Position", "Team",
                                            "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"])
        j = get("/seasons", metric="OPS", limit=200).json()
        self.assertEqual(len(df), j["total_rows"])
        self.assertEqual(list(zip(df["Year"].head(200), df["Player"].head(200))), [(x["year"], x["player"]["name"]) for x in j["rows"]])
        self.assertEqual(df["OPS"].head(200).tolist(), [x["stats"]["OPS"] for x in j["rows"]])
        self.assertTrue((df["AB"] >= j["qualification"]["min_ab"]).all())
        page = CLIENT.get("/api/v1/seasons", params={"metric": "OPS", "format": "csv", "offset": 10, "limit": 5}).text
        self.assertEqual(page.splitlines()[1:], r.text.splitlines()[11:16])

    def test_leaderboard_csv_columns_and_limit(self):
        r = CLIENT.get("/api/v1/leaderboards", params={"format": "csv", "limit": 25})
        self.assertIn('filename="leaderboards.csv"', r.headers["content-disposition"])
        df = pd.read_csv(io.StringIO(r.text))
        self.assertEqual(list(df.columns), ["Player", "Bats", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB",
                                            "BA", "OBP", "SLG", "OPS", "Score"])
        j = get("/leaderboards", limit=25).json()
        self.assertEqual(df["Player"].tolist(), [x["player"]["name"] for x in j["rows"]])
        self.assertEqual(df["Score"].tolist(), [round(x["score"], 1) for x in j["rows"]])
        everyone = pd.read_csv(io.StringIO(CLIENT.get("/api/v1/leaderboards", params={"format": "csv"}).text))
        self.assertEqual(len(everyone), j["total_rows"])


class OnePlayerTests(unittest.TestCase):  # R8
    def test_player_rows_are_the_page_rows_filtered_to_the_player(self):
        for pid, metric, extra in (("judgeaa01", "HR", {"start": 2016, "end": 2025}),
                                   ("bondsba01", "OPS", {"start": 1986, "end": 2007}),
                                   ("ruthba01", "BA", {"start": 1914, "end": 1935, "combine": True}),
                                   ("ramirma02", "OPS", {"start": 1993, "end": 2011, "minimums": {"HR": 30}})):
            with self.subTest(player=pid, metric=metric):
                r = svc.season_leaders(player_id=pid, metric=metric, limit=200, **extra)
                full = svc._season_query(metric=metric, **extra)
                page = full.ranked[full.ranked["playerID"] == pid]
                self.assertGreater(len(page), 0)
                self.assertEqual([(x.year, x.stats.AB, x.stats.HR) for x in r.rows],
                                 list(zip(page["yearID"], page["AB"].astype(float), page["HR"].astype(float))))
                self.assertEqual([x.rank for x in r.rows], list(range(1, len(page) + 1)))
                self.assertEqual((r.total_rows, r.ranked_rows, r.player_id), (len(page), len(page), pid))
                self.assertEqual(r.qualification, svc.season_leaders(metric=metric, limit=1, **extra).qualification)
                self.assertTrue(r.answer.headline.startswith(r.rows[0].player.name))

    def test_below_minimum_seasons_are_marked_and_unranked(self):
        r = svc.season_leaders(player_id="judgeaa01", metric="OPS", include_below_minimum=True, limit=200)
        ranked = [x for x in r.rows if x.meets_minimum]
        below = [x for x in r.rows if not x.meets_minimum]
        self.assertTrue(ranked and below)
        self.assertEqual(r.rows, ranked + below, "ranked seasons first")
        self.assertTrue(all(x.rank is None for x in below) and all(x.rank is not None for x in ranked))
        self.assertTrue(all(x.stats.AB < r.qualification.min_ab for x in below))
        self.assertEqual((r.ranked_rows, r.total_rows), (len(ranked), len(r.rows)))
        plain = svc.season_leaders(player_id="judgeaa01", metric="OPS", limit=200)
        self.assertEqual(plain.rows, ranked)
        self.assertEqual(sorted(x.year for x in r.rows),
                         [x.year for x in svc.player_seasons("judgeaa01").seasons], "every season, once")

    def test_player_defaults_to_the_career_and_errors_are_predictable(self):
        r = get("/seasons", player_id="ruthba01").json()
        self.assertEqual((r["start"], r["end"]), (1914, 1935))
        bad = CLIENT.get("/api/v1/seasons", params={"player_id": "nobody99"})
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (404, "player_not_found"))
        bad = CLIENT.get("/api/v1/seasons", params={"include_below_minimum": "true"})
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (422, "invalid_parameter"))
        bad = CLIENT.get("/api/v1/seasons", params={"min_AB": 100})
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (422, "invalid_parameter"))


class OptionalTests(unittest.TestCase):
    def test_player_summary(self):
        r = s.PlayerSummary.model_validate(get("/players/judgeaa01").json())
        self.assertEqual(r, s.PlayerSummary.model_validate(get("/players/judgeaa01/seasons").json()["player"]))
        r = CLIENT.get("/api/v1/players/nobody99")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "player_not_found"))

    def test_503_with_retry_after_while_loading(self):
        loading = svc.HistoryStore()
        loading._lock.acquire()  # stands in for the startup preload holding the load lock
        original = svc.STORE
        try:
            svc.STORE = loading
            for path in ("/api/v1/seasons", "/api/v1/catalog", "/api/v1/players/search?q=judge"):
                with self.subTest(path=path):
                    r = CLIENT.get(path)
                    self.assertEqual((r.status_code, r.json()["error"]["code"]), (503, "data_unavailable"))
                    self.assertEqual(r.headers["retry-after"], str(svc.RETRY_AFTER_SECONDS))
            self.assertEqual(CLIENT.get("/api/v1/health").status_code, 200, "health never waits on the data")
            self.assertFalse(svc.health(store=loading).data_loaded)
        finally:
            svc.STORE = original
            loading._lock.release()
        missing = svc.HistoryStore(base_dir=ROOT / "no_such_dir")
        with self.assertRaises(svc.ApiError) as ctx:
            missing.get(wait=False)
        self.assertIsNone(ctx.exception.details, "missing data is not a retry")


class OpenApiTests(unittest.TestCase):
    def test_new_contracts_are_described(self):
        spec = build_openapi()
        paths, comps = spec["paths"], spec["components"]["schemas"]
        for p in ("/api/v1/catalog", "/api/v1/players/{player_id}"):
            self.assertIn(p, paths)
        params = {x["name"] for x in paths["/api/v1/seasons"]["get"]["parameters"]}
        self.assertTrue({"offset", "format", "player_id", "include_below_minimum"} <= params)
        self.assertTrue({"offset", "format"} <= {x["name"] for x in paths["/api/v1/leaderboards"]["get"]["parameters"]})
        self.assertIn("text/csv", paths["/api/v1/seasons"]["get"]["responses"]["200"]["content"])
        self.assertIn("Retry-After", paths["/api/v1/seasons"]["get"]["responses"]["503"]["headers"])
        for model, fields in (("Catalog", {"seasons", "metrics", "historical", "leaderboards"}),
                              ("SeasonLeadersResult", {"answer", "offset", "ranked_rows", "player_id"}),
                              ("LeaderboardResult", {"answer", "offset"}), ("Qualification", {"summary", "explanation"}),
                              ("MetricInfo", {"name"}), ("SeasonRow", {"meets_minimum"}),
                              ("SeasonAnswer", {"headline", "body", "context", "tile_metrics"})):
            self.assertTrue(fields <= set(comps[model]["properties"]), model)
        self.assertEqual(comps["SeasonRow"]["properties"]["rank"]["anyOf"], [{"type": "integer"}, {"type": "null"}])

    def test_real_responses_match_the_schema_exactly(self):
        """Every required property is present and nothing undeclared is sent, all the way down, so
        generated TypeScript types neither miss fields nor mark always-sent ones optional."""
        spec = build_openapi()
        comps = spec["components"]["schemas"]

        def walk(value, schema, where):
            if "$ref" in schema:
                schema = comps[schema["$ref"].rsplit("/", 1)[1]]
            if "anyOf" in schema:
                options = [o for o in schema["anyOf"] if not (value is None and o.get("type") == "null")]
                if value is None:
                    self.assertTrue(any(o.get("type") == "null" for o in schema["anyOf"]), where)
                    return
                options = [o for o in options if o.get("type") != "null"]
                return walk(value, options[0], where)
            if isinstance(value, dict) and "properties" in schema:
                props = schema["properties"]
                self.assertEqual(set(value) - set(props), set(), f"undeclared at {where}")
                self.assertEqual(set(schema.get("required", [])) - set(value), set(), f"missing at {where}")
                for k, v in value.items():
                    walk(v, props[k], f"{where}.{k}")
            elif isinstance(value, list) and "items" in schema:
                for i, v in enumerate(value[:5]):
                    walk(v, schema["items"], f"{where}[{i}]")

        for path, params in (("/catalog", {}), ("/seasons", {"metric": "OPS", "limit": 3}),
                             ("/seasons", {"player_id": "judgeaa01", "metric": "OPS", "include_below_minimum": "true"}),
                             ("/leaderboards", {"limit": 3}), ("/players/search", {"q": "judge"}), ("/players/judgeaa01", {}),
                             ("/players/judgeaa01/seasons", {}), ("/health", {})):
            with self.subTest(path=path, **params):
                op = spec["paths"]["/api/v1" + path.replace("judgeaa01", "{player_id}")]["get"]
                walk(get(path, **params).json(), op["responses"]["200"]["content"]["application/json"]["schema"], path)
        err = CLIENT.get("/api/v1/seasons", params={"metric": "WAR"}).json()
        walk(err, {"$ref": "#/components/schemas/ErrorResponse"}, "error")
        walk(CLIENT.get("/api/v1/nope").json(), {"$ref": "#/components/schemas/ErrorResponse"}, "error-no-details")
        for broken in ({"error": {"code": "not_found"}}, {"error": {"code": "not_found", "message": "x", "extra": 1}}):
            with self.assertRaises(AssertionError):  # negative control: the walk does catch both
                walk(broken, {"$ref": "#/components/schemas/ErrorResponse"}, "control")


if __name__ == "__main__":
    unittest.main()
