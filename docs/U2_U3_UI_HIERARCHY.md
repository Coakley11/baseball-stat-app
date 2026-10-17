# U2/U3: answer-first analytics, draft and league pages

Status: implemented on `ui/u2-u3-simplification`, which branches from the accepted U1 checkpoint
`ui/u1-foundation @ 06acd43`. Not pushed, not deployed, `dev` untouched. Ask AMI (U5) is not part
of this work.

The page pattern is the U1 one ([U1_UI_HIERARCHY.md](U1_UI_HIERARCHY.md)):

```
page identity → the question's own controls → answer → one default visual → next actions → Explore more
```

All answer text comes from pure functions that only read values the page already computed:
`u2_answers` (analytics pages) and `u3_answers` (Lineup, Trade Center). Each is unit tested. No
statistic, ranking, model or trade judgment is computed just for an answer card.

New shared building blocks in `ui_hierarchy`:

| Block | Used by |
|---|---|
| `stat_bars` | head-to-head bars (Compare Players) |
| `info_cards` | sleeper and bust-risk cards |
| `commissioner_panel` | one "🛡️ Commissioner Tools" panel (Lineup, Waiver Wire, Trade Center) |
| `proxy_banner` | "Commissioner acting for Team X" notice |
| `trade_sides` | You give ⇄ You receive |

## Page by page

### Compare Players (key `Comparison Tool`)

| | Before (U1) | After |
|---|---|---|
| Top of page | Player picker, then profile cards, Chart options, year-by-year table, career table, trend chart, significance test | Player picker and season range (the question) |
| Answer | none | Head to head. Who leads in HR, RBI, SB, OBP and OPS over the same seasons, e.g. "Judge leads in HR, RBI and OPS; Soto leads in OBP and SB". Includes sample sizes and a playing-time note when one player had many more at-bats. Ties use displayed precision. **No overall winner.** |
| Default visual | none by default | Head-to-head bars, one group per metric, leader in full colour |
| Next actions | — | Each player's trend · Career totals |
| Explore more | — | Profiles, chart options, year-by-year and career tables, trend chart, trend intelligence, significance tests (all unchanged) |

States:
- **0 players:** the existing prompt.
- **1 player:** that player's numbers over the range, plus a nudge to add a second.
- **2–3 players:** the head-to-head answer.

Swapping players and the existing same-player guards in the significance test are unchanged.

### Career Totals

| | Before | After |
|---|---|---|
| Top | Hall of Fame Case Mode, year range, sort, advanced filters | Year range and sort stat |
| Answer | none | The leader's career within the filters. Covers span and seasons, games, the slash line, and the best season for counting stats (stints summed). The leader's margin over the next two. The active qualification rule is stated. |
| Default visual | Top-10 chart behind a checkbox | Top-10 chart shown |
| Next actions | — | Compare (leader) · Trend · Season view (Historical Explorer) · Leaderboards |
| Explore more | — | Hall of Fame Case Mode, filters, minimums, full career table, CSV |

### Trend Value

| | Before | After |
|---|---|---|
| Top | Window, minimum games, position, draft sync, sort stat, then three tables and two dashboards | Trend stat and window |
| Answer | none | Fastest riser and biggest drop with the per-season slope and first → last values. At-bats are shown for rate stats, with "Rate-stat trends weight seasons by playing time so small samples have less influence." A player sent here from another page leads the answer. |
| Default visual | none by default | Season-by-season line chart for the riser and the drop (or your player) |
| Next actions | — | Compare the pair · Valuation · Show top risers (when a player was sent) |
| Explore more | — | Minimum games, positions, draft sync, the full trend table, breakout/decline lists, player dashboards and charts |

Trend Value math is unchanged.

### Valuation

| | Before | After |
|---|---|---|
| Top | Window, minimum games, position, sync, weights | Window and position |
| Answer | Best/worst callouts at the bottom | The top hitter, with production rank and trend rank among the hitters valued. Trend direction is stated, and a zero trend is "about flat", never a decline. Gives the weights, and says what the score is: a weighted blend of the two percentiles, rescaled 0–100. Discloses a Research-mode position-need boost. |
| Default visual | none | Top-10 Valuation Score chart |
| Next actions | — | Compare the top two · Top player's trend · Sleepers & Busts |
| Explore more | — | Minimum games, blend weights, full table, explanations |

The hitter-only pool from Phase D7 is unchanged: pitchers and relievers without batting data stay
out.

### Sleepers & Busts (key `Fantasy Sleepers & Busts`)

| | Before | After |
|---|---|---|
| Top | Column glossary, window, format, scoring, filters, edge map | Projection window and format |
| Answer | none | Definitions first: a sleeper is ranked better by our model than by the market (FantasyPros rankings and ADP); a bust risk carries a market price above what our model supports. "These are ranking gaps, not predictions." |
| Default visual | Edge map (scatter) | Three sleeper and three bust-risk cards: model rank, market rank, Fantasy Edge, model projection |
| Next actions | — | Compare the top pair · Top sleeper's trend · Draft Assistant |
| Explore more | — | Glossary, minimums, scoring, filters, the edge map, full tables, profile cards |

### ML Predictions

| | Before | After |
|---|---|---|
| Top | Lookback, scope, tuning expander, Generate | Position, sort, Generate/Refresh |
| Answer | none | Top 5 projected hitters for the sort, each with the model's own confidence label (High / Medium / Risky). The held-out accuracy for that stat (MAE, R²) is quoted. **No interval is shown**, because the model does not produce one. |
| Default visual | table | Ranked list |
| Next actions | — | Compare the top pair · Top player's trend · Sleepers & Busts |
| Explore more | — | Lookback, minimums, scope, tuning, accuracy check, full table, age curves, feature importance |

Free/Pro gating is untouched: it is keyed on the page key in `baseball_monetization`, and nothing
is enforced.

### Draft tools (U3A)

The five draft tools keep their logic and keys. Each now says what it is for (`draft_tools.DRAFT_TOOLS`),
and an "Other draft tools" row links to the others.

| Tool | Why choose it |
|---|---|
| Live Draft Room | Draft in real time with pick timers and auto-pick, solo against the computer or in a shared room with your league. Saves as you draft. |
| Draft Room Simulator | Set up a league and log every pick yourself (practice, or mirroring a draft on another site). Draft Assistant reads this board. |
| Draft Assistant | Who to pick next: rankings from your board's needs, scarcity and market value, with reasons. |
| Draft Lab | Test a strategy: the computer runs a four-team snake mock, then grades every roster. |
| Saved Draft Library | Saved drafts and leagues: open, rename, share, or make one your active league. |

- **Landing:** Home's "Prepare for a Draft" card offers Run a Live Draft · Simulate a Draft · Analyze
  Draft Strategy · Open Saved Drafts. There is no separate landing page.
- **Live Draft:** shows the switcher only in its intro, never inside an active room. Live Draft
  internals are unchanged.
- **Wording:** Draft Room Simulator's board heading is "Draft board", no longer "Live draft board".

### Lineup (key `Fantasy Lineup Assistant`, label "Lineup & Trades")

| | Before | After |
|---|---|---|
| Top | Title, guide, active-league card + 3 links, tab radio, Manage team, Edit Lineup Format, calendar expander, Week, info line, team header | Title, tab radio, 🛡️ Commissioner Tools (commissioners only, collapsed), Week |
| Answer | "9/9 positions filled" line about 1,000 px down at 1280 | Complete or not, open spots (and whether the roster can fill them), and status. Status is one of: not saved, draft (kept, not submitted), saved and locked. Tiles: Starters, Open, Bench, Status. Missing positions show as chips. |
| Visual | Board (starters, bench), iframe sized for 4 per row | Same board with clearer states: open spots show "Open" and how many bench players can play there, starter and bench counts, bench position badges. The frame is sized to what was drawn. |
| Next actions | Use Suggested Lineup | Use Suggested Lineup · Check Waivers · Explore Trades. The primary one follows the answer: fill from the roster, else waivers. Save Lineup stays below the board. |
| Explore more | — | Start/sit recommendations, Recommended Starters, lineup diagnosis, category needs, bench/watch list |

- **Data:** the answer uses `validate_weekly_lineup` (the rule Save enforces) and the saved
  record's own status. The Phase D lineup and eligibility functions are not modified.
- **Use Suggested Lineup:** still suggest → fill the editable board → review → Save Lineup. It never
  saves, locks or finalizes.
- **Active-league card:** moved below the content, as on Standings and Waiver Wire.

### Commissioner Tools (U3C)

- **One panel:** a single collapsed "🛡️ Commissioner Tools" expander, shown only to commissioners
  (or when unclaimed teams can be proxied). Owners never see it.
- **On Lineup** it holds:
  - Manage team (act for an unclaimed team);
  - Edit Lineup Format;
  - the season calendar setup;
  - Finalize week (both the season-calendar and legacy flows).

  Owners still see "Week N is final" and the "commissioner has not set the calendar" note in the
  main flow.
- **Waiver Wire:** Manage team moved into the same panel.
- **Trade Center:** the commissioner trade for an unclaimed team moved into the same panel.
- **While proxying:** a purple "🛡️ Commissioner acting for Team X." banner stays visible outside
  the panel. The answer's kicker also says "Commissioner acting for Team X". Explore Trades is
  hidden, since Trade Center is for your own team.
- **Lineup format setup:** the first-time format setup, which blocks everything else, still
  renders in the main flow.
- **Invitations and team claims** stay in Saved Draft Library, where they already live.

### Trade Center verdict card (U3D)

After Analyze Exact Trade (or a restored analysis), in one slot above the action buttons:

1. **You give ⇄ You receive.** Players with position badges and their current-season stat line.
   Stacks on phones.
2. **Verdict.** A deterministic mapping of the trade engine's own classification
   (`evaluate_trade`, need-weighted gain ±2):

| Engine | Label |
|---|---|
| Good for your team | Favors your team |
| Neutral | Balanced |
| Bad for your team | Favors the other team |
| any + a required-slot gap or over-size roster on **your** team (`trade_roster_issues`) | Creates roster issue (the value label is kept in the headline) |

3. **Tiles and chips.**
   - Tiles: value difference (need-weighted), positions given, positions received, your roster
     check.
   - Chips: category impact per category, from the engine's own category rows.
4. **Detailed calculation** (expander). Everything the panel showed before:
   - the engine verdict and the tiered verdict text;
   - players in the deal;
   - the category table;
   - direction;
   - positions;
   - interpretation.

- **No other judgment:** no AI or extra judgment is added, and the trade engine is unchanged.
- **Roster issues:** your roster's issues show as warnings. The partner's issues, and any open
  roster spots, show as notes.
- **Before an analysis:** the roster checks still show on their own, as before.
- **Stat-line fix:** the Trade Center stat line no longer shows a counting stat of 0 as ".000".

## Labels changed

| Page key (unchanged) | Before | After | Why |
|---|---|---|---|
| Comparison Tool | 📈 Comparison Tool | 📈 Compare Players | matches the page title and the Home task |
| Fantasy Sleepers & Busts | 💎 Fantasy Sleepers & Busts | 💎 Sleepers & Busts | shorter; fits the phone picker |
| Fantasy Lineup Assistant | 🧠 Fantasy Lineup Assistant | 🧠 Lineup & Trades | the page also holds the Trade Center, which had no visible entry |

For each:
- The old label still resolves to the key (`_PAGE_LABEL_TO_KEY`), so saved sessions keep working.
- `?active_page=` deep links use keys and are unaffected.
- `PAGE_GUIDES` (Quick Guide) text is updated in this branch.

U1 labels (Home, League Standings, Waiver Wire) are unchanged.

## Default visuals

| Page | Default visual | Moved under Explore more |
|---|---|---|
| Compare Players | head-to-head bars | trend chart, trend intelligence, significance tests |
| Career Totals | top-10 career chart | — (chart already existed; now shown without a checkbox) |
| Trend Value | season-by-season line chart | player trend dashboards, visualizations |
| Valuation | top-10 Valuation Score chart | — |
| Sleepers & Busts | sleeper / bust cards | edge map (scatter), curve-adjusted lists |
| ML Predictions | top-5 ranked list | feature-importance chart, age-curve details |
| Lineup | lineup board | Recommended Starters photo strip, category charts |
| Trade Center | You give ⇄ You receive | category table (Detailed calculation) |

## Mobile and performance

### Mobile

Swept with Playwright at 430, 390 and 360 px (844 px tall) and 1280 px desktop, on a QA
workspace with a commissioner-run real league.

For every redesigned page at every width:
- the answer, or on draft pages the purpose block and tool switcher, is on the first screen;
- no horizontal overflow, no visual past the viewport edge, no exceptions.

Where the answer card starts, in pixels from the top of the page body. These were measured
before the phone-gap fix below; on phones every value is now about 74 px smaller. A dash means
the page was not measured at that width. At 390, Lineup was open on its Trade Center tab and
the draft pages ran with an earlier selector; 430 and 360 cover those phone cases.

| Page | 430 | 390 | 360 | 1280 | Controls above it (phone) |
|---|---|---|---|---|---|
| Compare Players (3 players) | 655 | 593 | 710 | 453 | 3 |
| Career Totals | 510 | 510 | 510 | 330 | 3 |
| Trend Value | 546 | 569 | 569 | 369 | 3 |
| Valuation | 571 | 593 | 593 | 369 | 3 |
| ML Predictions | 570 | 570 | 570 | 386 | 3 |
| Sleepers & Busts | 571 | 593 | 593 | 369 | 3 |
| Lineup & Trades | 630 | — | 654 | 458 | 4 (tab, Commissioner Tools, Week) |
| Waiver Wire | 458 | 458 | 458 | 302 | 1 |
| Draft pages (purpose + switcher) | 252–416 | — | 252–416 | 97–238 | 1 |

Also checked:
- **Compare Players:** 0, 1, 2 and 3 players at 390.
- **Lineup:** commissioner proxy view; incomplete lineup (open spots marked "Open" with
  bench-eligibility hints); bench position badges.
- **Trade verdict card:** at 1280 and 360; the two sides stack and the ⇄ turns vertical.
- **Waiver Wire:** Commissioner Tools and the proxy banner at 390.
- **Live Draft navigation smoke** at 1280 and 390:
  - intro, switcher → Draft Lab, sidebar → Live Draft, Home "Run a Live Draft", browser Back;
  - each has the right title and URL, and no exceptions.

**Phone gap above the title (fixed).** The ~74 px between the phone page picker and the page
title came from three flex gaps, the URL-sync component's 26 px container (around a 0 px iframe)
and a style-only markdown block. On phones only, those two invisible carriers are taken out of
the flex flow (`position: absolute`, zero size; `mobile_foundation` rule 8b). They are not hidden,
so the URL-sync iframe keeps running.
- The title moved from 264 px to 190 px at 390.
- Browser Back/Forward on a phone gives the same history and pages as the U1 control (checked
  side by side).
- Navigation code is unchanged.
- In passing: on the U1 control too, the "My League" section pill opens Saved Draft Library
  first, which adds a history entry.

**Not changed.** The stacked Waiver secondary buttons at 360 were accepted in U1. Lineup's
four tiles wrap two by two on phones.

### Performance (before = U1 `06acd43`, after = this branch)

How it was measured:
- **Interleaved A/B on one machine.** U1 ran on :8556 and this branch on :8555, both on a copy
  of the same QA workspace. The order alternated every page and round.
- **Fresh sessions.** Each load was a fresh browser context, so a new Streamlit session on a warm
  server. The first round was a warm-up and is excluded.
- **Medians in seconds,** at 1280 px.
- **Shared machine.** It sat at 70–80% CPU with under 1 GB of free RAM from other sessions, so
  differences under about 1 s are noise.

| Page | Before: useful / idle | After: useful / idle | Δ idle |
|---|---|---|---|
| Compare Players (3 players) | 14.6 / 18.5 | 13.1 / 18.2 | −0.3 |
| Career Totals | 13.3 / 16.0 | 12.6 / 15.3 | −0.7 |
| Trend Value | 14.9 / 17.4 | 12.9 / 16.7 | −0.7 |
| Valuation | 14.0 / 16.7 | 14.5 / 16.6 | −0.2 |
| Sleepers & Busts | 14.0 / 16.8 | 14.9 / 17.6 | +0.8 |
| ML Predictions (6 rounds, idle only) | 12.2 | 12.0 | −0.2 (mean −0.1) |
| Draft Room Simulator | 13.2 / 16.0 | 13.1 / 15.9 | −0.2 |
| Draft Assistant | 13.9 / 16.7 | 14.0 / 16.8 | +0.1 |
| Draft Lab (idle only) | 11.2 | 12.2 | +0.9 |
| Saved Draft Library (idle only) | 11.5 | 11.0 | −0.6 |
| Live Draft Room intro (idle only) | 11.4 | 10.1 | −1.3 |
| Lineup (6 rounds, idle only) | 13.2 | 13.8 | +0.6 (mean +0.6) |

Notes on the table:
- **"Useful"** is the first answer card, table, chart or board on screen.
- **ML Predictions:** before this branch it showed no content until Generate was pressed, so
  only time to idle compares.

Interactions (medians):

| Interaction | Before | After |
|---|---|---|
| ML Predictions: Generate / Refresh | 5.1 s | 4.2 s |
| Lineup → Trade Center tab | 2.9 s | 3.3 s |
| Trade Center → Lineup tab | 4.4 s | 4.9 s |

Reading of the results:
- **No material regression.** Most pages are within noise; several are slightly faster.
- **Lineup:** about +0.6 s (≈4%) on a 13 s load, but the runs overlap: before 12.9–13.6 s,
  after 12.6–15.7 s. The only added server work is one `validate_weekly_lineup` call over the
  roster (about 10 players) and about eight more page elements. Treat it as at most a small cost.
- **Answer cards** reuse each page's computed rows: no extra queries, model fits or rankings.

## Capability checklist (before → after)

Every item was in the page before and is still reachable. "Same key" means the widget key
is unchanged, so saved page state, autosave and restore keep working. Widget keys per page are
asserted in `tests/test_u2_pages.py`.

### Compare Players
- [x] Select up to 3 players, season range (same keys): top of page.
- [x] Chart options (stat, age range, x-axis mode, smoothing): under Explore more, same keys.
- [x] Player profile cards and player actions: unchanged.
- [x] Year-by-Year Comparison, Career Totals tables, CSV: unchanged.
- [x] Trend chart and Advanced Trend Intelligence: unchanged (no longer the first thing shown).
- [x] Significance test, including the same-player guard: unchanged.
- [x] 0-, 1-, 2- and 3-player states; replacing players (also via "Compare X & Y" from other
  pages, which replaces the selection).
- [x] Draft Room context notes and AMI page context: unchanged.

### Career Totals
- [x] Year range, sort stat: top. Batting hand, position mode and list, franchise/league,
  combine by team: under Explore more, same keys.
- [x] Stat minimums and rate-stat qualification: unchanged; the active rule is stated in the
  answer.
- [x] Hall of Fame Case Mode with target, analysis, memo and AMI hand-off: under Explore more,
  same keys.
- [x] Full career table, CSV, player actions: unchanged.
- [x] Top-10 chart: now shown without a checkbox.

### Trend Value
- [x] Sort/trend stat and window: top. Minimum games, Fantasy Position, Draft Room sync:
  under Explore more, same keys.
- [x] Trend table, breakout and decline lists, insight summary, single-player dashboard,
  player trend visualization, Advanced Trend Intelligence: unchanged.
- [x] A player sent from another page (Player Actions, contextual links) leads the answer.
  "Show top risers" returns to the list.
- [x] Trend math (playing-time weighted rate-stat slopes): unchanged.

### Valuation
- [x] Window and position: top. Minimum games, blend weights, Draft Room sync: under Explore
  more, same keys.
- [x] Full table (Valuation, Current, Trend scores and stats), player explanations,
  best/worst insight summaries, CSV, AMI context: unchanged.
- [x] Hitter-only pool (Phase D7): unchanged.

### Sleepers & Busts
- [x] Projection window and format: top. Column glossary, minimum games/AB, advanced scoring,
  projection style, top N, grade filter, points settings, position and age filters: under
  Explore more, same keys.
- [x] Fantasy Edge map with chart display options, curve-adjusted lists, sleeper and bust
  tables, insight summary, AMI send: unchanged.

### ML Predictions
- [x] Generate / Refresh, position, sort: top.
- [x] Lookback, scope, minimums, tuning (style, regression, aging, similar players, Apply):
  under Explore more, same keys.
- [x] Model accuracy check, full projection table, stabilization notes, age curves, feature
  importance, developer checks: unchanged.
- [x] Free/Pro gating: unchanged (`baseball_monetization.PAGE_FEATURES`, nothing enforced).

### Draft tools
- [x] Every draft page: same keys, same flows. Only the header line and an "Other draft tools"
  row were added.
- [x] Live Draft Room: the switcher shows only in the intro. Room, timers, picks and saving are
  unchanged.
- [x] Home: the four draft entry points open the existing pages through normal navigation.

### Lineup
- [x] Week selector, board drag and drop, Reset, Save Lineup, and the save-on-drop draft with
  read-back verification: unchanged.
- [x] Use Suggested Lineup: unchanged flow and key (suggest → fill → review → Save).
- [x] Open-spot prompts with their position-specific Waiver Wire buttons: unchanged, below
  the board.
- [x] Locked weeks: scoring dashboard, player detail panel, period result: unchanged.
- [x] Start-Sit recommendations (scoring mode, bench rows), slots, custom points scoring,
  Recommended Starters, CSV, contextual navigation, diagnosis, category standings, actionable
  recommendations, bench/watch list: unchanged, under Explore more.
- [x] Active-league card and its links: below the content.
- [x] Lineup identity diagnostics (developer): unchanged.

### Commissioner tools
- [x] Manage team / proxy on Lineup and Waiver Wire: same keys (`lineup_manage_team`,
  `waiver_manage_team`), now in the panel. Proxy saves are still logged as commissioner
  actions.
- [x] Lineup format setup and editing, season calendar creation, Finalize week (calendar and
  legacy), commissioner trade for unclaimed teams: same keys, in the panel.
- [x] Invitations and team claims: unchanged in Saved Draft Library.

### Trade Center
- [x] Trade partner, Players I Give / Receive, Find Trade Ideas, Analyze Exact Trade, Propose
  Trade, Confirm and send proposal, Clear, Reset Trade Builder, Offers & Activity, history:
  unchanged.
- [x] Analysis: everything it showed before is under "Detailed calculation". It is kept in the
  shared trade state and restored on rerun, as before.
- [x] Roster legality warnings: same checks and messages (`trade_roster_warnings` now returns
  the messages of `trade_roster_issues`).

### Navigation, state and history (all pages)
- [x] Page keys, `?active_page=` deep links, the single sidebar radio, phone section pills and
  picker, browser Back/Forward (URL sync): unchanged.
- [x] Old labels still resolve to page keys for saved sessions.
- [x] Session restore, autosave and page-state snapshots: no widget key changed. New buttons use
  `*_btn` keys, which are never snapshotted.

## AMI reconciliation notes

This branch does not edit AMI-owned files. These are the reconciliation steps for when it
meets `feature/ami-foundation`. All notes were checked read-only against `c5f3e08`.

1. **Quick Guide text (merge conflict expected).** AMI moved `PAGE_GUIDES` out of
   `streamlit_app.py` into `page_guides.py`. This branch changed the text of these entries in
   `streamlit_app.py`:
   - Career Totals, Comparison Tool, Trend Value, Valuation, ML Predictions;
   - Fantasy Sleepers & Busts, Fantasy Lineup Assistant;
   - Draft Room Simulator, Draft Assistant Simulator, Draft Lab / Simulation, Live Draft Room,
     Saved Draft Library.

   On merge, keep AMI's move and carry these strings into `page_guides.py`.
2. **Navigation labels.** New display labels:
   - Comparison Tool → "Compare Players";
   - Fantasy Sleepers & Busts → "Sleepers & Busts";
   - Fantasy Lineup Assistant → "Lineup & Trades".

   Page keys are unchanged, so `PAGE_HELP` keys and how-to page keys still match. Help prose
   that names pages for navigation should use the labels. Examples in `ami_assistant/page_help.py`:
   - "send a player to Comparison Tool or Trend Value";
   - "Standings Tracker, Lineup Assistant and Waiver Wire";
   - "Choose the **Trade Center** section".

   Better still, render names through `nav_groups.NAV_LABELS` / `page_option_label` so future
   renames follow automatically.
3. **Control labels.** All 145 control labels in AMI's help registry (`PageHelp.controls`,
   `HowTo.controls`) still exist in this branch's sources. That was checked by comparing the U1
   baseline sources with this branch, so AMI's label-check tests should keep passing. New
   controls AMI may want to mention:
   - "Use Suggested Lineup", "Check Waivers", "Explore Trades" (Lineup);
   - "🛡️ Commissioner Tools" (Lineup, Waiver Wire, Trade Center);
   - "Detailed calculation" (Trade Center);
   - the "Other draft tools" row.
4. **Trade verdict vocabulary.** The Trade Center now shows Balanced / Favors your team / Favors
   the other team / Creates roster issue. That is a deterministic mapping of `evaluate_trade`'s
   verdict plus `fantasy_trade_legality.trade_roster_issues`. If AMI describes trades, use
   `u3_answers.trade_verdict` (pure) so both surfaces say the same thing.
   `trade_roster_warnings` returns exactly what it did before. `trade_roster_issues` is the new
   structured form.
5. **Lineup status vocabulary.** "Not saved / Draft (not submitted) / Saved and locked" comes
   from `u3_answers.lineup_answer` over `validate_weekly_lineup` and the saved record. AMI's
   read API (`fantasy_read_api`) is unchanged.
6. **Draft tool purposes.** `draft_tools.DRAFT_TOOLS` is the single source for "why choose this
   tool". AMI's draft-page help could quote it rather than keep its own wording.

## Remaining (U4 / U5)

Not done here, by design or scope:

- **U5, Ask AMI:** the single entry, the phone header button, and retiring the Insight box.
  Owned by the AMI work.
- **Draft pages:** purpose and cross-links only. Their logic was not merged (as instructed), and
  they don't yet have an answer card. Two examples of what one would hold: Draft Assistant's
  "your next pick" and the Draft Room board summary. On phones their primary content is still
  below the first screen.
- **Trade Center:**
  - The hero banner and the trade-idea cards still use the older style.
  - Offers & Activity has no summary line.
  - The proposal's idea of a separate Trade nav entry was replaced by the "Lineup & Trades"
    label (no duplicate page).
- **Lineup:** the per-slot "stays empty" warnings below the board repeat what the answer already
  says. They are kept because each carries a position-specific Waiver Wire button. They could
  fold into the answer in U4.
- **Valuation and Compare:**
  - Valuation leads with the top-ranked hitter. A chosen player's components are under Explore
    more (`valuation_selected_player`).
  - Compare's "View player" actions point to each player's trend, because there is no
    single-player page yet.
- **Commissioner Tools:** invitations and team claims stay in Saved Draft Library; the panel
  does not duplicate them.
- **Phone gap:** see Mobile and performance.
- **Pre-existing test failures** seen on the U1 control as well (see the report):
  - `test_lineup_assistant_render_structure` looks for `if active_page ==` where the router
    uses `elif`;
  - two lineup smoke tests depend on the local identity in `data/`;
  - `test_draft_archive_callbacks::test_live_draft_save_click_records_trace_before_persist`.
