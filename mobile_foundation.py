"""Mobile responsive foundation — shared breakpoints, global CSS, opt-in layout helpers.

Layout only. No product logic, state, or data changes.

Breakpoint convention (max-width, aligned with Streamlit 1.59's own theme):
  ``PHONE_MAX_PX`` (640)   — Streamlit stacks ``st.columns`` at or below this width.
  ``TABLET_MAX_PX`` (768)  — existing app "compact layout" breakpoint.
  ``SMALL_PHONE_MAX_PX`` (400) — narrow phones (360–400px).

Feature CSS should reuse these values (``media_phone()`` etc.) instead of new ad-hoc
breakpoints.

Opt-in helpers (keyed ``st.container`` → ``st-key-<key>`` class hook):
  ``mobile_inline_row(st, key)`` — keep a short ``st.columns`` row side-by-side on
      phones (icon/button pairs, pagination) instead of stacking every column.
  ``mobile_wrap_row(st, key)``   — let a button/control row wrap into ~2-up tiles on
      phones instead of one full-width button per line.
  ``mobile_scroll_x(html)``      — wrap raw HTML (tables, boards) in a horizontal
      scroller so wide content scrolls inside its card, never the whole page.
"""

from __future__ import annotations

import html as _html
from typing import Any

PHONE_MAX_PX = 640
TABLET_MAX_PX = 768
SMALL_PHONE_MAX_PX = 400

INLINE_ROW_KEY_PREFIX = "m-inline-"
WRAP_ROW_KEY_PREFIX = "m-wrap-"
SCROLL_X_CLASS = "m-scroll-x"

__all__ = (
    "PHONE_MAX_PX",
    "TABLET_MAX_PX",
    "SMALL_PHONE_MAX_PX",
    "INLINE_ROW_KEY_PREFIX",
    "WRAP_ROW_KEY_PREFIX",
    "SCROLL_X_CLASS",
    "media_phone",
    "media_tablet",
    "media_small_phone",
    "mobile_foundation_css",
    "mobile_foundation_style_tag",
    "inject_mobile_foundation_css",
    "mobile_inline_row",
    "mobile_wrap_row",
    "mobile_scroll_x",
)


def media_phone() -> str:
    return f"@media (max-width: {PHONE_MAX_PX}px)"


def media_tablet() -> str:
    return f"@media (max-width: {TABLET_MAX_PX}px)"


def media_small_phone() -> str:
    return f"@media (max-width: {SMALL_PHONE_MAX_PX}px)"


_MAIN = '[data-testid="stMainBlockContainer"]'
_INLINE = f'[class*="st-key-{INLINE_ROW_KEY_PREFIX}"]'
_WRAP = f'[class*="st-key-{WRAP_ROW_KEY_PREFIX}"]'
# A horizontal block holding st.metric tiles and no interactive widgets, tables or charts.
# (:has() cannot be nested — browsers drop the whole rule — so keep both checks flat.)
_METRIC_ROW_EXCLUDES = ", ".join(
    f'[data-testid="{tid}"]'
    for tid in (
        "stButton", "stSelectbox", "stMultiSelect", "stTextInput", "stNumberInput",
        "stDataFrame", "stTable", "stVegaLiteChart", "stPlotlyChart", "stExpander",
    )
)
_METRIC_ROW = (
    '[data-testid="stHorizontalBlock"]'
    ':has(> [data-testid="stColumn"] [data-testid="stMetric"])'
    f":not(:has({_METRIC_ROW_EXCLUDES}))"
)


def mobile_foundation_css() -> str:
    """Global responsive rules. Pure string so tests can assert on it."""
    return f"""
/* Mobile foundation (M1) — layout only */

/* 1. Overflow containment at the source: media, code, markdown tables, long tokens. */
{_MAIN} img, {_MAIN} video, {_MAIN} iframe {{ max-width: 100%; }}
{_MAIN} img {{ height: auto; }}
{_MAIN} [data-testid="stMarkdownContainer"] {{ overflow-wrap: break-word; }}
{_MAIN} [data-testid="stMarkdownContainer"] pre {{ max-width: 100%; overflow-x: auto; }}
{media_phone()} {{
    {_MAIN} [data-testid="stMarkdownContainer"] table {{
        display: block; max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch;
    }}
}}
{_MAIN} [data-testid="stTable"] {{ max-width: 100%; overflow-x: auto; }}
{_MAIN} [data-testid="stVegaLiteChart"], {_MAIN} [data-testid="stArrowVegaLiteChart"],
{_MAIN} [data-testid="stPlotlyChart"], {_MAIN} [data-testid="stDataFrame"] {{ max-width: 100%; }}
.{SCROLL_X_CLASS} {{
    display: block; max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch;
}}
.{SCROLL_X_CLASS} > table {{ min-width: max-content; }}

/* 2. Columns: let wide-screen columns shrink instead of overflowing. Phone stacking
      (Streamlit's own <= {PHONE_MAX_PX}px rule) is left untouched. */
@media (min-width: {PHONE_MAX_PX + 1}px) {{
    [data-testid="stColumn"] {{ min-width: 0; }}
}}

/* 3. Compact page chrome + typography on tablets/phones. */
{media_tablet()} {{
    .title-box {{ padding: 14px 16px; border-radius: 12px; margin-bottom: 12px; }}
    .title-text {{ font-size: clamp(1.4rem, 0.9rem + 3vw, 2rem); line-height: 1.15; }}
    .subtitle-text {{ font-size: 14px; margin-top: 4px; }}
    .section-card {{ padding: 12px; margin-bottom: 12px; }}
    .section-title {{ font-size: clamp(1.1rem, 0.85rem + 1.6vw, 1.4rem); }}
    .page-guide {{ padding: 10px 12px; margin-bottom: 12px; }}
    .page-guide-body {{ font-size: 13px; }}
    .fantasy-source-card {{ padding: 12px 14px; }}
    .fantasy-source-name {{ font-size: 18px; }}
}}

{media_phone()} {{
    /* Gutters */
    {_MAIN} {{ padding-left: 0.75rem !important; padding-right: 0.75rem !important; }}
    {_MAIN} h1 {{ font-size: 1.75rem; }}
    {_MAIN} h2 {{ font-size: 1.4rem; }}
    {_MAIN} h3 {{ font-size: 1.2rem; }}

    /* M6: alerts (session-restore banners, warnings, etc.) use desktop-generous
       padding everywhere; every page can show one, so a little tightening adds up. */
    {_MAIN} [data-testid="stAlert"] {{ padding: 0.6rem 0.85rem; font-size: 0.92rem; }}

    /* 4. Touch targets: buttons >= 44px, radio/checkbox rows >= 40px. */
    [data-testid^="stBaseButton-"] {{ min-height: 2.75rem; }}
    [data-testid="stBaseButton-headerNoPadding"], [data-testid="stBaseButton-header"],
    [data-testid="stBaseButton-elementToolbar"] {{ min-height: 0; }}
    [role="radiogroup"] > label, [data-testid="stCheckbox"] > label {{
        min-height: 2.5rem; align-items: center;
    }}
    /* M2's Quick Guide is a raw <details>/<summary>, not a Streamlit widget, so the
       button sizing above never reaches it. Measured 21px tall on all 16 pages --
       below the 24px minimum, and on phones it is the only control that opens the
       card. Block layout is kept deliberately: the disclosure arrow is a floated
       ::after, and flex would stop honouring that float. Desktop is untouched --
       page_quick_guide.py makes the summary a non-toggle above {PHONE_MAX_PX}px. */
    .page-guide > summary {{ min-height: 2.25rem; padding: 8px 0; margin-bottom: 0; }}

    /* Inputs at 16px so iOS Safari does not zoom the page on focus. */
    input, textarea, [data-baseweb="select"] input, [data-baseweb="select"] > div {{
        font-size: 16px !important;
    }}

    /* 5. Dialogs / popovers fit the viewport. */
    [data-testid="stDialog"] div[role="dialog"] {{
        max-width: calc(100vw - 1rem) !important;
        max-height: calc(100dvh - 1.5rem);
        overflow-y: auto;
    }}
    [data-testid="stPopoverBody"] {{ max-width: calc(100vw - 1rem); }}
    [data-testid="stTabs"] [role="tablist"] {{ overflow-x: auto; scrollbar-width: none; }}
}}

/* 6. Rows made only of st.metric tiles go 2-up on phones instead of one per line.
      Values wrap (not ellipsis) so no metric text is hidden. */
{media_phone()} {{
    {_METRIC_ROW} {{ flex-wrap: wrap; gap: 0.75rem; }}
    {_METRIC_ROW} > [data-testid="stColumn"] {{
        min-width: calc(50% - 0.75rem) !important; flex: 1 1 calc(50% - 0.75rem) !important;
    }}
    {_METRIC_ROW} [data-testid="stMetricValue"] {{ font-size: 1.2rem !important; }}
    {_METRIC_ROW} [data-testid="stMetricValue"] > div {{
        white-space: normal; overflow-wrap: anywhere; text-overflow: clip;
    }}
}}

/* 7. Opt-in row helpers (see mobile_inline_row / mobile_wrap_row). */
{media_phone()} {{
    {_INLINE} [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap; gap: 0.5rem; }}
    {_INLINE} [data-testid="stColumn"] {{
        min-width: 0 !important; width: auto !important; flex: 1 1 0 !important;
    }}
    {_WRAP} [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; gap: 0.5rem; }}
    {_WRAP} [data-testid="stColumn"] {{
        min-width: min(9.5rem, 100%) !important; width: auto !important;
        flex: 1 1 calc(50% - 0.5rem) !important;
    }}
    /* Streamlit action buttons only: a bare ``button`` selector also stretched the
       select (react-aria ComboBox) chevron and number-input steppers over the field. */
    {_WRAP} [data-testid="stColumn"] [data-testid^="stBaseButton-"] {{ width: 100%; }}
}}

/* 8. A components.html() carrier rendered with height=0 (invisible sync/diagnostic
      iframes, several in Live Draft) is itself 0px tall, but its element-container
      still costs one flex `gap` — on a phone, with many such carriers stacked, that
      adds up to real wasted vertical space. Collapse only the genuinely zero-height
      case; anything with real height (may render content later) is left untouched. */
{media_phone()} {{
    {_MAIN} [data-testid="stElementContainer"]:has(> [data-testid="stIFrame"] > iframe[height="0"]),
    {_MAIN} [data-testid="stElementContainer"]:has(> [data-testid="stIFrame"][style*="height: 0px"]),
    {_MAIN} [data-testid="stElementContainer"]:has(> [data-testid="stIFrame"] > iframe[style*="height: 0px"]) {{
        display: none;
    }}
}}
"""


def mobile_foundation_style_tag() -> str:
    """``<style>`` tag for appending to an existing CSS ``st.markdown`` call.

    Prefer this over ``inject_mobile_foundation_css``: every separate ``st.markdown``
    adds an (empty) element container, and the block gap after it shifts the page down.
    """
    return f"<style>{mobile_foundation_css()}</style>"


def inject_mobile_foundation_css(st: Any) -> None:
    """Emit the foundation stylesheet as its own element (entry points without base CSS)."""
    st.markdown(mobile_foundation_style_tag(), unsafe_allow_html=True)


def _safe_key(key: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(key or "row")).strip("-") or "row"


def mobile_inline_row(st: Any, key: str):
    """Container whose ``st.columns`` stay side-by-side on phones (short rows only)."""
    return st.container(key=f"{INLINE_ROW_KEY_PREFIX}{_safe_key(key)}")


def mobile_wrap_row(st: Any, key: str):
    """Container whose ``st.columns`` wrap into ~2-up tiles on phones (button/control groups)."""
    return st.container(key=f"{WRAP_ROW_KEY_PREFIX}{_safe_key(key)}")


def mobile_scroll_x(inner_html: str, *, label: str | None = None) -> str:
    """Wrap raw HTML so wide content scrolls horizontally inside itself on phones."""
    aria = f' role="region" aria-label="{_html.escape(label)}" tabindex="0"' if label else ""
    return f'<div class="{SCROLL_X_CLASS}"{aria}>{inner_html}</div>'
