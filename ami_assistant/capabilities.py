"""AMI capability map: what it answers now, what waits on Phase C, what it must never do itself.

Grounding categories (every answer is labelled with one):

* ``app_data``       — computed from the app's own dataset and calculations (Lahman through the
  latest season loaded) or from state the user's pages already computed (draft snapshot).
* ``product_help``   — from the app-help registry (page guides, control labels, glossary).
* ``external_current`` — needs live/current MLB information the app's historical data can't
  give ("who leads MLB today"). AMI says so instead of answering from stale data.
"""

from __future__ import annotations

from dataclasses import dataclass

APP_DATA = "app_data"
PRODUCT_HELP = "product_help"
EXTERNAL_CURRENT = "external_current"
GROUNDING_LABELS = {
    APP_DATA: "App data",
    PRODUCT_HELP: "App help",
    EXTERNAL_CURRENT: "Outside the app's data",
}

LIVE = "live"
SNAPSHOT = "page_snapshot"  # reads what a page already computed this session
DEFERRED = "deferred_phase_c"
DISABLED = "disabled"


@dataclass(frozen=True)
class Capability:
    key: str
    title: str
    status: str
    examples: tuple[str, ...]
    tools: tuple[str, ...]
    notes: str = ""


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "app_guidance", "App guidance", LIVE,
        ("What can I do on this page?", "How do I compare two players?", "Where do I make a trade?",
         "What does Decision Score mean?", "How do I use Historical Explorer?"),
        ("explain_app_page", "explain_metric", "find_feature"),
    ),
    Capability(
        "historical_analytics", "Historical analytics", LIVE,
        ("Compare Aaron Judge and Juan Soto.", "Who had the higher OPS from 2022 to 2025?",
         "Show me Mike Trout's best seasons.", "Who are the best shortstops over the last five years?",
         "How has his power changed?", "Why does this player's trend look strong?", "Is he undervalued?"),
        ("search_players", "get_player_profile", "get_player_seasons", "compare_players", "get_leaderboard",
         "get_player_trends", "get_player_valuation"),
    ),
    Capability(
        "draft_intelligence", "Draft intelligence (read-only)", SNAPSHOT,
        ("Who should I draft next?", "Why is this player recommended?", "What positions am I weak at?",
         "Who are the best available shortstops?", "Should I draft for need or best available?"),
        ("get_active_draft_context", "get_draft_recommendations", "explain_draft_recommendation", "get_team_needs",
         "get_sleepers_busts"),
        notes="Reads the recommendations Draft Assistant / Live Draft Room computed; never recomputes or drafts.",
    ),
    Capability(
        "fantasy_team", "Fantasy team intelligence", DEFERRED,
        ("I need a shortstop. What can I do?", "Who should I drop?", "Would this trade improve my team?",
         "What categories am I weakest in?", "Who should I start this week?"),
        ("get_active_league", "get_team_roster", "get_lineup", "get_standings", "get_available_free_agents",
         "evaluate_trade"),
        notes="Contracts defined; wired after the Phase C fantasy model is accepted (see tools/fantasy.py).",
    ),
    Capability(
        "future_actions", "Actions (draft, waivers, trades, lineup)", DISABLED,
        ("Draft Bobby Witt Jr.", "Add him from waivers.", "Execute this trade.", "Start him at SS."),
        (),
        notes="Never callable from AMI in this phase. See FUTURE_ACTIONS.",
    ),
)


@dataclass(frozen=True)
class FutureAction:
    key: str
    title: str
    ui_path: str
    canonical_owner: str  # the existing transaction path AMI must reuse, never duplicate


# Declared so the router can recognise the request and point to the UI — never executable.
# When enabled they must: require an explicit user confirmation step, call the same canonical
# functions as the UI (listed here), and pass the same authorization/ownership checks.
FUTURE_ACTIONS: tuple[FutureAction, ...] = (
    FutureAction("draft_player", "Draft a player", "Live Draft Room / Draft Room Simulator",
                 "live_draft_pick_commit / draft_actions (owned by the draft pages)"),
    FutureAction("queue_player", "Queue a player", "Live Draft Room → Draft controls (Pause · Auto Pick · Queue)",
                 "live_draft_queue_persist"),
    FutureAction("add_waiver_player", "Add a waiver player", "Waiver Wire / Add-Drop Center",
                 "fantasy_waiver_wire (Phase C2 transaction path)"),
    FutureAction("drop_player", "Drop a player", "Waiver Wire / Add-Drop Center",
                 "fantasy_waiver_wire (Phase C2 transaction path)"),
    FutureAction("execute_trade", "Propose or accept a trade", "Fantasy Lineup Assistant → Trade Center",
                 "fantasy_trade_proposals + fantasy_trade_legality (Phase C3)"),
    FutureAction("change_lineup", "Change the starting lineup", "Fantasy Lineup Assistant → Lineup Management",
                 "fantasy_weekly_lineup (Phase C)"),
)
FUTURE_ACTION_KEYS = frozenset(a.key for a in FUTURE_ACTIONS)
CAPABILITY_BY_KEY = {c.key: c for c in CAPABILITIES}
