"""Authoritative app-help registry: what each page is for and how to use it.

Purpose / when / outputs / tips are the app's own Quick Guide copy (``page_guides.PAGE_GUIDES``,
shown at the top of each page). Controls are the exact widget labels on that page; tests
check every label against the page's source (``SOURCES``) so help can't describe a control
that doesn't exist. Navigation uses the real sidebar ("Choose Page") and the phone page
picker ("Jump to page", grouped by ``mobile_nav_m2.PAGE_GROUPS``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mobile_nav_m2 import PAGE_GROUPS
from page_guides import PAGE_GUIDES

# Where each page's controls live: "streamlit_app.py" means that page's branch of the
# main page router; other files are the modules the page delegates to.
MONOLITH = "streamlit_app.py"


@dataclass(frozen=True)
class PageHelp:
    key: str
    controls: tuple[str, ...]
    questions: tuple[str, ...]
    terms: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    sources: tuple[str, ...] = (MONOLITH,)
    aliases: tuple[str, ...] = ()
    # Only for pages without a Quick Guide entry: the page's own heading copy (test-pinned).
    purpose_fallback: str = ""

    @property
    def guide(self) -> dict:
        return PAGE_GUIDES.get(self.key, {})

    @property
    def group(self) -> str:
        return PAGE_GROUPS.get(self.key, "")

    @property
    def purpose(self) -> str:
        return str(self.guide.get("purpose") or self.purpose_fallback)

    @property
    def when(self) -> str:
        return str(self.guide.get("when") or "")

    @property
    def outputs(self) -> str:
        return str(self.guide.get("outputs") or "")

    @property
    def tips(self) -> tuple[str, ...]:
        return tuple(re.sub(r"</?strong>", "**", str(t)) for t in (self.guide.get("extra") or []))

    def navigation(self) -> str:
        phone = f"“Jump to page” at the top → {self.group} · {self.key}" if self.group else "“Jump to page” at the top"
        return f"In the sidebar, **Choose Page → {self.key}** (on a phone: {phone})."


PAGES: tuple[PageHelp, ...] = (
    PageHelp(
        "Historical Explorer",
        controls=("Year Range", "Sort by", "Order", "Advanced filters", "Batting Hand", "Position Filter Mode",
                  "Primary Position", "Franchise / League", "Combine split-team seasons into one primary-team row",
                  "Hall of Fame Case Mode", "Player actions"),
        questions=("Who had the best single seasons in a year range?", "Which shortstops hit the most HR in 2019?"),
        terms=("qualified", "ops"),
        next_steps=("Use **Player actions** to send a player to Comparison Tool or Trend Value.",),
        aliases=("historical", "explorer", "season search"),
    ),
    PageHelp(
        "Career Totals",
        controls=("Select Year Range", "Sort by", "Advanced filters", "Batting Hand", "Position Filter Mode", "Position",
                  "Franchise / League", "Show career totals separately by team", "Hall of Fame Case Mode", "Target player"),
        questions=("Who has the most career HR since 2010?", "Best shortstops over the last five years?",
                   "Does this player have a Hall of Fame case?"),
        terms=("qualified",),
        next_steps=("Turn on **Hall of Fame Case Mode** to build a Hall of Fame case for a player in the results.",),
        aliases=("career", "career totals"),
    ),
    PageHelp(
        "Leaderboards",
        controls=("Select Year Range", "Show Top N Players", "Sort by",
                  "Custom stat weights (defaults: HR / RBI / SB at 1.0; others 0)", "Weight for {stat}"),
        questions=("Who led in OPS from 2020 to 2025?", "Top 25 home run hitters this decade?"),
        terms=("qualified", "ops"),
        next_steps=("Use **Use these filters in another tool…** under the table to send the top players elsewhere.",),
        aliases=("leaderboard", "leaders", "rankings"),
    ),
    PageHelp(
        "Comparison Tool",
        controls=("Select up to 3 players", "Chart options", "Choose stat to plot", "Comparison X-Axis",
                  "Season Year Range", "Player Age Range", "Comparison Chart Mode", "Comparison Smoothing Window",
                  "Year-by-Year Comparison", "Career Totals", "Advanced: Statistical significance test",
                  "Player A", "Player B", "Stats to Test", "Significance Level"),
        questions=("Compare Aaron Judge and Juan Soto.", "Who was better at the same age?",
                   "Is the OPS difference statistically meaningful?"),
        terms=("ops",),
        next_steps=("Open **Advanced: Statistical significance test** to check whether a gap is more than noise.",),
        aliases=("compare", "comparison"),
    ),
    PageHelp(
        "Trend Value",
        controls=("Trend Window (Years)", "Minimum Games Played", "Fantasy Position", "Draft Room sync (optional)",
                  "Sort By Trend Stat", "Trend Table", "Single-Player Trend Dashboard",
                  "Stats to graph for selected player", "Select players to view trend", "Choose Trend Stat to Plot"),
        questions=("Who is improving fastest in OPS?", "Is this player's power trend real?", "Who is declining?"),
        terms=("trend_value",),
        next_steps=("Check the breakout and decline lists below the table, then confirm on Valuation or Comparison Tool.",),
        aliases=("trend", "trends", "trend value"),
    ),
    PageHelp(
        "Valuation",
        controls=("Valuation Window (Years)", "Minimum Games Played", "Fantasy Position", "Draft Room sync (optional)",
                  "Valuation blend weights", "Weight: Current Score", "Weight: Trend Score", "Valuation Insight Summaries"),
        questions=("Who are the best values right now?", "Why is this player ranked so high?",
                   "What happens if I weight trend more?"),
        terms=("valuation_score", "current_score", "trend_score"),
        next_steps=("Shortlist names here, then confirm on Trend Value or Comparison Tool.",),
        aliases=("valuation", "value"),
    ),
    PageHelp(
        "ML Predictions",
        controls=("Lookback Window", "Minimum Games in Lookback Window", "Projection Scope",
                  "Advanced projection tuning (defaults work well)", "Generate / Refresh ML Predictions",
                  "Sort Projections By", "Fantasy Position", "Model Accuracy Check", "Next-Season ML Projections"),
        questions=("Who does the model project for the most HR next season?", "How accurate is the model?"),
        aliases=("ml", "machine learning", "predictions", "projections"),
    ),
    PageHelp(
        "Fantasy Sleepers & Busts",
        controls=("Column glossary", "Projection Window (Years)", "Fantasy Format", "Minimum Games", "Minimum AB",
                  "Show top N sleepers / busts", "Advanced filters",
                  "Use Draft Room needs and remove already drafted players", "Position & age filters"),
        questions=("Who are the best sleepers?", "Which market favorites are bust risks?"),
        terms=("sleeper", "fantasy_edge", "player_grade"),
        aliases=("sleepers", "busts", "sleeper", "bust"),
    ),
    PageHelp(
        "Draft Room Simulator",
        controls=("Number of Teams", "Rounds", "Scoring Format", "Your Team", "Search player", "Set player on pick",
                  "Undo Last Pick", "Save Draft Board Now", "Team to View", "Post-draft roster grades"),
        questions=("How do I log picks for my draft?", "How did each team's draft grade out?"),
        terms=("relative_draft_grade",),
        next_steps=("Open Draft Assistant Simulator for pick recommendations based on the board you entered.",),
        aliases=("draft room", "draft board"),
    ),
    PageHelp(
        "Draft Assistant Simulator",
        controls=("Projection Window", "League Format", "Recommendations to Show",
                  "Position & category priorities (auto-filled; override if needed)", "Positions to prioritize",
                  "Categories / skills to strengthen", "Sort recommendations by", "Next pick recommendations",
                  "Top players left by market value", "Inspect player", "Position scarcity & roster category heatmap"),
        questions=("Who should I draft next?", "Why is this player recommended?", "What positions am I weak at?"),
        terms=("decision_score", "player_grade", "roster_fit", "fantasy_edge"),
        next_steps=("Enter picks in Draft Room Simulator (or draft live in Live Draft Room) to keep recommendations current.",),
        aliases=("draft assistant", "assistant"),
    ),
    PageHelp(
        "Draft Lab / Simulation",
        controls=("Projection Window", "Fantasy Format", "Projection Style", "Picks per Team",
                  "Run 4-Team Draft Simulation", "Full Draft Pick Order", "Team Rosters", "Final Team Rankings",
                  "Roster Needs Analysis", "Best, Good, and Questionable Picks"),
        questions=("How would a draft with these settings play out?", "Which strategy builds the best roster?"),
        terms=("decision_score", "player_grade"),
        aliases=("draft lab", "simulation", "mock draft"),
    ),
    PageHelp(
        "Live Draft Room",
        controls=("League & Draft Settings", "League Name", "Number of Teams", "Picks per Team", "Draft Type",
                  "Scoring Type", "Timer per Pick", "Auto-Pick Rule", "Roster Settings", "Start New Live Draft",
                  "Room code", "Recommendation Rankings", "Draft controls (Pause · Auto Pick · Queue)", "Draft Board",
                  "Save completed draft team"),
        questions=("How do I start a live draft?", "How do friends join?", "Who should I take when I'm on the clock?"),
        terms=("decision_score", "player_grade", "roster_fit"),
        next_steps=("When the draft ends, use **Save completed draft team** so it appears in Saved Draft Library.",),
        aliases=("live draft", "live"),
    ),
    PageHelp(
        "Saved Draft Library",
        controls=("Set Active Draft", "Draft name", "Clear Active", "New draft name", "Save rename",
                  "Create Shared League", "Export Draft", "Review Draft Results"),
        questions=("How do I make a saved draft my active team?", "How do I share a league with friends?"),
        next_steps=("Set an Active Draft so Standings Tracker, Lineup Assistant and Waiver Wire use that team.",),
        sources=("draft_archive_ui.py",),
        aliases=("library", "saved drafts", "saved draft"),
    ),
    PageHelp(
        "Fantasy Standings Tracker",
        controls=("Scoring Format", "Current Stats Source", "MLB API Season", "Refresh MLB stats",
                  "Drafted Rosters With Current Stats", "Live Fantasy Standings"),
        questions=("Where does my team rank in each category?", "Which categories am I weakest in?"),
        next_steps=("Category needs here feed Lineup Assistant and Waiver Wire.",),
        aliases=("standings",),
    ),
    PageHelp(
        "Fantasy Lineup Assistant",
        controls=("Lineup Management", "Trade Center", "Week", "Save Lineup", "Start-Sit recommendations",
                  "Recommended Starters", "Build & Analyze", "Offers & Activity", "Trade partner to search",
                  "Players I Give", "Players I Receive", "Analyze Exact Trade", "Propose Trade",
                  "Confirm and send proposal", "Find Trade Ideas"),
        questions=("Who should I start this week?", "Where do I make a trade?", "Would this trade help me?"),
        next_steps=("Use **View Waiver Options For Open Positions** to jump to Waiver Wire for an empty slot.",),
        sources=(MONOLITH, "fantasy_trade_ideas.py", "fantasy_weekly_lineup_ui.py", "fantasy_lineup_management_ui.py",
                 "fantasy_trade_center_ui.py"),
        aliases=("lineup", "lineup assistant", "start sit", "start-sit", "trade center", "trades"),
    ),
    PageHelp(
        "Waiver Wire / Add-Drop Center",
        controls=("Search available players", "Filter available players by position", "Add player (waiver pool)",
                  "Drop player (your roster)", "Add to Pending Moves", "Confirm Pending Waiver Moves", "Plan Add"),
        questions=("Which free agent fills my shortstop hole?", "Who should I drop?"),
        sources=("fantasy_waiver_wire_ui.py",),
        aliases=("waiver", "waivers", "waiver wire", "add drop", "add/drop", "free agents"),
    ),
    PageHelp(
        "Pricing & Upgrade",
        controls=("Free", "Pro", "Upgrade to Pro", "Manage Subscription"),
        questions=("What does Pro include?", "How do I manage my subscription?"),
        sources=("baseball_monetization_ui.py",),
        aliases=("pricing", "upgrade", "subscription", "pro", "billing"),
        purpose_fallback="Choose the level that fits how deeply you analyze and manage baseball.",
    ),
)

PAGE_HELP: dict[str, PageHelp] = {p.key: p for p in PAGES}


@dataclass(frozen=True)
class HowTo:
    key: str
    title: str
    page: str
    steps: tuple[str, ...]
    keywords: tuple[str, ...]
    controls: tuple[str, ...] = field(default_factory=tuple)  # label-checked like page controls
    note: str = ""


HOWTOS: tuple[HowTo, ...] = (
    HowTo(
        "compare_players", "Compare players", "Comparison Tool",
        ("Pick up to three names in **Select up to 3 players**.",
         "Read **Year-by-Year Comparison** and **Career Totals** for the side-by-side numbers.",
         "Open **Chart options** to change **Choose stat to plot** or limit the **Season Year Range**.",
         "Optional: **Advanced: Statistical significance test** checks whether a gap is more than noise."),
        ("compare", "comparison", "side by side", "versus"),
        ("Select up to 3 players", "Year-by-Year Comparison", "Career Totals", "Chart options", "Choose stat to plot",
         "Season Year Range", "Advanced: Statistical significance test"),
    ),
    HowTo(
        "make_trade", "Make a trade", "Fantasy Lineup Assistant",
        ("Choose the **Trade Center** section at the top of the page.",
         "In **Build & Analyze**, pick a **Trade partner to search**, then **Players I Give** and **Players I Receive**.",
         "Click **Analyze Exact Trade** to see the category impact (or **Find Trade Ideas** for suggestions).",
         "Click **Propose Trade**, then **Confirm and send proposal**. Replies show under **Offers & Activity**."),
        ("trade", "trades", "propose", "offer"),
        ("Trade Center", "Build & Analyze", "Trade partner to search", "Players I Give", "Players I Receive",
         "Analyze Exact Trade", "Find Trade Ideas", "Propose Trade", "Confirm and send proposal", "Offers & Activity"),
        note="You need an active league with your team claimed; AMI can't send trades for you.",
    ),
    HowTo(
        "add_waiver", "Add or drop a player", "Waiver Wire / Add-Drop Center",
        ("Find someone with **Search available players** or **Filter available players by position**.",
         "Pick them in **Add player (waiver pool)** and who goes in **Drop player (your roster)**.",
         "Click **Add to Pending Moves**, review, then **Confirm Pending Waiver Moves**."),
        ("waiver", "waivers", "add someone", "add a player", "drop", "free agent", "pick up", "pickup", "add/drop"),
        ("Search available players", "Filter available players by position", "Add player (waiver pool)",
         "Drop player (your roster)", "Add to Pending Moves", "Confirm Pending Waiver Moves"),
        note="Uses your Active Draft from Saved Draft Library. AMI can't make roster moves for you.",
    ),
    HowTo(
        "set_lineup", "Set your weekly lineup", "Fantasy Lineup Assistant",
        ("Choose the **Lineup Management** section.", "Pick the **Week**, arrange starters and bench, then **Save Lineup**.",
         "**Start-Sit recommendations** shows who the app would start."),
        ("lineup", "start", "sit", "starting", "bench", "start/sit"),
        ("Lineup Management", "Week", "Save Lineup", "Start-Sit recommendations"),
        note="AMI can't change your lineup for you.",
    ),
    HowTo(
        "historical_explorer", "Use Historical Explorer", "Historical Explorer",
        ("Set the **Year Range** and choose **Sort by** / **Order**.",
         "Open **Advanced filters** for **Batting Hand**, **Primary Position** and **Franchise / League**.",
         "Each row is one player-season; rate-stat sorts default to a qualified at-bat minimum."),
        ("historical explorer", "season search", "single season", "single-season"),
        ("Year Range", "Sort by", "Order", "Advanced filters", "Batting Hand", "Primary Position", "Franchise / League"),
    ),
    HowTo(
        "leaderboards", "Rank players on a stat", "Leaderboards",
        ("Set **Select Year Range**, choose a stat in **Sort by**, and **Show Top N Players**.",
         "The Score column uses **Custom stat weights** (HR, RBI and SB at 1.0 by default)."),
        ("leaderboard", "leaderboards", "rank players", "top players", "who led"),
        ("Select Year Range", "Sort by", "Show Top N Players"),
    ),
    HowTo(
        "career_totals", "See career totals or a position's best hitters", "Career Totals",
        ("Set **Select Year Range** and **Sort by**.",
         "Open **Advanced filters** → **Position** (and **Position Filter Mode**) to limit to one position."),
        ("career totals", "career stats", "by position"),
        ("Select Year Range", "Sort by", "Advanced filters", "Position", "Position Filter Mode"),
    ),
    HowTo(
        "trend_value", "Find improving or declining players", "Trend Value",
        ("Choose a **Trend Window (Years)** and **Minimum Games Played**.",
         "Sort with **Sort By Trend Stat**; green Δ = improving, red = declining.",
         "Use **Single-Player Trend Dashboard** to chart one player's stats."),
        ("trending", "improving", "declining", "breakout", "trend value page"),
        ("Trend Window (Years)", "Minimum Games Played", "Sort By Trend Stat", "Single-Player Trend Dashboard"),
    ),
    HowTo(
        "valuation", "Rank players by value", "Valuation",
        ("Pick the **Valuation Window (Years)** and **Minimum Games Played**.",
         "Sort by Valuation Score; adjust **Valuation blend weights** to favor recent production or trend."),
        ("valuation page", "best values", "undervalued"),
        ("Valuation Window (Years)", "Minimum Games Played", "Valuation blend weights"),
    ),
    HowTo(
        "draft_help", "Get draft pick recommendations", "Draft Assistant Simulator",
        ("Enter picks in Draft Room Simulator (or draft in Live Draft Room).",
         "On Draft Assistant Simulator, read **Next pick recommendations**; adjust "
         "**Position & category priorities (auto-filled; override if needed)** if needed.",
         "Use **Inspect player** for the score breakdown."),
        ("draft recommendation", "draft recommendations", "who to draft", "draft help", "draft assistant"),
        ("Next pick recommendations", "Position & category priorities (auto-filled; override if needed)", "Inspect player"),
    ),
    HowTo(
        "live_draft", "Run a live draft", "Live Draft Room",
        ("Fill in **League & Draft Settings** and **Roster Settings**.",
         "Click **Start New Live Draft**; friends join with the **Room code**.",
         "When it ends, **Save completed draft team** to keep it in Saved Draft Library."),
        ("live draft", "start a draft", "join a draft", "room code", "mock draft with friends"),
        ("League & Draft Settings", "Roster Settings", "Start New Live Draft", "Room code", "Save completed draft team"),
    ),
    HowTo(
        "active_draft", "Make a saved draft your active team", "Saved Draft Library",
        ("Open **Set Active Draft** and pick the draft.", "Click **Set Active Draft**; **Clear Active** undoes it."),
        ("active draft", "active team", "active league", "saved draft", "set active"),
        ("Set Active Draft", "Clear Active"),
    ),
    HowTo(
        "standings", "Check fantasy standings", "Fantasy Standings Tracker",
        ("Choose **Scoring Format** and **Current Stats Source**, then **Refresh MLB stats**.",
         "Read **Live Fantasy Standings** for category ranks."),
        ("standings", "category ranks", "where do i rank"),
        ("Scoring Format", "Current Stats Source", "Refresh MLB stats", "Live Fantasy Standings"),
    ),
    HowTo(
        "upgrade", "Upgrade or manage a subscription", "Pricing & Upgrade",
        ("Open Pricing & Upgrade to compare Free and Pro.", "Use **Upgrade to Pro** or **Manage Subscription**."),
        ("upgrade", "subscription", "pricing", "pro plan", "cancel"),
        ("Upgrade to Pro", "Manage Subscription"),
    ),
)

HOWTO_BY_KEY: dict[str, HowTo] = {h.key: h for h in HOWTOS}


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9/& ]+", " ", str(text or "").lower()) + " "


def find_page(text: str) -> PageHelp | None:
    """Page named in ``text`` (exact page name first, then the longest alias)."""
    low = _norm(text)
    best: tuple[int, PageHelp] | None = None
    for page in PAGES:
        for name in (page.key, *page.aliases):
            n = _norm(name).strip()
            if n and f" {n} " in low and (best is None or len(n) > best[0]):
                best = (len(n) + (100 if name == page.key else 0), page)
    return best[1] if best else None


def find_howto(text: str) -> HowTo | None:
    low = _norm(text)
    best: tuple[int, HowTo] | None = None
    for h in HOWTOS:
        for kw in h.keywords:
            n = _norm(kw).strip()
            if f" {n} " in low and (best is None or len(n) > best[0]):
                best = (len(n), h)
    return best[1] if best else None
