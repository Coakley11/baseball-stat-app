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
            "headline": (
                "This app is built for two kinds of people who love baseball: fans who settle "
                "kitchen-table debates, and fantasy managers who want an edge from draft day through October."
            ),
            "paths": [
                ("🔎 Baseball history fan", "Explore eras, compare legends, and build a Hall of Fame case."),
                ("🏆 Fantasy manager", "Prep drafts, run Live Draft with friends, then manage your roster all season."),
            ],
            "steps": [],
            "tries": [],
        },
        {
            "id": "historical",
            "kind": "normal",
            "title": "Historical Baseball",
            "icon": "🔎",
            "page_key": "Historical Explorer",
            "headline": (
                "Ever wonder whether Hank Aaron or Willie Mays was better across their primes? "
                "Want to settle a debate with your friends? Start here."
            ),
            "steps": [
                "Open **Historical Explorer** and set years, team, or position.",
                "Sort by the stat that wins your argument — HR, OPS, SB, and more.",
                "Jump to **Comparison Tool** when you want two or three players side by side.",
                "Use **Career Totals** when one season is not enough — you want the full run.",
                "Turn on **Hall of Fame Case Mode** when you are building (or busting) a Cooperstown case.",
            ],
            "tries": [
                "Compare Hank Aaron vs Willie Mays by peak seasons, then flip to career totals.",
                "Filter 1990s Mets hitters and sort by OPS — who was really the franchise star?",
                "Pick a borderline Hall of Fame candidate and test them in Hall of Fame Mode.",
            ],
            "tip": "Think of this as your research desk for arguments, eras, and all-time rankings — not homework.",
        },
        {
            "id": "draft_prep",
            "kind": "normal",
            "title": "Draft Preparation",
            "icon": "🧪",
            "page_key": "Draft Lab / Simulation",
            "headline": (
                "Draft night should not be the first time you see your board. "
                "Use the prep tools to practice strategy and find values before the clock starts."
            ),
            "steps": [
                "Run mock drafts in **Draft Lab / Simulation** and **Draft Room Simulator**.",
                "Open **Draft Assistant Simulator** while you draft — see who fits your roster right now.",
                "Check **Fantasy Sleepers & Busts**, **Trend Value**, and rankings for upside and landmines.",
                "Use player comparisons when two similar names are available at the same pick.",
                "Import or upload drafts from fantasy sites into your **Saved Draft Library**, then keep analyzing.",
            ],
            "tries": [
                "Run a short mock draft this weekend and try pitching-heavy vs bats-first.",
                "Star three sleepers, then see if they still look good under Draft Assistant pressure.",
                "Upload last year’s draft and study where your roster got thin.",
            ],
            "tip": "Practice mock drafts, experiment with strategy, and analyze the roster while you draft — mistakes in prep are free.",
        },
        {
            "id": "live_draft",
            "kind": "normal",
            "title": "Live Draft Room",
            "icon": "📡",
            "page_key": "Live Draft Room",
            "headline": (
                "When it is time for the real thing, move into the Live Draft Room — "
                "a shared room where your league drafts together in real time."
            ),
            "steps": [
                "Create a shared league room and invite your friends with the room code.",
                "Draft together on a live board with a real pick timer and auto-pick if someone stalls.",
                "Get live recommendations plus team-need and position-need updates while you are on the clock.",
                "Use the same draft tools you practiced with — queue, best available, and survival-style helps — during the draft.",
                "Chat with the league in the room so everyone stays on the same pick.",
            ],
            "tries": [
                "Invite a friend, claim teams, and run a two-manager practice room before draft night.",
                "On the clock with two shortstops left — trust the live recommendation, then decide.",
            ],
            "tip": "You do not need every panel on day one — the win is drafting together with live help when it counts.",
        },
        {
            "id": "fantasy_mgmt",
            "kind": "normal",
            "title": "Fantasy Management",
            "icon": "📊",
            "page_key": "Fantasy Standings Tracker",
            "headline": (
                "The draft is only opening day. These tools help you manage a fantasy team through the whole season."
            ),
            "steps": [
                "**Fantasy Standings Tracker** — see which categories you are winning and losing.",
                "**Fantasy Lineup Assistant** — set your weekly starters with help on positional needs.",
                "**Trade Center** — propose and evaluate trades, then keep the roster balanced.",
                "**Waiver Wire / Add-Drop Center** — find free agents who actually fit what your team needs.",
                "Use weekly lineup management as a habit — small edges stack over a season.",
            ],
            "tries": [
                "Load standings, notice you are last in steals, then hunt waivers for speed.",
                "Before lineup lock, open Lineup Assistant and challenge one of your benches.",
            ],
            "tip": "Standings → Lineup → Waivers/Trades is a simple weekly loop that keeps the league competitive.",
        },
        {
            "id": "finish",
            "kind": "end",
            "title": "You are ready to play ball",
            "icon": "🎉",
            "headline": (
                "Start with the path that matches you — history debates or fantasy season play — "
                "and reopen this tour anytime from Start Tutorial."
            ),
            "steps": [
                "Baseball fan? Open **Historical Explorer** and settle one debate today.",
                "Draft soon? Spend 20 minutes in **Draft Lab** or **Sleepers**, then try **Live Draft Room**.",
                "Season underway? Check **Standings**, set a lineup, then scan the **Waiver Wire**.",
            ],
            "tries": [
                "Pick one page right now and run one search or one mock pick — that is how the app clicks.",
            ],
            "tip": "You do not have to use every page. Use the ones that make baseball more fun and your fantasy week smarter.",
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
