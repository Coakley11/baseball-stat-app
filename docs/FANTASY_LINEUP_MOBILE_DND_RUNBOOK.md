# Fantasy Lineup — Circular Board Touch Validation Runbook

Last updated: 2026-07-10

Scope: the **single** Fantasy Lineup interaction — drag circular player faces into
circular position slots (or back to Bench). No separate editor, dropdowns, or
editor modes.

## What users see (normal mode)

1. Team and week header
2. Starting-lineup **position circles** (empty dashed or filled with a face)
3. Bench **player faces**
4. Simple validation messages when needed
5. **Save Lineup** and **Reset**

## Touch behavior (verify on Android phone)

Perform on a real Android device after deploy.

### Scroll vs drag
- [ ] Quick vertical swipe scrolls normally.
- [ ] Touch-and-hold a bench face ~0.3s activates drag.
- [ ] While dragging, page scrolling stops.

## Desktop mouse behavior (verify on Dell / laptop)

Perform with a mouse on the deployed build (not touch emulation).

### Activation
- [ ] Mouse down on a bench or slot face.
- [ ] Small movement (~5px) **or** brief press (~100ms) starts drag (no long hold).
- [ ] Drag ghost follows cursor outside the original face element.

### Drop
- [ ] Release over eligible oval commits the drop.
- [ ] Player remains in oval after Streamlit rerun.
- [ ] **Player face disappears from Bench immediately** (no duplicate).
- [ ] Dragging starter to Bench removes face from oval and adds to Bench immediately.
- [ ] Dropping onto occupied slot returns displaced player to Bench immediately.

### Bench deduplication (immediate, before rerun)
- [ ] After drop into a slot, bench re-renders from current assignments — assigned player not shown on bench until dragged back.

### Persistence
- [ ] **Save Lineup** shows “Lineup saved.”
- [ ] Reload restores assignments.

## Automated coverage

`tests/test_fantasy_lineup_state.py` — `apply_board_drop`, payload, canonical
state, save/refresh, no editor-mode widgets.

## Developer Mode

Storage probes, save traces, invite/trade/import diagnostics, and Start-Sit
recommendations remain available but are not part of the primary lineup UI.
