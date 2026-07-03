"""Fan-first onboarding tour — how to USE the app, not how it is built."""

from __future__ import annotations

import json
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
        data = json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_prefs(prefs: dict[str, Any]) -> None:
    try:
        _PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except OSError:
        pass


def init_tutorial_prefs() -> None:
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
    margin: -6px 0 18px 0; padding: 10px 16px;
    background: linear-gradient(90deg, #eef4ff 0%, #f8fbff 100%);
    border: 1px solid #c8daf5; border-radius: 12px;
}
.tutorial-bar-text { color: #3d5a73; font-size: 14px; margin: 0; }
.tour-hero {
    font-size: 17px; color: #12324a; font-weight: 600; line-height: 1.5;
    margin: 0 0 14px 0; padding: 12px 14px;
    background: linear-gradient(135deg, #e8f2ff 0%, #f5f9ff 100%);
    border-radius: 10px; border: 1px solid #c5daf5;
}
.tour-step-row {
    display: flex; gap: 12px; align-items: flex-start;
    background: #fff; border: 1px solid #d9e2ec; border-radius: 10px;
    padding: 10px 12px; margin-bottom: 8px;
}
.tour-step-num {
    flex-shrink: 0; width: 28px; height: 28px; border-radius: 50%;
    background: #1f4e79; color: #fff; font-weight: 800; font-size: 13px;
    display: flex; align-items: center; justify-content: center;
}
.tour-step-text { color: #2c3e50; font-size: 14px; line-height: 1.45; margin: 0; padding-top: 3px; }
.tour-try-label {
    font-size: 12px; font-weight: 700; color: #7a5a00; text-transform: uppercase;
    letter-spacing: 0.05em; margin: 14px 0 8px 0;
}
.tour-try-card {
    background: #fffbeb; border: 1px solid #f0d78c; border-radius: 8px;
    padding: 10px 12px; margin-bottom: 8px; font-size: 14px; color: #3d3d3d; line-height: 1.45;
}
.tour-tip {
    background: #edf7ed; border-left: 4px solid #2e7d32; padding: 10px 12px;
    border-radius: 6px; font-size: 13px; color: #2c4a2c; margin-top: 12px;
}
.tour-path-card {
    background: #f7f9fc; border: 1px solid #d9e2ec; border-radius: 10px;
    padding: 12px 14px; margin-bottom: 10px;
}
.tour-path-card strong { color: #12324a; }
.tour-progress-label { font-size: 12px; color: #5a6f82; margin-bottom: 4px; }
</style>
"""


def get_tutorial_steps() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": "welcome",
            "kind": "welcome",
            "title": "Welcome, baseball fan",
            "icon": "⚾",
            "headline": "This app is your baseball research desk and fantasy draft sidekick.",
            "paths": [
                ("🔎 Baseball fan", "Debate eras, compare legends, hunt fun stat lines."),
                ("🏆 Fantasy player", "Find sleepers, practice drafts, and win your league."),
            ],
            "steps": [],
            "tries": [],
        },
        {
            "id": "filters",
            "kind": "normal",
            "title": "Narrow your search",
            "icon": "🎛️",
            "page_key": None,
            "headline": "Filters help you find exactly the players you care about.",
            "steps": [
                "Pick a **year** or **year range** (one season or many).",
                "Pick a **team**, **position**, and **batting hand** if you want.",
                "Set **minimum stats** (like 20+ HR or .300 AVG) to cut the noise.",
                "Hit the table — your list updates right away.",
            ],
            "tries": [
                "Want great Mets hitters from the late 1990s? Choose Mets, set years to 1998–2002, then sort by HR or OPS.",
                "Hunting 30-HR seasons? Set minimum HR to 30 and pick a position.",
            ],
            "tip": "Filters stay saved when you switch pages, so you do not have to start over.",
        },
        {
            "id": "historical",
            "kind": "normal",
            "title": "Historical Explorer",
            "icon": "🔎",
            "page_key": "Historical Explorer",
            "headline": "Go here to explore season-by-season baseball history.",
            "steps": [
                "Open **Historical Explorer** in the sidebar.",
                "Set your filters (team, years, position, etc.).",
                "Sort the table by the stat you care about (HR, OPS, SB…).",
                "Optional: turn on a chart to see the leaders visually.",
            ],
            "tries": [
                "Find all right-handed Mets hitters from 1998–2002.",
                "Search for 30-HR shortstops in the 2000s.",
                "Compare steroid-era sluggers by sorting HR in the late 90s.",
            ],
            "tip": "Great for settle-the-argument debates at the kitchen table.",
        },
        {
            "id": "career",
            "kind": "normal",
            "title": "Career Totals",
            "icon": "📚",
            "page_key": "Career Totals",
            "headline": "Go here when one great season is not enough — you want the full career picture.",
            "steps": [
                "Open **Career Totals**.",
                "Choose the years you want included in the career window.",
                "Filter by team or position if you are focused on one franchise or role.",
                "Sort by HR, RBI, OPS, or whatever stat wins the debate.",
            ],
            "tries": [
                "Compare career totals for Mets stars — who was the franchise home run king?",
                "Settle a Hall of Fame argument with counting stats across a player's whole run.",
            ],
            "tip": "Use the by-team toggle if you care about what a player did for one franchise.",
        },
        {
            "id": "leaderboards",
            "kind": "normal",
            "title": "Leaderboards",
            "icon": "🏆",
            "page_key": "Leaderboards",
            "headline": "Go here for a fast answer: who led the league in this stat?",
            "steps": [
                "Open **Leaderboards**.",
                "Pick the stat to rank (HR, RBI, SB, OPS, AVG…).",
                "Set years and filters to match your question.",
                "Read the top of the table — that is your leaderboard.",
            ],
            "tries": [
                "Find the top OPS seasons by shortstops.",
                "Who stole the most bases in the 1980s?",
            ],
            "tip": "Perfect when you just need a quick top-10, not a deep dive.",
        },
        {
            "id": "comparison",
            "kind": "normal",
            "title": "Comparison Tool",
            "icon": "📈",
            "page_key": "Comparison Tool",
            "headline": "Go here to settle 'who was better?' between two or three players.",
            "steps": [
                "Open **Comparison Tool**.",
                "Pick up to three players from the dropdowns.",
                "Read the side-by-side stats and charts.",
                "Use **Actions for Player** to send someone to Trends or add them to your watchlist.",
            ],
            "tries": [
                "Compare Aaron Judge vs Juan Soto year by year.",
                "Compare two Hall of Fame candidates before you argue on Twitter.",
            ],
            "tip": "Quick actions let you compare, track, or analyze a trend without retyping names.",
            "advanced": {
                "bullets": [
                    "Actions for Player: send to Trends, Valuation, watchlist, or draft queue in one click.",
                ],
            },
        },
        {
            "id": "trends",
            "kind": "normal",
            "title": "Who is heating up?",
            "icon": "🔥",
            "page_key": "Trend Value",
            "headline": "Go here to see which players are rising, fading, or all over the place.",
            "steps": [
                "Open **Trend Value** (and **Valuation** for one combined ranking list).",
                "Filter to the position or years you care about.",
                "Look for players trending up before your fantasy draft or trade deadline.",
                "Open a scatterplot — each dot is a player; compare them visually.",
            ],
            "tries": [
                "Find a young hitter whose OPS keeps climbing — a possible breakout.",
                "Check a veteran before you trade him away — is he still trending up?",
            ],
            "tip": "Think of this as 'who is hot and who is cold' — not just one season snapshots.",
            "advanced": {
                "bullets": [
                    "Slope: trending up (positive) or down (negative).",
                    "R-squared: higher means a steadier trend you can trust more.",
                    "Volatility: how up-and-down his seasons have been.",
                ],
            },
        },
        {
            "id": "sleepers",
            "kind": "normal",
            "title": "Fantasy Sleepers & Busts",
            "icon": "💎",
            "page_key": "Fantasy Sleepers & Busts",
            "headline": "Go here to find underrated sleepers and overpriced busts before draft day.",
            "steps": [
                "Open **Fantasy Sleepers & Busts**.",
                "Browse the sleeper list for names the app likes more than the market.",
                "Check the bust list for players who might be drafted too high.",
                "Star the names you want on your draft board.",
            ],
            "tries": [
                "Look for undervalued outfielders with strong projected value.",
                "Avoid a big name with high bust risk before you reach in round 3.",
            ],
            "tip": "Run this page a few days before your draft while your rankings are still flexible.",
            "advanced": {
                "bullets": [
                    "Fantasy Edge: positive often means the app ranks him higher than ADP.",
                    "Sleeper Score: highlights hidden value picks.",
                ],
            },
        },
        {
            "id": "fantasy_workflow",
            "kind": "normal",
            "title": "Your fantasy draft game plan",
            "icon": "📋",
            "page_key": None,
            "headline": "A simple workflow many fantasy players follow in this app:",
            "steps": [
                "**Before the draft** — check Sleepers & Busts for value and landmines.",
                "**Build your plan** — use Draft Assistant to see who fits your roster.",
                "**Practice** — run a Draft Simulation so you are not surprised on draft night.",
                "**Draft night** — open Live Draft Room for picks, best available, and recommendations.",
                "**During the season** — Standings Tracker, then Lineup Assistant each week.",
            ],
            "tries": [
                "Run a 4-team mock draft this weekend to test going heavy on pitching early.",
                "On draft night, watch survival probability before you wait on a catcher.",
            ],
            "tip": "You do not have to use every page — pick the ones that match how your league drafts.",
        },
        {
            "id": "draft_assistant",
            "kind": "normal",
            "title": "Fantasy Draft Assistant",
            "icon": "🧩",
            "page_key": "Draft Assistant Simulator",
            "headline": "Use this during fantasy draft prep to see which players fit your team best.",
            "steps": [
                "Open **Draft Assistant Simulator**.",
                "Tell the app your roster needs (positions you still need to fill).",
                "Read the recommended players — who helps you most right now.",
                "Log picks in **Draft Room Simulator** as your real or mock draft moves along.",
            ],
            "tries": [
                "You need speed and steals — sort recommendations and grab a burner late.",
                "Compare two first basemen when you are on the clock in round 8.",
            ],
            "tip": "Draft Fit is plain English for 'does this guy help my team today?'",
            "advanced": {
                "bullets": [
                    "Player Grade: projected overall value.",
                    "Roster Fit Score: fit for your roster right now.",
                    "Scarcity: fewer good players left at that position.",
                ],
            },
        },
        {
            "id": "draft_sim",
            "kind": "normal",
            "title": "Draft Simulation",
            "icon": "🧪",
            "page_key": "Draft Simulation Test Mode",
            "headline": "Practice your fantasy draft strategy before the real one.",
            "steps": [
                "Open **Draft Simulation Test Mode**.",
                "Choose how many teams and rounds you want.",
                "Let the app run the mock draft.",
                "Review each team's strengths, weak spots, and best picks afterward.",
            ],
            "tries": [
                "Run a 4-team draft to see how different strategies play out.",
                "Try power early vs speed early and compare the final rosters.",
            ],
            "tip": "Treat this like a rehearsal — mistakes here are free.",
        },
        {
            "id": "live_draft",
            "kind": "normal",
            "title": "Live Draft Room",
            "icon": "📡",
            "page_key": "Live Draft Room",
            "headline": "The Live Draft Room helps you run a real fantasy draft with recommendations and best available players.",
            "steps": [
                "Open **Live Draft Room** on draft night.",
                "Set up your teams and draft order.",
                "Make picks manually or let the app suggest (and auto-pick if you want).",
                "Watch the draft board and best available list between picks.",
            ],
            "tries": [
                "On the clock with two good shortstops left — compare who the app recommends first.",
                "Your target catcher is still there — check if you can wait one more round.",
            ],
            "tip": "Survival probability answers: 'Can I wait, or should I grab him now?'",
        },
        {
            "id": "standings",
            "kind": "normal",
            "title": "Fantasy Standings Tracker",
            "icon": "📊",
            "page_key": "Fantasy Standings Tracker",
            "headline": "Go here during the season to see how your fantasy team is doing.",
            "steps": [
                "Open **Fantasy Standings Tracker**.",
                "Load or enter your league's rosters.",
                "See which categories you are winning and losing.",
                "Note what you need more of (HR, SB, ERA, etc.).",
            ],
            "tries": [
                "You are last in steals — look for trade targets who run.",
                "Compare your team to the league leader in home runs.",
            ],
            "tip": "Load standings before you open Lineup Assistant for the week.",
        },
        {
            "id": "lineup",
            "kind": "normal",
            "title": "Fantasy Lineup Assistant",
            "icon": "🧠",
            "page_key": "Fantasy Lineup Assistant",
            "headline": "Go here each week to decide who to start and who to bench.",
            "steps": [
                "Open **Fantasy Lineup Assistant** (after standings are loaded).",
                "Pick your fantasy team.",
                "Review suggested starters by position.",
                "Swap bench players if you disagree — you know your matchups too.",
            ],
            "tries": [
                "Bench a slumping outfielder and start your streaking utility man.",
                "Fill your UTIL slot with whoever helps weak categories most.",
            ],
            "tip": "Use this every scoring period — lineups win tight weeks.",
        },
        {
            "id": "shortcuts",
            "kind": "normal",
            "title": "Save time between pages",
            "icon": "↗️",
            "page_key": None,
            "headline": "You do not have to re-enter the same search on every page.",
            "steps": [
                "Run a search on one page (team, years, position, etc.).",
                "Look for a button to **send your filters** to another page.",
                "Optional: check **send top 3 players** to carry the leaders into Comparison or Trends.",
            ],
            "tries": [
                "Filter Mets hitters 1998–2002 in Historical Explorer, then jump to Career Totals with one click.",
                "Send the top three names from a leaderboard straight into Comparison.",
            ],
            "tip": "Tracked Players in the sidebar saves names you are studying across pages.",
        },
        {
            "id": "tracked",
            "kind": "normal",
            "title": "Tracked Players",
            "icon": "👀",
            "page_key": None,
            "headline": "Tracked Players lets you save players you are studying.",
            "steps": [
                "When you compare or send a player somewhere, he can land on your tracked list.",
                "Open the **Tracked players** section in the sidebar anytime.",
                "Keep your draft targets and trade ideas in one place.",
            ],
            "tries": [
                "Track three sleepers from the Sleepers page, then revisit them on draft day.",
                "Track a trade target all week while you negotiate.",
            ],
            "tip": "Also use Watchlist and Draft Queue in the sidebar during draft season.",
        },
        {
            "id": "finish",
            "kind": "end",
            "title": "You are ready to play ball",
            "icon": "🎉",
            "headline": "Pick a page in the sidebar and start exploring — you can reopen this tour anytime.",
            "steps": [
                "Baseball fan? Start with **Historical Explorer** or **Comparison Tool**.",
                "Fantasy player? Start with **Sleepers & Busts**, then **Draft Assistant**.",
                "Draft tonight? Open **Live Draft Room**.",
            ],
            "tries": [
                "Run one fun stat search in the next five minutes — that is the best way to learn.",
            ],
            "tip": "Tap **Start Tutorial** under the header whenever you want this walkthrough again.",
        },
    )


def _close_tutorial() -> None:
    st.session_state[TUTORIAL_OPEN_KEY] = False


def _set_step(idx: int) -> None:
    n = len(get_tutorial_steps())
    st.session_state[TUTORIAL_STEP_KEY] = max(0, min(int(idx), n - 1))


def render_tutorial_header_bar() -> None:
    init_tutorial_prefs()
    if tutorial_button_hidden():
        return

    st.markdown(_tutorial_css(), unsafe_allow_html=True)
    left, right = st.columns([3, 1])
    left.markdown(
        '<p class="tutorial-bar-text">New here? <strong>Start Tutorial</strong> for a '
        "quick, fan-friendly walkthrough.</p>",
        unsafe_allow_html=True,
    )
    if right.button(
        "Start Tutorial",
        key="tutorial_header_open_btn",
        use_container_width=True,
        type="primary",
    ):
        st.session_state[TUTORIAL_OPEN_KEY] = True
        st.session_state[TUTORIAL_STEP_KEY] = 0
        st.rerun()


def _render_progress(idx: int, total: int) -> None:
    st.markdown(f'<p class="tour-progress-label">Tour progress</p>', unsafe_allow_html=True)
    st.progress((idx + 1) / total)


def _render_headline(text: str | None) -> None:
    if text:
        st.markdown(f'<p class="tour-hero">{text}</p>', unsafe_allow_html=True)


def _render_numbered_steps(steps: list[str]) -> None:
    for i, line in enumerate(steps, start=1):
        col_n, col_t = st.columns([0.07, 0.93], gap="small")
        with col_n:
            st.markdown(
                f'<div class="tour-step-num" style="margin-top:2px">{i}</div>',
                unsafe_allow_html=True,
            )
        with col_t:
            st.markdown(line)


def _render_tries(tries: list[str]) -> None:
    if not tries:
        return
    st.markdown('<p class="tour-try-label">Try this</p>', unsafe_allow_html=True)
    for t in tries:
        st.markdown(f'<div class="tour-try-card">⚾ {t}</div>', unsafe_allow_html=True)


def _render_tip(text: str | None) -> None:
    if text:
        st.markdown(f'<div class="tour-tip">💡 <strong>Fan tip:</strong> {text}</div>', unsafe_allow_html=True)


def _render_paths(paths: list[tuple[str, str]]) -> None:
    for label, desc in paths:
        st.markdown(
            f'<div class="tour-path-card"><strong>{label}</strong><br>{desc}</div>',
            unsafe_allow_html=True,
        )


def _render_advanced(advanced: dict[str, Any] | None) -> None:
    if not advanced:
        return
    bullets = advanced.get("bullets") or []
    if not bullets:
        return
    with st.expander("Advanced analytics (optional)", expanded=False):
        st.caption("Only open this if you want the extra numbers jargon.")
        for b in bullets:
            st.markdown(f"- {b}")


def _render_welcome_buttons() -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Start Tour", key="tutorial_welcome_start", use_container_width=True, type="primary"):
            _set_step(1)
            st.rerun()
    with c2:
        if st.button("Skip", key="tutorial_welcome_skip", use_container_width=True):
            _close_tutorial()
            st.rerun()
    with c3:
        if st.button("Don't show again", key="tutorial_welcome_hide", use_container_width=True):
            hide_tutorial_button_permanently()
            _close_tutorial()
            st.rerun()


def _render_end_buttons() -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Finish Tour", key="tutorial_end_finish", use_container_width=True, type="primary"):
            _close_tutorial()
            st.rerun()
    with c2:
        if st.button("Restart Tour", key="tutorial_end_restart", use_container_width=True):
            _set_step(0)
            st.rerun()
    with c3:
        if st.button("Don't show again", key="tutorial_end_hide", use_container_width=True):
            hide_tutorial_button_permanently()
            _close_tutorial()
            st.rerun()


def _render_middle_nav(idx: int, n_steps: int) -> None:
    nav = st.columns([1, 1, 1, 1])
    with nav[0]:
        if st.button("Back", key="tutorial_btn_prev", disabled=idx <= 1, use_container_width=True):
            _set_step(idx - 1)
            st.rerun()
    with nav[1]:
        if st.button("Next", key="tutorial_btn_next", disabled=idx >= n_steps - 2, use_container_width=True):
            _set_step(idx + 1)
            st.rerun()
    with nav[2]:
        if st.button("Skip tour", key="tutorial_btn_skip", use_container_width=True):
            _close_tutorial()
            st.rerun()
    with nav[3]:
        if st.button("Hide tutorial button", key="tutorial_btn_hide", use_container_width=True):
            hide_tutorial_button_permanently()
            _close_tutorial()
            st.rerun()


@st.dialog("How to use Baseball Explorer", width="large")
def tutorial_dialog() -> None:
    st.markdown(_tutorial_css(), unsafe_allow_html=True)
    steps = get_tutorial_steps()
    init_tutorial_prefs()
    if TUTORIAL_STEP_KEY not in st.session_state:
        st.session_state[TUTORIAL_STEP_KEY] = 0

    idx = max(0, min(int(st.session_state.get(TUTORIAL_STEP_KEY, 0)), len(steps) - 1))
    step = steps[idx]
    kind = step.get("kind", "normal")

    _render_progress(idx, len(steps))
    st.markdown(f"## {step.get('icon', '')} {step.get('title', '')}")
    _render_headline(step.get("headline"))

    if step.get("paths"):
        _render_paths(step["paths"])

    how = step.get("steps") or []
    if how and kind not in ("welcome",):
        st.markdown("**How to use it**")
        _render_numbered_steps(how)

    _render_tries(step.get("tries") or [])
    _render_tip(step.get("tip"))
    _render_advanced(step.get("advanced"))

    page_key = step.get("page_key")
    if page_key and kind == "normal":
        st.markdown("---")
        if st.button(f"Take me to {page_key}", key=f"tutorial_go_{step.get('id', idx)}", type="primary"):
            st.session_state[TUTORIAL_NAV_PAGE_KEY] = page_key
            _close_tutorial()
            st.rerun()

    st.markdown("---")
    if kind == "welcome":
        _render_welcome_buttons()
    elif kind == "end":
        _render_end_buttons()
    else:
        _render_middle_nav(idx, len(steps))


def maybe_open_tutorial_dialog() -> None:
    if st.session_state.get(TUTORIAL_OPEN_KEY):
        tutorial_dialog()
