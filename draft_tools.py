"""The five draft tools, what each one is for, and how to move between them (U3A).

One place for the purpose copy, so the page headers, the "Draft tools" switcher and the Home
draft card all describe each tool the same way. Page keys are unchanged; nothing here touches
draft state. Live Draft shows the switcher only before a draft starts (its intro), never inside
an active room.
"""

from __future__ import annotations

from typing import Any, Callable

# (page key, icon, name, purpose) — purpose answers "use this when…"
DRAFT_TOOLS: tuple[tuple[str, str, str, str], ...] = (
    ("Live Draft Room", "📡", "Live Draft Room",
     "Draft in real time with pick timers and auto-pick: solo against the computer, or in a shared room with your league. "
     "Your board saves as you draft."),
    ("Draft Room Simulator", "🧾", "Draft Room Simulator",
     "Set up a league and log every pick yourself, for a practice draft or one running on another site. "
     "Draft Assistant reads this board."),
    ("Draft Assistant Simulator", "🧩", "Draft Assistant",
     "Who to pick next: rankings from your board's team needs, positional scarcity and market value, with reasons."),
    ("Draft Lab / Simulation", "🧪", "Draft Lab",
     "Test a strategy: the computer runs a four-team snake mock draft, then grades every roster."),
    ("Saved Draft Library", "📁", "Saved Draft Library",
     "Your saved drafts and leagues: open, rename, share, or make one your active league."),
)

# Home's draft card: the four ways in (a landing without a separate page).
HOME_DRAFT_CHOICES: tuple[tuple[str, str], ...] = (
    ("Run a Live Draft", "Live Draft Room"),
    ("Simulate a Draft", "Draft Room Simulator"),
    ("Analyze Draft Strategy", "Draft Lab / Simulation"),
    ("Open Saved Drafts", "Saved Draft Library"),
)

_BY_PAGE = {page: (icon, name, purpose) for page, icon, name, purpose in DRAFT_TOOLS}


def purpose(page: str) -> str:
    return _BY_PAGE.get(page, ("", "", ""))[2]


def render_draft_tool_nav(st: Any, current_page: str, navigate: Callable[[str], Callable[[], None]]) -> None:
    """A compact row of the other draft tools (tertiary buttons; the tooltip says what each is for).
    ``navigate(page)`` returns an on_click callback that only schedules navigation."""
    others = [(page, icon, name, why) for page, icon, name, why in DRAFT_TOOLS if page != current_page]
    if not others:
        return
    slug = "".join(ch if ch.isalnum() else "-" for ch in current_page.lower()).strip("-")
    from ui_hierarchy import inject_css

    inject_css(st)  # draft pages keep their own header, so the U1 styles may not be on the page yet
    # Tertiary buttons read as plain text, so these are drawn as outlined pills in the Draft
    # family colour: clearly something to tap, still lighter than the page's main actions.
    try:
        from feature_identity import family

        fam = family("draft")
        pill = (f'<style>[class*="st-key-u3dt_"] button {{ border: 1px solid {fam.border} !important; '
                f"background: {fam.tint} !important; border-radius: 999px !important; padding: 2px 12px !important; }}"
                f'[class*="st-key-u3dt_"] button p {{ color: {fam.color} !important; font-weight: 600; }}'
                f'[class*="st-key-u3dt_"] button:hover {{ border-color: {fam.color} !important; }}</style>')
    except ImportError:
        pill = ""
    st.markdown(pill + '<div class="u1-label">Other draft tools</div>', unsafe_allow_html=True)
    try:
        from mobile_foundation import mobile_wrap_row

        wrap = mobile_wrap_row(st, f"draft-tools-{slug}")
    except ImportError:
        wrap = st.container()
    with wrap:
        cols = st.columns(len(others))
    for i, ((page, icon, name, why), col) in enumerate(zip(others, cols)):
        col.button(f"{icon} {name}", key=f"u3dt_{slug}_{i}", type="tertiary", help=why, on_click=navigate(page))
