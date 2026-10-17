# U1 — answer-first pages, grouped navigation, Home

Status: U1 implemented on `ui/u1-foundation` for Home, Historical Explorer, Leaderboards,
League Standings and Waiver Wire, plus grouped navigation and Use Suggested Lineup. The other
pages keep their current layout until U2/U3.

## The page pattern

```
A. Page identity     ui_hierarchy.page_head(title, one plain line)
B. Answer            ui_hierarchy.answer_card / metric_tiles / ranked_list / chips
C. Visual summary    one chart or ranking, shown by default
D. Next actions      ui_hierarchy.action_row (2–4 buttons; callbacks only navigate or plan)
E. Explore more      ui_hierarchy.section_label("Explore more · …"), then the page's existing
                     filters, expanders, full tables, charts and methodology, unchanged
```

How it is built:

- The answer usually depends on filters that render further down the page. So the page
  reserves a container right under the question controls (`answer_slot = st.container()`) and
  fills it after the rows are computed.
- Every existing widget keeps its key, its expander and its order relative to the others.
  Expanders can't nest, so "Explore more" is a labelled section, not a wrapper.
- Answer text comes from pure functions (`u1_answers`), built only from rows the page already
  ranked. Claims are scoped ("among the 2,084 seasons shown").

## Navigation

The page keys and the single sidebar radio (`main_sidebar_page`) are unchanged. Only the order
and section headings change.

| Section | Pages (label shown; page key in brackets where it differs) |
|---|---|
| — | 🏠 Home (new) |
| Players | Historical Explorer, Career Totals, Comparison Tool, Leaderboards |
| Insights | Trend Value, Valuation, ML Predictions, Fantasy Sleepers & Busts |
| Draft | Draft Room Simulator, Draft Assistant Simulator, Draft Lab / Simulation, Live Draft Room |
| My League | 📊 League Standings [Fantasy Standings Tracker], Fantasy Lineup Assistant, 🔄 Waiver Wire [Waiver Wire / Add-Drop Center], Saved Draft Library |
| Account | Pricing & Upgrade |

How sections are shown:

- **Desktop:** `nav_groups.sidebar_section_css` draws the headings as generated CSS content
  above the first page of each section.
- **Phones:** six section pills, then that section's pages (one to four).
- **Same routing everywhere:** both route through the sidebar page key.

Labels:

- Only the two U1 pages whose own title changed were renamed.
- Old labels still resolve to their page keys, for saved sessions.
- Saved Draft Library sits under My League. It is where leagues are activated, renamed and
  shared; it also opens a new or imported draft.
- Trades remain the Trade Center tab of Fantasy Lineup Assistant (no duplicate page). The
  Standings and Home "Explore trades" buttons open that tab directly.

**Home** opens only for a genuinely new visit, where nothing has chosen a page. Deep links,
restored sessions, Back/Forward and explicit navigation are unchanged.
`PAGE_OPTIONS[0]` is still Historical Explorer, so the existing fallbacks behave as before.

## Top-of-page clutter

| Item | Before | After |
|---|---|---|
| Brand hero + subtitle | every page (~200 px desktop) | Home (compact) and draft pages (compact, unchanged); elsewhere the sidebar logo / phone header icon |
| "New here? Start Tutorial" bar | every page | foot of Home; the tutorial itself is unchanged |
| "Loaded your last session" / "We restored your settings" | green banner above the page | toast |
| Quick Guide | open card on desktop (~130 px) | one-line toggle at every width |
| Hall of Fame Case Mode checkbox | above the Historical Explorer title | Historical Explorer › Explore more (same key; Career Totals unchanged) |
| Active-league card | above Standings / Waiver content | below the content |

Warnings and errors are unchanged: auth, persistence (including the failed-cloud-read
warning), billing, destructive actions.

## Capability checklist (before → after)

### Historical Explorer
- [x] Year Range, Sort by: still visible at the top.
- [x] Order: moved into Advanced filters.
- [x] Advanced filters: batting hand, position mode, positions, franchise/league, combine
  split seasons (unchanged).
- [x] Stat minimum filters, rate-stat qualification, "Use qualified" restore: unchanged; the
  active rule is also stated in the answer.
- [x] Hall of Fame Case Mode and its cohort tools: under Explore more.
- [x] Summary metrics, full season table, CSV export, player action center, "Use these
  filters in another tool": unchanged.
- [x] Relationship Finder, scatterplot with fit options: unchanged.
- [x] Top-10 chart: now shown by default (no checkbox), labelled by season.
- [x] AMI page snapshot, activity log, page state save: unchanged.

### Leaderboards
- [x] Year Range, Sort by: at the top.
- [x] Show Top N: moved under Explore more next to the table it controls.
- [x] Custom stat weights: unchanged; the answer explains the active score in words.
- [x] Stat minimum filters, qualification caption and restore: unchanged; the rule is also in
  the answer.
- [x] Summary metrics, full ranking table, CSV, contextual navigation, developer diagnostics:
  unchanged.
- [x] Top-10 chart: shown by default.

### League Standings (Fantasy Standings Tracker)
- [x] Official standings table (category points) and completed-weeks browser: unchanged, now
  directly under the answer instead of after stats loading.
- [x] "How current rosters would rank (not official standings)" (was "Current Roster
  Snapshot"): still labelled not official, with its scoring format, stats source, MLB season,
  refresh, CSV upload, roster table and exports.
- [x] Legacy weekly table for calendar-less leagues: unchanged.
- [x] Contextual navigation, activity log, in-season state sync: unchanged.

### Waiver Wire
- [x] Commissioner "Manage team" picker: unchanged (above the answer, since it chooses whose
  answer).
- [x] Position filter, category ranks, Make a move (multiselects, impact, Confirm Waiver
  Move), diagnostics, all 15 recommended adds with Plan Add, recommended drops, full pool with
  search, manual planner, pending moves: unchanged under Explore more.
- [x] Phase C/D validation and ownership checks: unchanged.
- [x] Top-3 cards: "Consider add" = Plan Add (fills the planner), plus Compare and See trend.
  No card button executes a move.

### Lineup (Fantasy Lineup Assistant)
- [x] Use Suggested Lineup:
  - fills the board with the Recommended Starters (same start/sit scores and the same slot
    rule Save enforces);
  - saves it as a draft through the same ownership and lock checks as dragging;
  - runs the usual validation;
  - never saves, locks or finalizes;
  - Save Lineup is still required.

## Plain-language changes on U1 pages

| Before | After |
|---|---|
| Fantasy Standings Tracker — "Upload current-season player stats and score all drafted fantasy teams…" | League Standings — "Where your team stands, what's working, and what to do next." |
| Current Roster Snapshot (not official standings) | How current rosters would rank (not official standings) |
| Waiver Wire / Add-Drop Center — "Improve your active fantasy team using current-season category performance…" | Waiver Wire — "Who to pick up for your team, and why." |
| Waiver Transaction | Make a move (add / drop) |
| League snapshot | Your category ranks |
| "Waiver analysis uses current-season MLB stats and your Fantasy Source — not projections, ADP, Fantasy Edge…" | "Recommendations use current-season MLB stats for players in your league — not projections, draft rankings or draft-risk scores." (moved under Explore more) |
| Historical Explorer — "Find individual player seasons. Split-team seasons can stay…" | "The best single seasons for any years and stat, back to 1871." |
| Leaderboards — "Build custom offensive rankings with weighted stats, filters, summary cards, and charts." | "Who leads over a span of seasons — in one stat or a custom score." |

Internal names in code are unchanged.
