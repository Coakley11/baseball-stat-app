"""One colourful icon per kind of action, used app-wide (page icons live in feature_identity).

Owner rule (2026-11-07/08): anything important carries a colourful icon, never a monochrome one or
none at all, so an action never reads like descriptive text; the same action shows the same icon
everywhere; and the original emoji the app already used come first. So every value here is an
emoji (Streamlit's ``icon=`` accepts one; tab and expander labels take it in their text). Each line
says where it comes from: "original" = the emoji this action already had before the redesign
(6442d8d) or a page's own icon in feature_identity; "new" = no original existed, so an emoji from the
app's existing vocabulary was chosen. No Material Symbols remain on actions.

Labels, keys, handlers and permissions never depend on these values. Dangerous actions (delete,
cancel an invite) still sit in a container keyed ``bx-danger-…`` so they are shown in red
(``inject_action_styles``); the confirmation step that follows them is unchanged.
"""

from __future__ import annotations

from typing import Any

# --- draft and queue ------------------------------------------------------------------------------
ADD_TO_QUEUE = "⭐"  # original: "⭐ Add to Queue" on every recommendation card
DRAFT_PLAYER = "🔴"  # original: "🔴 Draft Player" on the Live Draft recommendation cards
DRAFT_QUEUE = "📋"  # original: the "📋 Draft Queue" expander
WATCHLIST = "👀"  # new: watching a player (no original)
SIMULATE_PICK = "🎲"  # new: Simulate Draft Pick (no original)
RUN_SIMULATION = "🧪"  # original: Draft Lab / Simulation's page icon
PAUSE = "⏸"  # original: "⏸ Pause Draft"
RESUME = "▶"  # original: "▶ Resume Draft"
AUTO_PICK = "⚡"  # original: "⚡ Auto Pick Now"
RESET_TIMER = "⏱"  # original: "⏱ Reset Timer"
UNDO = "↩️"  # new: Undo Last Pick, Restore original plan
START = "🚀"  # new: start / create a draft
LIVE_DRAFT = "📡"  # original: Live Draft Room's page icon
STRATEGY = "♟️"  # original: Draft Strategy's page icon
DRAFT_CONTROLS = "🎛️"  # new: the draft-controls panel

# --- research -------------------------------------------------------------------------------------
COMPARE = "⚖️"  # original: Compare Players' page icon
TREND = "🔥"  # original: Trend Value's page icon
PROJECTION = "🔮"  # new: projection breakdown
PLAYER_ACTIONS = "⚾"  # original: the Players family icon (the Player actions menu)
ML_PREDICTIONS = "🤖"  # original: ML Predictions' page icon
SEARCH = "🔎"  # original: "🔎 Find my completed Shared Drafts" / Historical Explorer
ANALYZE = "📈"  # new: Analyze Draft / This Trade (the Insights family icon)
REVIEW = "📝"  # new: Review Draft Results (the Draft family icon)
IDEAS = "💡"  # new: Find / Generate Trade Ideas, Use This Idea

# --- save, open, import, export -------------------------------------------------------------------
SAVE = "💾"  # original: "💾 Save & Continue Later"
SAVE_TO_LIBRARY = "📁"  # original: "📁 Save to Draft Library" / Saved Draft Library's page icon
OPEN = "📂"  # original: "📂 Open it in the Library"
IMPORT = "📥"  # new: Import existing draft / Import Draft
EXPORT = "📤"  # new: Export Draft, Export / Download CSV and Excel
EDIT = "✏️"  # new: Rename, Edit
DUPLICATE = "📑"  # new: Duplicate
SETTINGS = "⚙️"  # new: League setup, Edit Draft Setup, settings
REFRESH = "🔃"  # new: Refresh / reload / update from the queue
RECOVER = "♻️"  # original: "♻️ Recover draft"
PREVIEW = "👁️"  # original: "👁️ Preview"

# --- league, roster, trade ------------------------------------------------------------------------
ROSTER = "🧢"  # new: Rosters & grades, Team rosters, Generate Roster View
BOARD = "🧾"  # original: Draft Room Simulator's page icon (its Board tab)
LINEUP = "📋"  # original: Lineup & Trades' page icon
STATS = "📊"  # original: League Standings' page icon
WAIVERS = "🔄"  # original: Waiver Wire's page icon
TRADE = "🔁"  # original: Trade Analyzer's page icon (Propose, Apply, Explore Trades)
ACQUIRE = "🤝"  # new: Acquire / Counter Offer
PLAN_ADD = "➕"  # new: Plan Add, Add to Pending Moves
PLAN_DROP = "➖"  # new: Plan Drop
SHARED_LEAGUE = "🏟️"  # original: the My League family icon
SHARED_DRAFT = "👥"  # original: "👥 Room & managers"
ROOM = SHARED_DRAFT
CLAIM_TEAM = "🙋"  # new: Claim team
INVITE_MANAGER = "✉️"  # new: Send invite
JOIN_ROOM = "🔑"  # new: Join Room by Code (the code is the key)
CHAT = "💬"  # original: "💬 Live Draft Chat"
SET_ACTIVE = "⭐"  # original: "⭐ Set Active League" (kept in that label's text)
ACTIVE = "✅"  # original: "✅ Active League"

# --- confirm, cancel, remove ----------------------------------------------------------------------
ACCEPT = "✅"  # original: "✅" (Active, success) — Accept invite / trade, Confirm
DECLINE = "❌"  # new: Decline invite / trade
CANCEL = "✖️"  # new: Cancel a confirmation, Cancel invite / room
WARNING = "⚠️"  # original: "⚠️ Market Bust Risks" and the app's warnings
DELETE = "🗑"  # original: "🗑 End/Delete Draft for Everyone"
RESET = "🧹"  # new: Reset / Clear (board, setup, queue, watchlist)
CLEAR = RESET
REMOVE_FROM_LIST = "➖"  # new: takes an item off a working list; not a delete
MOVE_UP = "⬆️"  # new
MOVE_DOWN = "⬇️"  # new
MOVE_TOP = "⏫"  # new
PIN = "📌"  # new: pin a player in a Pro strategy (keeps his place)
RESEARCH_FINDING = "🔬"  # new: record a research finding in a Pro strategy
PREFERENCES = "🎯"  # new: a strategy's ranking preferences
REPLACE_QUEUE = "🔁"  # new: replace the Global Queue with a strategy (an explicit swap)
RESTORE = RECOVER  # restore a strategy from Recently deleted

# --- account and navigation -----------------------------------------------------------------------
HOME = "🏠"  # original: Home's page icon
LEAVE = "🚪"  # original: "🚪 Leave Room"
LOG_OUT = LEAVE
LOG_IN = "🔑"  # new
SUBSCRIPTION = "💳"  # original: Pricing & Upgrade's page icon
UPGRADE = SUBSCRIPTION
CANCEL_INVITE = CANCEL
TUTORIAL = "🎓"  # new
ACCOUNT = "👤"  # original: the Account family icon (Create account)
EMAIL = "✉️"  # new: Send reset email
PASSWORD = "🔒"  # new: Reset / Update password
CALENDAR = "📅"  # new: Create season calendar
COPY = DUPLICATE

# Names shared with feature/baseball-completion's module.
ICON_DELETE = DELETE
ICON_RESET = RESET
ICON_LEAVE = LEAVE
ICON_CANCEL = CANCEL

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
/* The final confirmation of a destructive action: solid red, never the theme's blue. */
div[class*="st-key-bx-danger-"] button[kind="primary"],
div[class*="st-key-bx-danger-"] button[data-testid="stBaseButton-primary"] {
  background: #b91c1c !important; border-color: #b91c1c !important; color: #ffffff !important;
}
div[class*="st-key-bx-danger-"] button[kind="primary"] p,
div[class*="st-key-bx-danger-"] button[data-testid="stBaseButton-primary"] p { color: #ffffff !important; }
div[class*="st-key-bx-danger-"] button[kind="primary"]:hover,
div[class*="st-key-bx-danger-"] button[data-testid="stBaseButton-primary"]:hover {
  background: #7f1d1d !important; border-color: #7f1d1d !important; color: #ffffff !important;
}
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
