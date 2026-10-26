# Baseball Explorer: simpler for fans, powerful underneath (proposal for review)

Status: **proposal only**. Nothing in this document is implemented. No analytical feature,
chart or calculation is removed; everything below is about what a visitor sees first, and
where the deeper tools live.

## 1. What a visitor meets today (measured)

Every page was swept on `quality/shared-functions` (1280 px desktop and 390 px phone). The
counts are rendered elements in the page body, including those inside collapsed expanders.

| Page | Controls | Tables | Expanders | Words | Height (px) | First thing below the shared header |
|---|---|---|---|---|---|---|
| Historical Explorer (opens first) | 27 | 1 | 3 | 241 | 2,262 | Year range, sort, order, filters |
| Career Totals | 26 | 1 | 3 | 271 | 2,167 | Same filter block |
| Leaderboards | 32 (26 numeric inputs) | 1 | 2 | 170 | 1,771 | Filters, custom weights |
| Comparison Tool | 11 | 0 | 2 | 192 | 1,323 | Player pickers |
| Trend Value | 27 | 3 | 2 | 479 | 3,960 | "Research mode … Fantasy Context Source …", window, games, position |
| Valuation | 23 | 1 | 3 | 540 | 2,877 | Window, games, position |
| ML Predictions | 14 | 0 | 1 | 167 | 1,473 | Model settings |
| Fantasy Sleepers & Busts | 20 | 3 | 5 | 711 | 4,823 | Edge map (market vs model rank, fitted curve) |
| Draft Room Simulator | 11 | 3 | 3 | 299 | 2,214 | Import / board |
| Draft Assistant Simulator | 15 | 4 | 6 | 983 | 4,791 | Settings and status |
| Draft Lab / Simulation | 5 | 0 | 1 | 166 | 997 | |
| Live Draft Room | 22 | 0 | 1 | 241 | 1,858 | Setup form |
| Saved Draft Library | 5 (14 buttons) | 0 | 1 | 431 | 2,721 | League cards |
| Fantasy Standings Tracker | 6 | 4 | 0 | 316 | 3,343 | League card, scoring format, stats source, season |
| Fantasy Lineup Assistant | 11 | 0 | 1 | 204 | 1,596 | Tab radio |
| Waiver Wire / Add-Drop Center | 8 (25 buttons, 45 captions) | 2 | 1 | 1,067 | 6,699 | League card, filters |

What stands out:

1. **No front door.** The app opens on Historical Explorer, a season-search table with 27
   controls. A fan who wanted "how is Judge doing?" or "who should I start?" has to know
   which of 17 pages to pick.
2. **17 equal sidebar items, five of them draft tools with overlapping names.** These are
   Draft Room Simulator, Draft Assistant Simulator, Draft Lab / Simulation, Live Draft Room
   and Saved Draft Library. Phones already group pages (Explore & Analyze / Draft Tools /
   Live Draft / Fantasy Team / Account); desktop does not.
3. **About 420 px of repeated chrome on every page** (desktop; more than a full screen on a
   phone) before any content: the brand banner, "New here? Start Tutorial", the page card
   and the Quick Guide card. A "Loaded your last session" banner stays at the top.
4. **Plumbing on screen.**
   - Trend Value / Valuation: "Research mode: General MLB (off) · Fantasy Context Source:
     Saved Draft Library Active League · league_import · Team: Team 1".
   - Standings asks about "Current Stats Source", "MLB API Season" and "Refresh MLB stats"
     before showing the standings.
5. **Charts are mostly off by default.** The top-10 charts sit behind "Show …" checkboxes
   and the scatter explorer behind "Show scatterplot", so most pages open as a filter block
   plus a big table. Where a chart is on by default, it is often the hardest one
   (Sleepers' market-vs-model edge map with a fitted curve).
6. **Two question boxes are coming.** The sidebar "Baseball Insight" box (Command Center
   hand-off) and the new Ask AMI panel on the AMI branch.

## 2. Proposed structure

### 2.1 One navigation, five sections, a Home page

Desktop and phone use the same groups. Page keys and `?active_page=` deep links stay
exactly as they are; only display labels and grouping change.

```
🏠 Home                         ← new front door (§2.2)
PLAYERS                         Explore players and statistics
   Season Explorer               (Historical Explorer)
   Career Totals
   Leaders                       (Leaderboards)
   Compare Players               (Comparison Tool)
INSIGHTS                        Trends, value, projections
   Trends: Rising & Falling      (Trend Value)
   Player Value                  (Valuation)
   Next-Season Projections       (ML Predictions)
   Sleepers & Busts
DRAFT                           Prepare for and run a draft
   Mock Draft (with advice)      (Draft Assistant Simulator)
   Draft Board                   (Draft Room Simulator)
   Live Draft                    (Live Draft Room)
   ▸ More draft tools: Draft Lab / Simulation
MY LEAGUE                       Manage a fantasy league
   League Home                   (Fantasy Standings Tracker, re-ordered §4.1)
   Lineup                        (Fantasy Lineup Assistant → Lineup)
   Trades                        (Fantasy Lineup Assistant → Trade Center)
   Waivers                       (Waiver Wire / Add-Drop Center)
   My Leagues                    (Saved Draft Library)
ACCOUNT
   Plans & Upgrade · Account & Workspace
```

The section names are the fan's verbs. "Advanced" is not a separate section: advanced tools
live inside each page (§3), so nothing is hidden behind a wall a fan never opens.

Implementation options for the grouped desktop sidebar (decision needed):

| Option | What | Risk |
|---|---|---|
| **A. Grouped labels on the existing radio (recommended first step)** | Same single radio and `MAIN_SIDEBAR_PAGE_KEY`; insert non-selectable section captions via the sidebar renderer, reorder `PAGE_OPTIONS` display, new labels in `PAGE_OPTION_LABELS` | Low: deep links, restore and URL sync untouched; `tests/test_mobile_nav_m2` keeps groups in sync |
| B. Section selector + page list | A section picker, then that section's pages | Medium: two widgets driving one page key |
| C. Streamlit native `st.navigation` with sections | Native grouped nav and URLs | High: replaces the page/URL/restore machinery tuned across the Live Draft and mobile passes |

The Trades entry is a deep link into Lineup Assistant's existing Trade Center tab (the tab
key already exists), so no page is split.

### 2.2 Home

```
┌───────────────────────────────────────────────────────────────┐
│ ⚾ Baseball Explorer           [ Ask AMI: “How is Judge doing?” ]│
├───────────────────────────────────────────────────────────────┤
│ What do you want to do?                                        │
│ [🔎 Look up a player] [⚖️ Compare two players] [📈 Who's hot]   │
│ [📝 Prepare for my draft] [🏆 My league]                         │
├───────────────────────────────────────────────────────────────┤
│ My league (if any): Team 1 · 2nd of 4 · Week 3 lineup due Mon  │
│   [Set lineup] [Standings] [Waivers]                           │
├───────────────────────────────────────────────────────────────┤
│ Today's quick takes: top risers · season leaders · a sleeper   │
│ (each a one-line answer that links to its page)                │
└───────────────────────────────────────────────────────────────┘
```

- The big banner and "Start Tutorial" move here, and only here.
- Returning users still land where they left off (existing restore); Home is for new visits
  and the logo link.
- "Look up a player" opens a player search, then the player's page (§3.1).

### 2.3 Shared page header (every other page)

- One line: page title + one-sentence purpose + a "How this works" link. The link opens the
  existing Quick Guide (kept, collapsed after the first view).
- "Loaded your last session" becomes a brief toast.
- Plumbing captions ("Research mode…", "Fantasy Context Source…", data-source pickers) move
  into a small "Using: league_import · Team 1 ▸" chip. Developer details stay in developer
  mode.
- The "Hall of Fame Case Mode" checkbox moves from above the title into Career Totals and
  Season Explorer's options (it already runs through the Insight pipeline; behavior is
  unchanged).

## 3. Simple first, advanced when needed (per page)

The same five-part pattern on every analysis page:

1. **Who / what:** player (or list) identity and context (team, position, age, season range).
2. **Three or four numbers that matter**, as metric tiles with plain labels: "OPS .945
   (top 5%)", not "OPS_trend 0.012".
3. **One sentence:** the takeaway in plain English. It is written from the page's own numbers
   by a deterministic template, the same way AMI composes answers; it is never a new
   statistic.
4. **One chart:** the most readable chart for that page, on by default.
5. **Next actions:** buttons such as "Compare with…", "See his trend", "Add to draft queue",
   "Ask AMI why".

Then one **"Explore more"** area (tabs or expanders, collapsed): full table, every filter,
custom weights, the advanced charts, methodology.

### 3.1 Before/after examples

Quoted sentences and numbers in the "after" descriptions are illustrative examples of the
format, not computed results.

**Season Explorer (Historical Explorer)**
- *Before:* year slider, sort, order, three expanders, a 250-row table; the top-10 chart is
  behind a checkbox; the relationship finder is behind another.
- *After:* "Top 10 seasons by HR, 2010–2025" chart visible, with a one-liner
  ("Aaron Judge's 62 HR in 2022 leads this range"). Year range + stat stay visible. The
  table, advanced filters, stat minimums and Relationship Finder (scatter + fits, unchanged)
  go under "Explore more".

**Compare Players**
- *Before:* pickers, then tables and per-stat matplotlib charts.
- *After:* a head-to-head card ("Judge leads in 5 of 7 categories; Soto gets on base more:
  .410 vs .390 OBP") and one overlaid trend chart for the chosen stat. Career table, chart
  options and the significance test stay under "Explore more" (already partly so).

**Trends: Rising & Falling (Trend Value)**
- *Before:* settings first, then the trend table, breakout/decline lists, insight summary
  and per-stat dashboards. The page is 3,960 px.
- *After:* "Rising" and "Falling" cards (top 5 each, one reason each, e.g. "+6 HR per season
  over 3 years") open the page. Click a player to see one trend chart. The window, minimum
  games, position, slopes table, volatility and dashboards go to "Explore more"; the math
  is unchanged.

**Player Value (Valuation)**
- *Before:* window, games, position, Draft Room sync, stat minimums, blend weights, table.
- *After:* "Top 10 by value" chart, with one line on what value means ("recent production
  blended with momentum, compared with other hitters"). Weights, sync and minimums go under
  "Adjust the formula". The D7 hitter-only pool is unchanged.

**Sleepers & Busts**
- *Before:* opens on the Market Rank vs Model Rank edge map with a fitted curve.
- *After:* two short lists, "Sleepers: cheaper than they should be" and "Bust risks", each
  with a one-line reason and the rank gap ("Drafted ~120th, our model says ~70th"). The edge
  map, curve choice and scoring settings move to "See the full market map".

**Next-Season Projections (ML Predictions)**
- *After:* a projection card per player showing a range ("likely 28–36 HR"), plus the main
  driver in words. Feature importance and tuning stay advanced (tuning already is).

## 4. Fantasy league workflows

### 4.1 League Home (Standings), before and after

*Before:* the league card, buttons, scoring format, stats source radio, MLB API season and
Refresh MLB stats come first. The official table and the current-roster snapshot appear
further down, both as wide tables.

*After* (layout sketch; the numbers are illustrative):

```
League Home · league_import                           Week 3 of 20 · lineups lock Mon
┌──────────────────────────────────────────────────────────────────────────────┐
│ You're 2nd of 4 — 5 points behind Team 1  (official, after 2 completed weeks)  │
│ 1 Team 1 19 · 2 YOU 14 · 3 Team 3 12 · 4 Team 2 5                             │
│ Where your points come from: R 3 · HR 2 · RBI 3 · SB 3 · AVG 3                │
│ Biggest gain available: HR (1 HR behind 3rd)          [See waivers for power] │
└──────────────────────────────────────────────────────────────────────────────┘
[ Set Week 3 lineup ]  [ Waivers ]  [ Trades ]
▸ Category points table (official)          ▸ Completed weeks (browse any final week)
▸ Analysis: current-roster snapshot (not official) · stats source · refresh
```

- Every number comes from `fantasy_read_api.official_standings_view`. The "points behind"
  and "biggest gain" lines are arithmetic on that table, not new statistics.
- The snapshot keeps its "not official" label and moves under Analysis.

### 4.2 Lineup

- A week status chip: Upcoming / Locked / Final (from the season ledger).
- The board stays.
- "Recommended Starters" becomes "Suggested lineup". It now uses the same eligibility rule
  as Save (`1e8af77`), so a new "Use suggested lineup" button would be safe (a new feature;
  needs approval).
- Diagnosis prose is cut to three bullets, with the category table under "Details".

### 4.3 Waivers (heaviest page: 6,699 px, 45 captions, 25 buttons)

- The top card answers two things:
  - "Your weakest category is SB (3rd of 4)";
  - "Best adds for you: three players, each with one reason, and an Add / drop… button".
- The pool tables, filters, paired add/drop planner and category ranks go under
  "Browse all free agents".

### 4.4 Trades

- Keep the builder.
- The result becomes a verdict card: "Fair / slight accept" + "You gain SB and AVG, lose
  HR" + legality warnings. It is built from `fantasy_read_api.evaluate_trade_for_team`.
- The category give/receive table goes under "Details".

### 4.5 Commissioner vs. owner

- Commissioner-only actions get one consistent "Commissioner tools" panel: a badge, an
  amber edge, and the wording "Only the commissioner sees this". It covers calendar setup,
  finalize week, acting for unclaimed teams, the commissioner trade and invites.
- The proxy banner ("Commissioner acting for Team X") stays on every screen where proxy is
  active.

### 4.6 Drafts

- "Prepare for my draft" (Home) leads to Mock Draft (with advice).
- Draft Board and Live Draft are second steps; Draft Lab is under "More draft tools".
- Live Draft pages are **not changed** in the first phase (they were just stabilized).

## 5. Charts: simpler defaults, nothing removed

| Chart (page) | Today | Proposed default | Moves to "Explore more" |
|---|---|---|---|
| Top-10 bar (Season Explorer, Career, Leaders, Value, ML importance) | behind a "Show …" checkbox | **visible**, plus a one-line takeaway | — |
| Relationship scatter (Season Explorer, Career) | behind checkbox + options; fit stats (r, R², equation) | unchanged (advanced) | stays advanced; add "What this shows" in words above the fit metrics |
| Player trend charts (Compare) | one matplotlib chart per stat | one overlaid chart for the chosen stat | per-stat dashboard |
| Single-player multi-stat dashboard (Trends) | many charts (one per stat) | one chart for the clicked player's headline stat | the full dashboard |
| Market vs Model edge map (Sleepers) | first thing on the page; fitted curve | lists first | the map, curve choice |
| Category strength tables (Lineup diagnosis, Waivers) | tables + prose | three plain bullets | tables |

Rules: one chart open per page by default; at most three series per chart by default;
labels in words ("Home runs", not "HR_trend"); every chart gets a one-sentence takeaway
from the same numbers it plots.

## 6. Ask AMI in the redesigned app (no second interface)

- **One entry point.**
  - Desktop: an "Ask AMI" box at the top of the sidebar, replacing the "Baseball Insight"
    section.
  - Phone: an "Ask AMI" button next to the page picker in the header, opening the same
    panel as a bottom sheet (AMI audit §8.5).
- **Page-aware.** The panel reads the current page through the AMI branch's
  `AmiPageContext`. Suggested questions change per page, e.g.:
  - League Home: "Why am I 2nd?", "What's my fastest way up?"
  - Trends: "Is Witt's decline real?"
- **Follow-ups** as tappable chips under each answer (already in the AMI foundation).
- **Path to detail.** Answers end with the matching button ("Open Trades with these
  players", "See the full table"), so AMI leads into the analytic pages instead of
  replacing them.
- **"Get a full analysis"** under an answer replaces the separate Baseball Insight box.
  It uses the same pipeline (AMI audit §3), so there is only one place to ask.
- **"Ask AMI why" buttons** on answer cards (§3) open the same panel with the question
  pre-filled. They are not a second interface.
- **Fantasy numbers** come only from `fantasy_read_api` (`docs/FANTASY_SHARED_INTERFACES.md`),
  so AMI and the pages always agree, and the snapshot can never be called the standings.

## 7. Summary: what goes where

**Stays immediately visible**
- Page title and one-line purpose.
- The main controls a fan uses: player, stat, year range.
- An answer card: identity, three or four metrics, one sentence.
- One default chart.
- Next-action buttons.
- On fantasy pages: rank and standings summary, week status, best adds, trade verdict.

**Moves into optional advanced sections ("Explore more", collapsed)**
- Full tables.
- Advanced and stat-minimum filters.
- Custom stat weights (Leaders), valuation blend weights, Draft Room sync.
- Trend slopes, volatility and the per-stat dashboards.
- Scatter / relationship finder with fits.
- Significance test.
- The market edge map and curve choice.
- Model tuning and feature importance.
- Category tables.
- The current-roster snapshot.
- Stats-source and refresh controls.
- Diagnostics captions (developer mode).

**Consolidated**
- The 17-item sidebar becomes five sections plus Home; desktop and phone use the same
  grouping.
- Banner, tutorial and session banner become Home-only, plus a toast.
- Quick Guide becomes the "How this works" link.
- "Baseball Insight" box + Ask AMI become one Ask AMI.
- Trade Center gets its own nav entry (a deep link to the existing tab).
- Commissioner actions go into one "Commissioner tools" panel.

**Remains completely unchanged**
- All calculations: official standings, scoring, valuation (including the D7 pool), trends,
  projections, eligibility.
- Every page key and `?active_page=` deep link; session restore, autosave and URL sync.
- Live Draft and Draft Room behavior.
- Billing / paywall gates; authentication and team authorization.
- Saved data formats.

## 8. Suggested phases (each separately reviewable)

| Phase | Scope | Risk |
|---|---|---|
| U1 | Grouped nav (option A) + Home page + Home-only banner/tutorial + toast for "Loaded your last session" | low |
| U2 | League Home re-order (standings summary first; snapshot/source controls under Analysis) + commissioner panel | low–medium |
| U3 | Answer card + default chart for Season Explorer, Compare, Trends, Value, Sleepers | medium (many pages; behavior-neutral) |
| U4 | Waivers and Trades summary cards (read API) | medium |
| U5 | Ask AMI single entry (with the AMI Claude), phone header button, retire the Insight box behind a flag | coordinated |

Decisions needed before U1:
- the grouped-sidebar option (A recommended);
- the display labels in §2.1;
- whether Home becomes the default for brand-new visitors;
- whether "Use suggested lineup" (one-click apply) is wanted.
