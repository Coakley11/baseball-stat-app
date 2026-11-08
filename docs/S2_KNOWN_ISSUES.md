# Slice 2 — known issues (recorded 2026-11-08, after the 255db97 Dev release)

## KI-1 · Global Queue still says "Loaded from <strategy>" after that strategy is deleted

**Status:** open. Scheduled for a later focused correction (owner, 2026-11-08). Not a release blocker.

**Seen in:** browser QA of the Slice 2 candidate on the QA project (qa_other). The Global Queue was replaced
from a strategy; the strategy was later deleted, then permanently deleted. The Global Queue section kept the
caption "Loaded from **<name>**".

**Where it comes from:** the session key `_draft_strategy_loaded` (`draft_strategy_store.LOADED_KEY`) is a
snapshot of the strategy the Global Queue was loaded from: its id, name, queue and notes. It is written by
`draft_strategy_store.load_strategy` / `draft_strategy_work` and persisted with the workspace
(`baseball_persistent_state`). `draft_strategy_ui.loaded_strategy_state` shows the caption whenever the
snapshot has an id, and never checks that the strategy still exists. `draft_strategy_pro_ui` drops the
snapshot when the Delete button removes that same strategy, but then calls `st.rerun()` without saving the
workspace. The likely path is that the saved workspace still carries the snapshot, so the next load brings
it back. Other deletion paths (Recently deleted → permanent delete, another device) never clear it. This
still has to be confirmed when the fix is made.

**What the stale snapshot touches (all the same account's own data):**
- the "Loaded from …" caption over the Global Queue (cosmetic);
- `draft_queue_modes.notes_for`, which supplies the deleted strategy's notes for players still in the
  Global Queue to the Adaptive "Pins & notes" view, and to a new strategy created from the Global Queue.
  These are notes the user wrote and can see and edit before saving.

**What it does not touch:** the Global Queue's players or order, Fixed / Adaptive ordering, the stored
strategies (live or deleted), or any other account.

**Planned correction:**
1. `loaded_strategy_state` and `notes_for` ignore a snapshot whose id is not a live strategy.
2. Every delete path (soft delete, permanent delete, a deletion seen from another device) clears the
   snapshot and saves the workspace.
3. Restore from Recently deleted does not bring the caption back unless the Global Queue is reloaded from it.
4. Tests: delete → reload shows no caption; permanent delete; second device; restore; notes no longer
   carried into a new strategy.
