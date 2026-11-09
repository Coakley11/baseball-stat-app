# Slice 2 — known issues (recorded 2026-11-08, after the 255db97 Dev release)

## KI-1 · Global Queue still says "Loaded from <strategy>" after that strategy is deleted

**Status:** fixed on `fix/s2-stale-loaded-strategy` (not deployed). The owner raised it from cosmetic to a focused correction on 2026-11-08: a deleted strategy must stop acting as an active source.

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

## KI-1 fix (2026-11-08)

**Confirmed cause:** the Delete button dropped the record only in the browser session and never scheduled
a workspace save, so a reload restored it from the saved workspace. Permanent delete, the older delete path
and deletions on another device never dropped it at all.

**Changes:**
- `draft_strategy_store.forget_loaded(session, strategy_id=None)` drops the record and marks the workspace
  for the end-of-run save (`draft_queue_modes.mark_personal_change`).
- `active_loaded_record` / `reconcile_loaded_strategy` keep the record only while its strategy is live
  for this account:
  - confirmed gone: the record is dropped;
  - access refused or storage unreachable: the record is not treated as active that run, but is kept,
    because a transient failure never erases anything.
- Every delete path:
  - the Pro editor's Delete and the store's `delete_strategy` drop the record when it names that strategy;
  - permanent delete re-checks what is live, because a copy kept before Restore Original shares the live
    strategy's id.
- Checked before anything reads the record:
  - the Draft Strategy page (before the Global Queue caption and notes are drawn);
  - the Adaptive panel (before explanations are built);
  - `draft_strategy_work.create` (a new strategy from the Global Queue);
  - AMI, which uses `active_loaded_record` (A1).
- **Drafts already in progress keep their own history.** Their "original plan" says the strategy was
  deleted since:
  - a Global Queue draft adds "its notes are no longer used";
  - a strategy-copy draft adds "this draft keeps its own copy". Its Save back is refused, because the
    strategy no longer exists.

**Unchanged:**
- the Global Queue's players, order and its own notes;
- other strategies;
- the deleted strategy's notes, pins and research (kept in Recently deleted).

Restore brings the strategy back under its id with its notes, pins and research, and changes nothing else.
It does not make it the Global Queue's source again; loading it again does that.

**Another device:** the deletion takes effect at the next refresh on this one (the strategy list read
cache lasts for the browser session, as it does for the page's own strategy list).

**Tests:**
- `tests/test_deleted_strategy_references.py` (17);
- `tests/test_draft_strategy_page.py`: 2 page tests (the Delete button, deletion on another device). Both
  fail on 255db97 and pass with the fix.
