# Fantasy Lineup — Mobile / Touch Drag-and-Drop Validation Runbook

Last updated: 2026-07-10

Scope: the redesigned **Fantasy Lineup** roster board and its **Drag & Drop**
lineup editor. Confirms drag-and-drop works on touch devices, that assignments
persist through Streamlit reruns, and that the stat line shows all six hitter
categories.

## Component / touch background

The Drag & Drop editor uses `streamlit-sortables` (>= 0.3.1), which wraps
[`@dnd-kit`](https://dndkit.com). The bundled build configures three sensors:

- **PointerSensor** — `activationConstraint: { distance: 10 }` (mouse/pen).
- **TouchSensor** — `activationConstraint: { delay: 250, tolerance: 5 }`.
- **KeyboardSensor** — arrow-key reordering for accessibility.

The touch `delay: 250ms` + `tolerance: 5px` means a quick swipe on a card still
**scrolls the page**, while a short **touch-and-hold** picks the card up for
dragging. Because of this we intentionally do **not** set `touch-action: none`
on cards (that would block scrolling that starts on a card). During an active
drag, `@dnd-kit` prevents the browser from scrolling automatically.

Conclusion: touch drag-and-drop is dependable with this component; no
replacement is required. Classic Dropdowns remains available as a reliable
fallback via the editor-mode radio.

## Canonical state model (why it now persists)

- Each fantasy week has **one canonical assignment dict** in session at
  `weekly_lineup_canon_{week}`.
- The board, validation, and Save all read from this single source.
- Drag & Drop and Classic Dropdowns write to canonical only when their output
  **differs** (normalized signature compare), then trigger one guarded
  `st.rerun()` so the board above refreshes — no rerun loop.
- Classic Dropdown widgets use a **separate** key namespace
  (`weekly_lineup_dd_{week}_{slot}`) and are **not instantiated in Drag & Drop
  mode**, so the inactive editor can never overwrite drag results.

## Manual validation checklist

Perform on at least one iPhone-width and one Android-width device (or browser
device emulation at 390px and 360px widths), in the deployed app.

### Setup
- [ ] Open the Fantasy Lineup page with an active draft / league context.
- [ ] Confirm the team header, Starting Lineup cards, OF 1/OF 2/OF 3, circular
      photos (or fallbacks), and the Bench grid all render above the editor.
- [ ] Set editor mode to **Drag & Drop**.

### Touch drag mechanics
- [ ] **Touch-and-hold** a Bench player ~0.3s, then drag — the card lifts.
- [ ] A quick vertical **swipe** on a card scrolls the page (does not drag).
- [ ] While actively dragging, the page does **not** scroll unexpectedly.
- [ ] Drop into an **empty** eligible slot — the player lands and stays.
- [ ] Drop into an **occupied** eligible slot — the previous starter returns to
      Bench, new player takes the slot.
- [ ] Drag a **starter back to Bench** — the slot shows "Open slot".
- [ ] Cards and drop zones are large enough to hit reliably with a finger.

### Persistence
- [ ] After each drop, the roster board **above** the editor updates to match.
- [ ] The player does **not** snap back after release or after the rerun.
- [ ] Tap **Save Weekly Lineup** — success flash appears.
- [ ] **Reload** the page — the saved lineup is restored exactly.
- [ ] Switch to another week and back — each week keeps its own assignments.
- [ ] Switch to **Classic Dropdowns** and back to **Drag & Drop** — the lineup
      is unchanged (dropdowns did not reset it).

### Stat line
- [ ] Each hitter card shows `R · HR · RBI · SB · AVG · OPS`
      (e.g. `R 52 · HR 21 · RBI 50 · SB 7 · AVG .320 · OPS .993`).
- [ ] AVG/OPS show three decimals; AVG drops the leading zero (`.320`).
- [ ] On a narrow screen the stat line wraps instead of being clipped.
- [ ] A player missing some columns still shows the columns it has.

## Automated coverage

`tests/test_fantasy_lineup_state.py`:
- Touch/mouse drag → canonical update → rerun-guard (no loop) → board → save →
  refresh restore.
- Drag starter back to Bench clears the slot.
- Weeks are isolated.
- Inactive dropdown widget values do not reset canonical state.
- Drag & Drop mode instantiates **no** dropdown selectboxes.
- Stat line shows all six categories, supports `AVG`/`BA`, strips leading zero,
  keeps OPS > 1 leading digit, and degrades cleanly for missing columns.
