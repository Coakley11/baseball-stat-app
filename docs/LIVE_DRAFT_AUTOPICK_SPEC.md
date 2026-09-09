# Live Draft auto-pick specification

## Principles

- **Roster legality** determines who may be selected.
- The **Auto-Pick Rule** chosen on the Live Draft setup page determines which legal player is selected.
- The **draft queue does not participate** in automatic selection.

The queue is a **manual drafting aid** only: display, reorder, highlight, and quick manual picks.

## Setup page rules (authoritative names)

The Live Draft setup page offers these **Auto-Pick Rule** options (see `LIVE_DRAFT_AUTO_RULES` in `streamlit_app.py`):

- `best market rank`
- `best model rank`
- `best projected fantasy value`
- `best roster need`
- `balanced recommendation`

There is **no** “Queue First” or queue-based auto-pick mode.

## Timer expiration process

When a pick timer expires:

1. Identify all players still undrafted and available.
2. Determine open roster slots for the team on the clock.
3. Remove players who cannot legally fill any open slot.
4. Apply mandatory end-of-draft position enforcement.
5. Apply the configured **Auto-Pick Rule** to the remaining legal pool.
6. Draft the highest-ranked legal player under that rule.
7. Commit exactly one pick, advance the turn, and install the next timer.

## Example

- One pick remains; only **C** is open.
- Queue contains an **OF**.
- Rule: `best model rank` (or any configured rule).

The OF must **not** be auto-drafted. Filter to legal catchers, rank by the rule, draft the top legal catcher.

When multiple positions remain open, consider every player who can fill at least one open slot, then rank that pool with the configured rule.

## How each Auto-Pick Rule ranks the legal pool

After roster legality filtering (team open required slots, then league-legal / BN when only flex/bench remains):

| Rule | Sort key (descending unless noted) |
|------|-------------------------------------|
| `best market rank` | lowest Market Rank, then Decision Score, Expected Fantasy Value |
| `best model rank` | lowest Model Rank, then Decision Score, Expected Fantasy Value |
| `best projected fantasy value` | Expected Fantasy Value, then Model Rank (asc) |
| `best roster need` | Positional Fit, Draft Fit Score, Expected Fantasy Value |
| `balanced recommendation` | Decision Score, Draft Fit Score, Expected Fantasy Value |

The same rule is stored on `room["config"]["auto_pick_rule"]` from the setup **Auto-Pick Rule** control and drives both Auto Pick and Live Draft recommendation ranking.

## Team-scoped legality

While required starters remain open (non-flex), candidates must be eligible for at least one open required slot. Bench (`BN`) is not used as an escape hatch in that phase. When only UTIL/DH/BN remain — or starters are filled — the candidate set widens to league-legal BPA under the selected rule.

