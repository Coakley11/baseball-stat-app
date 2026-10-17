"""Navigation sections shared by the desktop sidebar and the phone page picker.

Purely presentational: the page keys (``streamlit_app.PAGE_OPTIONS``), the single sidebar
radio, deep links (``?active_page=``) and Back/Forward handling are unchanged. The sidebar
radio lists ``NAV_ORDER``; ``sidebar_section_css`` draws the section headings above the
first page of each section; the phone picker groups by ``PAGE_SECTION``.
"""

from __future__ import annotations

HOME_PAGE = "Home"

# (section, pages in display order). Every page key appears exactly once.
NAV_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Home", (HOME_PAGE,)),
    ("Players", ("Historical Explorer", "Career Totals", "Comparison Tool", "Leaderboards")),
    ("Insights", ("Trend Value", "Valuation", "ML Predictions", "Fantasy Sleepers & Busts")),
    ("Draft", ("Draft Room Simulator", "Draft Assistant Simulator", "Draft Lab / Simulation", "Live Draft Room")),
    ("My League", ("Fantasy Standings Tracker", "Fantasy Lineup Assistant", "Waiver Wire / Add-Drop Center",
                   "Saved Draft Library")),
    ("Account", ("Pricing & Upgrade",)),
)

NAV_ORDER: tuple[str, ...] = tuple(page for _section, pages in NAV_SECTIONS for page in pages)
PAGE_SECTION: dict[str, str] = {page: section for section, pages in NAV_SECTIONS for page in pages}
SECTION_ORDER: tuple[str, ...] = tuple(section for section, _pages in NAV_SECTIONS)

# Sidebar/phone display labels. Keys never change; only what the user reads. A page is renamed
# only when its own title changes with it (U1: League Standings, Waiver Wire; U2/U3: Compare
# Players, Sleepers & Busts, Lineup & Trades). Old labels still resolve to the key.
NAV_LABELS: dict[str, str] = {
    HOME_PAGE: "🏠 Home",
    "Fantasy Standings Tracker": "📊 League Standings",
    "Waiver Wire / Add-Drop Center": "🔄 Waiver Wire",
    "Comparison Tool": "📈 Compare Players",
    "Fantasy Sleepers & Busts": "💎 Sleepers & Busts",
    "Fantasy Lineup Assistant": "🧠 Lineup & Trades",  # U3: the page also holds the Trade Center
}


def ordered_pages(page_options) -> list[str]:
    """``page_options`` in section order; any page not registered here is appended (never lost)."""
    known = [p for p in NAV_ORDER if p in set(page_options)]
    return known + [p for p in page_options if p not in PAGE_SECTION]


def sidebar_section_css(radio_key: str, pages: list[str]) -> str:
    """CSS that draws a small section heading above the first page of each section.

    Targets the one sidebar radio (``.st-key-<radio_key>``); headings are generated
    content, so the radio, its options and its value are untouched.
    """
    rules = []
    seen: set[str] = set()
    for idx, page in enumerate(pages, start=1):
        section = PAGE_SECTION.get(page)
        if not section or section in seen:
            continue
        seen.add(section)
        if section == "Home":
            continue  # Home sits alone at the top; a "HOME" heading over it adds nothing.
        sel = f'section[data-testid="stSidebar"] .st-key-{radio_key} [role="radiogroup"] > label:nth-of-type({idx})'
        rules.append(
            f"{sel} {{ margin-top: 1.55rem; position: relative; }}\n"
            f'{sel}::before {{ content: "{section.upper()}"; position: absolute; left: 0; top: -1.3rem; '
            "font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; color: #6b7c8f; "
            "pointer-events: none; white-space: nowrap; }"
        )
    return "<style>\n" + "\n".join(rules) + "\n</style>"
