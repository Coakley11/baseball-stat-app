"""Metric definitions, taken from the app's own copy wherever it exists.

* Draft scores come straight from ``draft_score_display.SCORE_TOOLTIPS`` (the column tooltips).
* Valuation terms come from the Valuation page guide (``page_guides.PAGE_GUIDES``).
* Trend method and qualification rules come from the constants in ``trend_slopes`` and
  ``rate_stat_qualification``.
* Formulas (BA/OBP/SLG/OPS) describe ``lahman_data.add_rate_stats``; tests check them.
* Inline page copy that isn't importable (the Sleepers column glossary) is quoted and pinned
  by tests against ``streamlit_app.py`` so it can't silently drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from draft_score_display import DISPLAY_PICK_SCORE, DISPLAY_PLAYER_GRADE, DISPLAY_RELATIVE_GRADE, DISPLAY_ROSTER_FIT, SCORE_TOOLTIPS
from fantasy_read_api import ELIGIBILITY_RULE, OFFICIAL_BASIS, OFFICIAL_LABEL, SNAPSHOT_BASIS
from fantasy_standings_snapshot import SNAPSHOT_LABEL
from page_guides import PAGE_GUIDES

# The Waiver Wire card caption, quoted verbatim (tests pin it to fantasy_waiver_wire_ui.py).
CONSIDER_ADD_CAPTION = "“Consider add” puts the player in the move planner below. Nothing changes until you confirm a move."
from rate_stat_qualification import AB_PER_TEAM_GAME, MULTI_SEASON_CAP_AB
from trend_slopes import RATE_SHRINK_PA


@dataclass(frozen=True)
class Term:
    key: str
    name: str
    definition: str
    where: tuple[str, ...]  # pages where the user sees it
    aliases: tuple[str, ...] = ()
    source: str = ""


def _plain(text: str) -> str:
    return re.sub(r"</?strong>", "**", str(text or "")).strip()


def _valuation_extra(label: str) -> str:
    for line in PAGE_GUIDES.get("Valuation", {}).get("extra", []):
        plain = _plain(line)
        if plain.startswith(f"**{label}"):
            return re.sub(r"^\*\*[^*]+\*\*\s*", "", plain)
    return ""


def _terms() -> list[Term]:
    return [
        Term(
            "decision_score", DISPLAY_PICK_SCORE, SCORE_TOOLTIPS[DISPLAY_PICK_SCORE],
            ("Draft Assistant Simulator", "Live Draft Room", "Draft Lab / Simulation"),
            ("decision score", "pick score"), "draft_score_display.SCORE_TOOLTIPS",
        ),
        Term(
            "player_grade", DISPLAY_PLAYER_GRADE, SCORE_TOOLTIPS[DISPLAY_PLAYER_GRADE],
            ("Draft Assistant Simulator", "Live Draft Room", "Fantasy Sleepers & Busts", "Draft Lab / Simulation"),
            ("player grade", "expected fantasy value", "efv"), "draft_score_display.SCORE_TOOLTIPS",
        ),
        Term(
            "roster_fit", DISPLAY_ROSTER_FIT, SCORE_TOOLTIPS[DISPLAY_ROSTER_FIT],
            ("Draft Assistant Simulator", "Live Draft Room"),
            ("roster fit", "roster fit score", "draft fit score"), "draft_score_display.SCORE_TOOLTIPS",
        ),
        Term(
            "fantasy_edge", "Fantasy Edge",
            SCORE_TOOLTIPS["Fantasy Edge"] + " On Fantasy Sleepers & Busts: Fantasy Edge = Market Rank − Model Rank "
            "(positive = sleeper, negative = bust risk).",
            ("Fantasy Sleepers & Busts", "Draft Assistant Simulator"),
            ("fantasy edge", "edge"), "draft_score_display.SCORE_TOOLTIPS + Sleepers column glossary",
        ),
        Term(
            "relative_draft_grade", DISPLAY_RELATIVE_GRADE, SCORE_TOOLTIPS[DISPLAY_RELATIVE_GRADE],
            ("Draft Room Simulator",), ("relative draft grade", "draft grade"), "draft_score_display.SCORE_TOOLTIPS",
        ),
        Term(
            "valuation_score", "Valuation Score", _valuation_extra("Valuation Score"),
            ("Valuation",), ("valuation score", "valuation"), "Valuation page guide",
        ),
        Term(
            "current_score", "Current Score", _valuation_extra("Current Score"),
            ("Valuation",), ("current score",), "Valuation page guide",
        ),
        Term(
            "trend_score", "Trend Score", _valuation_extra("Trend Score"),
            ("Valuation",), ("trend score",), "Valuation page guide",
        ),
        Term(
            "trend_value", "Trend Value",
            "The Trend Value page measures how each stat changed per season over the last 3, 4 or 5 seasons "
            "(the Δ columns; green = improving, red = declining). Each Δ is a least-squares slope; BA/OBP/SLG/OPS "
            f"weight seasons by plate appearances and pull tiny samples toward league average ({RATE_SHRINK_PA} PA).",
            ("Trend Value",), ("trend value", "trend", "trends", "slope", "Δ"), "Trend Value page + trend_slopes",
        ),
        Term(
            "qualified", "Qualified minimum (rate stats)",
            f"When a ranking is sorted by BA, OBP, SLG or OPS, the Min AB filter defaults to {AB_PER_TEAM_GAME} at-bats "
            "per scheduled team game (MLB's batting-title rule in AB) — one full season on Historical Explorer, summed "
            f"over the range (capped at {MULTI_SEASON_CAP_AB:,} AB) on Leaderboards and Career Totals. You can change it; "
            "“Use qualified” restores it.",
            ("Historical Explorer", "Career Totals", "Leaderboards"),
            ("qualified", "qualification", "min ab", "minimum at-bats"), "rate_stat_qualification",
        ),
        Term(
            "ops", "OPS", "On-base plus slugging: OBP + SLG.", ("Historical Explorer", "Leaderboards"), ("ops",), "lahman_data.add_rate_stats",
        ),
        Term(
            "obp", "OBP", "On-base percentage: (H + BB + HBP) ÷ (AB + BB + HBP + SF).", (), ("obp", "on-base"), "lahman_data.add_rate_stats",
        ),
        Term(
            "slg", "SLG", "Slugging: total bases ÷ AB, where total bases = 1B + 2×2B + 3×3B + 4×HR.", (), ("slg", "slugging"), "lahman_data.add_rate_stats",
        ),
        Term(
            "ba", "BA", "Batting average: H ÷ AB.", (), ("ba", "batting average", "average", "avg"), "lahman_data.add_rate_stats",
        ),
        Term(
            "official_standings", OFFICIAL_LABEL,
            f"The league's standings. {OFFICIAL_BASIS} Not the same as **{SNAPSHOT_LABEL}**, which is a what-if on "
            f"today's rosters: {SNAPSHOT_BASIS}",
            ("Fantasy Standings Tracker", "Home"),
            ("official standings", "league standings", "standings", "official vs current", "difference between official"),
            "fantasy_read_api.OFFICIAL_BASIS / SNAPSHOT_BASIS",
        ),
        Term(
            "current_roster_snapshot", SNAPSHOT_LABEL,
            f"{SNAPSHOT_BASIS} Use it to see how your roster stacks up now; for where you actually stand, "
            f"use **{OFFICIAL_LABEL}**.",
            ("Fantasy Standings Tracker",),
            ("current roster", "current rosters", "current roster snapshot", "roster snapshot",
             "how current rosters would rank"),
            "fantasy_read_api.SNAPSHOT_BASIS / fantasy_standings_snapshot.SNAPSHOT_LABEL",
        ),
        Term(
            "eligibility", "Position eligibility",
            f"{ELIGIBILITY_RULE} The same rule decides what Save Lineup accepts; nothing is assumed from a player's "
            "reputation (no automatic 1B↔3B or 2B↔SS).",
            ("Fantasy Lineup Assistant", "Waiver Wire / Add-Drop Center"),
            ("eligibility", "eligible", "position eligibility", "multi-position"),
            "fantasy_read_api.ELIGIBILITY_RULE",
        ),
        Term(
            "use_suggested_lineup", "Use Suggested Lineup",
            "Use Suggested Lineup fills the editable lineup with the recommended starters. It does not save, lock or "
            "finalize the lineup; review it and then press Save Lineup.",
            ("Fantasy Lineup Assistant",),
            ("use suggested lineup", "suggested lineup"),
            "suggested_lineup.py (module docstring)",
        ),
        Term(
            "consider_add", "Consider add",
            CONSIDER_ADD_CAPTION.replace("“Consider add”", "**Consider add**"),
            ("Waiver Wire / Add-Drop Center",),
            ("consider add",),
            "fantasy_waiver_wire_ui caption",
        ),
        Term(
            "explore_more", "Explore more",
            "Redesigned pages lead with the answer and one chart; the filters, full tables, advanced settings and "
            "methodology are still there, under the **Explore more** label further down the page.",
            ("Historical Explorer", "Leaderboards", "Fantasy Standings Tracker", "Waiver Wire / Add-Drop Center"),
            ("explore more",),
            "docs/U1_UI_HIERARCHY.md",
        ),
        Term(
            "sleeper", "Sleeper / Bust",
            "On Fantasy Sleepers & Busts, a sleeper is a player the app's model ranks well ahead of the market (ADP); "
            "a bust risk is one the market ranks well ahead of the model. Fantasy Edge = Market Rank − Model Rank.",
            ("Fantasy Sleepers & Busts",), ("sleeper", "sleepers", "bust", "busts", "bust risk"), "Sleepers page guide + column glossary",
        ),
    ]


TERMS: dict[str, Term] = {t.key: t for t in _terms()}


def match_term(text: str) -> tuple[Term | None, int]:
    """The term whose longest alias appears in ``text`` (whole words), and that alias's length."""
    low = f" {str(text or '').lower()} "
    best: tuple[int, Term] | None = None
    for term in TERMS.values():
        for alias in (term.name.lower(), *term.aliases):
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", low):
                if best is None or len(alias) > best[0]:
                    best = (len(alias), term)
    return (best[1], best[0]) if best else (None, 0)


def find_term(text: str) -> Term | None:
    return match_term(text)[0]
