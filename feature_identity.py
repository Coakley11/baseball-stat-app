"""One visual identity per feature: icon, display name, family colour and a one-line purpose.

Purely presentational. Page keys (``streamlit_app.PAGE_OPTIONS``) never change here; this only
decides what a user *sees* next to a page wherever it appears (sidebar, phone picker, Home,
page headers, action buttons), so the same feature always carries the same icon and colour.

Families group the product the way a user thinks about it: look players up (Players), see who
is moving (Insights), get ready for a draft (Draft), run a league (My League), and ask a
question (Ask AMI). Colours are mid-dark so text in them passes WCAG AA on white, and nothing
is told by colour alone: every coloured element also carries its icon and words.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    key: str
    name: str
    icon: str
    color: str  # text/accent, >= 4.5:1 on white
    tint: str  # light background for chips/cards
    border: str


FAMILIES: dict[str, Family] = {
    "home": Family("home", "Home", "🏠", "#334155", "#f1f5f9", "#dbe3ec"),
    "players": Family("players", "Players", "⚾", "#1f5fa8", "#edf4fc", "#c9dcf2"),
    "insights": Family("insights", "Insights", "📈", "#0f766e", "#e8f6f4", "#bfe5df"),
    "draft": Family("draft", "Draft", "📝", "#b45309", "#fdf3e7", "#f3d3ad"),
    "league": Family("league", "My League", "🏟️", "#2e7d4f", "#ebf6ef", "#c3e3cf"),
    "account": Family("account", "Account", "👤", "#475569", "#f1f5f9", "#dbe3ec"),
    "ami": Family("ami", "Ask AMI", "💬", "#6d28d9", "#f3effd", "#d9ccf6"),
}

# nav_groups section name -> family key
SECTION_FAMILY: dict[str, str] = {
    "Home": "home",
    "Players": "players",
    "Insights": "insights",
    "Draft": "draft",
    "My League": "league",
    "Account": "account",
}


@dataclass(frozen=True)
class Feature:
    page: str  # page key (routing identifier, never shown as-is when a name exists)
    icon: str
    name: str  # what the user reads: the same words as the sidebar label
    family: str
    purpose: str  # one plain line: what this is for


_FEATURES: tuple[Feature, ...] = (
    Feature("Home", "🏠", "Home", "home", "Start here: every tool in one place."),
    Feature("Historical Explorer", "🔎", "Historical Explorer", "players",
            "Look up the best single seasons for any years and stat."),
    Feature("Career Totals", "📚", "Career Totals", "players",
            "Whole careers in numbers, including Hall of Fame cases."),
    Feature("Comparison Tool", "⚖️", "Compare Players", "players",
            "Two or three hitters side by side over the same seasons."),
    Feature("Leaderboards", "🏆", "Leaderboards", "players",
            "Who leads over a span of seasons, in one stat or a custom score."),
    Feature("Trend Value", "🔥", "Trend Value", "insights",
            "Who is rising or falling in a stat over recent seasons."),
    Feature("Valuation", "💰", "Valuation", "insights",
            "One value score per hitter, ranked."),
    Feature("ML Predictions", "🤖", "ML Predictions", "insights",
            "Next-season projections from a model trained on past seasons."),
    Feature("Fantasy Sleepers & Busts", "💎", "Sleepers & Busts", "insights",
            "Where our model and the draft market disagree."),
    Feature("Live Draft Room", "📡", "Live Draft Room", "draft",
            "Run or join a live draft with pick timers."),
    Feature("Draft Room Simulator", "🧾", "Draft Room Simulator", "draft",
            "Practice a draft and log every pick yourself."),
    Feature("Draft Assistant Simulator", "🧩", "Draft Assistant Simulator", "draft",
            "Who to pick next, with reasons."),
    Feature("Draft Lab / Simulation", "🧪", "Draft Lab / Simulation", "draft",
            "Test a draft strategy and grade every roster."),
    Feature("Saved Draft Library", "📁", "Saved Draft Library", "draft",
            "Open, share or activate a saved draft or league."),
    Feature("Fantasy Standings Tracker", "📊", "League Standings", "league",
            "Where your team stands and what to do next."),
    Feature("Fantasy Lineup Assistant", "📋", "Lineup & Trades", "league",
            "Set your weekly lineup and work on trades."),
    Feature("Waiver Wire / Add-Drop Center", "🔄", "Waiver Wire", "league",
            "Who to pick up for your team, and why."),
    Feature("Pricing & Upgrade", "💳", "Pricing & Upgrade", "account", "Plans and upgrades."),
)

FEATURES: dict[str, Feature] = {f.page: f for f in _FEATURES}

AMI = Feature("__ami__", "💬", "Ask AMI", "ami", "Ask a baseball question in plain English.")


def feature(page: str) -> Feature | None:
    return FEATURES.get(str(page or "").strip())


def family(page_or_family: str) -> Family:
    """Family for a page key, a family key, or a nav section name (falls back to Home)."""
    key = str(page_or_family or "").strip()
    if key in FAMILIES:
        return FAMILIES[key]
    if key in SECTION_FAMILY:
        return FAMILIES[SECTION_FAMILY[key]]
    feat = FEATURES.get(key)
    return FAMILIES[feat.family] if feat else FAMILIES["home"]


def icon(page: str) -> str:
    feat = feature(page)
    return feat.icon if feat else ""


def nav_label(page: str) -> str:
    """Icon + display name, as the sidebar and phone picker show it."""
    feat = feature(page)
    return f"{feat.icon} {feat.name}" if feat else str(page)


def action_label(page: str, text: str) -> str:
    """A button that opens ``page``: the page's icon, then an action phrase (e.g. "View Judge's trend")."""
    ico = icon(page)
    return f"{ico} {text}" if ico else text


def section_label(section: str) -> str:
    fam = family(section)
    return f"{fam.icon} {fam.name}"
