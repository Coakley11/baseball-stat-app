"""Guided onboarding tutorial — lightweight static content, dialog UI, persisted prefs."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import streamlit as st

TUTORIAL_OPEN_KEY = "tutorial_open"
TUTORIAL_STEP_KEY = "tutorial_step_index"
TUTORIAL_HIDE_BUTTON_KEY = "tutorial_hide_button"
TUTORIAL_NAV_PAGE_KEY = "_navigate_to_page"

_PREFS_PATH = Path(__file__).resolve().parent / ".tutorial_prefs.json"


def _load_prefs() -> dict[str, Any]:
    try:
        raw = _PREFS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_prefs(prefs: dict[str, Any]) -> None:
    try:
        _PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except OSError:
        pass


def init_tutorial_prefs() -> None:
    """Hydrate session from disk once per run (does not override explicit session choices)."""
    if TUTORIAL_HIDE_BUTTON_KEY not in st.session_state:
        st.session_state[TUTORIAL_HIDE_BUTTON_KEY] = bool(_load_prefs().get("hide_button", False))


def tutorial_button_hidden() -> bool:
    init_tutorial_prefs()
    return bool(st.session_state.get(TUTORIAL_HIDE_BUTTON_KEY, False))


def hide_tutorial_button_permanently() -> None:
    st.session_state[TUTORIAL_HIDE_BUTTON_KEY] = True
    prefs = _load_prefs()
    prefs["hide_button"] = True
    _save_prefs(prefs)


def _tutorial_css() -> str:
    return """
<style>
.tutorial-bar {
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;
    margin: -6px 0 18px 0; padding: 10px 16px;
    background: linear-gradient(90deg, #eef4ff 0%, #f8fbff 100%);
    border: 1px solid #c8daf5; border-radius: 12px;
}
.tutorial-bar-text { color: #3d5a73; font-size: 14px; margin: 0; line-height: 1.4; }
.tutorial-step-pill {
    display: inline-block; background: #1f4e79; color: #fff; font-size: 12px; font-weight: 700;
    padding: 4px 10px; border-radius: 999px; letter-spacing: 0.03em;
}
.tutorial-card {
    background: #f7f9fc; border: 1px solid #d9e2ec; border-radius: 12px;
    padding: 14px 16px; margin-bottom: 12px;
}
.tutorial-card h4 { margin: 0 0 8px 0; color: #12324a; font-size: 15px; }
.tutorial-card p, .tutorial-card li { color: #2c3e50; font-size: 14px; line-height: 1.45; }
.tutorial-tagline { color: #4f6475; font-size: 15px; margin: 0 0 12px 0; }
</style>
"""


@lru_cache(maxsize=1)
def get_tutorial_steps() -> tuple[dict[str, Any], ...]:
    """Static step definitions — cached in-process, rendered one step at a time."""
    return (
        {
            "id": "welcome",
            "title": "Welcome",
            "icon": "⚾",
            "page_key": None,
            "tagline": "Your all-in-one MLB history explorer and fantasy draft companion.",
            "sections": [
                {
                    "title": "What this app does",
                    "bullets": [
                        "Explore decades of Lahman MLB stats — filter, rank, compare, and chart.",
                        "Spot rising and fading players with trend and valuation tools.",
                        "Prep fantasy drafts with sleepers, busts, draft assistants, and live draft rooms.",
                        "Track in-season standings and optimize weekly lineups.",
                    ],
                },
                {
                    "title": "Baseball fans",
                    "bullets": [
                        "Hunt legendary seasons, era comparisons, and niche stat lines.",
                        "Build leaderboards and side-by-side comparisons for debate-ready evidence.",
                        "Use scatterplots and correlation tools to see how stats relate.",
                    ],
                },
                {
                    "title": "Fantasy players",
                    "bullets": [
                        "Find undervalued sleepers and risky busts vs market ADP.",
                        "Run mock drafts, test strategies, and get next-pick recommendations.",
                        "Use Decision Score and roster-fit tools during live drafts.",
                    ],
                    "expandable": True,
                },
                {
                    "title": "How pages connect",
                    "bullets": [
                        "**Explore** (Historical → Career → Leaderboards) → shortlist names.",
                        "**Analyze** (Comparison, Trend Value, Valuation) → confirm breakout/decline and rank.",
                        "**Draft prep** (Sleepers & Busts → Draft Room → Draft Assistant) → build your board.",
                        "**Draft day** (Simulation Test Mode or Live Draft Room) → practice or run the room.",
                        "**Season** (Standings Tracker → Lineup Assistant) → score teams and set lineups.",
                    ],
                },
            ],
        },
        {
            "id": "historical",
            "title": "Historical Explorer",
            "icon": "🔎",
            "page_key": "Historical Explorer",
            "tagline": "Search individual player-seasons across MLB history.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Explore historical MLB seasons one row per player-year (or per team if split seasons are kept).",
                        "Compare eras, find breakout years, and build custom leaderboards from filters.",
                    ],
                },
                {
                    "title": "Key filters",
                    "bullets": [
                        "Year range, team, batting hand, position (season vs career primary).",
                        "Sort stat and order; optional minimum stat thresholds in Advanced.",
                        "Combine split seasons toggles one primary-team row per player-year.",
                    ],
                },
                {
                    "title": "Common workflows",
                    "bullets": [
                        "Set filters → scan the table → open charts for the filtered pool.",
                        "Send players to Comparison, Trend Value, or Valuation via contextual actions.",
                    ],
                },
                {
                    "title": "Interesting things to try",
                    "bullets": [
                        "Mets right-handed hitters, 1998–2002, OPS > .850.",
                        "30 HR / 30 SB seasons at shortstop.",
                        "Steroid-era slugger leaderboards with HR and SLG mins.",
                    ],
                    "expandable": True,
                },
            ],
        },
        {
            "id": "career",
            "title": "Career Totals",
            "icon": "📚",
            "page_key": "Career Totals",
            "tagline": "Roll up counting and rate stats across a year window.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "See full-career (or windowed) production instead of single seasons.",
                        "Great for Hall of Fame debates and career-shape comparisons.",
                    ],
                },
                {
                    "title": "Key filters",
                    "bullets": [
                        "Year range, team, position mode, batting hand, sort stat.",
                        "By-team toggle: one row per franchise stint vs one combined career row.",
                    ],
                },
                {
                    "title": "Workflows",
                    "bullets": [
                        "Set a year window (e.g. 2000–2016) → rank by WAR-proxy stats like OPS or HR.",
                        "Transfer top names to Comparison or valuation pages.",
                    ],
                },
            ],
        },
        {
            "id": "leaderboards",
            "title": "Leaderboards",
            "icon": "🏆",
            "page_key": "Leaderboards",
            "tagline": "Fast who-leads-in-X rankings.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Single-stat leaderboards with light filters — the quickest rank view.",
                    ],
                },
                {
                    "title": "Key filters",
                    "bullets": [
                        "Year range, top N, sort stat, team/position/hand as needed.",
                    ],
                },
                {
                    "title": "Interesting things to try",
                    "bullets": [
                        "Who led the league in SB in the 1980s?",
                        "Top OPS seasons for a franchise in a decade.",
                    ],
                    "expandable": True,
                },
            ],
        },
        {
            "id": "trends",
            "title": "Trend Value",
            "icon": "🔥",
            "page_key": "Trend Value",
            "tagline": "Trends and Valuation — part 1: who's improving or declining.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Identify improving and declining players using recent-season deltas and slopes.",
                        "Spot breakout candidates and regression risks before your league mates do.",
                    ],
                },
                {
                    "title": "Important metrics",
                    "bullets": [
                        "**Slope** — direction/strength of the stat trend over the window.",
                        "**R²** — how consistent the trend is (higher = steadier pattern, not noisier).",
                        "**Volatility** — how swingy year-to-year results are.",
                        "Change columns (Δ) show year-over-year movement in counting and rate stats.",
                    ],
                },
                {
                    "title": "Workflows",
                    "bullets": [
                        "Filter by position/team/year → sort by slope or breakout lists.",
                        "Send a name to Comparison or add to your draft watchlist.",
                    ],
                },
                {
                    "title": "Interesting things to try",
                    "bullets": [
                        "Find young players with positive OPS slope and high R².",
                        "Compare two sluggers' HR slopes before a trade offer.",
                    ],
                    "expandable": True,
                },
            ],
        },
        {
            "id": "valuation",
            "title": "Valuation",
            "icon": "💰",
            "page_key": "Valuation",
            "tagline": "Trends and Valuation — part 2: one ranked shortlist.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Blend recent production (Current Score) with trend direction (Trend Score) into Valuation Score.",
                        "Best single table when you want a draft or trade shortlist.",
                    ],
                },
                {
                    "title": "Workflows",
                    "bullets": [
                        "Sort by Valuation Score → sanity-check HR, RBI, OPS, and components.",
                        "Confirm on Trend Value or Comparison before drafting or trading.",
                    ],
                },
            ],
        },
        {
            "id": "sleepers",
            "title": "Fantasy Sleepers & Busts",
            "icon": "🧠",
            "page_key": "Fantasy Sleepers & Busts",
            "tagline": "Market vs model — find edge before draft day.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Surface sleepers (model likes more than the market) and busts (fade candidates).",
                        "Compare FantasyPros/ADP-style ranks to the app's model ranks.",
                    ],
                },
                {
                    "title": "Important metrics",
                    "bullets": [
                        "**Fantasy Edge** — Market Rank minus Model Rank (positive ≈ undervalued).",
                        "**Expected Fantasy Value (EFV)** — blended projected production score.",
                    ],
                },
                {
                    "title": "Interesting things to try",
                    "bullets": [
                        "Sort sleepers by Fantasy Edge and cross-check Trend Value slopes.",
                        "Avoid busts with negative edge and rising volatility.",
                    ],
                    "expandable": True,
                },
            ],
        },
        {
            "id": "draft_assistant",
            "title": "Fantasy Draft Assistant",
            "icon": "🧩",
            "page_key": "Draft Assistant Simulator",
            "tagline": "Next-pick recommendations — pair with Draft Room Simulator for logged picks.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Optimize roster construction with need, scarcity, and projection-aware ranks.",
                        "Log picks in **Draft Room Simulator**; get next-pick help here.",
                    ],
                },
                {
                    "title": "Important metrics",
                    "bullets": [
                        "**Draft Fit Score** — how well a player fills your roster needs and categories.",
                        "**Scarcity Score** — positional supply pressure (grab scarce positions earlier).",
                        "Market rank vs model rank — same edge idea as Sleepers & Busts.",
                    ],
                },
                {
                    "title": "Workflows",
                    "bullets": [
                        "Enter your roster needs → review top available → draft in Draft Room.",
                        "Toggle projection style (Conservative / Balanced / Aggressive) to taste.",
                    ],
                },
                {
                    "title": "Interesting things to try",
                    "bullets": [
                        "Test scarcity across roto vs points scoring in Draft Simulation Test Mode.",
                        "Compare two CFs with similar EFV but different category fit.",
                    ],
                    "expandable": True,
                },
            ],
        },
        {
            "id": "draft_sim",
            "title": "Draft Simulation Test Mode",
            "icon": "🧪",
            "page_key": "Draft Simulation Test Mode",
            "tagline": "Run full mock drafts and compare strategies.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Simulate snake drafts (portfolio-friendly lab) with Draft Assistant-style scoring.",
                        "Analyze team strengths, weaknesses, best picks, and positional gaps after the draft.",
                    ],
                },
                {
                    "title": "Workflows",
                    "bullets": [
                        "Pick scoring format and teams → run sim → review grades and trade ideas.",
                        "Compare aggressive vs balanced projection modes across runs.",
                    ],
                },
            ],
        },
        {
            "id": "live_draft",
            "title": "Live Draft Room",
            "icon": "📡",
            "page_key": "Live Draft Room",
            "tagline": "Run a live snake draft with timers and smart recommendations.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Conduct mock or live drafts in the browser with pick board and rosters.",
                        "Get pick-by-pick guidance tuned to your slot and roster holes.",
                    ],
                },
                {
                    "title": "Important metrics",
                    "bullets": [
                        "**Decision Score** — overall pick quality blending value, need, and urgency.",
                        "**Survival probability** — how likely a target is to last until your next pick.",
                        "Auto-pick rules fill picks when you're on the clock under time pressure.",
                    ],
                },
                {
                    "title": "Workflows",
                    "bullets": [
                        "Configure teams and slots → draft manually or with auto-pick → export results.",
                        "Hand off completed rooms to simulation analysis when needed.",
                    ],
                },
            ],
        },
        {
            "id": "standings",
            "title": "Fantasy Standings Tracker",
            "icon": "🏆",
            "page_key": "Fantasy Standings Tracker",
            "tagline": "Score every team with live category standings.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Load rosters and current-season stats to see category ranks and totals.",
                        "Feeds the Lineup Assistant with the same stat bundle.",
                    ],
                },
                {
                    "title": "Workflows",
                    "bullets": [
                        "Import or enter rosters → review category deficits → plan trades.",
                        "Send category focus to trade and lineup tools.",
                    ],
                },
            ],
        },
        {
            "id": "lineup",
            "title": "Fantasy Lineup Assistant",
            "icon": "🧠",
            "page_key": "Fantasy Lineup Assistant",
            "tagline": "Set optimal lineups and bench decisions each scoring period.",
            "sections": [
                {
                    "title": "Purpose",
                    "bullets": [
                        "Recommend legal starting lineups by position eligibility.",
                        "Start/sit guidance and trade ideas based on category needs.",
                    ],
                },
                {
                    "title": "Workflows",
                    "bullets": [
                        "Load stats from Standings Tracker → review recommended starters → adjust for matchups.",
                    ],
                },
            ],
        },
        {
            "id": "metrics",
            "title": "Key metrics glossary",
            "icon": "📐",
            "page_key": None,
            "tagline": "Short definitions for scores you'll see across fantasy pages.",
            "sections": [
                {
                    "title": "Metric cheat sheet",
                    "bullets": [
                        "**Fantasy Edge** — Market Rank − Model Rank; higher often means undervalued.",
                        "**Draft Fit Score** — Roster/category fit for your team right now.",
                        "**Decision Score** — Live-draft pick quality (value + need + urgency).",
                        "**Scarcity Score** — How thin the position is on the remaining board.",
                        "**Volatility** — Year-to-year unpredictability in production.",
                        "**Slope** — Trend direction/strength over the selected window.",
                        "**R²** — Consistency of that trend (not the same as 'good player').",
                        "**Expected Fantasy Value (EFV)** — Blended projected fantasy production score.",
                    ],
                },
            ],
        },
    )


def _close_tutorial() -> None:
    st.session_state[TUTORIAL_OPEN_KEY] = False


def _set_step(idx: int) -> None:
    steps = get_tutorial_steps()
    st.session_state[TUTORIAL_STEP_KEY] = max(0, min(int(idx), len(steps) - 1))


def render_tutorial_header_bar() -> None:
    """Lightweight bar directly under the main app title (not in sidebar)."""
    init_tutorial_prefs()
    if tutorial_button_hidden():
        return

    st.markdown(_tutorial_css(), unsafe_allow_html=True)
    left, right = st.columns([4, 1])
    with left:
        st.markdown(
            '<p class="tutorial-bar-text">New here? Take a guided tour of every major tool — '
            "about three minutes, at your own pace.</p>",
            unsafe_allow_html=True,
        )
    with right:
        if st.button(
            "📘 Start Tutorial",
            key="tutorial_header_open_btn",
            use_container_width=True,
            type="secondary",
        ):
            st.session_state[TUTORIAL_OPEN_KEY] = True
            st.session_state[TUTORIAL_STEP_KEY] = 0
            st.rerun()


def _render_step_sections(sections: list[dict[str, Any]]) -> None:
    for block in sections:
        title = block.get("title") or ""
        bullets = block.get("bullets") or []
        body = block.get("body")
        if block.get("expandable"):
            with st.expander(title, expanded=False):
                if body:
                    st.markdown(body)
                if bullets:
                    st.markdown("\n".join(f"- {b}" for b in bullets))
        else:
            st.markdown(f'<div class="tutorial-card"><h4>{title}</h4>', unsafe_allow_html=True)
            if body:
                st.markdown(body)
            if bullets:
                st.markdown("\n".join(f"- {b}" for b in bullets))
            st.markdown("</div>", unsafe_allow_html=True)


@st.dialog("Daniel Cohen Baseball Explorer — Tutorial", width="large")
def tutorial_dialog() -> None:
    steps = get_tutorial_steps()
    init_tutorial_prefs()
    if TUTORIAL_STEP_KEY not in st.session_state:
        st.session_state[TUTORIAL_STEP_KEY] = 0

    idx = int(st.session_state.get(TUTORIAL_STEP_KEY, 0))
    idx = max(0, min(idx, len(steps) - 1))
    step = steps[idx]

    st.markdown(
        f'<span class="tutorial-step-pill">Step {idx + 1} of {len(steps)}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f"### {step.get('icon', '')} {step.get('title', '')}")
    if step.get("tagline"):
        st.markdown(f'<p class="tutorial-tagline">{step["tagline"]}</p>', unsafe_allow_html=True)

    st.divider()
    _render_step_sections(step.get("sections") or [])

    page_key = step.get("page_key")
    if page_key:
        st.caption(f"Related page: **{page_key}**")
        if st.button(
            f"Open {page_key}",
            key=f"tutorial_open_page_{step.get('id', idx)}",
            use_container_width=False,
        ):
            st.session_state[TUTORIAL_NAV_PAGE_KEY] = page_key
            _close_tutorial()
            st.rerun()

    st.divider()
    nav = st.columns([1, 1, 1, 1, 1])
    with nav[0]:
        if st.button(
            "← Previous",
            key="tutorial_btn_prev",
            disabled=idx <= 0,
            use_container_width=True,
        ):
            _set_step(idx - 1)
            st.rerun()
    with nav[1]:
        if st.button(
            "Next →",
            key="tutorial_btn_next",
            disabled=idx >= len(steps) - 1,
            use_container_width=True,
        ):
            _set_step(idx + 1)
            st.rerun()
    with nav[2]:
        if st.button("Finish Tour", key="tutorial_btn_finish", use_container_width=True):
            _close_tutorial()
            st.rerun()
    with nav[3]:
        if st.button("Close", key="tutorial_btn_close", use_container_width=True):
            _close_tutorial()
            st.rerun()
    with nav[4]:
        if st.button("Don't show again", key="tutorial_btn_hide", use_container_width=True):
            hide_tutorial_button_permanently()
            _close_tutorial()
            st.rerun()

    st.caption(
        "Tip: Each analytics page also has a short **Quick guide** at the top when you visit it."
    )


def maybe_open_tutorial_dialog() -> None:
    """Call once per run after navigation helpers exist."""
    if st.session_state.get(TUTORIAL_OPEN_KEY):
        tutorial_dialog()
