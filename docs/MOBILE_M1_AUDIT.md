# Baseball Mobile M1 — Audit + Responsive Foundation

Baseline: `dev @ cafe437` · Branch: `mobile/m1-foundation` · Streamlit 1.59.1
Widths checked: 360 / 390 / 430 (phone) and 1280 (desktop reference).

## Method

- Local app (no secrets, local storage), navigated **via the sidebar radio** (the
  `?active_page=` deep link is overridden by "Loaded your last session" restore).
- Per page × width: document + `stMain` horizontal overflow, overflow-origin elements
  (overflowing while parent does not, outside any intended scroller), actionable
  touch targets < 40px (Streamlit buttons, radio/checkbox rows, selects), metric-row
  layout, sticky/fixed elements, `stException` count, plus a 390×2600 capture.
- Foundation CSS parse check: browser-accepted rule count vs. source (39/39).

## Headline results

| Check | Before (cafe437) | After (M1) |
|---|---|---|
| Whole-page horizontal overflow, 16 pages × 4 widths | 0 | 0 |
| Runtime exceptions | 0 | 0 |
| Actionable controls < 40px tall on phones (Leaderboards) | 1 | **0 on every page** |
| Sidebar page-radio row height (phone) | 22px | 40px |
| Metric rows on phones (Leaderboards 3 metrics) | 3 lines | 2 lines (2-up) |
| Hero banner height / title size at 390px | 268px / 36px | 159px / 26px |
| First filter control, px from top of page at 390px | 812 | 645 |
| Desktop 1280: hero / first control position | 133px / 543px | 133px / 543px (unchanged) |

(Positions measured without the transient "Loaded your last session" banner, which
adds ~72px on some loads in both builds.)

Streamlit already contains most overflow (dataframes scroll inside the grid; columns
stack at ≤ 640px). The real phone problems are **density, ordering and touch size**,
not page-level overflow.

## Breakpoint convention

Aligned with Streamlit's own theme (`sm 576`, `columns 640`, `md 768`):

- `PHONE_MAX_PX = 640` — Streamlit stacks `st.columns` here; phone-only rules.
- `TABLET_MAX_PX = 768` — existing app "compact" convention.
- `SMALL_PHONE_MAX_PX = 400`.

Use `mobile_foundation.media_phone()` / `media_tablet()` in feature CSS.

## Foundation delivered (M1)

`mobile_foundation.py`, appended to the base page `<style>` markdown in
`streamlit_app.py` (same `st.markdown` call — a separate call adds an empty element
and a 16px block gap on every page):

1. **Overflow at the source**: media `max-width: 100%`; markdown tables/`pre` scroll
   inside themselves; `st.table`, charts and dataframes capped at container width;
   `overflow-wrap: break-word` in markdown. No clipping, nothing hidden.
2. **Columns ≥ 641px** get `min-width: 0` so wide-screen columns shrink instead of
   overflowing (the old `[data-testid="column"]` rule in `portfolio_polish.py` never
   matched Streamlit 1.59's `stColumn` and was removed). Phone stacking untouched.
3. **Compact chrome/typography ≤ 768px**: hero, section cards, Quick Guide, fantasy
   source card, headings (`clamp()`), 0.75rem gutters.
4. **Touch targets ≤ 640px**: buttons ≥ 44px; radio/checkbox rows ≥ 40px (this is
   what fixes the sidebar page list).
5. **Inputs at 16px ≤ 640px** so iOS Safari does not zoom on focus.
6. **Dialogs/popovers** limited to viewport width/height; tab strips scroll.
7. **Metric-only rows 2-up on phones**; values wrap instead of ellipsis.
8. **Opt-in helpers** for later slices: `mobile_inline_row` (keep a short column row
   side-by-side), `mobile_wrap_row` (button/control group → 2-up tiles),
   `mobile_scroll_x` (wrap raw HTML tables/boards in an in-card scroller).

## Findings by workflow

### Global chrome / navigation — **M2**
- First phone screen is almost all chrome: hero + "Start Tutorial" CTA + page intro
  card + Quick Guide ≈ 600px before any control (M1 reduced the hero; the order and
  what shows by default is an M2 decision — e.g. collapse Quick Guide / tutorial CTA
  on phones after first visit).
- Page nav lives only in the collapsed sidebar; the page list starts ~280–375px down
  (varies with sidebar state) below Build/Login/Portfolio toggles; 16 flat items, no
  grouping. M2: mobile nav
  (grouped pages, current-page title in header, fewer toggles above the list).
- Sidebar also carries Baseball Insight + Live Draft queue; long scroll (≈2000px).
- `?active_page=` deep links are overridden by session restore (affects shared links
  on phones as well as tooling).

### Historical Explorer / Career Totals / Leaderboards / Valuation — **M5**
- Filters stack cleanly (full-width selects, sliders) — fine.
- Wide dataframes scroll inside the grid; first column (Player) scrolls away — M5:
  pinned name column / phone column subsets.
- Range sliders' thumbs are small touch targets (Streamlit internals).
- "Use these filters in another tool…" transfer row is fine.

### Trend Value / ML Predictions / Fantasy Sleepers & Busts — **M5**
- Tables with coloured delta cells lose context horizontally (only ~2 stat columns
  visible at 390px).
- Many charts per page (Trend Value: 15); none overflow, but axis labels/legends at
  360px need a per-chart pass.

### Comparison Tool — **M5**
- Empty state only in this environment; three-player tables/charts need a data run.

### Draft Room Simulator / Draft Assistant Simulator / Draft Lab — **M6**
- Draft Assistant's Draft status metrics now 2-up (M1); long scroll of settings before
  recommendations; recommendation tables wide.
- File uploader dropzone OK.

### Live Draft Room — **M3**
Setup and Ready surfaces audited in the browser; in-progress layout audited from
code (see "Environment limits").
- **Content order (highest impact):** Solo in-progress deliberately paints full
  recommendation cards *first* (`streamlit_app.py` "Solo first-viewport landing"),
  then Control Center, then `st.columns([1.45, 1.0])` → board/queue column, then the
  rec column which holds the **On-the-Clock banner + timer**. On phones the columns
  stack, so the order becomes recs → controls → entire queue/board → clock. The clock
  and "who's picking" must come first on phones, recs must not dominate the top.
  DOM order cannot be fixed safely with CSS; needs a phone-specific arrangement.
- Setup: Roster Settings = 9 number inputs stacked full-width (~1,300px); team rename
  inputs likewise. Candidate for `mobile_wrap_row` (2-up) in M3.
- Setup validation error ("picks per team must be ≥ required positions") appears
  below the fold next to Start New Live Draft only after the tap.
- `.live-draft-controls` is `position: sticky; top: 0`; Streamlit's header is a 60px
  absolute bar — verify the sticky bar is not hidden under it on phones.
- Action button rows (`live-draft-action-row`, Control Center 2-col grids, chat
  `[4, 1]` input/send rows) stack one-per-line; use `mobile_inline_row` /
  `mobile_wrap_row`.
- Stale selector: `live_draft_navigation.py` quick-tile CSS targets
  `div[data-testid="column"]` (never matches in 1.59).
- Rec-card detail cells use `min-width: 160px` flex cells — fine at 360px but tight.

### Saved Draft Library — **M4/M6**
- Library list OK at phone widths; action icons are small.

### Fantasy Standings / Lineup Assistant / Waiver Wire / Trades — **M4**
- Gated behind "No fantasy context" without a saved active draft/league, so their real
  surfaces (standings tables, lineup board, add/drop planner, trade builder) were not
  exercisable here. Lineup already has phone CSS and a mobile DnD runbook
  (`docs/FANTASY_LINEUP_MOBILE_DND_RUNBOOK.md`); trade center has a 768px block.
- The three "go to" buttons in the no-context card stack full width — fine.

### Multiplayer / shared draft — **M3**
- Shared room lobby (room code, join, Refresh Lobby, Cancel) not exercised (needs two
  identities + storage); room-code styles already have a 768px rule.

## Verification

- `tests/test_mobile_foundation.py`: 14 passed (CSS contract: breakpoints, no stale
  `column` test id, phone-scoped touch/zoom rules, no content hiding, no nested
  `:has()`, metric-row rule, helpers, app wiring).
- Full suite on the M1 branch: 4242 passed / 273 failed / 11 collection errors — all
  pre-existing on `cafe437` (same collection errors; failing set re-run on a pristine
  `cafe437` worktree; the remainder are order- or disk-state-dependent, e.g.
  `test_workflow_persist_guard.py` is 8 failed / 39 passed on both clean trees).
- Browser: all 39 foundation rules accepted by Chromium (parse check), 16 pages ×
  360/390/430/1280 with no overflow or exceptions.

## Environment limits (this pass)

- The in-progress Solo draft could not be reached locally from committed `cafe437`:
  the Ready lobby ("Preparing your draft — Loading rankings and player projections…")
  kept Start Draft disabled for 7+ minutes on both baseline and M1 builds. The Ready
  lobby itself fits phones well (0 overflow, full-width Start Draft). In-progress
  findings above come from code; M3 must start with a live capture at 360/390/430.
- `?active_page=` deep links are overridden by session restore, so tooling must
  navigate via the sidebar.
- Fantasy in-season pages need a saved active draft/league fixture.

## Slice plan (adjustable)

- **M2 navigation/header** — phone nav, page title, chrome collapse, deep-link restore.
- **M3 Live Draft Room** — phone order (clock → my pick → board/queue → recs), setup
  grid, sticky controls, action rows, multiplayer lobby.
- **M4 roster/team/transactions** — standings, lineup, waiver, trades with fixtures.
- **M5 analytics/charts/tables** — pinned columns / phone column sets, chart sizing.
- **M6 remaining workflows** — simulators, Draft Lab, Saved Draft Library.
- **M7 stabilization** — real-device pass (iOS Safari / Android Chrome), regression
  harness in CI.
