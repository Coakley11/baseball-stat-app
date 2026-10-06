"""Mobile M2 — top-of-page navigation and header compaction.

Phone-only additions, CSS-gated so desktop is byte-for-byte unaffected:

- ``render_mobile_quick_nav``: a compact "current page" label plus a single
  grouped jump selectbox, rendered at the very top of the main content column
  (before the hero). Lets a phone visitor see where they are and switch pages
  without ever opening the sidebar. Routes through the SAME
  ``MAIN_SIDEBAR_PAGE_KEY`` / on_change contract as an ordinary sidebar click
  (passed in by the caller) — no parallel navigation state, no new precedence
  rules to reconcile with baseball_persistent_state's restore logic.
- ``hide_hero_subtitle_on_phone_css``: the generic hero subtitle line is
  redundant with both this quick-nav label and each page's own title card;
  hidden on phones only.

Preserves all Baseball product logic: this module only ever reads
``active_page`` / the page-options list handed to it and writes the same
sidebar-radio session key an ordinary click would.
"""

from __future__ import annotations

from typing import Any, Callable

try:
    from mobile_foundation import PHONE_MAX_PX
except ImportError:  # pragma: no cover - foundation module always present in-repo
    PHONE_MAX_PX = 640

QUICK_NAV_ROOT_KEY = "m-quick-nav-root"
QUICK_NAV_SELECT_KEY = "_mobile_quick_nav_select"

# Every PAGE_OPTIONS entry must appear here exactly once — validated against the
# live streamlit_app.PAGE_OPTIONS list by tests/test_mobile_nav_m2.py so a newly
# added page can't silently fall out of the mobile quick-nav.
PAGE_GROUPS: dict[str, str] = {
    "Historical Explorer": "Explore & Analyze",
    "Career Totals": "Explore & Analyze",
    "Leaderboards": "Explore & Analyze",
    "Comparison Tool": "Explore & Analyze",
    "Trend Value": "Explore & Analyze",
    "Valuation": "Explore & Analyze",
    "ML Predictions": "Explore & Analyze",
    "Fantasy Sleepers & Busts": "Explore & Analyze",
    "Draft Room Simulator": "Draft Tools",
    "Draft Assistant Simulator": "Draft Tools",
    "Draft Lab / Simulation": "Draft Tools",
    "Saved Draft Library": "Draft Tools",
    "Live Draft Room": "Live Draft",
    "Fantasy Standings Tracker": "Fantasy Team",
    "Fantasy Lineup Assistant": "Fantasy Team",
    "Waiver Wire / Add-Drop Center": "Fantasy Team",
}

# Fixed display order for groups; anything not in PAGE_GROUPS is appended,
# ungrouped, at the end — so a future page that forgets to register a group
# stays reachable (never silently dropped) instead of erroring.
GROUP_ORDER: tuple[str, ...] = ("Explore & Analyze", "Draft Tools", "Live Draft", "Fantasy Team")

__all__ = (
    "PAGE_GROUPS",
    "GROUP_ORDER",
    "QUICK_NAV_ROOT_KEY",
    "QUICK_NAV_SELECT_KEY",
    "grouped_page_options",
    "render_mobile_quick_nav",
    "mobile_header_compaction_css",
)


def grouped_page_options(page_options: list[str]) -> list[str]:
    """``page_options`` reordered so same-group pages sit together.

    Group order is fixed by ``GROUP_ORDER``; relative order within a group is
    preserved from the input list. Every input page is kept — an unmapped page
    is appended at the end rather than dropped.
    """
    by_group: dict[str, list[str]] = {g: [] for g in GROUP_ORDER}
    ungrouped: list[str] = []
    for page in page_options:
        group = PAGE_GROUPS.get(page)
        if group in by_group:
            by_group[group].append(page)
        else:
            ungrouped.append(page)
    ordered: list[str] = []
    for group in GROUP_ORDER:
        ordered.extend(by_group[group])
    ordered.extend(ungrouped)
    return ordered


def _quick_nav_css() -> str:
    # Hide only ABOVE the phone breakpoint. On phones keep Streamlit's own flex-column
    # layout for this keyed stVerticalBlock: forcing ``display: block`` (M2) collapsed
    # the label's element container to ~7px and the selectbox overlapped the label.
    return f"""<style>
@media (min-width: {PHONE_MAX_PX + 1}px) {{
    .st-key-{QUICK_NAV_ROOT_KEY},
    [data-testid="stLayoutWrapper"]:has(> .st-key-{QUICK_NAV_ROOT_KEY}) {{ display: none; }}
}}
@media (max-width: {PHONE_MAX_PX}px) {{
    .st-key-{QUICK_NAV_ROOT_KEY} {{ gap: 4px; }}
    /* Streamlit pulls every markdown container up by -1rem to cancel a trailing <p>
       margin; this label is a <div> with no such margin, so that collapsed its row
       and the selectbox overlapped the label. */
    .st-key-{QUICK_NAV_ROOT_KEY} [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
    .m-quick-nav-current {{
        font-size: 12px; font-weight: 700; color: #0b3d6e;
        text-transform: uppercase; letter-spacing: 0.04em;
        margin-bottom: 4px;
    }}
    .st-key-{QUICK_NAV_ROOT_KEY} [data-testid="stSelectbox"] > div {{
        min-height: 2.5rem;
    }}
}}
</style>"""


def mobile_header_compaction_css() -> str:
    """Hide the generic hero subtitle line on phones only.

    It is redundant there: the quick-nav "current page" label above it and
    each page's own title card below it already say what page this is.
    Desktop keeps the subtitle exactly as before.
    """
    return f"""<style>
@media (max-width: {PHONE_MAX_PX}px) {{
    .title-box .subtitle-text {{ display: none; }}
}}
</style>"""


def render_mobile_quick_nav(
    st: Any,
    *,
    active_page: str,
    page_options: list[str],
    page_option_label: Callable[[str], str],
    main_sidebar_page_key: str,
    on_sidebar_page_change: Callable[[], None],
) -> None:
    """Render the phone-only current-page banner + jump selectbox.

    No-op visually on desktop (CSS-hidden); still mounts the same two elements
    every run so Streamlit's widget identity stays stable across reruns.

    The stylesheet rides inside the label's markdown (inside the keyed container), so
    on desktop the whole quick-nav — styles included — is one hidden layout item and
    costs no flex gap. A ``<style>`` still applies inside a ``display: none`` parent.
    """
    ordered = grouped_page_options(page_options)
    try:
        current_index = ordered.index(active_page)
    except ValueError:
        current_index = 0
    # Keep the widget's own session-state key in lockstep with the resolved
    # active_page for THIS rerun. Without this, navigating via the sidebar (or a
    # deep link) would leave this selectbox showing a stale prior selection —
    # Streamlit widgets prefer their session_state[key] over `index=` once set.
    if st.session_state.get(QUICK_NAV_SELECT_KEY) != active_page:
        st.session_state[QUICK_NAV_SELECT_KEY] = active_page

    def _format(page: str) -> str:
        group = PAGE_GROUPS.get(page, "")
        label = page_option_label(page)
        return f"{group} · {label}" if group else label

    def _on_change() -> None:
        picked = st.session_state.get(QUICK_NAV_SELECT_KEY)
        if not picked or picked == st.session_state.get(main_sidebar_page_key):
            return
        st.session_state[main_sidebar_page_key] = picked
        on_sidebar_page_change()

    with st.container(key=QUICK_NAV_ROOT_KEY):
        # Each <style> block and the label start on their own line (CommonMark HTML
        # blocks end on the line containing </style>).
        st.markdown(
            _quick_nav_css()
            + "\n"
            + mobile_header_compaction_css()
            + "\n"
            # Mobile M7 (a11y): a real <nav> landmark, so a screen-reader user can jump
            # straight to the phone page switcher — the app otherwise exposes no <nav>
            # landmark at all. Same class, so M2's styling and layout are unchanged;
            # <nav> is a CommonMark block tag like <div>, so parsing is unchanged too.
            # The pin emoji is decorative and hidden from the accessibility tree.
            + f'<nav class="m-quick-nav-current" aria-label="Current page">'
            + f'<span aria-hidden="true">\U0001f4cd</span> {page_option_label(active_page)}</nav>',
            unsafe_allow_html=True,
        )
        st.selectbox(
            "Jump to page",
            ordered,
            index=current_index,
            format_func=_format,
            key=QUICK_NAV_SELECT_KEY,
            on_change=_on_change,
            label_visibility="collapsed",
        )
