"""Authoritative app-help registry: what each page is for and how to use it.

Purpose / when / outputs / tips are the app's own Quick Guide copy (``page_guides.PAGE_GUIDES``).
Pages redesigned in U1 also carry their one-line page heading (``headline``), which is what the
user reads first. Controls are the exact labels on that page; tests check every label against
the page's source (``sources``), so help can't describe a control that doesn't exist.

Navigation follows the real app:

- page keys stay authoritative;
- the label the user sees comes from ``nav_groups.NAV_LABELS``;
- the section is ``nav_groups.PAGE_SECTION`` (desktop sidebar headings, the phone "Section" pills).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ami_assistant.context import display_label
from nav_groups import HOME_PAGE, PAGE_SECTION
from page_guides import PAGE_GUIDES

# Where each page's controls live: "streamlit_app.py" means that page's branch of the
# main page router; other files are the modules the page delegates to.
MONOLITH = "streamlit_app.py"


@dataclass(frozen=True)
class PageHelp:
    key: str
    controls: tuple[str, ...]
    # Suggested questions for this page: shown as examples and usable as quick-question
    # chips; tests require every one to route to a real answer (never "please rephrase").
    questions: tuple[str, ...]
    terms: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    sources: tuple[str, ...] = (MONOLITH,)
    aliases: tuple[str, ...] = ()
    # Only for pages without a Quick Guide entry: the page's own heading copy (test-pinned).
    purpose_fallback: str = ""
    # U1 pages: the line under the page title (``ui_hierarchy.page_head``), test-pinned.
    headline: str = ""
    # U1 pages: what sits under the "Explore more" label (advanced controls, full tables).
    explore_more: str = ""

    @property
    def guide(self) -> dict:
        return PAGE_GUIDES.get(self.key, {})

    @property
    def group(self) -> str:
        return PAGE_SECTION.get(self.key, "")

    @property
    def label(self) -> str:
        return display_label(self.key)

    @property
    def purpose(self) -> str:
        return str(self.headline or self.guide.get("purpose") or self.purpose_fallback)

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
        label = self.label
        if self.key == HOME_PAGE:
            return "In the sidebar, choose **Home** at the top (on a phone: the **Home** section at the top)."
        where = f"under **{self.group}**, choose **{label}**" if self.group else f"choose **{label}**"
        phone = (f"tap **{self.group}** under Section, then pick **{label}** in “Jump to page”" if self.group
                 else f"pick **{label}** in “Jump to page”")
        return f"In the sidebar, {where} (on a phone: {phone})."


PAGES: tuple[PageHelp, ...] = (
    PageHelp(
        HOME_PAGE,
        # Task card buttons come from home_page.TASKS; the rest are Home's league actions.
        controls=("Find a player", "Compare players", "Start a mock draft", "Open my league", "League standings",
                  "Set lineup", "Waiver wire", "Start or import a draft", "Open saved drafts"),
        questions=("What can I do here?", "Where should I go to compare players?", "How do I manage my league?",
                   "Where do I start a draft?"),
        next_steps=("Pick a task card, or use the sidebar sections: Players, Insights, Draft, My League, Account.",),
        sources=("home_page.py",),
        aliases=("home", "home page", "start page"),
        headline="Look up players, spot who's rising, prepare for your draft and run your fantasy league.",
    ),
    PageHelp(
        "Historical Explorer",
        controls=("Year Range", "Sort by", "Order", "Advanced filters", "Batting Hand", "Position Filter Mode",
                  "Primary Position", "Franchise / League", "Combine split-team seasons into one primary-team row",
                  "Hall of Fame Case Mode", "Player actions"),
        questions=("Who was the best hitter in 1927?", "Show me Babe Ruth's best seasons", "What does this page show?"),
        terms=("qualified", "ops"),
        next_steps=("Use **Player actions** to send a player to Comparison Tool or Trend Value.",),
        aliases=("historical", "explorer", "season search"),
        headline="The best single seasons for any years and stat, back to 1871.",
        explore_more=("The page leads with the answer and a top-10 chart. Order, the advanced filters, Hall of Fame "
                      "Case Mode, the full season table and the scatterplots are under **Explore more**."),
    ),
    PageHelp(
        "Career Totals",
        controls=("Select Year Range", "Sort by", "Advanced filters", "Batting Hand", "Position Filter Mode", "Position",
                  "Franchise / League", "Show career totals separately by team", "Hall of Fame Case Mode", "Target player"),
        questions=("Who has the most career HR since 2010?", "Who are the best shortstops over the last five years?",
                   "What is the qualified minimum?"),
        terms=("qualified",),
        next_steps=("Turn on **Hall of Fame Case Mode** to build a Hall of Fame case for a player in the results.",),
        aliases=("career", "career totals"),
    ),
    PageHelp(
        "Leaderboards",
        controls=("Select Year Range", "Show Top N Players", "Sort by",
                  "Custom stat weights (defaults: HR / RBI / SB at 1.0; others 0)", "Weight for {stat}"),
        questions=("Who led in OPS from 2020 to 2025?", "Who hit the most home runs since 2015?",
                   "What does qualified mean?"),
        terms=("qualified", "ops"),
        next_steps=("Use **Use these filters in another tool…** under the table to send the top players elsewhere.",),
        aliases=("leaderboard", "leaders", "rankings"),
        headline="Who leads over a span of seasons — in one stat or a custom score.",
        explore_more=("The page opens with the top player, the qualification rule in plain words (for BA/OBP/SLG/OPS "
                      "the minimum at-bats) and a top-10 chart. Show Top N, the custom stat weights, stat minimums and "
                      "the full ranking are under **Explore more**."),
    ),
    PageHelp(
        "Comparison Tool",
        controls=("Select up to 3 players", "Chart options", "Choose stat to plot", "Comparison X-Axis",
                  "Season Year Range", "Player Age Range", "Comparison Chart Mode", "Comparison Smoothing Window",
                  "Year-by-Year Comparison", "Career Totals", "Advanced: Statistical significance test",
                  "Player A", "Player B", "Stats to Test", "Significance Level"),
        questions=("Compare Aaron Judge and Juan Soto.", "Who had more power, Judge or Soto?",
                   "What can I do on this page?"),
        terms=("ops",),
        next_steps=("Open **Advanced: Statistical significance test** to check whether a gap is more than noise.",),
        aliases=("compare", "comparison"),
    ),
    PageHelp(
        "Trend Value",
        controls=("Trend Window (Years)", "Minimum Games Played", "Fantasy Position", "Draft Room sync (optional)",
                  "Sort By Trend Stat", "Trend Table", "Single-Player Trend Dashboard",
                  "Stats to graph for selected player", "Select players to view trend", "Choose Trend Stat to Plot"),
        questions=("Who is improving fastest in OPS?", "How has Mookie Betts's power changed?", "What is Trend Value?"),
        terms=("trend_value",),
        next_steps=("Check the breakout and decline lists below the table, then confirm on Valuation or Comparison Tool.",),
        aliases=("trend", "trends", "trend value"),
    ),
    PageHelp(
        "Valuation",
        controls=("Valuation Window (Years)", "Minimum Games Played", "Fantasy Position", "Draft Room sync (optional)",
                  "Valuation blend weights", "Weight: Current Score", "Weight: Trend Score", "Valuation Insight Summaries"),
        questions=("Who are the best values?", "Is Gunnar Henderson undervalued?", "What does Valuation Score mean?"),
        terms=("valuation_score", "current_score", "trend_score"),
        next_steps=("Shortlist names here, then confirm on Trend Value or Comparison Tool.",),
        aliases=("valuation", "value"),
    ),
    PageHelp(
        "ML Predictions",
        controls=("Lookback Window", "Minimum Games in Lookback Window", "Projection Scope",
                  "Advanced projection tuning (defaults work well)", "Generate / Refresh ML Predictions",
                  "Sort Projections By", "Fantasy Position", "Model Accuracy Check", "Next-Season ML Projections"),
        questions=("What can I do on this page?", "What does ML Predictions show?"),
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
        questions=("How do I log picks for my draft?", "What does Relative Draft Grade mean?"),
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
        questions=("What can I do on this page?", "What does Decision Score mean?"),
        terms=("decision_score", "player_grade"),
        aliases=("draft lab", "simulation", "mock draft"),
    ),
    PageHelp(
        "Live Draft Room",
        controls=("League & Draft Settings", "League Name", "Number of Teams", "Picks per Team", "Draft Type",
                  "Scoring Type", "Timer per Pick", "Auto-Pick Rule", "Roster Settings", "Start New Live Draft",
                  "Room code", "Recommendation Rankings", "Draft controls (Pause · Auto Pick · Queue)", "Draft Board",
                  "Save completed draft team"),
        questions=("How do I start a live draft?", "How do I run a live draft with friends?", "Who should I take when I'm on the clock?"),
        terms=("decision_score", "player_grade", "roster_fit"),
        next_steps=("When the draft ends, use **Save completed draft team** so it appears in Saved Draft Library.",),
        aliases=("live draft", "live"),
    ),
    PageHelp(
        "Saved Draft Library",
        controls=("Set Active Draft", "Draft name", "Clear Active", "New draft name", "Save rename",
                  "Create Shared League", "Export Draft", "Review Draft Results"),
        questions=("How do I make a saved draft my active team?", "How do I share a league with friends?"),
        next_steps=("Set an Active Draft so League Standings, Lineup Assistant and Waiver Wire use that team.",),
        sources=("draft_archive_ui.py",),
        aliases=("library", "saved drafts", "saved draft"),
    ),
    PageHelp(
        "Fantasy Standings Tracker",
        controls=("League Standings (official)", "Completed week", "Set lineup", "Check waivers", "Explore trades",
                  "Scoring Format", "Current Stats Source", "MLB API Season", "Refresh MLB stats",
                  "Drafted Rosters With Current Stats", "How current rosters would rank (not official standings)"),
        questions=("Where am I in the standings?", "Where could I gain a roto point?",
                   "What are my strongest categories?"),
        terms=("official_standings", "current_roster_snapshot"),
        next_steps=("Use **Set lineup**, **Check waivers** or **Explore trades** under the answer.",),
        sources=(MONOLITH, "league_home_ui.py", "fantasy_season_results_ui.py", "fantasy_standings_snapshot.py"),
        # Old names stay understood: the page was "Fantasy Standings Tracker" (and showed
        # "Live Fantasy Standings") before Phase D5 / U1.
        aliases=("standings", "league standings", "fantasy standings", "standings tracker",
                 "fantasy standings tracker", "live fantasy standings", "official standings"),
        headline="Where your team stands, what's working, and what to do next.",
        explore_more=("The page opens with your place, the gap to first, your strongest categories and closest gains, "
                      "then the official standings (the sum of completed weeks). Under **Explore more**: the full "
                      "standings, each completed week, and **How current rosters would rank (not official standings)** "
                      "— a what-if on today's rosters with season-to-date stats."),
    ),
    PageHelp(
        "Fantasy Lineup Assistant",
        controls=("Lineup Management", "Trade Center", "Week", "Use Suggested Lineup", "Save Lineup",
                  "Start-Sit recommendations", "Recommended Starters", "Build & Analyze", "Offers & Activity",
                  "Trade partner to search", "Players I Give", "Players I Receive", "Analyze Exact Trade",
                  "Propose Trade", "Confirm and send proposal", "Find Trade Ideas", "Manage team"),
        questions=("Which positions are empty?", "Do I have an eligible shortstop?",
                   "What does Use Suggested Lineup do?"),
        terms=("use_suggested_lineup", "eligibility"),
        next_steps=("Use **View Waiver Options For Open Positions** to jump to Waiver Wire for an empty slot.",),
        sources=(MONOLITH, "fantasy_trade_ideas.py", "fantasy_weekly_lineup_ui.py", "fantasy_lineup_management_ui.py",
                 "fantasy_trade_center_ui.py"),
        aliases=("lineup", "lineup assistant", "start sit", "start-sit", "trade center", "trades", "set lineup"),
    ),
    PageHelp(
        "Waiver Wire / Add-Drop Center",
        controls=("Consider add", "Compare", "See trend", "Manage team", "Search available players",
                  "Filter available players by position", "Add player (waiver pool)", "Drop player (your roster)",
                  "Add to Pending Moves", "Confirm Pending Waiver Moves", "Plan Add"),
        questions=("Which position needs the most help?", "What does Consider add do?", "Where can I gain a point?"),
        terms=("consider_add",),
        sources=(MONOLITH, "fantasy_waiver_wire_ui.py"),
        aliases=("waiver", "waivers", "waiver wire", "add drop", "add/drop", "free agents", "check waivers"),
        headline="Who to pick up for your team, and why.",
        explore_more=("The page opens with your team's biggest need and the top three recommended adds as cards "
                      "(**Consider add**, **Compare**, **See trend**). The position filter, all recommendations, the "
                      "player pool, recommended drops, the move planner and pending moves are under **Explore more**."),
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
        ("live draft", "join a draft", "join my draft", "friends join", "room code", "draft with friends",
         "live draft room"),
        ("League & Draft Settings", "Roster Settings", "Start New Live Draft", "Room code", "Save completed draft team"),
    ),
    HowTo(
        "log_picks", "Log picks for a draft", "Draft Room Simulator",
        ("Set up the league (**Number of Teams**, **Rounds**, **Your Team**).",
         "For each pick, **Search player**, choose the **Pick**, then **Set player on pick**.",
         "**Undo Last Pick** fixes a mistake; **Save Draft Board Now** keeps the board."),
        ("log picks", "enter picks", "record picks", "draft board"),
        ("Number of Teams", "Rounds", "Your Team", "Search player", "Pick", "Set player on pick", "Undo Last Pick",
         "Save Draft Board Now"),
    ),
    HowTo(
        "share_league", "Share a league with friends", "Saved Draft Library",
        ("Open the saved draft and choose **Create Shared League**.",
         "Pick your team in **Which team is yours?**, then **Confirm Create Shared League**.",
         "Friends join with the invite and claim their own teams."),
        ("share a league", "share my league", "shared league", "invite friends"),
        ("Create Shared League", "Which team is yours?", "Confirm Create Shared League"),
    ),
    HowTo(
        "active_draft", "Make a saved draft your active team", "Saved Draft Library",
        ("Open **Set Active Draft** and pick the draft.", "Click **Set Active Draft**; **Clear Active** undoes it."),
        ("active draft", "active team", "active league", "saved draft", "set active"),
        ("Set Active Draft", "Clear Active"),
    ),
    HowTo(
        "standings", "Check league standings", "Fantasy Standings Tracker",
        ("The answer at the top shows your place, the gap to first, your strongest categories and closest gains.",
         "**League Standings (official)** is the sum of completed weeks; pick a **Completed week** to see one week.",
         "Under Explore more, **How current rosters would rank (not official standings)** is a what-if on today's "
         "rosters — load stats with **Current Stats Source** and **Refresh MLB stats** first."),
        ("standings", "category ranks", "where do i rank", "league standings", "fantasy standings"),
        ("League Standings (official)", "Completed week", "How current rosters would rank (not official standings)",
         "Current Stats Source", "Refresh MLB stats"),
    ),
    HowTo(
        "manage_league", "Manage your league", "Fantasy Standings Tracker",
        ("Start at **League Standings** (Home's **Open my league** card goes there): your place and what to do next.",
         "Use **Set lineup**, **Check waivers** and **Explore trades** under the answer for the next step.",
         "Leagues are picked, renamed and shared in **Saved Draft Library** (also under My League)."),
        ("manage my league", "manage league", "my league", "run my league", "fantasy league"),
        ("Set lineup", "Check waivers", "Explore trades"),
    ),
    HowTo(
        "start_draft", "Start a draft", "Draft Assistant Simulator",
        ("For a mock draft with pick-by-pick advice, use Home's **Start a mock draft** card (Draft Assistant Simulator).",
         "For a real draft with friends, go to **Live Draft Room** (under Draft) and start a new live draft.",
         "To log a draft you already ran, use **Draft Room Simulator** (Home's **Start or import a draft**)."),
        ("start a draft", "start draft", "mock draft", "begin a draft", "new draft", "do a draft"),
    ),
    HowTo(
        "use_suggested_lineup", "Use Suggested Lineup", "Fantasy Lineup Assistant",
        ("In **Lineup Management**, pick the **Week** and press **Use Suggested Lineup**.",
         "It fills the editable lineup with the recommended starters (the same slot rule Save Lineup enforces).",
         "It does not save, lock or finalize anything — review the board, then press **Save Lineup**."),
        ("use suggested lineup", "suggested lineup"),
        ("Lineup Management", "Week", "Use Suggested Lineup", "Save Lineup"),
        note="AMI explains it but can't press it for you.",
    ),
    HowTo(
        "consider_add", "Consider a waiver add", "Waiver Wire / Add-Drop Center",
        ("Each recommended player card has **Consider add**, **Compare** and **See trend**.",
         "**Consider add** only puts the player in the move planner below; nothing changes yet.",
         "Pick who to drop if needed, then confirm the move in the planner (**Confirm Pending Waiver Moves**)."),
        ("consider add",),
        ("Consider add", "Compare", "See trend", "Confirm Pending Waiver Moves"),
        note="AMI can't make roster moves for you.",
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
