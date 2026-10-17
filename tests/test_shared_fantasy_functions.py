"""Shared fantasy calculations moved out of streamlit_app.py: outputs pinned to the pre-move code.

Every EXPECTED_* value below was produced by the original functions in streamlit_app.py at
38d1e3e (before the move) on this fixture; the tests prove the modules still return them.
A broader randomized parity run (real 2026 MLB stats, 300 leagues) is described in
docs/FANTASY_SHARED_INTERFACES.md.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pandas as pd

from fantasy_lineup_scoring import build_lineup_assistant_scores, build_position_aware_lineup, lineup_diagnosis_report
from fantasy_slot_eligibility import enrich_lineup_roster_positions
from fantasy_standings_snapshot import SNAPSHOT_LABEL, score_current_roster_standings, summarize_team_category_needs
from fantasy_trade_evaluation import build_trade_verdict_text, evaluate_trade

ROOT = Path(__file__).resolve().parents[1]


def _p(player, team, pos, ab, h, hr, rbi, r, sb, bb, obp, slg):
    ba = h / ab
    return {"Player": player, "Team": team, "Primary Position": pos, "G": 20, "AB": ab, "H": h, "HR": hr,
            "RBI": rbi, "R": r, "SB": sb, "BB": bb, "BA": ba, "OBP": obp, "SLG": slg, "OPS": obp + slg}


LEAGUE = pd.DataFrame([
    _p("Ann Able", "Aces", "C", 80, 20, 4, 14, 11, 0, 8, 0.330, 0.450),
    _p("Cal Cole", "Aces", "1B", 90, 27, 7, 20, 15, 1, 10, 0.380, 0.560),
    _p("Dee Dash", "Aces", "2B", 85, 22, 1, 8, 16, 9, 9, 0.330, 0.360),
    _p("Eve East", "Aces", "SS", 70, 15, 2, 9, 10, 6, 4, 0.270, 0.330),
    _p("Fay Fern", "Aces", "OF", 95, 30, 6, 18, 19, 3, 12, 0.400, 0.520),
    _p("Gus Gale", "Aces", "DH", 60, 12, 5, 13, 7, 0, 6, 0.280, 0.480),
    _p("Ben Bolt", "Bombers", "OF", 100, 32, 9, 25, 21, 4, 11, 0.390, 0.600),
    _p("Hal Hart", "Bombers", "3B", 88, 21, 3, 12, 12, 2, 7, 0.300, 0.400),
    _p("Ivy Ives", "Bombers", "SS", 75, 19, 1, 7, 13, 5, 6, 0.310, 0.350),
    _p("Jo Jett", "Cyclones", "OF", 92, 26, 5, 16, 17, 7, 10, 0.350, 0.470),
    _p("Kit Kane", "Cyclones", "C", 70, 14, 3, 10, 6, 0, 5, 0.260, 0.380),
    _p("Lou Lake", "Cyclones", "2B", 82, 24, 2, 11, 14, 4, 9, 0.360, 0.410),
])

# --- Outputs of the original streamlit_app.py functions at 38d1e3e on LEAGUE (generated, do not edit) ---
EXPECTED_STANDINGS = [{'Fantasy Team': 'Aces',
  'Players': 6,
  'Total HR': 25,
  'Total RBI': 82,
  'Total R': 78,
  'Total SB': 19,
  'Team BA': 0.2625,
  'Team OPS': 0.7816666667,
  'Total HR Points': 3.0,
  'Total RBI Points': 3.0,
  'Total R Points': 3.0,
  'Total SB Points': 3.0,
  'Team BA Points': 2.0,
  'Total Roto Points': 14.0,
  'League Rank': 1.0},
 {'Fantasy Team': 'Bombers',
  'Players': 3,
  'Total HR': 13,
  'Total RBI': 44,
  'Total R': 46,
  'Total SB': 11,
  'Team BA': 0.2737642586,
  'Team OPS': 0.7833333333,
  'Total HR Points': 2.0,
  'Total RBI Points': 2.0,
  'Total R Points': 2.0,
  'Total SB Points': 1.5,
  'Team BA Points': 3.0,
  'Total Roto Points': 10.5,
  'League Rank': 2.0},
 {'Fantasy Team': 'Cyclones',
  'Players': 3,
  'Total HR': 10,
  'Total RBI': 37,
  'Total R': 37,
  'Total SB': 11,
  'Team BA': 0.262295082,
  'Team OPS': 0.7433333333,
  'Total HR Points': 1.0,
  'Total RBI Points': 1.0,
  'Total R Points': 1.0,
  'Total SB Points': 1.5,
  'Team BA Points': 1.0,
  'Total Roto Points': 5.5,
  'League Rank': 3.0}]
EXPECTED_POINTS = [{'Fantasy Team': 'Aces', 'Estimated Points': 317.5416666667, 'League Rank': 1.0},
 {'Fantasy Team': 'Bombers', 'Estimated Points': 183.5833333333, 'League Rank': 2.0},
 {'Fantasy Team': 'Cyclones', 'Estimated Points': 154.5833333333, 'League Rank': 3.0}]
EXPECTED_NEEDS = {'Aces': {'BA': True, 'OPS': True},
 'Bombers': {'HR': True, 'RBI': True, 'R': True, 'SB': True},
 'Cyclones': {'HR': True, 'RBI': True, 'R': True, 'SB': True, 'BA': True, 'OPS': True}}
EXPECTED_TRADE = ([{'Category': 'HR', 'Give Away': 11.0, 'Receive': 9.0, 'Net Gain': -2.0},
  {'Category': 'RBI', 'Give Away': 34.0, 'Receive': 25.0, 'Net Gain': -9.0},
  {'Category': 'R', 'Give Away': 26.0, 'Receive': 21.0, 'Net Gain': -5.0},
  {'Category': 'SB', 'Give Away': 1.0, 'Receive': 4.0, 'Net Gain': 3.0},
  {'Category': 'BA', 'Give Away': 0.275, 'Receive': 0.32, 'Net Gain': 0.045},
  {'Category': 'OPS', 'Give Away': 0.86, 'Receive': 0.99, 'Net Gain': 0.13}],
 'Bad for your team',
 -12.7375)
EXPECTED_VERDICT_TEXT = ('Decline: The trade appears to cost too much projected value or category balance. Team-need weighted score: '
 '-12.74.')
EXPECTED_SCORES = [{'Player': 'Ann Able', 'Lineup Confidence': 0.3806443733, 'Start/Sit Recommendation': 'Sit'},
 {'Player': 'Cal Cole', 'Lineup Confidence': 0.9475356311, 'Start/Sit Recommendation': 'Start'},
 {'Player': 'Dee Dash', 'Lineup Confidence': 0.3455906973, 'Start/Sit Recommendation': 'Sit'},
 {'Player': 'Eve East', 'Lineup Confidence': 0.0, 'Start/Sit Recommendation': 'Sit'},
 {'Player': 'Fay Fern', 'Lineup Confidence': 1.0, 'Start/Sit Recommendation': 'Start'},
 {'Player': 'Gus Gale', 'Lineup Confidence': 0.1334074019, 'Start/Sit Recommendation': 'Sit'}]
EXPECTED_REASONS = ['Confidence: Low\n'
 'Reason:\n'
 '- Current production below roster alternatives\n'
 '- Production trend declining recently',
 'Confidence: High\n'
 'Reason:\n'
 '- Strong current production trend\n'
 '- Positive momentum vs bench alternatives\n'
 '- Consistent playing time and rate support\n'
 '- Strong OPS (0.940)',
 'Confidence: Low\n'
 'Reason:\n'
 '- Current production below roster alternatives\n'
 '- Production trend declining recently\n'
 '- Limited playing time or unstable rates\n'
 '- Useful speed contribution (9 SB)',
 'Confidence: Low\n'
 'Reason:\n'
 '- Current production below roster alternatives\n'
 '- Production trend declining recently\n'
 '- Limited playing time or unstable rates',
 'Confidence: High\n'
 'Reason:\n'
 '- Strong current production trend\n'
 '- Positive momentum vs bench alternatives\n'
 '- Consistent playing time and rate support\n'
 '- Strong OPS (0.920)',
 'Confidence: Low\n'
 'Reason:\n'
 '- Current production below roster alternatives\n'
 '- Production trend declining recently\n'
 '- Limited playing time or unstable rates']
EXPECTED_LINEUP = ([{'Fantasy slot': 'C', 'Player': 'Ann Able'},
  {'Fantasy slot': '1B', 'Player': 'Cal Cole'},
  {'Fantasy slot': '2B', 'Player': 'Dee Dash'},
  {'Fantasy slot': 'SS', 'Player': 'Eve East'},
  {'Fantasy slot': 'OF1', 'Player': 'Fay Fern'},
  {'Fantasy slot': 'UTIL', 'Player': 'Gus Gale'}],
 [],
 [])
EXPECTED_DIAG = {'archetype': 'This lineup has a **balanced power and speed** mix.',
 'strongest': ['HR', 'RBI'],
 'weakest': ['SB', 'AVG'],
 'strongest_detail': 'Strong **HR** — driven by **Cal Cole** (7 HR), **Fay Fern** (6 HR), **Gus Gale** (5 '
                     'HR), **Ann Able** (4 HR).',
 'weakest_detail': 'Soft AVG — power-heavy bats like Gus Gale, Eve East pull the rate down.',
 'balance_label': 'This roster has several strengths but still has a few areas that could be upgraded.',
 'position_note': '**Weakest Position:** SS\n'
                  '\n'
                  '**Current Starter:** Eve East\n'
                  '\n'
                  '**Best Waiver Option:** none eligible at SS in the current waiver pool',
 'dragger_note': '',
 'surplus_note': '**Trade From:** starters carry **~100%** of team **HR** while **AVG** is weakest — swap '
                 'some **HR** for **AVG**-shaped help.',
 'recommendations': [{'Type': 'Category repair',
                      'Label': 'Need',
                      'Detail': 'Your starters’ AVG is **0.263**. Add contact hitters or bench the '
                                'lowest-AVG names in this lineup.'},
                     {'Type': 'Trade recommendation',
                      'Label': 'Trade From → Target profile',
                      'Detail': 'Ship **HR** surplus for **AVG** without emptying your best starters.'}],
 'slot_gaps': '',
 'weakest_pos': 'SS'}
EXPECTED_DIAG_TABLE = [{'Category': 'HR', 'Lineup total': 25.0, '% of team': 100.0, 'Rel. strength (0–100)': None},
 {'Category': 'RBI', 'Lineup total': 82.0, '% of team': 100.0, 'Rel. strength (0–100)': None},
 {'Category': 'R', 'Lineup total': 78.0, '% of team': 100.0, 'Rel. strength (0–100)': None},
 {'Category': 'SB', 'Lineup total': 19.0, '% of team': 100.0, 'Rel. strength (0–100)': None},
 {'Category': 'AVG', 'Lineup total': 0.2625, '% of team': 100.0, 'Rel. strength (0–100)': None}]
# --- end of generated values ---


def _records(df, cols=None, ndigits=10):
    df = (df if cols is None else df[cols]).round(ndigits)
    return df.astype(object).where(df.notna(), None).to_dict("records")


class CurrentRosterStandingsTests(unittest.TestCase):
    def test_roto_table_matches_pre_move_output(self):
        self.assertEqual(_records(score_current_roster_standings(LEAGUE, "5x5 Roto")), EXPECTED_STANDINGS)

    def test_points_estimate_matches_pre_move_output(self):
        table = score_current_roster_standings(LEAGUE, "Points League")
        self.assertEqual(_records(table, ["Fantasy Team", "Estimated Points", "League Rank"]), EXPECTED_POINTS)

    def test_category_needs(self):
        table = score_current_roster_standings(LEAGUE, "5x5 Roto")
        self.assertEqual({t: summarize_team_category_needs(table, t) for t in ("Aces", "Bombers", "Cyclones")}, EXPECTED_NEEDS)
        self.assertEqual(summarize_team_category_needs(table, "Nobody"), {})

    def test_snapshot_is_labeled_not_official(self):
        self.assertIn("not official", SNAPSHOT_LABEL)
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("from fantasy_standings_snapshot import SNAPSHOT_LABEL as _SNAPSHOT_LABEL", src)
        self.assertIn("st.subheader(_SNAPSHOT_LABEL)", src)


class TradeEvaluationTests(unittest.TestCase):
    def test_trade_matches_pre_move_output(self):
        standings = score_current_roster_standings(LEAGUE, "5x5 Roto")
        table, verdict, gain = evaluate_trade(["Ann Able", "Cal Cole"], ["Ben Bolt"], LEAGUE[LEAGUE.Team == "Aces"],
                                              LEAGUE, standings, "Aces")
        self.assertEqual((_records(table), verdict, round(gain, 10)), EXPECTED_TRADE)
        self.assertEqual(build_trade_verdict_text(table, gain), EXPECTED_VERDICT_TEXT)

    def test_verdict_bands(self):
        self.assertTrue(build_trade_verdict_text(None, 5).startswith("Strong accept"))
        self.assertTrue(build_trade_verdict_text(None, 1).startswith("Slight accept"))
        self.assertTrue(build_trade_verdict_text(None, 0.99).startswith("Fair / neutral"))
        self.assertTrue(build_trade_verdict_text(None, -1).startswith("Slight decline"))
        self.assertTrue(build_trade_verdict_text(None, -5).startswith("Decline"))
        self.assertTrue(build_trade_verdict_text(None, "not a number").startswith("Fair / neutral"))


class LineupScoringTests(unittest.TestCase):
    def setUp(self):
        self.team = LEAGUE[LEAGUE.Team == "Aces"].copy()

    def test_scores_and_reasons_match_pre_move_output(self):
        scored = build_lineup_assistant_scores(self.team, "5x5 Roto")
        self.assertEqual(_records(scored, ["Player", "Lineup Confidence", "Start/Sit Recommendation"]), EXPECTED_SCORES)
        self.assertEqual(scored["Lineup Reason"].tolist(), EXPECTED_REASONS)

    def test_recommended_lineup_and_diagnosis_match_pre_move_output(self):
        enriched = enrich_lineup_roster_positions(build_lineup_assistant_scores(self.team, "5x5 Roto"))
        package = build_position_aware_lineup(enriched, slots=["C", "1B", "2B", "SS", "OF", "UTIL"])
        self.assertEqual((package["lineup_df"][["Fantasy slot", "Player"]].to_dict("records"), package["missing_slots"],
                          package["slot_warnings"]), EXPECTED_LINEUP)
        diag = lineup_diagnosis_report(package["lineup_df"], enriched, "5x5 Roto", "BA",
                                       missing_slots=package["missing_slots"], slot_warnings=package["slot_warnings"])
        self.assertEqual({k: v for k, v in diag.items() if isinstance(v, (str, list))}, EXPECTED_DIAG)
        self.assertEqual(_records(diag["hitting_table"]), EXPECTED_DIAG_TABLE)


class AppWiringTests(unittest.TestCase):
    """The page uses the shared modules; the formulas live in one place."""

    def setUp(self):
        self.src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")

    def test_app_imports_instead_of_defining(self):
        for name in ("evaluate_trade", "build_trade_verdict_text", "summarize_team_category_needs", "lineup_diagnosis_report",
                     "build_position_aware_lineup", "enrich_lineup_roster_positions", "_player_eligible_for_slot",
                     "normalize_series", "safe_numeric_series", "fmt_int"):
            self.assertNotIn(f"\ndef {name}(", self.src, name)
        self.assertIn("return _score_current_roster_standings(roster_df, scoring_format)", self.src)
        self.assertIn("return _build_lineup_assistant_scores(roster_stats, scoring_format, custom_weights)", self.src)

    def test_shared_modules_never_import_the_app(self):
        for mod in ("stat_helpers", "fantasy_standings_snapshot", "fantasy_trade_evaluation", "fantasy_slot_eligibility",
                    "fantasy_lineup_scoring"):
            tree = ast.parse((ROOT / f"{mod}.py").read_text(encoding="utf-8"))
            imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertFalse(imported & {"streamlit_app", "streamlit"}, mod)


if __name__ == "__main__":
    unittest.main()
