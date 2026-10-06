# Baseball release candidate — integration record

Local release candidate on `integration/baseball-release-candidate`, built from
`dev @ 5ba62dd`. Nothing here was pushed, and `dev` was not moved.

Written for: whoever approves moving `dev`, and whoever integrates the next slice.

## 1. Sources and method

| line | checkpoint | how it entered |
|---|---|---|
| stabilized core | `5ba62dd` | branch base |
| presentation + Mobile M1–M7 | `c3da981` | fast-forward (it descends directly from `5ba62dd`) |
| monetization M1–M3 | `588f5c2` (`a72e032` → `9bdada7` → `588f5c2`) | merge commit `e372e55` |

The M3 merge was textually clean — the only shared file, `streamlit_app.py`,
took M3's four hunks without conflict — but a clean merge still left one
combined-tree regression, fixed in the merge commit:

- **Pricing had no phone quick-nav group.** M3 adds `"Pricing & Upgrade"` to
  `PAGE_OPTIONS`; Mobile M2 keeps its own `PAGE_GROUPS`. M2's safety net appended
  the unmapped page ungrouped (still reachable, but without a heading) and
  `PageGroupCoverageTests` failed. Pricing now sits in an `Account` group, last
  in `GROUP_ORDER`, and got the `💳 Pricing & Upgrade` sidebar label it lacked.

Checked and left alone: the gate rewrites `active_page` to a sentinel, but the
phone quick-nav renders long before that point, so phones label the page the
user actually requested.

## 2. Defects found during acceptance

Both are **pre-existing in monetization M3** — reproduced identically on a clean
checkout of `588f5c2` — and were invisible to M3's isolated AppTest fixture.
They are fixed on this branch only; Codex's branch is untouched.

1. **Both paywall buttons were dead** (`573341c`). `schedule_page()` wrote the
   sidebar radio's widget key `main_sidebar_page` from a button in the main area,
   after the radio was instantiated → `StreamlitAPIException`, before
   `st.rerun()`. M3's fixture keys its radio `test_page`, so it never saw this.
   `schedule_page()` now writes only `_navigate_to_page`, matching the app's own
   `navigate_to_page()`.
2. **"Back to Historical Explorer" was silently dropped** (`3f015c1`), masked
   until (1) was fixed. `begin_page_run()` writes the gate sentinel into
   `session["active_page"]`; the same-page guard in
   `_consume_scheduled_navigation()` coerced that unknown value to
   `PAGE_OPTIONS[0]` — "Historical Explorer" — and discarded the request as a
   redundant schedule. The guard now counts only a real page (raw membership,
   since `normalize_page_key()` coerces unknown values too). Strictly narrower;
   M7's deep-link rule is unchanged, and `begin_page_run()` is not touched.

`tests/test_monetization_gate_real_app_nav.py` drives the **real**
`streamlit_app.py` through both buttons (~2 min); nothing smaller reproduces
either bug. `tests/test_monetization_gate_navigation.py` reproduces (1) under the
real widget order and fails on unfixed M3 with the exact production exception.

## 3. Logo

- `static/brand/dcbe_logo_512.png` (brand master) and `dcbe_logo_128.png`
  (display, 25 KB) — web-optimized from the supplied 1254×1254 / 1.6 MB asset.
  Served through the existing `enableStaticServing`, so it is fetched once and
  browser-cached.
- **Hero title** (full and compact draft-page variants): the logo replaces the
  old `⚾` emoji rather than sitting beside it. Sized in `em`, so one rule scales
  with the title: 54px at 1280, 38–41px at 360–430, aspect 1.00, no overflow.
  Decorative beside visible text, so `alt=""` and `aria-hidden`.
- **Sidebar**: compact mark via `st.logo`. Its collapsed-sidebar copy in the
  header bar is hidden — phones start collapsed, which stacked a second logo
  directly above the hero. Only these two placements exist (pinned by
  `tests/test_brand_logo.py`).

## 4. Account & Workspace

A UI consolidation only. Authentication, workspace resolution and ownership
rules are unchanged; the control calls the same functions as before.

| state | before | now |
|---|---|---|
| header | "Login" (auth off or signed out) / "Account & Workspace · Name" | "Account & Workspace", always |
| sign-in disabled | header "Login", nothing to log into | "Local workspace — sign-in isn't available on this deploy" |
| signed out | auth panel, no status | "**Not signed in**", local workspace vs Real Account explained, existing email/password panel |
| signed in | identity, **two Log out buttons** | identity, workspace, Command Center, Saved Sessions, **one** Log out |
| active workspace | never shown | shown in every state |

- The duplicate came from a trailing `render_auth_panel()` call described as
  "password/session management"; signed in, that panel renders only its own Log
  out. Password tabs exist only in its signed-out branch, which still runs.
- Whether Shared Draft rooms are described as requiring sign-in follows
  `shared_room_requires_auth()`, so the copy can't claim more than the product
  enforces.
- **Plan status is not shown here, deliberately.** Resolving it calls
  `resolve_trusted_entitlement()`, a live Supabase read once billing is on, and
  the sidebar renders before the page gate computes its snapshot. Billing
  authority stays with Supabase `auth.users.id` in the accepted entitlement
  layer; the Pricing page shows the plan.
- **Portfolio Screenshot / Demo Mode** render only in Developer Mode. When
  hidden, both mode keys are cleared: capture mode skips background persistence,
  so a user left in it with no toggle would silently stop saving.
- The Developer Mode "Auth & workspace" diagnostic (authenticated, email,
  workspace, owner user id, save-block reason) already existed, gated, and is
  unchanged. The **Build** caption stays: `run_staged_cloud_verification.py`
  reads it to confirm the deployed SHA.

## 5. Acceptance results

**Browser matrix — 17 pages × 360/390/430/1280**, including Pricing and both
gated pages: zero horizontal overflow, CSS-as-text, wide tables, runtime
exceptions, clipped actions or chart overflow; no sub-16px phone inputs; every
phone nav label correct. The only flag is a 26×26 unlabeled `<summary>` on
Fantasy Sleepers & Busts — present on `c3da981` too, and above the 24px
WCAG 2.5.8 minimum.

**Free/Pro on the integrated app — 390 and 1280, all green, 0 server tracebacks**:
ML Predictions and Draft Lab gated with their bodies never initialized; "page
context preserved" shown; no false loading state for anonymous users; Pricing
deep link; gate → Pricing; gate → Historical Explorer; Live Draft free; no
sentinel or dev plan control visible; phone nav names the requested page.

**Pro simulation** cannot be exercised in a local browser by design: it needs
both server opt-ins *and* Developer Mode, which requires a verified admin email
from an authenticated session (fail-safe against forged ids and query params).
It is verified through M3's permitted test path,
`tests/test_baseball_monetization_apptest.py` (Free gate, Pro across refresh and
navigation, Live Draft free) — passing on this tree.

**Solo Live Draft** (corrected harness, uncontended, own fresh server): 5/5
starts; Setup → active median 10.17s, worst 15.49s, best 9.53s — inside the
existing thresholds (median < 20s, worst < 35s) and faster than the accepted
`c3da981` run (median 12.54s). Prewarm present at height 0 with no clock text
during Ready in every attempt; the real clock iframe appears 0.01–0.07s after
the draft becomes active. An earlier run concurrent with the 132-file test
union had one 144s cold-attempt failure; uncontended, the cold attempt succeeds
in 15.49s, so that was CPU contention. Interaction checks match `c3da981`.

**Multiplayer** (two browsers, host 8511 / guest 8512), on authoritative state:
room created, guest joined and routed (member, team "Team B"), both participants
persisted, refresh before Start keeps the lobby, Start → disk `in_progress`,
699-row shared pool on disk, per-account queues isolated. The harness then stops
at PICKS: both browsers still paint "Waiting to Start" / paused after Start, so
Draft clicks land on a stale surface and the board stays at 0. **Identical on a
`c3da981` control** (same verdict, add counts, board 0, paint). It is the known
pre-existing host-repaint latency, not an integration change.

**Account & Workspace — 360/390/430/1280**: one header, no clipping, no
overflow, no undersized controls, no Portfolio toggles.

## 6. Test classification

Union of 132 files (focused Live Draft, mobile/nav/deep-link, monetization M1–M3,
account/auth/workspace, logo). Two vendored suite test files fail to *collect* on
`5ba62dd` as well (`test_auth_page_preserve.py`: missing
`AUTH_PAGE_PRESERVE_KEY`; `test_suite_workspace.py`: needs the Music app's
`music_resume_payload`) and were excluded.

Every failure was re-run on the source checkpoint that owns its file:

- **49 pre-existing.** All fail on `c3da981`. 39 are in the accepted 44-failure
  `5ba62dd` focused baseline; the other 10 (mostly auth/workspace tests outside
  the focused set, never measured before) fail on `5ba62dd` too.
- **23 test-isolation artifacts, pre-existing.** All share one cause:
  `suite_activity_client._load_storage_module()` inserts the sibling
  `daniel-ai-command-center` repo at `sys.path[0]` to import `suite_storage`, so
  any shared-suite module imported afterwards resolves from the Command Center
  (`ImportError: BASEBALL_INSIGHT_SECTION_TITLE`). The trigger is
  `test_active_live_draft_mode_precedence.py` running before M7's deep-link tests
  in one process — the first time this union put those groups together.
  Reproduced identically on a fresh `c3da981` checkout; all 23 pass on this tree
  in their own process.
- **0 genuine regressions.**

## 7. Known limitations carried forward

- The `sys.path` hazard above: running the whole suite in one process gives
  misleading failures until `suite_activity_client` stops inserting at index 0.
  Shared suite module; not changed here.
- Pre-existing shared render/rerun latency on the host browser after Start
  (presentation only; authoritative state correct).
- Per-paint diagnostic disk I/O across ~15 Live Draft modules.
- Streamlit's own sub-32px chrome on phones (help icons, dataframe toolbar,
  multiselect chips); no `h1` on any page.
- The gate sentinel still lives in `session["active_page"]` by M3's design; the
  navigation guard now tolerates it, and any other reader that coerces
  `active_page` would see `PAGE_OPTIONS[0]`.
