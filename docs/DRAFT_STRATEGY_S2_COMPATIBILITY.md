# Pro Draft Strategies S2: storage and release compatibility

S2 connects the v2 strategy store (S1) to the Draft Strategy page and the in-draft Draft Strategy
panel. This note records what it stores, and which releases can safely run against that data.

## What S2 writes

| Item type (`suite_saved_items`, account scoped) | Key | Written when |
|---|---|---|
| `draft_strategy` | strategy id | Create, Save, Restore, Restore Original Version, Save back from a draft |
| `draft_strategy_v1_backup` | strategy id | Once, before a v1 strategy's first v2 save (S1) |
| `draft_strategy_research` | strategy id | Add finding |
| `draft_strategy_trash` | `<id>~<deleted_at>` | Delete, and before Restore Original Version |

Local single-user installs keep one JSON file per item type in the workspace folder
(`draft_strategies.json`, `draft_strategy_trash.json`, ...).

Session only, never saved with the workspace and never in a Shared Draft room document:
`_draft_strategy_work` (working copies), `_draft_strategy_open_id`, `_draft_strategy_open_pick`,
`_draft_strategy_open_next`. A draft's chosen plan lives in that draft's own adaptive state
(`draft_queue_adaptive[<draft>].draft_plan_source`), which is personal workspace data and is listed as
private in `draft_room_shared_state`. All of these are dropped on sign-out or an account switch.

## Owner decisions applied

- **Size:** up to 300 players per strategy; 512 KB per stored strategy. Measured: 300 players with a
  full 500-character note on every one is about 370 KB (notes are kept twice, in `notes` and in the v1
  `players` mirror), a typical 300-player strategy with notes on a third about 190 KB, one edit on a
  227 KB strategy about 13 ms. The caps refuse growth only: a larger stored strategy loads in full,
  can still be reordered, trimmed or renamed, and nothing is trimmed on read or save (long notes and
  pin lists over the new-item caps are kept).
- **Deletion:** Delete moves the strategy to Recently deleted for 30 days; Restore brings it back (as
  a copy if its id or name was reused). Permanent delete is a separate confirmation and also removes
  the strategy's research log and v1 backup, unless the strategy or another deleted copy still exists.
  Expired items are purged lazily when the owner opens their own Draft Strategy page (there is no
  background job). Restore Original Version (from the v1 backup) is confirmed and first puts the
  current version under Recently deleted. Every save, delete and restore checks the stored revision
  and `updated_at`, so newer work from another tab or device is never overwritten.
- **Player ids:** an MLBAM id is stored on an entry (and its note) only when it resolves offline and
  unambiguously: the draft pool row, the built-in seed map, then the photo id cache. No network call.
  A name shared by two pool players is flagged `id_status: "ambiguous"` and keeps its name key. Notes
  are looked up by id first, then by name, so all existing name-keyed notes keep working.

## Release floor

- **S0 (ea84d8a) is the minimum rollback.** Its reader lists any `schema_version >= 1` row, keeps
  the v1 `players` mirror, and loads it into the queue. Tested against S2 data
  (`tests/test_draft_strategy_s2.py::S0FloorTests`): a 251-player v2 row with MLBAM ids lists and
  loads in full with its notes; a deleted strategy is not shown (trash is another item type or file).
- **Anything older than S0 (e.g. eaf3d03) must not run against S2 data.** It lists only
  `schema_version == 1` rows, so every strategy saved by S1/S2 would be hidden (not deleted). S0 must
  be on Dev before any build that writes v2.
- On S0, deleting or editing a strategy uses its own v1 code: an edit rewrites the v1 fields only
  (S1's `upgrade` adopts it from the mirror on the next S2 read); a delete there is a hard delete
  (S0 predates Recently deleted).

## Draft entry

The Draft Strategy panel's **Starting plan for this draft** chooses the Global Queue (default) or a
saved strategy. A strategy is copied into the draft: Fixed follows the copy's order, Adaptive
re-orders a separate working order from it using the strategy's approach, pins, notes and research,
plus the league rules and roster needs. Neither the strategy nor the Global Queue changes unless the
user ticks the confirmation and presses **Save back**. Auto Pick is unchanged: it follows the room's
rule and never reads a queue or a plan.

Known limits in S2: the sidebar queue, recommendation-card **Add to Queue** and the Draft Strategy
page's Global Queue controls always act on the Global Queue, also while a draft follows a strategy
(the panel's own suggestions add to the draft's copy). Working copies live in the browser session: a
page reload drops unsaved strategy edits.
