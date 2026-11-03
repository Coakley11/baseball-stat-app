# Draft Queue missing after a completed Shared Draft (room `da9e78`, 2026-11-02)

**Reported:** Paul Goldschmidt was still in the owner's Draft Queue when the Danny vs Barry draft finished (4 of 4 picks). After a later sign-in he was gone. The owner did not remove him.

## Where the queue lives (deployed code `369b9e7`)
The queue is stored only in the account's own workspace record (`suite_app_current_state` → `full_session`), in two places:
- `draft_room_participant_state[<room>].by_participant[<participant id>].workflow.queue`: the private per-room queue, keyed by the Auth user id;
- `draft_queue`, plus `draft_state.queue`: the session copies of the current queue.

The shared room never stores private queues. Its participant records hold only public fields (team, name, ids).

**So:** a queue is durable only when the account's workspace save succeeds.

## Evidence (owner's read-only queries, 2026-11-02/03)
| Check | Result |
|---|---|
| Account workspace saves | Refused from 18:42 UTC until the end of the draft at 21:19 UTC (stale revision, "cause B") |
| Goldschmidt in `draft_queue` / per-room queue (main workspace, last saved 2026-11-03 04:38 UTC) | Absent |
| Every path mentioning him (`goldschmidt_paths.sql`) | Exactly two, both `$.fantasy_in_season_state.hitter_stats_records[209]` (`Player`, `Player Key`) |
| Queue metadata, `draft_state.queue`, per-room queue, resumable draft slots | No match |
| Older workspace | No match anywhere |

The two hits are ordinary in-season player statistics, unrelated to any queue.

## Conclusion
- **Not recoverable:** no saved queue record holds him. The owner chose not to rebuild the queue from the statistics row.
- **Most likely cause: failed persistence.** He was queued, or the queue last changed, after the last successful account save (18:42 UTC). The queue then lived only in that browser session, and the next sign-in restored the 18:42 state.
- **Supporting:** `_queue_player_meta` (queue display details) is written whenever a queued player is shown, is never pruned, and is restored with the workspace. Its absence fits a queue that was never saved with him in it. It is not proof, because a later session could have skipped restoring the queue fields and then saved without them.
- **Ruled out:**
  - completing the draft (nothing in completion touches the queue);
  - the drafted-player removal (he was not drafted);
  - Barry's account (separate record);
  - the Auth vs suite account id split (the slot is keyed by the Auth id, and the restore reads the account's own record);
  - the security release and the preservation hotfix (neither touches queue storage).
- **Also clears the queue:** creating any new Solo or Shared Live Draft (`reset_context_for_new_live_draft`).

## Future fix (separate; not deployed)
1. **Persistence:** Stage B (`stageb/library-recovery`). Refused saves are rebased and retried; a save after a failed re-read recovers; repeated refusals show a visible warning.
2. **Historical queue (owner's preference):** when a draft completes, keep each participant's remaining queue as a read-only snapshot of that completed draft, private to that participant.
   - Never draftable.
   - Never cleared by completion or by a new draft.
   - Never visible to other participants.
   - Saved queues and Draft Strategies untouched.

   Owned by the hybrid-queue work (account-level saved strategies plus per-draft working queues), after Stage B, since both use the same queue storage.
3. **Tests to add with it:**
   - Goldschmidt left in the queue at completion survives refresh, reopen and sign-in;
   - commissioner and participant queues stay separate;
   - an unrelated account cannot read another participant's queue;
   - drafted versus undrafted queued players are handled correctly;
   - a refused autosave during the draft is retried, or warned about, so the queue is not silently lost;
   - starting a new draft does not erase a completed draft's snapshot.
