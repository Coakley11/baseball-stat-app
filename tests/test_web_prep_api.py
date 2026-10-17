"""WEB-PREP2: the read-only API proof — typed responses, predictable errors, OpenAPI, the security
boundary, and execution without Streamlit, session state or persistence writes."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

os.environ.setdefault("BASEBALL_API_PRELOAD", "0")

from starlette.testclient import TestClient  # noqa: E402

from baseball_api import schemas as s  # noqa: E402
from baseball_api import services as svc  # noqa: E402
from baseball_api.app import app  # noqa: E402
from baseball_api.openapi import build_openapi  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLIENT = TestClient(app)


def get(path, **params):
    return CLIENT.get(path, params=params)


class ResponseSchemaTests(unittest.TestCase):
    def test_search_seasons_leaderboards_validate_against_their_models(self):
        cases = [
            ("/api/v1/players/search", {"q": "judge"}, s.PlayerSearchResult),
            ("/api/v1/players/judgeaa01/seasons", {"start": 2022, "end": 2024}, s.PlayerSeasonsResult),
            ("/api/v1/seasons", {"start": 2024, "end": 2024, "metric": "OPS", "limit": 5}, s.SeasonLeadersResult),
            ("/api/v1/leaderboards", {"start": 2020, "end": 2025, "limit": 5}, s.LeaderboardResult),
            ("/api/v1/health", {}, s.HealthInfo),
        ]
        for path, params, model in cases:
            with self.subTest(path=path):
                r = get(path, **params)
                self.assertEqual(r.status_code, 200, r.text)
                model.model_validate(r.json())
                self.assertIn("business;dur=", r.headers["server-timing"])

    def test_identity_is_the_player_id_not_the_name(self):
        r = get("/api/v1/players/search", q="aaron judge").json()
        first = r["results"][0]["player"]
        self.assertEqual(first["player_id"], "judgeaa01")
        seasons = get(f"/api/v1/players/{first['player_id']}/seasons", start=2022, end=2022).json()
        self.assertEqual(seasons["seasons"][0]["stats"]["HR"], 62.0)
        self.assertEqual(seasons["seasons"][0]["team"]["team_id"], "NYY")

    def test_qualification_and_metric_metadata_travel_with_rankings(self):
        r = get("/api/v1/seasons", start=2024, end=2024, metric="OPS", limit=3).json()
        self.assertEqual(r["metric"], {"key": "OPS", "label": "OPS", "name": "OPS", "kind": "rate", "higher_is_better": True,
                                       "decimals": 3})
        self.assertTrue(r["qualification"]["applies"])
        self.assertEqual(r["qualification"]["mode"], "auto")
        self.assertGreater(r["qualification"]["min_ab"], 400)
        self.assertIn("Qualified hitters only", r["qualification"]["text"])
        self.assertTrue(all(row["stats"]["AB"] >= r["qualification"]["min_ab"] for row in r["rows"]))
        manual = get("/api/v1/seasons", start=2024, end=2024, metric="OPS", limit=3, min_ab=100).json()["qualification"]
        self.assertEqual((manual["mode"], manual["min_ab"]), ("manual", 100))
        counting = get("/api/v1/leaderboards", start=2021, end=2023, metric="HR", limit=1).json()["qualification"]
        self.assertFalse(counting["applies"])

    def test_no_html_or_streamlit_markup_in_payloads(self):
        for path, params in (("/api/v1/seasons", {"limit": 5}), ("/api/v1/leaderboards", {"limit": 5})):
            body = get(path, **params).text
            self.assertNotIn("<div", body)
            self.assertNotIn("st.", body)


class ErrorContractTests(unittest.TestCase):
    def expect(self, r, status, code):
        self.assertEqual(r.status_code, status, r.text)
        err = r.json()["error"]
        self.assertEqual(err["code"], code)
        s.ErrorResponse.model_validate(r.json())
        self.assertNotIn("Traceback", r.text)
        return err

    def test_documented_errors(self):
        self.expect(get("/api/v1/players/nobody99/seasons"), 404, "player_not_found")
        err = self.expect(get("/api/v1/players/resolve", name="Frank Thomas"), 409, "ambiguous_player")
        self.assertGreaterEqual(len(err["details"]["candidates"]), 2)
        self.expect(get("/api/v1/leaderboards", metric="WAR"), 422, "invalid_metric")
        self.expect(get("/api/v1/seasons", start=2025, end=2020), 422, "invalid_date_range")
        self.expect(get("/api/v1/seasons", start=1700, end=1750), 422, "invalid_date_range")
        self.expect(get("/api/v1/nope"), 404, "not_found")

    def test_malformed_requests(self):
        for path, params in [
            ("/api/v1/players/search", {"q": "a"}), ("/api/v1/players/search", {"q": "judge", "limit": "abc"}),
            ("/api/v1/seasons", {"limit": 0}), ("/api/v1/seasons", {"limit": 10_000}),
            ("/api/v1/seasons", {"order": "sideways"}), ("/api/v1/seasons", {"combine": "maybe"}),
            ("/api/v1/seasons", {"min_XYZ": 3}), ("/api/v1/seasons", {"min_HR": "lots"}),
            ("/api/v1/leaderboards", {"weights": "HR=1"}), ("/api/v1/leaderboards", {"weights": "WAR:1"}),
            ("/api/v1/leaderboards", {"weights": "HR:99"}), ("/api/v1/players/judgeaa01/seasons", {"split": "x"}),
        ]:
            with self.subTest(params=params):
                self.expect(get(path, **params), 422, "invalid_parameter")
        r = CLIENT.post("/api/v1/leaderboards")
        self.assertEqual(r.status_code, 405)

    def test_unexpected_failure_is_generic(self):
        original = svc.leaderboard
        try:
            def boom(**_kw):
                raise RuntimeError(f"secret detail {ROOT}")
            svc.leaderboard = boom
            err = self.expect(get("/api/v1/leaderboards"), 500, "internal_error")
            self.assertNotIn("secret", json.dumps(err))
        finally:
            svc.leaderboard = original

    def test_missing_data_is_data_unavailable(self):
        store = svc.HistoryStore(base_dir=ROOT / "no_such_dir")
        with self.assertRaises(svc.ApiError) as ctx:
            svc.search_players("judge", store=store)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("data_unavailable", 503))


class SecurityBoundaryTests(unittest.TestCase):
    def test_responses_leak_no_paths_or_secrets(self):
        bodies = [get("/api/v1/health").text, get("/api/v1/openapi.json").text, get("/api/v1/seasons", limit=3).text]
        for body in bodies:
            self.assertNotIn(str(ROOT), body)
            self.assertNotIn(str(ROOT).replace("\\", "/"), body)
            for word in ("service_role", "sk_live", "sk_test", "SUPABASE", "STRIPE", "session_state", "cookie"):
                self.assertNotIn(word, body)

    def test_get_only_no_cookies_no_cors_by_default(self):
        r = CLIENT.get("/api/v1/health", headers={"Origin": "https://evil.example", "Cookie": "a=b"})
        self.assertNotIn("access-control-allow-origin", r.headers)
        self.assertNotIn("set-cookie", r.headers)
        for route in __import__("baseball_api.app", fromlist=["ROUTES"]).ROUTES:
            self.assertEqual(set(route.methods or []) - {"HEAD"}, {"GET"})

    def test_no_fantasy_or_account_routes(self):
        paths = list(build_openapi()["paths"])
        self.assertFalse([p for p in paths if any(w in p for w in ("league", "team", "account", "billing", "lineup", "trade"))])


class OpenApiTests(unittest.TestCase):
    def test_every_ref_resolves_and_every_model_is_published(self):
        spec = build_openapi()
        self.assertEqual(spec["openapi"], "3.1.0")
        comps = spec["components"]["schemas"]
        text = json.dumps(spec)
        for ref in set(part.split('"')[0] for part in text.split('"$ref": "#/components/schemas/')[1:]):
            self.assertIn(ref, comps)
        for name in ("PlayerSummary", "PlayerSeason", "CareerSummary", "LeaderboardResult", "ComparisonResult", "TrendResult",
                     "ValuationResult", "LeagueSummary", "StandingsResult", "LineupReport", "TradeEvaluation", "ErrorResponse"):
            self.assertIn(name, comps)
        self.assertIn("2B", comps["StatLine"]["properties"], "serialized names (aliases) are what the client sees")

    def test_served_document_matches_the_builder(self):
        self.assertEqual(get("/api/v1/openapi.json").json(), json.loads(json.dumps(build_openapi())))


NO_STREAMLIT_PROBE = r"""
import json, os, sys
os.environ["BASEBALL_API_PRELOAD"] = "0"
writes = []
def audit(event, args):
    # Every file this process opens for writing, renames or deletes (other processes can't confuse it).
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        mode = str(args[1] or "r") if len(args) > 1 else "r"
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        if any(c in mode for c in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            writes.append(str(args[0]))
    elif event in ("os.rename", "os.replace", "os.remove", "os.unlink", "shutil.rmtree"):
        writes.append(f"{event}:{args[0]}")
sys.addaudithook(audit)
from starlette.testclient import TestClient
from baseball_api.app import app
c = TestClient(app)
codes = [c.get(u, params=p).status_code for u, p in [
    ("/api/v1/players/search", {"q": "judge"}), ("/api/v1/players/judgeaa01/seasons", {}),
    ("/api/v1/seasons", {"limit": 5}), ("/api/v1/leaderboards", {"limit": 5}),
    ("/api/v1/catalog", {}), ("/api/v1/players/judgeaa01", {}),
    ("/api/v1/seasons", {"player_id": "judgeaa01", "metric": "OPS", "include_below_minimum": "true"}),
    ("/api/v1/seasons", {"format": "csv", "limit": 50}), ("/api/v1/leaderboards", {"format": "csv"})]]
loaded = [m for m in ("streamlit", "baseball_persistent_state", "suite_user_persistence", "suite_storage",
                      "suite_activity_client", "supabase", "baseball_billing") if m in sys.modules]
print(json.dumps({"codes": codes, "loaded": loaded, "writes": sorted(set(writes))}))
"""


class NoStreamlitExecutionTests(unittest.TestCase):
    def test_endpoints_run_without_streamlit_session_or_persistence(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run([sys.executable, "-c", NO_STREAMLIT_PROBE, str(ROOT)], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=600)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        result = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(result["codes"], [200] * 9)
        self.assertEqual(result["loaded"], [], "an endpoint pulled in Streamlit or a persistence module")
        self.assertEqual(result["writes"], [], "an endpoint opened a file for writing, renamed or deleted one")

    def test_negative_control_the_write_audit_sees_writes(self):
        import tempfile

        target = Path(tempfile.gettempdir()) / "baseball_api_audit_probe.txt"
        hook = NO_STREAMLIT_PROBE.split("from starlette.testclient")[0]
        script = hook + f"open(r'{target}', 'w').write('x')\nprint(json.dumps(writes))\n"
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
        target.unlink(missing_ok=True)
        self.assertIn(str(target), json.loads(out.stdout.strip().splitlines()[-1]))


if __name__ == "__main__":
    unittest.main()
