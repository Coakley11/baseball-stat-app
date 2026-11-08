# Draft Strategy Slice 0: compatibility release (rollback floor)

Slice 0 goes to Dev on its own, before any build that writes the Slice 2 strategy format. It
contains only reader tolerance, the S0 bug fixes, and a temporary pause on deleting strategies. It
has no Slice 2 UI and no AMI work.

## What it contains

- **Reader tolerance.** Any `schema_version >= 1` strategy row is listed and loaded. Fields the
  reader does not know are kept when it saves (rename and update copy the whole row).
- **S0 fixes:**
  - the loaded strategy keeps its notes and approach;
  - queue notes survive save and load;
  - the help text no longer says that drafting removes players from the queue.
- **Deletion pause (`strategy_deletion_guard.py`).** "Deleting strategies is temporarily paused
  while recoverable deletion is being introduced." The Delete button is disabled. The following
  also refuse:
  - `draft_strategy_store.delete_strategy`;
  - both storage backends;
  - `suite_storage_supabase.invalidate_saved_item` for the `draft_strategy` item type.

  Viewing, editing, renaming, duplicating and saving work as before. Slice 2 lifts the pause when
  it adds recoverable deletion (a 30-day Recently deleted list and a separately confirmed
  permanent delete).

## Compatibility with what Slice 2 writes

`tests/fixtures/s2_written_strategies.json` was written by the Slice 2 store's own code
(`feature/pro-strategy-queues` @ 55dd6f3). It contains:

- a v1 strategy;
- a 251-player v2 strategy with MLBAM ids, a note, a pin, an edit and a research entry;
- a soft-deleted strategy.

`tests/test_strategy_s0_compat_guard.py` checks that Slice 0:

- lists and loads both live strategies in full, with 251 players, the Slice 2 order and the
  notes, on both the local and the cloud path;
- never shows the deleted strategy, because Slice 2 keeps it under a separate item type;
- keeps every Slice 2 field (ids, notes, pins, revision, edit log) when it renames or updates a
  Slice 2 strategy;
- bumps `updated_at`, so Slice 2's conflict check sees the edit.

A cross-branch round trip was also checked. Slice 0 edited the 251-player strategy (reordered it
and added a note), and the Slice 2 reader then adopted both edits. All 251 ids, the existing note,
the pin and the revision were kept.

## Release order and rollback floor

1. Deploy Slice 0 (this release) to Dev and verify it.
2. Only then deploy any build that writes the Slice 2 format.
3. From the first Slice 2 save onwards, **Slice 0 is the oldest build that may be redeployed.**

   Builds older than Slice 0, including eaf3d03, de44bdf and 5059b07, list only
   `schema_version == 1` rows. They would *hide* (not delete) strategies saved by Slice 2, and
   they still have a working Delete button for v1 strategies.

To keep an older build from becoming the rollback target by accident:

- tag the deployed Slice 0 commit `strategy-rollback-floor` (this needs owner approval to push);
- roll back only to that tag or later;
- record the floor in the release notes for every later strategy deploy.
