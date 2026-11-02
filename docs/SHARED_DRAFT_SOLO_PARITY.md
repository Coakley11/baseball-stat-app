# Shared Draft drafting screen follows the Solo Draft layout

Branch `ui/shared-draft-solo-parity`, based on `origin/dev` `50c3e9b`. It has six commits, one per step. Everything is local: nothing is pushed, merged or deployed.

This branch is separate from the synchronization fix (`fix/shared-draft-lobby-start-sync`), and the two touch different files.

## What changed for the user

Once the commissioner starts a shared draft, and until the last pick, the drafting screen reads like Solo. The lobby, the waiting room, joining, completed drafts and Solo itself are unchanged.

| Order | Desktop (Shared) | Was |
|---|---|---|
| 1 | Compact caption: `League · Shared · Pick N of M · Round R · On clock: Team`, one room-code panel, "👥 Room & managers" (collapsed) | League header, room header card, badges, two summary cards, room code up to 3 times |
| 2 | **Synchronized clock**, full width | Narrow right column, below controls and chat |
| 3 | **Team Needs** with the category outlook | Narrow right column, no outlook |
| 4 | **Recommended Players**: full-width cards (Solo settings: horizontal, 6 cards, no summary banner), Add to Queue on every card | Narrow right column, with the summary banner |
| 5 | **Manual Pick** | Bottom of the right column |
| 6 | **Slim control bar**: Pause · Resume · Auto Pick; "More draft controls" holds Reset Timer (commissioner) or Leave Room (guest) | "Draft Control Center" 2×2 card beside the chat, above the clock |
| 7 | Queue and Draft Board, then **💬 Live Draft Chat** (collapsible) under the board; Rankings / Quick Tools in the right column | Chat beside the controls |

**Phone (390 px).** Clock → Manual Pick → Team Needs → cards as swipe strips → bar → queue → board → chat. This is Solo's phone order.

**Unchanged.** Every button's key, permission and handler is the same. That covers commissioner-only Pause, Resume and Reset Timer, Auto Pick through `participant_may_auto_pick`, and Leave Room for guests. Picks still commit through the shared revision check. The chat keeps its fragment, commissioner tools and Hide.

## How

- **Header (step 1).**
  - `_shared_drafting_view` selects the compact caption.
  - The room header, badges and the first summary card are skipped.
  - The second summary card, which keeps the phone hook, moves into an expander.
- **Clock, cards, Manual Pick (steps 2–3).**
  - Containers created at the top of the page (`_shared_top_clock` / `_cards` / `_manual`) are filled from the sections' existing call sites.
  - Execution order is therefore unchanged: timer sync and expired-pick handling still run before the clock, and the cards are still prepared for the current pick before they paint.
  - `_ldr_top_slot()` returns the slot on a full run. During a fragment rerun it draws in place, because a fragment rerun cannot draw outside its own container.
- **Team Needs (step 2).**
  - It paints at the top from the main script. The rec-column copy is skipped through the existing per-run flag.
  - Solo's computation moved, unchanged, into `live_draft_room_ui.render_team_needs_for_team`, which both modes now use.
- **Controls and chat (step 4).**
  - `render_live_draft_control_center(layout="bar")` changes containers only.
  - `render_control_center_with_live_chat(chat_inline=False)` paints the bar alone.
  - `render_live_draft_chat_section` puts the unchanged chat panel in an expander.
- **Phone (step 5).**
  - On this screen the bar takes no phone tier.
  - New CSS gives the clock slot the clock tier, and the Manual Pick slot the action tier.
- **Fix (step 0).**
  - `_live_draft_team_needs_rendered` survived across runs, so a Shared draft after a Solo draft in the same session never showed Team Needs. It is now cleared per run.

## Tests

- **`tests/live_draft_real_app_harness.py` and `tests/test_live_draft_real_app_layout.py` (12 tests).**
  - These boot the **real** `streamlit_app.py` on an active draft (Solo, Shared commissioner, Shared guest) and read the section order from the rendered tree.
  - **Isolation:**
    - local-file rooms in a temporary directory, never Supabase;
    - `SUITE_STORAGE_ISOLATED`;
    - a fresh `SUITE_WORKSPACE_ID` per boot;
    - UTF-8 standard output and error;
    - a one-hour clock.
  - **Coverage:**
    - Solo order pinned;
    - every Shared section present once, with no duplicate widget keys;
    - commissioner versus guest controls;
    - each step's order and settings;
    - a commissioner pick, then reruns in both browsers;
    - Solo → Shared in one session, which keeps Team Needs.
  - Each boot takes about 30–90 s, and the file takes about 4 min.
- **`tests/test_live_draft_team_needs_flag.py`** and **`tests/test_shared_draft_mobile_parity.py`.** Source and CSS checks.
- **Layout suites (16 files).**
  - The mobile layout, control centre layout, core interactions, Solo card UX, room-code visibility, room UX, chat, presence chat and multiplayer UI suites, plus the new files.
  - **163 passed, 10 failed.** The same 10 fail on `origin/dev` `50c3e9b`, so none are new.
- **Browser check.**
  - Local `streamlit run` through a seeding wrapper, with Playwright at 1366 px and 390 px.
  - Commissioner and guest positions measured as in the table above, with no horizontal scroll.
  - Screenshots were taken locally and are not committed.

## Known leftovers (not changed here)

- **"Loading recommendations…".** The caption can show above cards that are already painted. It was in the narrow column before; it is more visible now.
- **The chat's own "Hide" toggle.** It sits inside the new chat expander. It is harmless, and its behaviour is kept on purpose.
- **The rec column still has "Recommendation Rankings" and Quick Draft Tools beside the board.** This is the same as in Solo.
- **The 10 baseline layout-test failures.** They are pre-existing and stale. Examples are room-code markup and layout-name strings.

## Risks

- **Clock fragment identity.** The clock fragment now mounts in a top container. Its position is stable from run to run, as the right column's was, and the commissioner pick plus rerun test passes. The hosted two-browser test should still watch the clock across several picks.
- **The deferred first paint.** In the heavy-paint fragment path, cards draw in place for that one fragment rerun and move to the top on the next full run.
- **Visual test coverage.** The test tool does not apply CSS. Phone ordering was verified once in a browser, and source tests keep the rules in place.

## Manual QA before deploying (hosted, two browsers, desktop and phone)

1. **Create and join.** The commissioner creates a room and the guest joins. The lobby is unchanged.
2. **Start.** The commissioner starts the draft. Both screens open in the order above.
3. **Picks and queue.** Make picks from a card, from Manual Pick and with Auto Pick. Use Add to Queue. Picks reach both browsers.
4. **Commissioner controls.** Pause and Resume as the commissioner. On the guest's screen they are disabled, and the guest's "More draft controls" shows Leave Room.
5. **Chat.** Open the chat under the board and send a message both ways.
6. **Phone.** Repeat on a phone and check the order: clock, Manual Pick, Team Needs, swipeable cards, then the rest.
7. **Regression.** Solo draft: unchanged.

## Integration

- **Order.** Integrate after the synchronization fix. The two branches touch disjoint files (`draft_room_context.py` and `draft_room_supabase_store.py` versus `streamlit_app.py`, `live_draft_room_ui.py`, `live_draft_control_center_ui.py` and `live_draft_mobile_layout.py`).
- **Deployment.** It needs separate approval, its own deploy-marker pin, and the manual QA above.
