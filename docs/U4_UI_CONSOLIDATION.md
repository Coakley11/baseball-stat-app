# U4: draft answer cards, Lineup / Trade / Valuation cleanup, consistency

Status: on `ui/u4-migration-readiness`, branched from the accepted U2/U3 checkpoint
`ui/u2-u3-simplification @ 4bc3d30`. Not pushed, not deployed, `dev` untouched.

The pattern is unchanged: answer → useful visual → obvious next action → Explore more.

All new answer text comes from pure functions (`u4_answers`, plus additions to `u2_answers` and
`u3_answers`) that read only what the page already computed. They are covered by
`tests/test_u4_pages.py`.

## Draft pages (U4A)

| Page | Before (U3) | After |
|---|---|---|
| Draft Room Simulator | Purpose line, then the import uploader and its controls on the first screen. Board status deep inside the Board tab. | **Answer:** picks made of total, the pick on the clock and which team, your next pick, where the board's last change came from (an imported file / picks entered here / the Live Draft Room), and unsaved changes (claimed only once picks exist). **Tiles:** Picks, On the clock, Your next pick, Board (Saved / Unsaved / Empty). **Actions:** see below the table. Import, board, queue, rosters, grades and league setup are under Explore more. |
| Draft Assistant | Settings, status expanders and team-needs controls first; recommendations further down. | **Answer:** "Best pick now: …" is the recommendation the page already ranks first (Decision Score order, its own "Why this pick"). Also: the highest raw value when it's a different player, your next pick and the pick on the clock, and the roster's open positions. They are not ranked, so there is no "biggest need" claim. **Actions:** compare best fit vs raw value, Open Draft Board, Live Draft Room. |
| Draft Lab | Model controls (window, format, style, picks) and a model explainer first; a five-metric row after a run. | **Answer:** "Projected best draft: Team D", from the simulation's own team ranking; the Draft Lab Team Score and margin over second; that team's Best Pick with the analysis' own reason; and its open positions. **Then:** Run 4-Team Draft Simulation, followed by Explore more (Simulation settings with the same keys, how the model works, all results). Empty state: "No simulation yet". |
| Saved Draft Library | Invites, the active-draft section and sync controls before the list. | **Answer:** active league, your team and team count, number of saved drafts, the most recent draft. **Actions:** League Standings, Lineup & Trades, ⭐ Set Active and Rename on the most recent draft, through the same paths as the cards. Invitations, active-league tools, sync and every saved draft are under Explore more. |
| Live Draft Room | Purpose line, tool switcher, Draft Mode descriptions | Reviewed and unchanged: the intro already explains Solo vs Shared. Live Draft internals are untouched. |

Draft Room Simulator actions:

| Action | What it does |
|---|---|
| Draft Player | A small popover. Sets a player on the next open pick through the board's own `submit_board_pick_assignment`, with the same arguments as "Set player on pick". |
| Import Draft | Opens the import section. It now sits in an expander above the tabs (never inside a tab, which resets on rerun) and opens on its own while an upload is under review. |
| Save Draft | The same request as "Save Draft Board Now". |
| Open Saved Drafts | Opens Saved Draft Library. |

Verified in the browser (1280):
- **Draft Player:** set Aaron Judge on pick 1, and the answer moved to "Pick 2 is next … Team 2 is on
  the clock".
- **Save Draft:** ran the same save path. Locally there is no cloud backup, so the message reads
  "saved on this device, online backup did not confirm", and the Board tile correctly stays
  Unsaved.
- **Import Draft:** opened the uploader.
- **Library Rename:** opened the existing rename box.
- **Draft Lab:** after a run, the answer reads "Projected best draft: Team D — Draft Lab Team Score
  8.30, 0.08 ahead of Team C. Best pick: Randy Arozarena (…)".

## Lineup, Trade Center, Valuation (U4B)

**Lineup warnings.**
- The answer states the result once: "Your lineup has 3 open positions: Second Base, Third Base
  and Shortstop" ("Team 2's lineup …" while proxying). Then it groups them:
  - **From the bench:** spots an unused rostered player can fill.
  - **Needs a waiver or trade:** `unfillable_slots` from the same validation Save enforces. These
    score nothing this week.
  - **Not eligible where placed:** including players assigned twice.
- Chips mirror the groups.
- The per-slot "stays empty / not eligible / assigned twice" warning stack below the board is gone.
  Only the spots with a position-specific "Open Waiver Wire for …" button keep a row.
- Phase D eligibility is untouched.

**Trade Center.**
- **Header:** the gradient banner is now a compact heading with league, team and pending-offer
  chips.
- **Builder:** reads "You give · Team" / "You receive", matching the verdict card (U3).
- **Trade-idea cards:**
  - give ⇄ receive with position badges and stat lines, then the engine's chips (value, team fit,
    value match);
  - "Why it's suggested" is built only from the idea generator's own value note and category gains
    (e.g. "balanced value (value match 100/100); helps HR");
  - then "You gain", "You give up" and "Risk".
- **Engine text:** the generator's "Why It Helps" string mixes gains and weaknesses, and those are
  already shown on their own lines, so it is not repeated as a reason. The engine is unchanged.

**Valuation.**
- A player chosen in "Choose a player to explain" (or sent from another page) leads the answer.
  The default selection is the top player, and that still reads as "Top valuation".
- The answer shows:
  - rank and score ("Juan Soto: Valuation 89, 25th of 630");
  - production and trend ranks;
  - the exact blend: production points + trend points =
    (w_current·Perf_Pct + w_trend·Trend_Pct)/(w_current+w_trend), before the 0–100 rescale;
  - the weights and a plain interpretation.
- "Show top player" returns to the top-ranked hitter. A selected player missing from the filtered
  list is named.
- The valuation math is unchanged. "Both rank high" is only said when both percentiles are at least
  0.7.

## Consistency (U4.5)

| Item | Change |
|---|---|
| Old page names in visible copy | The tutorial, Draft Room and Lineup instructions, the Waiver Wire stats hint and the library's tool buttons now say League Standings / Lineup & Trades / Waiver Wire / Compare Players / Sleepers & Busts. |
| Same action, different labels | One label everywhere: Set Lineup / Check Waivers / Explore Trades (Home, League Standings, Lineup). |
| Page links | Use the page name: "Career Totals" (was "Career totals"), "Historical Explorer" (was "Season view"), "League Standings", "Waiver Wire". |
| Explore more | Every redesigned page, the draft pages included, now has one "Explore more · …" label naming what's below. |
| Empty states | Draft Room "Ready to draft…", Draft Assistant "No recommendation yet" / "Your draft is complete", Draft Lab "No simulation yet", Library "No saved drafts yet" / "No active league yet". |
| Compatibility | No page key changed. Old labels still resolve to keys (`_PAGE_LABEL_TO_KEY`, tested), and `?active_page=` deep links are unchanged. |

## Mobile

Swept at 1280, 430, 390 and 360. Every U4 page has its answer on the first screen, with no
horizontal overflow, clipped visual or exception.

Where the answer starts, in px from the top of the page body:

| Page | 1280 | 430 | 390 | 360 |
|---|---|---|---|---|
| Draft Room Simulator | 460 | 634 | 655 | 654 |
| Draft Assistant | 516 | 694 | 693 | 714 |
| Draft Lab | 460 | 634 | 633 | 632 |
| Saved Draft Library | 391 | 529 | 528 | 528 |
| Lineup & Trades | 458 | 540 | 564 | 564 |
| Valuation | 369 | 497 | 520 | 520 |

On phones the draft pages still carry the compact brand banner U1 kept on draft pages, so their
answers land lower than the analytics pages'.

## Performance

Interleaved A/B on one machine:
- **Before:** `4bc3d30` (U2/U3) on :8556. **After:** this branch, U4 plus the WEB-PREP1
  extraction, on :8555.
- Both on a copy of the same workspace, with the order alternating.
- Measured to idle (identity selector), at 1280, 2 measured rounds after a warm-up.

The regression suites were running at the same time, so every load is slow (35–66 s) and
differences under ~5 s are noise.

| Page | Before | After | Δ |
|---|---|---|---|
| Draft Room Simulator | 39.5 | 38.1 | −1.5 |
| Draft Assistant | 38.1 | 45.2 | +7.1 (see below) |
| Draft Lab | 38.9 | 36.2 | −2.7 |
| Saved Draft Library | 38.9 | 36.0 | −2.9 |
| Lineup & Trades | 66.4 | 60.1 | −6.3 |
| Valuation | 41.8 | 37.8 | −4.1 |
| Historical Explorer (extraction) | 58.0 | 52.2 | −5.8 |
| Leaderboards (extraction) | 36.2 | 39.4 | +3.1 |
| Career Totals | 49.8 | 47.9 | −1.9 |

Draft Assistant was checked with py-spy:
- During a full Draft Assistant load, 0 of 869 app-script samples (one sample every 20 ms) fell
  inside `_render_u4_draft_assistant_answer`.
- The new answer reads values the page already computed and costs less than one sample. The
  difference is machine load, not U4.
- The new draft answers reuse the page's own computations (`derive_draft_progress` on the board,
  the already-ranked recommendations, the simulation's own tables, the archive list). No pool is
  rebuilt and nothing is re-scored.

## Capability checklist (U4 pages)

**Draft Room Simulator**
- [x] Import (upload, validation review, apply, clear) works the same. It sits in an expander above
  the tabs and opens on its own during a review.
- [x] Board, Undo, Reset, delete Live Draft Room draft, queue, "Set player on pick", Save Draft
  Board Now, pick log export, roster views, post-draft grades and league setup: same keys, same
  places.

**Draft Assistant**
- [x] Settings, research badge, status, pick adjustment, team needs, sort, recommendation cards,
  table, insight, scarcity and heatmap: unchanged under Explore more.

**Draft Lab**
- [x] Run, settings (same keys and callbacks), model explainer, consistency check, result tabs
  (board, rosters, team analysis with score details, best/questionable picks, exports), handoff
  from Live Draft: unchanged. The five-metric row is replaced by the answer.

**Saved Draft Library**
- [x] Invites, commissioner invite panel, active-draft tools, Clear Active, team claim, sync,
  persistence diagnostics, every card's Set Active / Rename / Delete: unchanged.

**Lineup**
- [x] Board, drag and drop, Save, Reset, Use Suggested Lineup, locked-week dashboards, finalize,
  commissioner panel: unchanged.
- [x] Position-specific waiver buttons: kept.

**Trade Center**
- [x] Builder keys, Find / Analyze / Propose / Clear / Reset, idea actions (Use / Analyze /
  Propose), verdict card, Detailed calculation, Offers & Activity, commissioner trade: unchanged.

**Valuation**
- [x] Selectbox key `valuation_selected_player`, profile card, insight summaries, table,
  contextual transfer: unchanged.

## AMI reconciliation notes (U4)

Checked read-only against `feature/ami-foundation @ 4705b51` (its registry has 166 control labels).
AMI files were not edited.

1. **Three control labels changed case.** "Set lineup", "Check waivers" and "Explore trades" are
   now "Set Lineup", "Check Waivers", "Explore Trades", the same labels the Lineup page uses (U4.5).
   Update the matching entries in `ami_assistant/page_help.py`; its label-check tests are
   case-sensitive. Every other registered label still exists.
2. **Help prose still uses old page names:** "Comparison Tool", "Fantasy Lineup Assistant" /
   "Lineup Assistant", "Standings Tracker", "Fantasy Sleepers & Busts". The visible names are
   Compare Players, Lineup & Trades, League Standings, Sleepers & Busts. Page keys are unchanged,
   so routing still works. Rendering names through `nav_groups.NAV_LABELS` would keep help in step
   automatically.
3. **New controls AMI may want to describe:**
   - Draft Player, Import Draft, Save Draft, Open Saved Drafts (Draft Room);
   - Open Draft Board (Draft Assistant);
   - Simulation settings and Run 4-Team Draft Simulation under the answer (Draft Lab);
   - ⭐ Set Active / Rename on the most recent draft (Library);
   - Show top player (Valuation).
4. **Shared answer functions.** `u4_answers` (draft pages) and the `focus` parameter of
   `u2_answers.valuation_answer` are pure. AMI can reuse them so both surfaces describe drafts and
   valuations the same way.
5. **Quick Guide text.** U4 did not change `PAGE_GUIDES`. The U2/U3 note about carrying the guide
   text into AMI's `page_guides.py` still applies.
