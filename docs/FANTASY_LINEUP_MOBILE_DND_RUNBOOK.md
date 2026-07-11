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

Perform on a real Android device after deploy (not desktop emulation only).

### Scroll vs drag
- [ ] Quick vertical swipe on the page scrolls normally.
- [ ] Touch-and-hold a bench face ~0.3s activates drag (face lifts/enlarges).
- [ ] While dragging, page scrolling stops (`fl-drag-active` on body).

### Drop feedback
- [ ] Eligible position circles highlight (light blue).
- [ ] Circle under finger highlights stronger (hover-target).
- [ ] Ineligible circles stay dimmed.
- [ ] Drop on eligible circle — player stays after Streamlit rerun.
- [ ] Drop on Bench — starter removed from lineup.
- [ ] Release outside valid target — player returns to original spot.

### Persistence
- [ ] **Save Lineup** shows “Lineup saved.”
- [ ] Reload restores assignments.

## Automated coverage

`tests/test_fantasy_lineup_state.py` — `apply_board_drop`, payload, canonical
state, save/refresh, no editor-mode widgets.

## Developer Mode

Storage probes, save traces, invite/trade/import diagnostics, and Start-Sit
recommendations remain available but are not part of the primary lineup UI.
