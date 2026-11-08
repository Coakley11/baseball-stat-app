"""One icon per kind of action, used on buttons app-wide (page icons live in feature_identity).

One library throughout: Google Material Symbols through Streamlit's built-in ``icon=":material/…:"``
(no extra package, no network fetch beyond Streamlit's own font). Names and values match the
``action_icons`` module on ``feature/baseball-completion`` so the two branches agree; this module adds
the actions that branch did not cover.

Owner decision 2026-11-07: wherever a control had an original colourful emoji before the redesign
(page labels, "⭐ Set Active League", "✅ Active Draft", "📁 Save to Draft Library", "⏸ Pause Draft",
"▶ Resume Draft", "⚡ Auto Pick Now", "🚪 Leave Room"), that emoji is back in its label and no
Material icon is set there. These Material codes remain only on controls that had no icon before.

Significant actions keep their words next to the icon ("Manage Subscription", "Delete Draft").
The suite navigation controls (Home, Command Center logo) are icon-only and carry a tooltip.
Simple step controls (Next, Back, Continue, Keep it, Cancel rename) deliberately have no icon.

Dangerous actions (delete, cancel an invite) sit in a container keyed ``bx-danger-…`` so they are
shown in red (``inject_action_styles``); the confirmation step that follows them is unchanged.
"""

from __future__ import annotations

from typing import Any

# --- shared with feature/baseball-completion (same names, same values) ---------------------------
ICON_DELETE = ":material/delete:"
ICON_RESET = ":material/restart_alt:"
ICON_LEAVE = ":material/logout:"
ICON_CANCEL = ":material/cancel:"

ADD_TO_QUEUE = "⭐"
WATCHLIST = ":material/bookmark_add:"
SIMULATE_PICK = ":material/sports_baseball:"
SAVE = ":material/save:"
DELETE = ICON_DELETE
RESET = ICON_RESET
EDIT = ":material/edit:"
DUPLICATE = ":material/content_copy:"
OPEN = ":material/folder_open:"
IMPORT = ":material/upload_file:"
SEARCH = ":material/search:"
SETTINGS = ":material/settings:"
SET_ACTIVE = ":material/check_circle:"
LINEUP = ":material/groups:"
REMOVE_FROM_LIST = ":material/remove_circle_outline:"  # takes an item off a working list; not a delete

# --- added here ---------------------------------------------------------------------------------
HOME = ":material/home:"
SUBSCRIPTION = ":material/credit_card:"
UPGRADE = ":material/workspace_premium:"
LOG_OUT = ICON_LEAVE
EXPORT = ":material/download:"
ACCEPT = ":material/check:"
DECLINE = ICON_CANCEL
CANCEL_INVITE = ICON_CANCEL
INVITE_MANAGER = ":material/person_add:"
SHARED_LEAGUE = ":material/emoji_events:"
SHARED_DRAFT = ":material/groups:"
JOIN_ROOM = ":material/login:"
DRAFT_QUEUE = ":material/format_list_numbered:"
STRATEGY = ":material/psychology:"  # the other branch uses "♟️"; reconcile to this when they meet
TRADE = ":material/swap_horiz:"
ROSTER = ":material/groups:"
STATS = ":material/bar_chart:"
PAUSE = ":material/pause:"
RESUME = ":material/play_arrow:"
AUTO_PICK = ":material/bolt:"
CLAIM_TEAM = ":material/how_to_reg:"
ANALYZE = ":material/analytics:"
WAIVERS = ":material/person_search:"
REFRESH = ":material/refresh:"

DANGER_KEY_PREFIX = "bx-danger-"

_STYLES = """
<style>
/* Destructive actions: red text and border, a stronger red on hover and focus. */
div[class*="st-key-bx-danger-"] button {
  color: #b91c1c !important; border-color: #fca5a5 !important;
}
div[class*="st-key-bx-danger-"] button:hover,
div[class*="st-key-bx-danger-"] button:focus-visible {
  color: #7f1d1d !important; border-color: #b91c1c !important; background: #fef2f2 !important;
}
/* Icon + label buttons: the icon sits on the text's baseline with one consistent gap. */
div[data-testid="stButton"] button [data-testid="stIconMaterial"],
div[data-testid="stLinkButton"] a [data-testid="stIconMaterial"] { font-size: 1.15rem; }
/* Suite navigation row (Command Center logo, Home): equal 44 px targets. */
div[class*="st-key-bx-suite-nav"] [data-testid="stHorizontalBlock"] { gap: 0.5rem; align-items: center; }
div[class*="st-key-bx-suite-nav"] button { min-height: 44px; min-width: 44px; }
a.bx-cc-logo { display:flex; align-items:center; justify-content:center; min-height:44px; min-width:44px;
  border:1px solid #94a3b8; border-radius:0.5rem; background:#fff; box-sizing:border-box; }
a.bx-cc-logo:hover, a.bx-cc-logo:focus-visible { border-color:#1e3a8a; box-shadow:0 0 0 2px rgba(30,58,138,.18); outline:none; }
</style>
"""


def inject_action_styles(st: Any) -> None:
    """Add the shared button styles. Call once per run (render_global_app_chrome does)."""
    try:
        st.markdown(_STYLES, unsafe_allow_html=True)
    except Exception:
        pass


def danger_container(st: Any, key: str) -> Any:
    """A container that shows the button(s) inside it as a dangerous action."""
    try:
        return st.container(key=DANGER_KEY_PREFIX + str(key))
    except TypeError:  # pragma: no cover - Streamlit without keyed containers
        return st.container()
