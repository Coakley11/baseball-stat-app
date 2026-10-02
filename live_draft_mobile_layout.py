"""Live Draft mobile layout (M3) — phone-only composition for the Live Draft Room.

Presentation only. This module owns no draft, room, queue, timer or recommendation
state. It emits CSS and hands out keyed ``st.container`` hooks that wrap EXISTING
render calls in ``streamlit_app.py`` / ``live_draft_control_center_ui.py``. Python
render order is never changed.

Why CSS ``order`` + ``display: contents`` instead of moving code: the Live Draft page
mounts ``st.fragment`` timers whose identity is ``hash(function + delta_path)``.
Moving calls, or inserting new sibling elements above a fragment, changes its delta
path and remounts the clock — the exact failure the Live Draft code is hardened
against. Each hook here wraps one existing call site, and every reorder is visual.

Phone hierarchy (<= ``PHONE_MAX_PX``) for the full live view (multiplayer, or Solo
while its clock is not owned by the timer fragment). Desktop is untouched.

  1. On the Clock / current pick / timer          (banner compacted, timer beside team)
  2. Essential status pills, primary draft action  (Manual Draft: search + Draft)
  3. Host controls (Pause / Auto Pick / Reset)
  4. Team Needs, decision context, Recommendations (cards become swipe rows)
  5. Draft Queue + Draft Board
  6. Rankings tables, then room/team context, chat, rosters, totals

The 2-column desktop block (board | recommendations) and the control-center/chat
block are "flattened" on phones with ``display: contents`` so their children become
flex items of the page column and can be ordered across the whole page.

The Solo minimal-clock view (timer fragment owns the page and the ScriptRun stops
after the Quick Queue) only gets the redundant-title removal and banner compaction:
it renders nothing else to reorder.
"""

from __future__ import annotations

from typing import Any

try:
    from mobile_foundation import PHONE_MAX_PX
except ImportError:  # pragma: no cover - foundation module always present in-repo
    PHONE_MAX_PX = 640

# Keyed-container hooks (Streamlit renders ``key=`` as the ``st-key-<key>`` class).
ACTION_KEY = "ldr-m-action"                 # rec column Manual Draft panel
ACTION_EARLY_KEY = "ldr-m-action-early"     # Solo early-viewport Manual Draft panel
CONTROLS_KEY = "ldr-m-controls"             # Draft Control Center (+ live chat columns)
RECS_KEY = "ldr-m-recs"                     # recommendation cards (rec column)
RECS_EARLY_KEY = "ldr-m-recs-early"         # Solo early-viewport recommendation cards
ACTIVE_TITLE_KEY = "ldr-m-active-title"     # active-draft "### Live Draft Room" title
BRAND_CAPTION_KEY = "ldr-m-brand"           # suppressed-hero brand caption
DUP_SUMMARY_KEY = "ldr-m-dup-summary"       # 2nd Draft Status Summary (multiplayer)
DUP_ROOM_HEADER_KEY = "ldr-m-dup-room-header"  # room header card repeating code/teams

# Setup rows wrapped with mobile_foundation.mobile_wrap_row (2-up on phones).
LEAGUE_SETTINGS_ROW = "ldr-league-settings"
ROSTER_SLOTS_ROW = "ldr-roster-slots"
TEAM_NAMES_ROW = "ldr-team-names"

# Phone order tiers (lower = higher on the page). Untiered page items keep order 0.
ORDER_QUICK_NAV = -100
ORDER_ALERTS = -97          # top-level status messages (e.g. "Drafted X to Team A")
ORDER_CLOCK = -95
ORDER_STATUS_PILLS = -93
ORDER_ACTION = -90
ORDER_CONTROLS = -85
ORDER_REC_COLUMN = -50
ORDER_BOARD_COLUMN = -20
ORDER_REC_TABLES = -10
ORDER_CHAT = 5

__all__ = (
    "ACTION_KEY",
    "ACTION_EARLY_KEY",
    "CONTROLS_KEY",
    "RECS_KEY",
    "RECS_EARLY_KEY",
    "ACTIVE_TITLE_KEY",
    "BRAND_CAPTION_KEY",
    "DUP_SUMMARY_KEY",
    "DUP_ROOM_HEADER_KEY",
    "LEAGUE_SETTINGS_ROW",
    "ROSTER_SLOTS_ROW",
    "TEAM_NAMES_ROW",
    "live_draft_mobile_css",
    "live_draft_mobile_style_tag",
    "keyed",
)

_ACTIONS = f'[class*="st-key-{ACTION_KEY}"]'  # matches both action hooks
_HB = '[data-testid="stHorizontalBlock"]'
_COL = '[data-testid="stColumn"]'
_VB = '[data-testid="stVerticalBlock"]'
_LW = '[data-testid="stLayoutWrapper"]'
# The page column of a live Live Draft view (only it contains a draft-action hook).
_PAGE = f'[data-testid="stMainBlockContainer"] > {_VB}:has({_ACTIONS})'
# The desktop board | recommendations block = the columns block holding the action.
_MAIN_HB = f"{_HB}:has(> {_COL} {_ACTIONS})"
_BOARD_ITEMS = f"{_PAGE} {_MAIN_HB} > {_COL}:not(:has({_ACTIONS})) > {_VB} > *"
_REC_ITEMS = f"{_PAGE} {_MAIN_HB} > {_COL}:has({_ACTIONS}) > {_VB} > *"
_CLOCK_IFRAME = 'iframe[srcdoc*="live-draft-on-clock"]'
_EC = '[data-testid="stElementContainer"]'
_MDC = '[data-testid="stMarkdownContainer"]'
# Any Live Draft page (setup rows, active title / brand hooks, action hooks).
_LD_PAGE = '[data-testid="stMainBlockContainer"]:has([class*="ldr-"])'
_CTRL = f".st-key-{CONTROLS_KEY}"
_RECS = f'[class*="st-key-{RECS_KEY}"]'  # matches both rec-card hooks
# The control | chat 2-column block, with or without the control-center function's own
# inner container (observed live: ldr-m-controls > LW > VB > LW > HB). Explicit paths
# on purpose: a generic ``:has(2-column)`` would also flatten the bordered Control
# Center card, which has its own 2-column button rows.
_CTRL_HB_PATHS = (
    f"{_CTRL} > {_LW} > {_HB}",
    f"{_CTRL} > {_HB}",
    f"{_CTRL} > {_LW} > {_VB} > {_LW} > {_HB}",
)


def _hide(key: str) -> str:
    return (
        f".st-key-{key}, {_LW}:has(> .st-key-{key}) "
        "{ display: none !important; }"
    )


def _flatten() -> str:
    """Let the 2-column and control/chat blocks' children join the page flex column.

    One rule, one selector list — so every selector must be valid on its own (a single
    invalid selector, e.g. a nested ``:has()``, makes the browser drop the whole rule).
    """
    sel = ",\n    ".join(
        [
            f"{_PAGE} > {_LW}:has(> {_HB} > {_COL} {_ACTIONS})",
            f"{_PAGE} {_MAIN_HB}",
            f"{_PAGE} {_MAIN_HB} > {_COL}",
            f"{_PAGE} {_MAIN_HB} > {_COL} > {_VB}",
            f"{_PAGE} > {_LW}:has(> {_CTRL})",
            f"{_PAGE} {_CTRL}",
            f"{_PAGE} {_CTRL} > {_LW}",
            f"{_PAGE} {_CTRL} > {_LW} > {_VB}:has(> {_LW} > {_HB} > {_COL} + {_COL})",
            f"{_PAGE} {_CTRL} > {_LW} > {_VB} > {_LW}:has(> {_HB} > {_COL} + {_COL})",
        ]
        + [
            f"{_PAGE} {path}{tail}"
            for path in _CTRL_HB_PATHS
            for tail in ("", f" > {_COL}", f" > {_COL} > {_VB}")
        ]
    )
    return f"{sel} {{ display: contents !important; }}"


def _ctrl_cols() -> str:
    first = ", ".join(f"{_PAGE} {p} > {_COL}:first-child > {_VB} > *" for p in _CTRL_HB_PATHS)
    chat = ", ".join(f"{_PAGE} {p} > {_COL} + {_COL} > {_VB} > *" for p in _CTRL_HB_PATHS)
    return f"{first} {{ order: {ORDER_CONTROLS}; }}\n    {chat} {{ order: {ORDER_CHAT}; }}"


def live_draft_mobile_css() -> str:
    """Phone-only Live Draft composition rules. Pure string so tests can assert on it."""
    return f"""
/* Live Draft mobile layout (M3) — phone only, presentation only */
@media (max-width: {PHONE_MAX_PX}px) {{
    /* Redundant on phones: the M2 quick-nav label already names the page. */
    {_hide(ACTIVE_TITLE_KEY)}
    {_hide(BRAND_CAPTION_KEY)}
    /* Duplicates of the room code / status already shown once in the live view. */
    {_PAGE} {_hide(DUP_SUMMARY_KEY)}
    {_PAGE} {_hide(DUP_ROOM_HEADER_KEY)}

    /* Zero-height elements still cost the column's 1rem flex gap; on the Live Draft
       page a dozen of them stacked ~200px of blank space above the clock. Style-only
       markdown blocks and the deploy-build instrumentation marker are taken out of
       LAYOUT only — <style> rules still apply and the marker stays in the DOM. */
    {_LD_PAGE} {_EC}:has(> [data-testid="stMarkdown"] {_MDC} > style:first-child):not(:has(> [data-testid="stMarkdown"] {_MDC} > :not(style))),
    {_LD_PAGE} {_EC}:has(#solo-deploy-build) {{ display: none !important; }}

    /* 1. On the Clock: compact card, timer beside the team name (same markup). */
    .live-draft-on-clock {{
        display: grid !important; grid-template-columns: 1fr auto; column-gap: 12px;
        align-items: center; padding: 14px 14px 12px 16px !important;
        border-radius: 14px !important; margin-bottom: 4px !important;
    }}
    .live-draft-on-clock .ld-title {{ grid-column: 1; margin-bottom: 2px !important; }}
    .live-draft-on-clock .ld-team-name {{
        grid-column: 1; font-size: 1.7rem !important; margin: 0 0 6px 0 !important;
        overflow-wrap: anywhere;
    }}
    .live-draft-on-clock .ld-pick-pills, .live-draft-on-clock .ld-next-pick {{ grid-column: 1; }}
    .live-draft-on-clock .ld-next-pick {{ margin: 6px 0 0 0 !important; }}
    .live-draft-on-clock .ld-meta {{
        grid-column: 2; grid-row: 1 / span 4; flex-direction: column !important;
        justify-content: center !important; align-items: center !important; gap: 4px !important;
    }}
    .live-draft-on-clock .ld-clock-label {{ font-size: 10px !important; letter-spacing: 0.08em; }}
    .live-draft-on-clock .live-draft-timer {{
        font-size: 26px !important; min-width: 64px !important; padding: 8px 12px !important;
    }}

    /* 2-6. Full live view: flatten the desktop column blocks, then order by tier. */
    {_flatten()}
    {_PAGE} > {_LW}:has(> .st-key-m-quick-nav-root) {{ order: {ORDER_QUICK_NAV}; }}
    {_PAGE} > *:has(.live-draft-status-badges) {{ order: {ORDER_STATUS_PILLS}; }}
    {_REC_ITEMS} {{ order: {ORDER_REC_COLUMN}; }}
    {_REC_ITEMS}:has([data-testid="stExpander"]) {{ order: {ORDER_REC_TABLES}; }}
    {_BOARD_ITEMS} {{ order: {ORDER_BOARD_COLUMN}; }}
    {_PAGE} > {_EC}:has(> [data-testid="stAlert"]) {{ order: {ORDER_ALERTS}; }}
    /* Host controls: without live chat the control center's own items sit directly
       under the hook; with chat, its 2 columns are flattened and ordered separately. */
    {_PAGE} {_CTRL} > {_LW} > * {{ order: {ORDER_CONTROLS}; }}
    {_ctrl_cols()}
    /* Clock + action LAST and on the same base selectors as the tier rules above, so
       they win on specificity / source order (the generic rec-column rule otherwise
       beat the action rule — caught live). Solo banner is in-page markup; the shared
       banner is a components.html iframe whose srcdoc carries the same class. */
    {_PAGE} > *:has(.live-draft-on-clock) {{ order: {ORDER_CLOCK}; }}
    {_REC_ITEMS}:has(.live-draft-on-clock),
    {_REC_ITEMS}:has({_CLOCK_IFRAME}) {{ order: {ORDER_CLOCK}; }}
    {_PAGE} > *:has(> {_ACTIONS}),
    {_REC_ITEMS}:has(> {_ACTIONS}) {{ order: {ORDER_ACTION}; }}

    /* 4. Recommendation cards: each 3-card row becomes a swipe strip (all cards and
       their Draft / Queue buttons stay rendered; peek of the next card signals more). */
    {_RECS} {_HB} {{
        flex-wrap: nowrap !important; overflow-x: auto; scroll-snap-type: x mandatory;
        -webkit-overflow-scrolling: touch; gap: 0.75rem; padding-bottom: 6px;
    }}
    {_RECS} {_HB} > {_COL} {{
        flex: 0 0 82% !important; min-width: 82% !important; width: 82% !important;
        scroll-snap-align: start;
    }}
}}
"""


def live_draft_mobile_style_tag() -> str:
    """``<style>`` tag for appending to an existing CSS ``st.markdown`` call (no extra element)."""
    return f"<style>{live_draft_mobile_css()}</style>"


def keyed(st: Any, key: str):
    """Keyed container hook. Wrap exactly one existing call site with it."""
    return st.container(key=key)
