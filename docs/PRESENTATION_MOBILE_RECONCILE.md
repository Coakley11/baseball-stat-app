# Baseball presentation + Mobile M1–M7 reconciliation

Final presentation/mobile pass, branched from the accepted presentation checkpoint
`900d7a2` on `presentation/mobile-reconcile`. Nothing here was pushed or merged.

Written for: whoever integrates this line into `dev` later.

## 1. What landed

| commit | what |
|---|---|
| `52aa0eb` | Mobile M1–M7 reconciliation (merge of `ffd5244` into `900d7a2`) |
| `c572bbf` | Shared countdown no longer looks frozen at zero |
| `db45f6e` | Desktop/mobile polish: Quick Guide tap target, heading-level skip |
| `19a1e56` | Solo acceptance harness fixes + declared-component clock probes |
| `a2dd674` | Tests pinning the Solo prewarm mount's inertness |

## 2. Reconciliation method

Three-way merge, not a rebase: merge base `cafe437`, so all eight accepted mobile
commits replay as one merge commit with both `900d7a2` and `ffd5244` as parents.
`mobile/m1-foundation` was not moved.

36 files auto-merged. One file conflicted — `streamlit_app.py`, two hunks:

1. **Rec-cards early paint.** The root cause was indentation, not intent: the
   stabilized build de-indented the block (20 → 16), so M3's hook addition no
   longer aligned. Resolved by keeping all of main's behaviour (`cache_only`,
   the `_sp_mark`/`_start_paint_marks` instrumentation, the deferred-pool `else`
   branch) and re-applying the `_ldr_m_hook("ldr-m-recs-early")` wrapper at
   main's indentation.
2. **Rankings expander.** Kept both sides: the mobile anchor div and tail flags,
   plus the stabilized build's `type="compact"`.

### Live Draft selector adaptations

The stabilized build replaced the in-page Solo clock with a declared Streamlit
component, so M3/M7's assumptions had to be adapted:

- The clock hook is the keyed element container,
  `[class*="st-key-solo_live_clock_"]`, with the prewarm mount excluded via
  `:not([class*="st-key-solo_live_clock_prewarm_"])`. The prewarm key is
  *prefixed by* the real clock key, so every real-clock selector must exclude it.
- `iframe[title="solo_live_clock"]` is never used and is asserted absent. The
  real title is module-qualified (`solo_live_clock_component.solo_live_clock`),
  so that selector matches nothing.
- Every `.live-draft-on-clock` inner rule was dropped (`.ld-title`,
  `.ld-team-name`, `.ld-pick-pills`, `.ld-meta`, `.ld-clock-label`,
  `.live-draft-timer`). The component frontend owns its internals and parent CSS
  cannot reach into an iframe anyway; the parent now sets outer width/margin only.
- `iframe[srcdoc*="live-draft-on-clock"]` is kept purely as an **ordering** hook
  for the shared/multiplayer banner, which still paints through
  `components.html`. This does not reintroduce legacy Solo markup.
- M6 density was extended to the second Rankings expander the stabilized build
  added, so the two Rankings surfaces do not differ.

## 3. Shared countdown — display-only fix

Both countdowns a shared draft shows live in one-way `components.html` srcdoc
iframes, and both tick loops returned at zero, leaving a bare `0` under a "Time
remaining" label until the next canonical repaint — tens of seconds on the shared
path, which reads as a broken clock.

At expiry the label now becomes `Time expired • +Ns` and keeps ticking at 1 Hz so
the surface is visibly alive; the big number stays `0` because zero really is the
time remaining, and the overtime is secondary text so it cannot be mistaken for a
running clock. The root gains `data-expired="1"`. Past `EXPIRED_HINT_AFTER_SEC`
(120s) it stops counting and shows a reload hint, which also bounds the loop.

Applied to both surfaces, because fixing only the banner would have left a frozen
`0` beside a live one on the same page:

- `live_draft_on_clock_ui.py` — the On-the-Clock banner
- `live_draft_timer_ui.py` — the standalone "Time on clock" block that
  `render_live_draft_timer_bar` paints

`EXPIRED_HINT_AFTER_SEC` lives in `live_draft_timer_ui.py` because
`live_draft_on_clock_ui` already imports from it; the reverse would be a cycle.

**Safety.** Nothing emits an event, writes state, persists anything or creates a
second deadline authority. `tests/test_live_draft_shared_countdown_display.py`
asserts the emitted markup contains no `setComponentValue`, `postMessage`,
`fetch`, `XMLHttpRequest`, storage access or `window.parent` reach-out. The
canonical room deadline remains the only authority for expiry and auto-pick.

Verified in a real browser against the shipped markup (captured by patching
`components.html`, not retyped), at 360px:

| case | observed |
|---|---|
| running | `Time remaining`, `3 → 2 → 1` |
| hits zero | `Time expired • +0s … +10s`, number stays `0`, `data-expired="1"` |
| mounts already expired | never a bare frozen `0` |
| past the 120s bound | `Time expired • refresh if stuck`, ticking stopped |
| timer bar | same, `Expired • +Ns` |

No horizontal overflow at 360px; card height stable within 2px.

**Out of scope, deliberately:** `_mount_js_countdown`'s `element_id` branch, which
writes into the parent document for the inline Solo card. The Solo clock is the
declared component and its architecture is preserved; a test pins that branch's
existing behaviour so the boundary is explicit.

## 4. Solo clock: prewarm proven, cold first-mount resolved

`900d7a2` added the Ready-time prewarm without end-to-end evidence. Measured here
across four runs (a fifth spanned a machine sleep — see §7):

**During Ready**

| requirement | observed |
|---|---|
| keyed Solo clock container exists | yes |
| iframe exists | 1 |
| iframe title | `solo_live_clock_component.solo_live_clock` |
| container / iframe height | 0 / `[0]` |
| clock text | `''` |
| countdown digits | False |
| real clock containers present | 0 |
| first mount relative to Ready | same sample as the Ready card |

**After Start** — authoritative room `in_progress`, exactly 1 clock iframe,
container height 205, real clock iframe present **0.07–0.21s** after the draft
becomes active (timed from the Start click, so pool/Ready cost is excluded).

`900d7a2` documented the pre-fix behaviour as a keyed container with *no iframe
child* at +4.2s on a fresh process, during which the documented legacy fallback
was unreachable, so the user saw "TIME REMAINING" with no clock. That gap is gone.

**The Solo cold first-mount issue is resolved.**

`tests/test_solo_clock_prewarm_inert.py` pins the structural reasons the mount
cannot do anything else: `prewarm=True` reaches the frontend branch that clears
the tick, reports height 0 and returns before `paint()`; `expire_token=""` while
`emitExpire` is gated behind a truthy token; `deadline=0.0`/`clock_seconds=0`; no
`on_change`; the function body touches no room/session/timer state; and the
collapse `<style>` is emitted every run rather than behind a session flag (a
once-only guard was measured going 0 → 40 → 26px as the rule vanished).

## 5. Solo acceptance timings

Corrected harness, 5/5 successes:

| stage | measured |
|---|---|
| Setup → Ready card (create + pool) | 8.32 – 15.97s |
| Pick-1 snapshot → `Start Draft` enabled | same instant as Ready, every run |
| Ready → authoritative active draft | 1.94 – 3.20s |
| total Setup → active | 10.26 / 10.65 / 12.54 / 12.72 / 18.53s |

Median 12.54s, worst 18.53s. The existing thresholds (median < 20s, worst < 35s)
**still hold and were left unchanged.** A second instrumented run agreed
(median 12.64s, worst 21.83s excluding the sleep-spanning attempt).

## 6. Desktop/mobile polish

A 16-page × 360/390/430/1280 matrix found **zero hard failures**: no horizontal
overflow, no CSS printed as text, no wide tables, no runtime exceptions, no
clipped actions, no chart overflow, all dialogs fit, and no sub-16px inputs at any
phone width. Desktop composition at 1280 was already consistent, so the polish
list is deliberately short rather than a redesign.

1. **Quick Guide tap target.** 21px tall on all 16 pages, under the 24px minimum.
   It is M2's own raw `<details>/<summary>`, not a Streamlit widget, so the
   existing phone touch-target rules never reached it — and on phones it is the
   only control that opens the card. Now 37px at 360/390/430. Desktop is
   untouched by construction: `page_quick_guide.py` already makes the summary a
   non-toggle above 640px, and it still measures 21px with `cursor: default` at
   1280. Block layout is kept on purpose — the disclosure arrow is a floated
   `::after` that flex would stop honouring.
2. **Heading-level skip.** Fantasy Lineup Assistant jumped h3 → h5 at "Team
   Summary"; both h5s sit under the "Lineup Diagnosis" h3, so both became h4 and
   the page now has no skips.

**Not changed, deliberately:** desktop Quick Guide behaviour and the stacked page
chrome above the fold (both M2 Preserve items), and Draft Room Simulator's four
primary buttons, which belong to separate tab sections rather than competing in
one view.

## 7. Findings that were withdrawn, with evidence

Every "defect" below was investigated and traced to the observer or the
environment, not the product. None produced a product change.

| reported | actual cause |
|---|---|
| `SOLO DRAFT STILL BLOCKED — solo_start_handoff`, 0/5 | harness set `Picks per Team = 6` against a 14-slot default roster, so the product correctly **refused** to create the room. Identical failure on the `900d7a2` control; no room was ever created. |
| Solo `Start` never completes | creating the room no longer starts the draft — it lands on the Ready card, and the harness had no second `Start Draft` click, so it could only time out |
| `rankings_above_quick_tools` false | harness searched `"Recommendation rankings"` case-sensitively; the product renders `"Recommendation Rankings"` |
| setup fields not taking effect | a bare `fill()` does not commit a Streamlit number input; needs `click → fill → Tab → input_value()` read-back |
| one Solo start took 21571s | the machine slept mid-run (system event log: sleep 06:06, resumed from low power 09:04) |
| page title rendering `&amp;` | observer artifact — the DOM shows `innerText` "FANTASY SLEEPERS & BUSTS" and `innerHTML` `&amp;`, both correct |
| `LOCAL SHARED DRAFT BLOCKED — SHARED_POOL_HANDOFF` | pre-existing shared render/rerun latency. Control on `900d7a2`: `pool_wait_s` 242.5 vs reconciled 243.2, same verdict, same 0/0 add counts, same host/guest paint split |
| `test_mixed_matrix_thirty_two_pick_rendered_three_runs` | baseline/timing-sensitive — see §8 |

Two self-inflicted detours during investigation were restored: the device pointer
`data/suite_active_workspace.json` was briefly repointed at a nonexistent
workspace (which makes the Live Draft page hang), and a leftover room file was
moved aside (leaving the workspace referencing a missing room). Both restored and
verified byte-identical.

## 8. Mixed-matrix test classification

`test_mixed_matrix_thirty_two_pick_rendered_three_runs`:

- Reconciled tree, isolation: **3/3 fail**, always `board lag at cycle 7`
- Control `900d7a2`, isolation: **3/3 fail**, cycles **7, 14, 9**
- Pre-mobile `cafe437` baseline: failed as `index lag at cycle 7`
- `5ba62dd` full-suite run: passed

Both sides fail, with varying cycle numbers on the control → **baseline /
timing-sensitive**, not a reconciliation regression. Its AppTest fixture never
imports `streamlit_app.py`, the only merged file in its area, and both the
fixture and `tests/live_draft_accelerated_harness.py` are byte-identical to
`900d7a2`. No product code was changed for it.

## 9. Known limitations carried forward

These are pre-existing, confirmed against controls, and presentation-only:

- **Shared render/rerun latency.** After the host starts a shared draft, the
  host's own browser can keep painting "Waiting to Start" for ~4 minutes while
  authoritative disk state is already `in_progress` and the guest paints "In
  Progress". Measured at 243.2s reconciled vs 242.5s on the `900d7a2` control.
  State correctness is unaffected. Phase 1 accepted this and explicitly froze the
  routing/rerun design.
- **Per-paint diagnostic disk I/O.** `render_live_on_clock_banner` writes
  `data/tb_probe/on_clock_banner_enter.json` on every paint, and ~15 other Live
  Draft modules write similar probes. Gating them needs `developer_mode_enabled()`
  from `streamlit_app.py`, which would be a cross-module refactor outside a
  presentation pass.
- **Streamlit chrome below comfortable tap size on phones.** 16×16 `help=`
  tooltip icons, 22×22 dataframe toolbar buttons, 28px multiselect chips, the
  24×24 "Clear all" icon, and hover-only heading anchor links. These are
  Streamlit's own widgets, not app markup.
- **No `h1` on any page.** The visible page title is a styled banner rather than
  a heading element, so pages expose only `h3`+ (or no headings at all). Changing
  this touches all 16 pages and the accessibility brief says to document
  structural limitations rather than rewrite during this pass.
- **Cold-process Live Draft paint.** On a genuinely fresh process the Live Draft
  page can take long enough that drive scripts relying on sidebar text as a
  readiness signal start interacting before the main column paints. The clock
  measurements above therefore separate pool/Ready time from component-mount time
  rather than reporting a single cold-start number.
