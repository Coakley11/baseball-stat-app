# Baseball Mobile M7 — stabilization, accessibility, navigation, integration readiness

Base: M6 checkpoint `041e8b1` on `mobile/m1-foundation`. Widths: 360 / 390 / 430
(phone) and 1280 (desktop reference). Final mobile stabilization slice: one real
navigation bug fixed, accessibility measured and documented, full-app browser
matrix run, and a read-only integration-readiness analysis against the separate
newer Live Draft work in the main worktree.

No product features added. No Live Draft, Fantasy transaction, scoring,
projection, persistence or workspace-ownership logic changed.

---

## 1. Deep-link precedence bug — root cause and fix

### Symptom (reported in M5)

`?active_page=...` on a fresh session could lose to the workspace's stale saved
page. M5 reproduced it but did not isolate it; M2's explicit-navigation
precedence mechanism (`EXPLICIT_PAGE_NAV_KEY`) existed and its own unit tests
passed, so the gap was somewhere else.

### Root cause (found in M7)

Not in M2's precedence mechanism at all — **upstream of it**, in
`_consume_scheduled_navigation()` (`streamlit_app.py`):

```python
current = get_sidebar_page_value(st.session_state.get("active_page"))
if target == current:
    return None          # drop the schedule as a redundant "same-page" nav
```

`get_sidebar_page_value()` coerces anything it doesn't recognise — including an
**unset** `active_page` — to `PAGE_OPTIONS[0]`. On a fresh session `active_page`
is unset, so `current` was fabricated as the default page. A genuine deep link
to the default page therefore looked identical to a redundant same-page
schedule: it was dropped, `active_page` / `main_sidebar_page` were never set,
and the workspace restore further down then applied its stale saved page.

This is why the symptom was so confusing: deep links to **any other page worked
fine**. Confirmed by direct comparison before the fix, same stale saved page
(`ML Predictions`) in both cases:

| Deep link target | Result before fix |
|---|---|
| `Historical Explorer` (= `PAGE_OPTIONS[0]`) | ❌ landed on `ML Predictions` |
| `Leaderboards` (any other page) | ✅ landed on `Leaderboards` |

### Fix

Require `active_page` to actually be set before the same-page guard can fire:

```python
_current_raw = str(st.session_state.get("active_page") or "").strip()
current = get_sidebar_page_value(_current_raw)
if _current_raw and target == current:
    ...
```

Deliberately narrow — the guard itself is still wanted (it stops sticky
same-page schedules from older restore paths skipping sidebar align), so it is
kept, just no longer able to fire against a fabricated "current" page. No
persistent navigation state was redesigned; nothing else in the restore chain
changed.

### Coverage

`tests/test_deep_link_precedence_m7.py` — 11 fast unit tests driving the real
function with a fake `st`:

| Scenario | Expected | Test |
|---|---|---|
| fresh session + deep link to default page | deep link wins | `test_fresh_session_deep_link_to_default_page_is_applied` |
| fresh session + deep link to any other page | deep link wins | `test_fresh_session_deep_link_to_non_default_page_is_applied` |
| stale saved page + deep link | deep link wins, restore told to skip | `test_stale_saved_page_in_session_does_not_block_the_deep_link` |
| already on target page | schedule still ignored (guard intact) | `test_same_page_schedule_is_still_ignored_when_already_on_that_page` |
| no deep link | nothing consumed, restore stays the fallback | `test_no_schedule_leaves_state_untouched` |
| ordinary sidebar / quick-nav click | unchanged | `test_ordinary_in_app_navigation_still_consumed` |
| invalid page value | safe coercion to default, no raise | `test_invalid_schedule_value_falls_back_to_default_page` |
| re-entry after consumption | popped once, no re-fire (no oscillation) | `test_schedule_is_consumed_once_and_not_resurrected` |

`tests/test_deep_link_precedence_m7_e2e.py` — 4 end-to-end `AppTest` runs
against a controlled on-disk workspace whose saved page conflicts with the deep
link, covering the same precedence plus invalid-value safety.

**Verified against the M6 baseline**: the unit regression test and the e2e
default-page test both **fail on `041e8b1`** and pass on M7 — they pin the
actual bug, not just current behavior.

---

## 2. Accessibility / DOM-order reconciliation

### What M3 actually does

M3 reorders Live Draft blocks on phones with CSS `order` tiers inside a scope
that only matches when the Manual Draft hook is present:

```
_PAGE = '[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"]:has([class*="st-key-ldr-m-action"])'
```

CSS `order` changes visual order only; DOM order (and therefore keyboard and
screen-reader order) is untouched. So divergence is possible **only where that
scope matches**.

### Measured

Instrumented probe walking the page's flex column, recording document order and
visual (top-sorted) order for the same blocks, counting pairwise inversions:

| Live Draft state (390px) | blocks | blocks with a CSS tier | DOM↔visual inversions |
|---|---|---|---|
| Setup | 3 | 0 | 0 |
| Ready | 3 | 0 | 0 |
| **Active Solo, on the clock (Mode A)** | **10** | **0** | **0** |
| Completed draft summary | 29 | 0 | 0 |

In every state reachable in this environment, **no block carried a CSS order
tier at all** — the `_PAGE` scope never matched, because Solo Mode A renders
Quick Queue without a Manual Draft panel (committed behavior M3 documented). So
in these states visual order and DOM order are identical and there is **no
accessibility divergence**.

### Mode B (full view) — determined analytically, not measured

The full view with the Manual Draft panel could not be reached in this
environment within a reasonable attempt budget, so its divergence is derived
from the source rather than observed, and is reported as such. Source (DOM)
order of the tiered hooks vs their assigned tiers:

| Hook (source order) | `streamlit_app.py` | CSS tier |
|---|---|---|
| `ldr-m-recs-early` | L27304 | `ORDER_REC_COLUMN` = −50 |
| `ldr-m-action-early` | L27362 | `ORDER_ACTION` = −90 |
| `ldr-m-controls` | L27777 | `ORDER_CONTROLS` = −85 |
| `ldr-m-recs` | L28582 | −50 (−10 with tables) |
| `ldr-m-action` | L29007 | −90 |

Both action hooks sit **after** their recommendation counterpart in DOM but are
pulled **before** it visually. So in Mode B:

> **The Manual Draft panel — the primary action — is shown first visually but
> reached late in keyboard / screen-reader order**, after the recommendation
> widgets (and in the late path, after the board/recommendation area).

### What was fixed

- **A real `<nav>` landmark for the phone page switcher** (`mobile_nav_m2.py`).
  The app exposed **zero** `<nav>` landmarks (measured: `nav_landmarks: 0` on
  every page), so a screen-reader user had no landmark to jump to for
  navigation. The quick-nav current-page element is now
  `<nav class="m-quick-nav-current" aria-label="Current page">` with the
  decorative 📍 marked `aria-hidden`. Same class, so M2 styling and layout are
  byte-identical; `<nav>` is a CommonMark block tag exactly like `<div>`, so
  parsing is unchanged. The "Jump to page" select keeps its accessible name
  (label is visually collapsed, not removed). Covered by
  `test_quick_nav_exposes_a_navigation_landmark`.

### What remains architectural (not fixed)

- **Mode B focus order.** The only two ways to fix it are (a) reordering the
  Python, which M3 established breaks Streamlit fragment identity and would
  break draft timers/reruns, or (b) an in-page skip anchor — which would have to
  be added in `streamlit_app.py` L27042–27186, **the exact region the main
  worktree is currently rewriting** (§8). Adding it now would manufacture a merge
  conflict for no user-visible gain today. Deferred to post-reconciliation.
- **Focus order inside stacked columns.** Measured on the active draft: tab order
  runs `y=762 → 800 → 648 → 708`, i.e. it jumps back up the page. This is
  Streamlit's own behavior — a `st.columns` row is a row in DOM, stacks
  vertically on phones, and focus follows DOM. It is not caused by M3's CSS and
  affects any Streamlit app using columns on a narrow screen.
- **No `<main>` landmark, no `h1`/`h2`.** Measured: `main_landmarks: 0`,
  `h1: 0`, `h2: 0`, headings start at `h3` (the app's `###` markdown). Streamlit
  owns the document skeleton; the heading levels are an app-wide content
  decision, not a mobile-layout one.
- **No `aria-live` region for the draft clock.** Measured `aria_live: 0`. The
  clock and on-the-clock team change without announcement. The banner markup
  lives in `live_draft_on_clock_ui.py` — one of the main worktree's 13 dirty
  files (§8) — so changing it now would create a conflict where none exists.
- **Unlabeled focusable iframes** (2 on the Live Draft page) and a small number
  of unlabeled controls (1–6 per page). These are Streamlit-generated elements;
  CSS cannot set `tabindex`/`aria-*` on them.

The full accessibility remediation remains out of scope for this slice by the
brief's own instruction, and is not claimed as done.

---

## 3. Full-app browser matrix

**All 16 pages × 4 widths (360 / 390 / 430 / 1280) = 64 page-width
combinations.** Driven by `scratchpad/m7/m7_matrix.py` (14 pages via the M2
quick-nav in one session) plus `m7_matrix2.py` (the remaining 2 via deep link,
see "driver limitation" below). At each page/width the probe measured:
horizontal overflow, CSS-leaked-as-visible-text, over-wide tables, Streamlit
exception elements, quick-nav label correctness, `<nav>` landmark presence,
dialog/popover fit, fixed/sticky overlays, visible button count and content
height. Screenshots captured at 390 and 1280.

### Result

**Zero problems across all 64 combinations.** Every page/width reported:

| Measure | Result everywhere |
|---|---|
| Horizontal page overflow (`scrollWidth − clientWidth`) | **0 px** |
| CSS leaked as visible text | **0** (none of the 6 M3-failure-mode markers) |
| Tables wider than the viewport | **0** |
| Streamlit exception elements | **0** |
| Fixed/sticky overlays covering content | **0** |
| Over-wide dialogs/popovers | **0** |
| Quick-nav current-page label | correct on **every** page |
| `<nav>` landmark present (§2) | **true** on every page/width |

Per-page content height confirms the phone layouts behave as intended — phone
widths are consistently taller than 1280 (vertical stacking), with the largest
reflow on the dense pages: Fantasy Sleepers & Busts 6130 → 4709 px, Draft
Assistant Simulator 6517 → 4677 px, Trend Value 4829 → 3847 px. Visible button
counts are within ±2 between 360 and 1280 on every page, i.e. **no page hides
actions on phones**.

Pages covered: Historical Explorer, Career Totals, Leaderboards, Comparison
Tool, Trend Value, Valuation, ML Predictions, Fantasy Sleepers & Busts, Draft
Room Simulator, Draft Assistant Simulator, Draft Lab / Simulation, Saved Draft
Library, Live Draft Room, Fantasy Standings Tracker, Fantasy Lineup Assistant,
Waiver Wire / Add-Drop Center.

### Driver limitation (honest note)

Pass 1 covered 14 pages in a single browser session and then the **test driver**
failed on the last two: `Locator.click: Timeout 20000ms exceeded` waiting for
the quick-nav selectbox, after the Fantasy Standings Tracker page. This was a
driver/session timeout — a slow rerun on the preceding page leaving the
selectbox unhittable — **not a defect on those pages**, and not a failure the
checks themselves reported.

Rather than treat that as coverage, pass 2 re-ran those two pages with a fresh
page load per page, navigating by `?active_page=` deep link instead of driving
the selectbox. Both measured clean — Fantasy Lineup Assistant (5741 px at 390)
and Waiver Wire / Add-Drop Center (8315 px at 390). That path also doubles as
independent confirmation of the §1 deep-link fix working in a real browser: both
pages landed on the requested page, with the correct quick-nav label.

Waiver Wire's 8315 px phone height is the **longest page in the app** and is the
M6-correction limitation showing up as a measurement: the phone list is long
because the show-more shortening was reverted to preserve desktop behavior
(§6 / M6 correction). It is long, not broken — no overflow, no clipped actions.

---

## 4. M1–M6 regression verification

Verified against the brief's per-slice checklist. Nothing in M7 touched M1–M6
CSS, wrappers or table/chart helpers: M7's entire diff vs `041e8b1` is **76
insertions / 14 deletions across 3 files** (`streamlit_app.py` +13−2 in one
hunk, `mobile_nav_m2.py` +8−1, `tests/test_mobile_nav_m2.py` +69−11), plus two
new test files and this document.

| Slice | What was re-verified | Result |
|---|---|---|
| **M1** foundation | 16px inputs (no iOS zoom), tap targets, alert padding, empty-iframe collapse rule still present and phone-gated | ✅ unchanged; M1 CSS file untouched by M7 |
| **M2** navigation | quick-nav renders on every page, correct current-page label, grouped options, routes through `MAIN_SIDEBAR_PAGE_KEY`; hero subtitle still hidden on phones only | ✅ label correct on **all 16** pages (§3); M7 only changed the label element's tag `div`→`nav`, same class |
| **M3** Live Draft | order tiers, clock hoisting, duplicate-suppression hooks, swipe strip, `_PAGE` scope intact | ✅ source contracts unchanged; measured 0 DOM↔visual inversions in all reachable states (§2) |
| **M4** Fantasy | roster/standings/waiver/add-drop/trades layouts, fixture seeds via production paths | ✅ Fantasy Standings, Fantasy Lineup Assistant, Waiver Wire all clean at 4 widths (§3) |
| **M5** analytics | wide-table pinning (13 wirings), legible charts, Leaderboards, Historical Explorer, projections | ✅ 0 over-wide tables and 0 overflow on every analytics page at 360/390/430 (§3) |
| **M6** cleanup | Fantasy header density, ML dual-width table, Rankings `type="compact"`, empty-iframe gaps, gated MP diagnostics, **Waiver desktop behavior restored** | ✅ ML Predictions clean at all widths; Waiver list length matches M5 (desktop unchanged) |

The one M6 item the user rejected — the Waiver show-more that reduced desktop
from 15 to 5 cards — stays reverted. `fantasy_waiver_wire_ui.py` is byte-identical
to M5's `17128af` except for the removed duplicate `st.caption`, and the M6 tests
pin that (M5-identical) behavior.

---

## 5. Real-device vs emulation coverage

**All browser verification in M1–M7 was Chromium desktop emulation** (Playwright,
`--disable-gpu`, viewport resizing). **No real phone or tablet was used at any
point.** Nothing in this project should be read as real-device verified.

Emulation does not faithfully represent, and these remain unverified on hardware:

- momentum/touch scrolling inside horizontally scrolling tables and the M3
  recommendation swipe strip (`scroll-snap-type: x mandatory`)
- the lineup drag-and-drop board under touch (long-press, drag threshold,
  scroll-vs-drag disambiguation)
- native select/`combobox` behavior on iOS Safari and Android Chrome, including
  the 16px-font zoom guard M1 added
- `100dvh` dialog sizing against mobile browser chrome that grows/shrinks on
  scroll
- sticky/frozen grid columns under touch-drag in `glide-data-grid`
- hardware keyboard focus and VoiceOver/TalkBack announcement order

Recommended first real-device pass: iOS Safari and Android Chrome at 390px on
Live Draft (active), Waiver Wire, and ML Predictions — the three surfaces most
dependent on touch scrolling, frozen columns and swipe.

---

## 6. Live Draft presentation items — deliberately not changed

Reviewed the M3/M6 deferred presentation list. **None were changed**, for one
consistent reason: each lives in a file or region the main worktree is actively
rewriting, so touching it now would manufacture merge conflicts (§8) for no
user-visible gain.

| Deferred item | Lives in | Why not now |
|---|---|---|
| Multiplayer banner fixed 210px height | `live_draft_on_clock_ui.py` | one of main's 13 dirty files |
| Rankings placement / default state | `streamlit_app.py` L27042–28452 | inside main's rewrite region; M6 already applied the one safe change (`type="compact"`) |
| Early Solo-view ordering | `streamlit_app.py` L27042–27186 | main is restructuring this exact early-paint path |
| Empty embedded-frame gaps | — | already fixed in M6 (phone-only CSS rule) |
| Remaining duplicate status text | mixed | re-examined and **not** duplicates: "You are managing X" (your team) and "On clock: X" (whose turn) differ in multiplayer. M3 already hid the genuine duplicates (`ldr-m-dup-summary`, `ldr-m-dup-room-header`) on phones |

---

## 7. Test determinism audit

- **Runtime-data independence.** 9 of the 10 M1–M7 mobile test files
  (`test_mobile_foundation`, `_nav_m2`, `_table_layout`, `_chart_layout`,
  `_analytics_layout`, `_m6_cleanup`, `test_fantasy_mobile_layout`,
  `test_live_draft_mobile_layout`, `test_deep_link_precedence_m7`) are pure
  source/CSS-contract tests with no `data/` access at all. The tenth
  (`test_deep_link_precedence_m7_e2e.py`) needs a workspace file: it backs the
  path up in `setUpClass`, rewrites known state in **every** `setUp`, and
  restores in `tearDownClass`. Verified deterministic by running it twice in a
  row against a dirty leftover autosave — same results both times. (The app's
  own autosave can re-create that file after teardown; that is production
  behavior, and it cannot affect the tests because every scenario rewrites the
  state it depends on.)
- **Order dependence removed.** `test_mobile_nav_m2.py::PageGroupCoverageTests`
  was the M1–M6 suite's only order-dependent mobile failure: three tests did
  `import streamlit_app` purely to read `PAGE_OPTIONS`, which executes the whole
  app script and fails in a bare pytest process once an earlier test has touched
  Streamlit session state. They now read `PAGE_OPTIONS` statically with `ast`,
  testing the same contract deterministically and much faster. A new guard test
  (`test_page_options_source_read_matches_the_imported_module`) fails loudly if
  `PAGE_OPTIONS` ever stops being a module-level literal, so the static read
  can't silently drift.
- **Legacy suite**: not repaired (out of scope). Results in §10.

---

## 8. Integration-readiness analysis (read-only; main worktree untouched)

Analysis only — nothing in `C:/Users/danie/Documents/GitHub/baseball-stat-app`
was read-write touched, no merge or cherry-pick performed.

### Overlap

Main's uncommitted Live Draft work: 13 tracked modifications on `dev @ cafe437`,
plus untracked new source. Mobile branch: 33 files changed vs `cafe437`.

**Exactly one file is modified by both: `streamlit_app.py`.** Every other main
dirty file (`live_draft_expired_pick.py`, `live_draft_on_clock_ui.py`,
`live_draft_pick_commit.py`, `live_draft_ready_contract.py`,
`live_draft_rec_live_paint.py`, `live_draft_setup_mode.py`,
`live_draft_setup_ui.py`, `live_draft_solo_expire_chain.py`,
`live_draft_solo_heartbeat.py`, `live_draft_ui_cache.py`,
`tests/test_live_draft_core_interactions.py`) is **untouched by mobile**. The
mobile branch's only Live Draft file is a new one (`live_draft_mobile_layout.py`)
that main does not know about, so it cannot conflict.

### `streamlit_app.py` conflict surface — quantified

Main: **17 hunks** spanning L9861–28447. Mobile: **69 hunks** spanning
L813–31148 (68 at M6 + the one M7 fix). Most of mobile's hunks fall inside
main's overall span, but hunk-level overlap (within git's 3-line merge context)
is only **4 pairs**:

| # | Main's change | Mobile's change | Risk |
|---|---|---|---|
| 1 | L25366: `accept_short_timer` query-param gate for timer choices | M3's `mobile_wrap_row("ldr-league-settings")` around `lc1, lc2, lc3 = st.columns(3)` | **Low** — adjacent lines, no semantic interaction |
| 2 | L27042–27186: early Solo paint restructured; "Manual Draft" moved earlier, `_sp_mark()` instrumentation added, `##### Recommended Players` / `_defer_heavy_recs_for_timer` branch reworked | M3's `ldr-m-recs-early` / `ldr-m-action-early` hook containers | **High** — main rewrites the exact structure M3's hooks wrap |
| 3 | L27214–27223: `_sp_mark` + new "never st.stop()" client-timer block | same early-paint hook region | **High** — same region as #2 |
| 4 | L28447: new `live-draft-recommendation-rankings` anchor div immediately above the Rankings expander | M6's `type="compact"` on that same `st.expander(...)` line | **Low but certain** — direct line conflict; resolution is to keep both |

The M7 deep-link fix itself is at L13812 — ~4,000 lines from main's nearest
hunk, so it adds **no** merge risk.

### Mobile assumptions newer Live Draft logic may invalidate

1. **The new Solo clock component breaks M3's clock handling outright.** The
   highest-value finding in this analysis, and it is confirmed, not speculative.

   Main has an untracked `solo_live_clock_component/` declaring a **path-based**
   component:
   ```python
   _COMPONENT = components.declare_component("solo_live_clock", path=str(_FRONTEND_DIR))
   ```
   `live_draft_on_clock_ui.py` — one of main's 13 dirty files — already imports
   and *prefers* it, returning early so it replaces the old card:
   ```python
   if component_frontend_ready():
       render_solo_live_clock(st, session, live_room, slot_view, ...)
       _mark_on_clock_done()
       return
   ```
   `component_frontend_ready()` is only
   `(_FRONTEND_DIR / "index.html").is_file()`, and that file exists as a real
   13,292-byte build — **so this path is live in main today**, not staged for
   later.

   Main's Solo on-the-clock now has three paths, which M3 handles very
   differently:

   | Path | Rendering | M3 clock CSS |
   |---|---|---|
   | 1. `render_solo_live_clock` (**preferred**) | declared component → `<iframe title="solo_live_clock" src="/component/…">` | ❌ **nothing matches** |
   | 2. `st.html` card (legacy fallback) | inline, **not** iframed, `class="live-draft-on-clock"` | ✅ fully, incl. inner layout |
   | 3. `components.html` (Shared/multiplayer, unchanged) | iframe with `srcdoc` | ✅ ordering via `_CLOCK_IFRAME` |

   M3's rules are:
   ```
   _CLOCK_IFRAME = 'iframe[srcdoc*="live-draft-on-clock"]'
   {_PAGE} > *:has(.live-draft-on-clock)      { order: ORDER_CLOCK; }   /* -95 */
   {_REC_ITEMS}:has(.live-draft-on-clock),
   {_REC_ITEMS}:has({_CLOCK_IFRAME})          { order: ORDER_CLOCK; }
   ```
   Path 1 matches **neither** branch: the iframe uses `src=`, not `srcdoc`, and
   `.live-draft-on-clock` now lives in a separate document app CSS cannot reach.
   After a naive merge the Solo clock silently loses both its top-of-page
   position and all of M3's phone layout — no error, just a mis-ordered,
   unstyled clock.

   The ordering fix is small and already scoped — one more branch:
   ```
   {_PAGE} > *:has(iframe[title="solo_live_clock"]),
   {_REC_ITEMS}:has(iframe[title="solo_live_clock"]) { order: ORDER_CLOCK; }
   ```
   The *inner* phone layout (rules on `.ld-title` / `.ld-team-name` /
   `.ld-pick-pills` / `.live-draft-timer`) is **not** fixable from the app at
   all — it is cross-document. Those styles have to move into
   `solo_live_clock_component/frontend/index.html`, which is main's file. A
   genuine unavoidable follow-up, not something M7 can pre-empt.

   One upside: path 2 uses `st.html`, which Streamlit 1.59 renders **inline
   rather than iframed**, so M3's inner layout rules start applying to the
   fallback card where they could never reach the old `srcdoc` banner.

   **Checked and safe:** M6's rule 8 (collapse zero-height iframe carriers) does
   *not* endanger the new component. `render_solo_live_clock` passes no explicit
   height and the frontend sizes itself with `Streamlit.setFrameHeight()`, so the
   iframe genuinely *is* 0px tall for the first paint. But Streamlit 1.59 gives
   declared components `data-testid="stCustomComponentV1"`, a different testid
   from `stIFrame` (both confirmed present in the installed Streamlit bundle),
   and M6's rule is scoped exclusively to `stIFrame`:
   ```
   [data-testid="stElementContainer"]:has(> [data-testid="stIFrame"] > iframe[height="0"])
   ```
   So the clock cannot be collapsed. **This is a reason not to broaden that rule
   to all iframes during reconciliation** — doing so would hide the Solo clock
   on every first paint, intermittently and invisibly.
2. **M3's hook containers must survive the early-paint rewrite.** Overlaps #2/#3
   restructure the code the `ldr-m-recs-early` / `ldr-m-action-early` hooks wrap.
   If the hooks are dropped during conflict resolution, the entire `_PAGE` scope
   (`:has(.st-key-ldr-m-action)`) stops matching and **all** M3 phone ordering
   silently disappears.
3. **Semantic coupling M6 created.** M6 removed the `live-draft-setup-anchor`
   caption from `streamlit_app.py`; main's dirty
   `scripts/local_tb_realtime_analytics_accept.py` still greps for that string
   (L127, L301). Verified both OR-chains also match on `"Draft Setup"`, which the
   heading still provides — so it works today, but anything that tightens that
   script to require the anchor would break.
4. **`#solo-deploy-build` gap-collapse rule.** M3's gap rule keys off that id,
   emitted by `live_draft_solo_expire_chain.py` — one of main's dirty files. If
   the marker moves, the rule silently no-ops (cosmetic only).
5. **`type="compact"` + the new Rankings anchor** (overlap #4) must both survive.

### Recommended reconciliation order

1. **Land main's Live Draft work first**, on its own, to a committed state. It is
   the more volatile line, it is uncommitted, and it is mid-rewrite of exactly
   the region in question.
2. **Then rebase/replay the mobile branch onto it slice by slice**, not
   wholesale. M1, M2, M5 and most of M6 are nearly disjoint from main's work and
   should replay cleanly. M3 is the slice that genuinely interacts.
3. **Resolve the 4 overlaps in this order**: #4 and #1 first (mechanical — keep
   both sides), then #2/#3 together, re-attaching M3's hooks to whatever the new
   early-paint structure is.
4. **Re-verify before accepting**: the M3 clock rule against the new clock
   implementation (assumption 1), the `_PAGE` scope still matching (assumption
   2), then re-run the M1–M7 mobile suite and a 390/1280 Live Draft pass.

### Wholesale or slice-by-slice?

**Slice-by-slice.** A wholesale merge would resolve `streamlit_app.py` in one
large conflict spanning main's rewritten early-paint path, and the failure mode
for M3 is *silent* (CSS selectors that stop matching produce no error — just the
old, wrong phone order). Replaying per slice keeps each conflict small enough to
verify against that slice's own tests, and the M1–M7 mobile tests include
wiring/contract assertions (hook names, selector text, order tiers) that will
catch a dropped hook immediately rather than at review time.

---

## 9. Product bugs deliberately left out of scope

Carried forward unchanged from M4–M6, none of which block M7 acceptance:
Edit Lineup Format does nothing; stale Waiver drop list after refresh; Live
Draft leagues can lose "my team" without sign-in; bench/capacity without a saved
lineup format; trade to an unowned team after a warning; default Live Draft
picks-per-team below the required roster positions; multiplayer clock
disappearance; Solo timer restarting on refresh; Quick Queue/manual-draft
product behavior.

---

## 10. Tests and results

### New in M7

| File | Tests | Result |
|---|---|---|
| `tests/test_deep_link_precedence_m7.py` | 11 | all pass (2 fail on M6 baseline) |
| `tests/test_deep_link_precedence_m7_e2e.py` | 4 | all pass (1 fails on M6 baseline) |
| `tests/test_mobile_nav_m2.py` (extended) | 17 | all pass; +`test_quick_nav_exposes_a_navigation_landmark`, +`test_page_options_source_read_matches_the_imported_module`, 3 rewritten to be order-independent |

### Regression run

A 61-file regression list covering every area M1–M7 touched plus the app's
navigation, workspace, fantasy, draft and projection suites, run on M7 and again
on the accepted M6 checkpoint `041e8b1` in a throwaway worktree, with the two
M7 test files copied in so the comparison includes them.

| | Tests | Failures | Errors | Time |
|---|---|---|---|---|
| **M7** | 587 | 20 | 0 | 619 s |
| **M6 baseline `041e8b1`** | 585 | 23 | 0 | 793 s |

Failure-set diff (by test id, not just count):

| | Count |
|---|---|
| Shared — pre-existing, unchanged by M7 | **20** |
| **New on M7 (regressions)** | **0** |
| Red on baseline, green on M7 | **3** |

The 3 that flipped green are precisely the tests written to pin the §1 bug:

```
- test_deep_link_precedence_m7::test_fresh_session_deep_link_to_default_page_is_applied
      AssertionError: None != 'Historical Explorer'
- test_deep_link_precedence_m7::test_same_page_guard_requires_a_set_active_page
      AssertionError: '_current_raw' not found in 'def _consume_scheduled_navigation(): ...'
- test_deep_link_precedence_m7_e2e::test_deep_link_to_default_page_beats_stale_saved_page
      AssertionError: 'ML Predictions' != 'Historical Explorer'
```

The e2e message is the reported symptom verbatim: the deep link asked for
Historical Explorer and the workspace's stale saved page (ML Predictions) won.

The 587 vs 585 test-count difference is the two tests M7 added to
`test_mobile_nav_m2.py` (585 + 2 = 587). The 619 s vs 793 s difference is the
determinism fix in §7: replacing three `import streamlit_app` calls with a
static `ast` read removed three full app-script executions.

**All 20 M7 failures are pre-existing legacy-suite failures, not M7
regressions** — established two ways:

1. **Empirically**, by the failure-set diff above: the 20 failing test ids on M7
   are a strict subset of the 23 on `041e8b1`, and the set difference in the
   regression direction is empty.
2. **Structurally.** M7's only product change is one edit inside
   `streamlit_app._consume_scheduled_navigation()`. None of the failing modules
   import `streamlit_app` at all (`grep -c streamlit_app` = **0** for
   `test_draft_lab_resume.py`, `test_draft_lab_handoff_pending.py`,
   `test_live_draft_workspace_isolation.py`,
   `test_coakley11_workspace_ownership_e2e.py`), and none reference
   `_consume_scheduled_navigation`. They exercise separate modules
   (`draft_lab_resume`, `suite_resume_launch`, workspace ownership) with their
   own query-param fakes.

The failure signatures are all independent pre-existing drift:

| Signature | Count | Cause |
|---|---|---|
| `'_FakeSt' object has no attribute 'query_params'` | 3 | test stub predates the app's `st.query_params` adoption |
| `'Draft Simulation Test Mode' != 'Draft Lab / Simulation'` | 1 | `DRAFT_LAB_PAGE_LEGACY` vs `DRAFT_LAB_PAGE` rename drift |
| `None != 'Draft Lab / Simulation'` | 3 | same rename drift, via `draft_lab_resume` |
| `build_submit_context() got an unexpected keyword argument 'question'` | 1 | AMI send API drift |
| Waiver roster/pairs assertions | 4 | pre-existing waiver fixture expectations |
| Draft-assistant "why" column assertions | 2 | pre-existing |
| Draft Lab handoff widget-key assertions | 2 | pre-existing |
| Workspace-ownership source-text assertions | 2 | pre-existing |
| Deferred-activation / filter-persistence | 2 | pre-existing |

Note the one navigation-adjacent name, `test_suite_page_query_schedules_draft_lab_not_historical`,
was checked specifically because it describes the same *family* of bug M7 fixed
("don't fall back to Historical Explorer"). It lives in `draft_lab_resume`, a
different code path, and fails identically on the M6 baseline — M7's fix is
scoped to `_consume_scheduled_navigation()` and deliberately does not reach it.

**Zero failures in any mobile test file.** All 10 mobile/M7 test files
(`test_mobile_foundation`, `_nav_m2`, `_table_layout`, `_chart_layout`,
`_analytics_layout`, `_m6_cleanup`, `test_fantasy_mobile_layout`,
`test_live_draft_mobile_layout`, `test_deep_link_precedence_m7`,
`test_deep_link_precedence_m7_e2e`) pass on M7.

The legacy suite was **not** repaired — out of scope for a mobile slice, and
repairing it would mean editing product-behavior expectations this project is
not authorized to change.
