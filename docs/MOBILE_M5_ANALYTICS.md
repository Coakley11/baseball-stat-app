# Baseball Mobile M5 — Analytics, charts, leaderboards, projections, wide tables

Base: M4 checkpoint `d771cdb` on `mobile/m1-foundation`. Widths: 360 / 390 / 430
(phone) and 1280 (desktop reference). Presentation only: no statistical
calculation, projection, ranking, sorting/filtering semantics, player identity,
fantasy scoring, persistence, account/workspace ownership, Live Draft, M2
navigation, M3 Live Draft layout or M4 Fantasy workflow logic changed.

## 1. Surfaces audited

Historical Explorer, Career Totals, Leaderboards, Comparison Tool, Trend Value,
Fantasy Sleepers & Busts, Valuation, ML Predictions, and the Waiver player pool
table deferred from M4. For each: wide-table identity-column behavior, chart
widths/heights and legibility, filter-row density, vertical gaps, and page
overflow.

**What the foundation already handled (verified, not changed):** `st.pyplot()`
on this Streamlit version defaults to `width="stretch"`, so matplotlib charts
already never overflow the page. The two Altair/Vega-Lite scatterplots
(`st.altair_chart(..., width="stretch")`) are vector and already crisp at any
width. `st.dataframe` scrolls horizontally *inside itself* already (M1's
`max-width: 100%` keeps it off the page). The app's custom HTML leaderboard bar
chart and player comparison cards (`player_photos.py`) already use CSS Grid
`auto-fit`/`minmax()`, so they already reflow to one column on phones with no
CSS changes needed. None of this needed M5 work; the real gaps were identity
columns disappearing on wide-table scroll, matplotlib text legibility, and
filter-row density.

## 2. Wide-table strategy

Generalized M4's Fantasy-only column-pinning helper into a shared module,
**`mobile_table_layout.py`** (`leading_identity_columns`,
`pinned_identity_column_config`, `GENERAL_IDENTITY_COLUMNS`).
`fantasy_mobile_layout.py` now re-exports from it unchanged, so M4's API and
tests are unaffected. `render_output_table`'s existing `pin_columns=` opt-in
now imports from the generic module.

Rule (unchanged from M4): only a **contiguous leading run** of identity columns
is pinned — pinning never promotes a column that isn't already first. A column
sitting after a non-identity column (e.g. "Team" after "Bats") is left alone
rather than reordered.

| Table | Pinned |
|---|---|
| Historical Explorer | Year, Player |
| Career Totals | Player |
| Leaderboards | Player |
| Comparison — Year-by-Year | Year, Player |
| Comparison — Career Totals | Player |
| Trend Value — Top Breakouts / Biggest Declines | Player, Position |
| Trend Value — single-player snapshot | Player |
| Fantasy Sleepers & Busts — curve/market sleepers/busts (3 tables) | Player, Team, Primary Position |
| Valuation | Player, Position |
| ML Predictions | Player, Position, Team |
| Waiver available-player pool (`fantasy_waiver_wire_ui.py`, inline) | leading run of whatever's first among Player/MLB Team/Team/Primary Position/Position |

**Deliberately left unpinned:** `comparison_significance_tests`,
`comparison_advanced_trend_intelligence`, `trend_advanced_intelligence` —
`Player` is not their leading column (a `Stat`/metric dict is built first,
`Player` added later), and pinning would either no-op or require reordering,
which the brief rules out. `ml_accuracy`, `ml_feature_importance`,
`ml_age_curve` — 2–3 columns total, not wide enough to need it.

**Verified in the browser (390px, scroll right then screenshot):**
- **Historical Explorer** — Year/Player pinned confirmed: before scroll shows
  Year, Player, Bats, Primary Position, Team; after scrolling right the same
  10 rows (2022 Aaron Judge, 2025 Cal Raleigh, …) still show Year and Player on
  the left while BA/OBP/SLG/OPS are now visible.
- **ML Predictions — pinning does not hold.** Scrolling even a single small
  step loses Player and Position (Team briefly survives one step, then also
  goes). This table has ~24 columns, versus 9 (curve-adjusted sleepers, which
  *does* pin 3 columns correctly) or 17 (Historical Explorer). The wiring is
  identical to the tables that work (same `pinned_identity_column_config`,
  same `st.dataframe(..., column_config=...)` call shape) — this looks like a
  practical limit of Streamlit's `glide-data-grid` on very wide tables, not a
  bug in this code. Documented honestly rather than claimed as fixed; see §6.

## 3. Charts

**Matplotlib** (`st.pyplot`, 4 call sites: Comparison Tool trends, Trend
Value's main chart, Trend Value's single-player multi-stat dashboard, and a
dead-code fallback in `top_bar_chart`): wrapped in a new
**`mobile_chart_layout.legible_matplotlib_chart()`** context manager — a
`matplotlib.rc_context` bump to title/label/tick/legend font sizes plus
`figure.autolayout` (tight layout, so the larger title doesn't clip). This is
a deliberate, bounded trade, not a true fix: a static raster image can't be
crisp at every render width without knowing the client's viewport, and this
app has never had a client-width signal (M1–M4 stayed CSS/media-query only for
the same reason). Desktop keeps the same figure, just modestly more legible
text.

**Altair/Vega-Lite** (2 scatterplots): already `width="stretch"` — vector,
crisp at any size — left untouched. Fixed `height=520`/`540` makes them tall
and narrow on a phone; not changed, since reducing it needs a client-width
signal this app doesn't have (same constraint as the matplotlib charts).

**HTML bar chart / profile cards** (`player_photos.py`): already CSS-Grid
responsive (`auto-fit`, `minmax(240px, 1fr)`); confirmed unchanged, no M5 work
needed.

## 4. Filter-row compaction

21 filter rows across 8 pages wrapped with M1's `mobile_wrap_row` — the
established pattern: wrap the *existing* `st.columns(...)` call in a keyed
container; subsequent `with cN:` blocks are untouched. Desktop is unaffected
(the wrapper is CSS-hidden above 640px, same as M3/M4). Rows that are already
2-up-friendly go to 2 columns per row on phones instead of stacking 3–5 deep;
confirmed in the browser for Historical Explorer (Year Range / Sort by / Order
→ 2 rows instead of 3) and Fantasy Sleepers & Busts (Projection Window /
Format / Min Games / Min AB → clean 2×2 grid).

Rows deliberately **not** wrapped: pure `st.metric()` rows (already 2-up via
M1's generic `_METRIC_ROW` CSS — wrapping again would double-apply it) and the
side-by-side Sleepers/Busts table columns (`c8, c9`), which must stay
full-width-stacked on phones, not forced 2-up, since each holds a wide table.

## 5. Results

0 horizontal overflow, 0 offending elements, 0 exceptions at 360/390/430/1280
across all 9 surfaces (36 width/page combinations measured). Desktop 1280
structure unchanged — every wrapped filter row renders as a single row on
desktop, verified directly (e.g. Historical Explorer's Year Range / Sort by /
Order stay one row at 1280, exactly as before M5).

## 6. Product issues found (pre-existing; not fixed, per scope discipline)

### 6.1 ML Predictions table: pinned columns don't hold under scroll

See §2. Not caused by M5 — the pinning *mechanism* works (proven on 4 other
tables up to 9–17 columns wide); this table's ~24 columns appear to exceed
some practical limit. Left wired (harmless no-op) rather than removed, in case
a future Streamlit release handles it. Worth a follow-up with Streamlit's
`glide-data-grid` component directly if this surface gets more mobile work.

### 6.2 Explicit deep link does not reliably win over a workspace's stale saved page

Observed while building test scripts for this slice, reproduced from a clean
room with Streamlit's own `AppTest` (bypasses the live server, so this isn't a
test-concurrency or memory-pressure artifact):

```python
at = AppTest.from_file("streamlit_app.py")
at.query_params["active_page"] = "Historical Explorer"
at.query_params["suite_workspace"] = "<a workspace whose last saved page is something else>"
at.run()
# at.session_state["_qp_active_page_nav_target"] == "Historical Explorer"   (correct)
# at.session_state["_qp_active_page_nav_consumed"] == True                 (correct)
# at.session_state["active_page"]                  == "<the stale saved page>"   (WRONG)
```

The deep-link handler in `streamlit_app.py` correctly identifies and flags the
target. M2's own unit test (`test_explicit_deep_link_beats_stale_owned_page`)
confirms `apply_baseball_disk_state` honors an *already-set* `active_page`
correctly — but that test pre-seeds `active_page`/`main_sidebar_page` as
already equal to the deep-link target before calling the function, so it
doesn't exercise the earlier step (`_consume_scheduled_navigation()`, called
before restore) that's supposed to actually set them from the flagged target
in the first place. That earlier step is the likely gap; not confirmed further
since it's outside M5's scope (session/persistence plumbing).

**Workaround used for this slice's own verification:** reach pages via the M2
quick-nav selectbox within an already-loaded session (the real interaction a
phone user relies on) rather than a fresh-session deep link to a workspace
with different stale state. This is also what §5's screenshots and the
pin-scroll proofs in §2 used.

**Not an M5 regression**: M5 touches no navigation, session, or workspace
code. Flagged here per the brief's "isolate and report" instruction, not
fixed.

### 6.3 A page switch via quick-nav is not reflected in the browser URL

A hard refresh after navigating with quick-nav returns to the app's default
landing content, not the page last viewed. Confirmed this is simply how the
app is built (page switches are server-side `session_state`, not client-side
routing) — not a new bug, just worth recording since the brief asks about
refresh/persistence behavior.

## 7. Tests

- **New:** `mobile_table_layout.py`, `mobile_chart_layout.py`, each with a
  dedicated test file (`tests/test_mobile_table_layout.py`,
  `tests/test_mobile_chart_layout.py`), plus
  `tests/test_mobile_analytics_layout.py` — wiring/contract tests for every
  pin-column call site, every matplotlib wrap, and every filter-row wrap
  (presence, exact placement, and that metric-only/side-by-side-table rows are
  correctly *not* wrapped).
- **M1–M5 mobile suite:** 104 tests, all passing (includes the M1/M2/M3/M4
  mobile tests run together with the new M5 ones — no regressions among them).
- **Regression set:** 37 files (Leaderboards/Historical/Career/Comparison/
  Trend/Valuation/ML/projection/chart/waiver state + every M1–M5 mobile test),
  run on M5 (384 test cases) and on the M4 checkpoint `d771cdb` from a
  temporary detached worktree (351 test cases). **Identical failure set on
  both: the same 7 pre-existing failures**, all in `test_fantasy_waiver_wire.py`
  (6 tests: deferred activation, waiver-move-pair matching, roster sync, filter
  persistence) and `test_sleepers_ami_send.py` (1 test: bust routing). None of
  these touch any file this slice changed. The 33 extra M5 test cases are the
  new presentation tests. **M5 introduces no regressions.**

## 8. Deferred (M6/M7)

- ML Predictions wide-table pinning (§6.1) — needs either a narrower default
  column set on phones or a `glide-data-grid` version bump.
- The two fixed-height Altair scatterplots' tall/narrow aspect on phones —
  needs a client-width signal this app doesn't have.
- Deeper Leaderboards/ML Predictions tuning-expander filter rows (sliders
  nested in "Advanced" sections) — wrapped at the top level (§4) but not
  audited column-by-column for slider-specific touch-target sizing.
- §6.2/§6.3 — pre-existing navigation/persistence behavior, not M5 scope.
- Final accessibility pass, broader player-explorer/account refactors: M6/M7+.
