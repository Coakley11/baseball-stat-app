"""Guided onboarding tutorial — fan-friendly walkthrough (not developer docs)."""

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
.tutorial-tagline { color: #4f6475; font-size: 15px; margin: 0 0 12px 0; line-height: 1.5; }
.tutorial-example {
    background: #fff8e6; border-left: 4px solid #e6a817; padding: 12px 14px;
    border-radius: 8px; margin: 10px 0 14px 0; font-size: 14px; color: #3d3d3d; line-height: 1.45;
}
.tutorial-example strong { color: #7a5a00; }
</style>
"""


@lru_cache(maxsize=1)
def get_tutorial_steps() -> tuple[dict[str, Any], ...]:
    """Fan-focused steps — one screen at a time, short and practical."""
    return (
        {
            "id": "welcome",
            "kind": "welcome",
            "title": "Welcome",
            "icon": "⚾",
            "page_key": None,
            "tagline": (
                "This app helps you explore baseball history, compare players, find trends, "
                "discover fantasy sleepers, simulate drafts, and run a live fantasy draft."
            ),
            "sections": [
                {
                    "title": "What you can do here",
                    "bullets": [
                        "Research any era — great seasons, franchise legends, fun stat hunts.",
                        "Prep for fantasy — sleepers, busts, mock drafts, and live draft help.",
                        "Follow your season — standings, lineups, and category needs.",
                    ],
                },
            ],
        },
        {
            "id": "filters",
            "kind": "normal",
            "title": "How to use filters",
            "icon": "🎛️",
            "page_key": None,
            "tagline": "Most pages let you narrow the player pool before you look at tables and charts.",
            "sections": [
                {
                    "title": "The basics",
                    "bullets": [
                        "**Choose years** — one season or a range (e.g. 1998–2002).",
                        "**Choose teams** — one club or several.",
                        "**Choose positions** — SS, OF, C, and more.",
                        "**Choose batting hand** — left, right, or switch.",
                        "**Set minimum stats** — e.g. at least 20 HR or a .300 batting average.",
                    ],
                },
            ],
            "example": (
                "Want Mets hitters from 1998–2002 with 20+ home runs? "
                "Pick **Mets**, set the **year range**, and set **minimum HR** to 20."
            ),
        },
        {
            "id": "historical",
            "kind": "normal",
            "title": "Historical Explorer",
            "icon": "🔎",
            "page_key": "Historical Explorer",
            "tagline": "Search season-by-season baseball history and discover great years.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "Browse individual seasons across MLB history.",
                        "Find breakout years, compare eras, and spot patterns.",
                        "Filter by team, year, position, batting hand, and stat minimums.",
                        "Sort the table and turn on charts when you want a visual look.",
                    ],
                },
            ],
            "example": "Try finding all right-handed Mets hitters from 1998–2002.",
        },
        {
            "id": "career",
            "kind": "normal",
            "title": "Career Totals",
            "icon": "📚",
            "page_key": "Career Totals",
            "tagline": "See what players did over the long haul — not just one season.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "View career totals across the years you pick.",
                        "Compare long-term production between stars.",
                        "See totals by team or franchise — great for “best Met ever” debates.",
                        "Settle Hall of Fame or franchise-greatest arguments with real numbers.",
                    ],
                },
            ],
            "example": (
                "Compare career totals for Mets stars, or see who hit the most home runs "
                "for a franchise in a given era."
            ),
        },
        {
            "id": "leaderboards",
            "kind": "normal",
            "title": "Leaderboards",
            "icon": "🏆",
            "page_key": "Leaderboards",
            "tagline": "Quick answer: who led in this stat?",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "Rank players by HR, RBI, SB, OPS, batting average, and more.",
                        "See the top seasons or careers for the stat you care about.",
                        "Use filters to narrow the list (years, position, team, etc.).",
                    ],
                },
            ],
            "example": "Find the top OPS seasons by shortstops in the 2010s.",
        },
        {
            "id": "comparison",
            "kind": "normal",
            "title": "Comparison Tool",
            "icon": "📈",
            "page_key": "Comparison Tool",
            "tagline": "Pick players and compare them side by side.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "Choose up to three players and compare their stats directly.",
                        "See who was better in counting stats, rate stats, and trends.",
                        "Use charts to compare production year by year.",
                    ],
                },
                {
                    "title": "Actions for a player",
                    "bullets": [
                        "Quickly **send a player** to another page (Trends, Valuation, and more).",
                        "**Add to your watchlist** while you draft or research.",
                        "**Compare** or **analyze his trend** without retyping his name.",
                    ],
                },
            ],
        },
        {
            "id": "trends_valuation",
            "kind": "normal",
            "title": "Trends and Valuation",
            "icon": "🔥",
            "page_key": "Trend Value",
            "tagline": "See who is heating up, cooling off, or worth a closer look.",
            "sections": [
                {
                    "title": "Use these pages to…",
                    "bullets": [
                        "Spot players whose stats are **going up** or **going down**.",
                        "Use **trend charts** to see whether production is rising or falling.",
                        "Use **scatterplots** to compare many players at once — each dot is a player.",
                        "**Valuation** gives you one ranked list mixing recent stats and trend direction.",
                    ],
                },
                {
                    "title": "A few terms, in plain English",
                    "bullets": [
                        "**Slope** — Positive means trending up; negative means trending down.",
                        "**R²** — Higher means the trend is more steady and reliable (less random noise).",
                        "**Volatility** — How up-and-down the player has been from year to year.",
                        "**Scatterplot** — Players farther right or up are stronger on those axes, depending on the chart.",
                    ],
                },
            ],
            "example": "Before a trade, check whether a hitter’s OPS slope is positive and his R² is high.",
        },
        {
            "id": "sleepers",
            "kind": "normal",
            "title": "Fantasy Sleepers & Busts",
            "icon": "💎",
            "page_key": "Fantasy Sleepers & Busts",
            "tagline": "Find underrated picks and players who might be overpriced.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "Find **sleepers** — players the app likes more than the market does.",
                        "Watch **bust risk** — names that may be drafted too high.",
                        "**Fantasy Edge** — positive often means “the app likes him more than ADP.”",
                        "**Sleeper Score** — highlights hidden value.",
                    ],
                },
            ],
            "example": "Look for players with a high Fantasy Edge and strong projected value.",
        },
        {
            "id": "draft_assistant",
            "kind": "normal",
            "title": "Fantasy Draft Assistant",
            "icon": "🧩",
            "page_key": "Draft Assistant Simulator",
            "tagline": "Get help building your roster during draft prep.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "See who to draft next based on value, position, team needs, and risk.",
                        "Decide whether a player **fits your roster** right now.",
                        "Pair with **Draft Room Simulator** to log picks as you go.",
                    ],
                },
                {
                    "title": "Scores you’ll see",
                    "bullets": [
                        "**Expected Fantasy Value** — How valuable the player is projected to be.",
                        "**Draft Fit Score** — How well he fits your team right now.",
                        "**Decision Score** — The app’s overall recommendation for this pick.",
                        "**Scarcity** — How hard it is to find good players at that position.",
                    ],
                },
            ],
        },
        {
            "id": "draft_sim",
            "kind": "normal",
            "title": "Draft Simulation Test Mode",
            "icon": "🧪",
            "page_key": "Draft Simulation Test Mode",
            "tagline": "Practice a full fantasy draft before the real one.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "Run a **mock draft** with the number of teams and rounds you choose.",
                        "See how each team’s roster turns out.",
                        "Review **strengths, weaknesses, best picks, risky picks, and position gaps**.",
                        "Try different strategies (power early vs speed, etc.) and compare results.",
                    ],
                },
            ],
            "example": "Run a 4-team draft to see how different strategies play out.",
        },
        {
            "id": "live_draft",
            "kind": "normal",
            "title": "Live Draft Room",
            "icon": "📡",
            "page_key": "Live Draft Room",
            "tagline": "Run your draft night in the app.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "Draft players **manually** or use **recommendations** and **auto-pick**.",
                        "Follow the **draft board**, **team rosters**, and **best available** list.",
                        "See **Decision Score** to compare options on the clock.",
                    ],
                },
                {
                    "title": "Survival probability",
                    "body": (
                        "Answers a simple question: **Can I wait another round, or should I draft him now?** "
                        "Higher means he’s more likely to still be there next time you pick."
                    ),
                },
            ],
        },
        {
            "id": "standings",
            "kind": "normal",
            "title": "Fantasy Standings Tracker",
            "icon": "📊",
            "page_key": "Fantasy Standings Tracker",
            "tagline": "See how your fantasy teams stack up.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "Track how each fantasy team is doing by category.",
                        "Spot **strengths** (categories you’re winning) and **weaknesses** (what you need).",
                        "Figure out whether you need more HR, SB, ERA, or other categories.",
                    ],
                },
            ],
        },
        {
            "id": "lineup",
            "kind": "normal",
            "title": "Fantasy Lineup Assistant",
            "icon": "🧠",
            "page_key": "Fantasy Lineup Assistant",
            "tagline": "Set a stronger lineup each week.",
            "sections": [
                {
                    "title": "Use this page to…",
                    "bullets": [
                        "Get help deciding **who to start** and who to bench.",
                        "Balance categories based on what your team needs.",
                        "Works best after you’ve loaded teams in **Fantasy Standings Tracker**.",
                    ],
                },
            ],
        },
        {
            "id": "send_filters",
            "kind": "normal",
            "title": "Sending filters to another page",
            "icon": "↗️",
            "page_key": None,
            "tagline": "Save time — you don’t have to re-enter the same filters everywhere.",
            "sections": [
                {
                    "title": "How it works",
                    "bullets": [
                        "Many pages let you **send your current filters** to another page.",
                        "Your year range, team, position, and minimums carry over automatically.",
                    ],
                },
                {
                    "title": "Top 3 players checkbox",
                    "bullets": [
                        "On some pages you can check **“Also send top 3 players from current results.”**",
                        "The app sends the top three names from your table or chart to **Comparison** or **Trends**.",
                    ],
                },
            ],
            "example": (
                "If you filtered Mets hitters from 1998–2002 in Historical Explorer, "
                "you can send those filters to Career Totals or Leaderboards in one click."
            ),
        },
        {
            "id": "tracked",
            "kind": "normal",
            "title": "Tracked Players",
            "icon": "👀",
            "page_key": None,
            "tagline": "Keep a short list of names you’re watching.",
            "sections": [
                {
                    "title": "Use this for…",
                    "bullets": [
                        "Players you’re studying for a draft, trade, or debate.",
                        "Names you sent to Comparison or Trends — they can land in your tracked list.",
                        "Quick access in the sidebar while you jump between pages.",
                    ],
                },
            ],
        },
        {
            "id": "finish",
            "kind": "end",
            "title": "You are all set",
            "icon": "🎉",
            "page_key": None,
            "tagline": (
                "You can use this app as a **baseball research tool**, a **fantasy draft prep tool**, "
                "or a **live fantasy draft assistant**. Pick a page in the sidebar and start exploring."
            ),
            "sections": [
                {
                    "title": "Quick reminders",
                    "bullets": [
                        "Open **📘 Tutorial** under the header anytime for this tour again.",
                        "Each page has a short **Quick guide** at the top when you visit it.",
                        "Use the sidebar **watchlist** and **draft queue** during draft season.",
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
            '<p class="tutorial-bar-text">New here? Take a quick tour — '
            "built for baseball fans and fantasy players.</p>",
            unsafe_allow_html=True,
        )
    with right:
        if st.button(
            "📘 Tutorial",
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


def _render_example(text: str | None) -> None:
    if text:
        st.markdown(f'<div class="tutorial-example"><strong>Try this:</strong> {text}</div>', unsafe_allow_html=True)


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
        if st.button("← Previous", key="tutorial_btn_prev", disabled=idx <= 1, use_container_width=True):
            _set_step(idx - 1)
            st.rerun()
    with nav[1]:
        if st.button("Next →", key="tutorial_btn_next", disabled=idx >= n_steps - 2, use_container_width=True):
            _set_step(idx + 1)
            st.rerun()
    with nav[2]:
        if st.button("Skip tour", key="tutorial_btn_skip", use_container_width=True):
            _close_tutorial()
            st.rerun()
    with nav[3]:
        if st.button("Don't show again", key="tutorial_btn_hide", use_container_width=True):
            hide_tutorial_button_permanently()
            _close_tutorial()
            st.rerun()


@st.dialog("Baseball Explorer — Quick Tour", width="large")
def tutorial_dialog() -> None:
    steps = get_tutorial_steps()
    init_tutorial_prefs()
    if TUTORIAL_STEP_KEY not in st.session_state:
        st.session_state[TUTORIAL_STEP_KEY] = 0

    idx = int(st.session_state.get(TUTORIAL_STEP_KEY, 0))
    idx = max(0, min(idx, len(steps) - 1))
    step = steps[idx]
    kind = step.get("kind", "normal")

    if kind != "welcome":
        st.markdown(
            f'<span class="tutorial-step-pill">Step {idx + 1} of {len(steps)}</span>',
            unsafe_allow_html=True,
        )

    st.markdown(f"### {step.get('icon', '')} {step.get('title', '')}")
    if step.get("tagline"):
        st.markdown(f'<p class="tutorial-tagline">{step["tagline"]}</p>', unsafe_allow_html=True)

    st.divider()
    _render_step_sections(step.get("sections") or [])
    _render_example(step.get("example"))

    page_key = step.get("page_key")
    if page_key and kind == "normal":
        if st.button(
            f"Go to {page_key}",
            key=f"tutorial_open_page_{step.get('id', idx)}",
        ):
            st.session_state[TUTORIAL_NAV_PAGE_KEY] = page_key
            _close_tutorial()
            st.rerun()

    st.divider()
    if kind == "welcome":
        _render_welcome_buttons()
    elif kind == "end":
        _render_end_buttons()
    else:
        _render_middle_nav(idx, len(steps))


def maybe_open_tutorial_dialog() -> None:
    if st.session_state.get(TUTORIAL_OPEN_KEY):
        tutorial_dialog()
