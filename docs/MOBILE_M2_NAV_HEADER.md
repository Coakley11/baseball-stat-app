# Baseball Mobile M2 — Navigation + Header

Base: M1 checkpoint `8b8c615` on `mobile/m1-foundation`. Widths checked: 360 /
390 / 430 (phone) and 1280 (desktop reference). Scope: navigation, header/intro
compaction, and the deep-link/session-restore precedence bug M1 flagged.
No product logic changed (draft/recommendation/roster/scoring/analytics/
account/multiplayer all untouched — see "Files changed" below).

## 1. Deep-link vs. session-restore precedence — root cause and fix

**Bug** (M1 finding): `?active_page=Live%20Draft%20Room` could silently land on
a different page than requested.

**Root cause**, traced and reproduced directly against `apply_baseball_disk_state`
(`baseball_persistent_state.py`): consuming *any* scheduled navigation —
an explicit deep link exactly like an ordinary sidebar click — sets
`_suite_page_user_nav = True` for the rest of that rerun. Workspace restore
then treats `_suite_page_user_nav` as license to promote a **stale**
`_suite_user_owned_page` (wherever the user was on a *previous*, unrelated
in-session navigation) to `preferred_page`, the single highest-priority
"page to restore" signal — with no check that it actually agrees with the
just-consumed deep link. The deep link is quietly discarded.

Reproduced in isolation (see `tests/test_baseball_nav_restore.py::
test_explicit_deep_link_beats_stale_owned_page` — this test fails against the
pre-fix code path and passes after):

```
active_page after consuming deep link "Live Draft Room": Live Draft Room  (correct so far)
_suite_user_owned_page (stale, from an earlier in-session nav): Fantasy Standings Tracker
apply_baseball_disk_state(...) -> active_page = "Fantasy Standings Tracker"   # BUG
```

**Fix**: a single, explicit, single-rerun-scoped signal —
`baseball_persistent_state.EXPLICIT_PAGE_NAV_KEY` — set by the deep-link
handler in `streamlit_app.py` right where it already sets `_navigate_to_page`
/ `_skip_page_restore_for`, and read-and-cleared (`ss.pop(...)`) at the very
top of the SAME `preferred_page` precedence chain restore already uses,
outranking `auth_preserve_page` and `owned_page`. It:

- **Wins over stale owned_page/blob restore** — the bug above, closed.
- **Never lingers**: popped on read; guarded by an equality check against
  `active_page` so a copy left over from a rerun where restore was skipped
  entirely (`warm_skip`) is ignored once the page has since moved on.
- **Does not touch** `_navigate_to_page`, `_skip_page_restore_for`, draft-lab
  resume, HOF-case resume, or the `_suite_nav_consumed_target` cross-check —
  all existing precedence paths are untouched and still run exactly as before
  for ordinary sidebar navigation (no deep link this rerun → the new key is
  simply absent → 100% pre-M2 behavior, unit-tested explicitly).
- **Invalid/unknown `?active_page=` values**: unchanged, pre-existing
  behavior — `get_sidebar_page_value` already coerces anything not in
  `PAGE_OPTIONS` to the default page (`Historical Explorer`) before the deep
  link is even accepted; verified with a regression test rather than changed.

### Expected-behavior checklist (from the M2 brief)

| Requirement | Status |
|---|---|
| Explicit valid deep link opens the requested page | Fixed + tested |
| Session restore used when no explicit nav request | Unit-tested unaffected (`test_normal_restore_unaffected_without_explicit_nav`) |
| Ordinary in-app navigation persists correctly | Untouched code path; existing `test_baseball_nav_restore.py` cases still pass |
| Refresh does not randomly jump to another page | A true refresh starts a fresh session (`_suite_user_owned_page` unset) → unaffected; same-session "refresh" with a lingering stale key is exactly the bug this closes |
| Invalid/unknown page values fail safely to the existing default | Confirmed unchanged (`DeepLinkPageValueNormalizationTests`) |

## 2. Mobile quick-nav (current page + jump) — `mobile_nav_m2.py`

New, additive, CSS-gated so **desktop is byte-for-byte unaffected**
(confirmed live — see §4): a compact block at the very top of the main
content column, rendered from inside `render_global_app_chrome` (before the
hero, and *before* the Live Draft "suppress hero" branch, so it's still
present when the hero itself is hidden mid-draft):

- **Current page, unambiguous**: `📍 <page label>`, e.g. "📍 🔎 Historical
  Explorer" — solves M1's "redundant page title/context" finding: the hero
  is generic ("Daniel Cohen Baseball Explorer") on every page, so this is the
  first thing that actually names the page.
- **One jump selectbox**, grouped so scanning is fast without adding a second
  interaction step:
  - Explore & Analyze — Historical Explorer, Career Totals, Leaderboards,
    Comparison Tool, Trend Value, Valuation, ML Predictions, Fantasy Sleepers
    & Busts
  - Draft Tools — Draft Room Simulator, Draft Assistant Simulator, Draft Lab
    / Simulation, Saved Draft Library
  - Live Draft — Live Draft Room
  - Fantasy Team — Fantasy Standings Tracker, Fantasy Lineup Assistant,
    Waiver Wire / Add-Drop Center
  - Every `PAGE_OPTIONS` entry is covered by a test that pulls the *live*
    list from `streamlit_app`, so a future page that forgets to register a
    group fails CI immediately instead of silently vanishing from mobile nav.
- **No parallel navigation state**: picking an option writes
  `MAIN_SIDEBAR_PAGE_KEY` then calls the *exact same* `_on_sidebar_page_change`
  callback the real sidebar radio uses — identical side effects (ownership
  claim, `_navigate_to_page` clear, nav-trace logging), nothing for
  `baseball_persistent_state`'s restore logic to reconcile that it doesn't
  already handle for a sidebar click.
- **Kept in sync every rerun**: the selectbox's own session-state key is
  reset to the resolved `active_page` before the widget mounts each run —
  without this, navigating via the sidebar or a deep link would leave the
  quick-nav selectbox showing a stale prior page (Streamlit widgets prefer
  `session_state[key]` over `index=` once set).
- Hidden above the phone breakpoint (`max-width: 640px`, aligned with M1's
  `mobile_foundation.PHONE_MAX_PX`); reachable at **top ≈ 139px** on a 390px
  phone (measured live — see §4), well above the sidebar's page list, which
  M1 found starting 280–375px down a *collapsed* sidebar the user must first
  open.

## 3. Header/intro compaction

- **Hero subtitle hidden on phones only** (`mobile_header_compaction_css`):
  the generic marketing subtitle ("Explore MLB history, compare players...")
  is redundant with both the new current-page label above it and each page's
  own title card below it. Desktop keeps it exactly as before (CSS scoped
  to the phone media query only, verified by a test that the selector never
  appears outside that block).
- **Quick Guide card is now a native `<details>`/`<summary>` disclosure**
  (`page_quick_guide.py`, the single shared helper every page already calls —
  zero call-site changes): collapsed by default on phones (tap the header to
  expand — "▸" rotates to "▾"), forced back to always-visible on desktop via
  a CSS override of the browser's native collapse behavior
  (`details > *:not(summary) { display: block !important }` above the phone
  breakpoint) so desktop presentation is pixel-identical to before M2. This
  alone removes 125–195px (M1's measured Quick Guide height) from the first
  phone viewport on every page, by default, without deleting any content —
  it stays one tap away.
- Tutorial bar ("Start Tutorial") was left as-is: already a compact single
  row (M1 already tightened its spacing); not touched in M2.

## 4. Live browser verification

The dev machine is memory-constrained and shared with the user's own
concurrent work (their own Streamlit servers, a running pytest process, and
an editor using several GB); the local Streamlit server for this app crashed
or became unresponsive under Playwright load several times during this pass
(also documented as a recurring limitation in the M1 report). Where a full
scripted multi-step Playwright run wasn't reliably reproducible, a lighter,
single-shot DOM probe against a freshly booted server **was** captured
successfully and is the evidence below (screenshots retained):

**Confirmed live, phone (390×844), Historical Explorer:**
- Quick-nav container present, visible, **top = 139px**.
- Current-page label: `📍 🔎 Historical Explorer`.
- Selectbox's real DOM value: `"Explore & Analyze · 🔎 Historical Explorer"`
  — group prefix and page label both render correctly.
- Quick Guide `<details open=False>` — collapsed by default.
- Tapping the Quick Guide summary → `open=True` (native disclosure works).
- Hero subtitle: `display: none`.

**Confirmed live, desktop (1280×900), same page:**
- Quick-nav container: `display: none` (fully hidden, not just visually
  empty).
- Hero subtitle: visible, unchanged text.
- Quick Guide content: visible despite `<details>` having no `open`
  attribute (the desktop CSS override works).
- A "Return to Live Draft Lobby" sidebar card from an earlier test in the
  same warm session persisted correctly across the page switch — incidental
  confirmation that quick-nav page changes don't disturb unrelated session
  state (draft room state, in this case).

**Not captured live** (server became unresponsive before this specific
step): the click-through interaction of picking a different page *from* the
quick-nav selectbox and observing the resulting rerun. This exact code path
— the `on_change` callback writing `MAIN_SIDEBAR_PAGE_KEY` and invoking
`_on_sidebar_page_change` — is covered by `tests/test_mobile_nav_m2.py::
RenderMobileQuickNavTests` (routes through the identical callback the real
sidebar radio uses; no-ops on reselecting the current page; syncs on every
rerun). Recommend a follow-up interactive pass once the shared machine has
more headroom, before this ships.

### Acceptance criteria from the M2 brief

| # | Requirement | Result |
|---|---|---|
| 1 | Current page obvious on phones | Confirmed live: `📍 🔎 Historical Explorer` label, top of page |
| 2 | Navigation reachable near the top | Confirmed live: quick-nav top ≈ 139px (vs. 280–375px for the old sidebar list, and that required opening the sidebar first) |
| 3 | All page destinations remain accessible | Unit-tested: every live `PAGE_OPTIONS` entry present in the grouped list; sidebar radio (all 16 pages) untouched |
| 4 | Touch targets remain usable | Selectbox given a 2.5rem min-height on phones (M2 CSS); M1's button/radio touch rules untouched |
| 5 | Quick Guide/tutorial content | Quick Guide now collapses on phones (was always-expanded, 125–195px); tutorial bar unchanged |

## Files changed

- `baseball_persistent_state.py` — `EXPLICIT_PAGE_NAV_KEY` + precedence fix
  (+26/-2 lines; no other restore behavior touched).
- `streamlit_app.py` — deep-link handler sets the new key (+7 lines); quick-nav
  call added at the top of `render_global_app_chrome` (+13 lines).
- `page_quick_guide.py` — `<details>`/`<summary>` markup + collapse CSS in the
  one shared helper; **zero changes to any call site**.
- `mobile_nav_m2.py` (new) — quick-nav render + grouping + CSS.
- `tests/test_baseball_nav_restore.py` — +6 tests (deep-link precedence bug
  repro/fix, stale-key guard, invalid-value fail-safe).
- `tests/test_mobile_nav_m2.py` (new) — 13 tests (grouping/coverage,
  render/sync/callback-routing, CSS scoping, app-wiring).
- `tests/test_page_guide_markup.py` — updated for the new `<details>` markup
  (was pinned to a `<div>`-only contract); +1 test for the collapse/desktop
  CSS.

Untouched: draft state, recommendation logic, roster/team behavior, analytics
calculations, player data, scoring, account/workspace ownership, multiplayer
behavior, and every existing sidebar-radio / `_navigate_to_page` /
`_suite_nav_consumed_target` code path for ordinary (non-deep-link)
navigation.
