# Stage B: integration status and the primary-key migration decision (2026-11-03)

**Branch:** `stageb/library-recovery` (local), reconciled with the deployed baseline `369b9e7`.

## Integration
- **Reconciled base:** `9905240`, Stage B (`fix/cloud-restore-hydration`) merged onto `ebcb540`; no conflicts.
- **Merged since:** `369b9e7` (`0ae0470`). One conflict, in `save_live_draft_league_context`, resolved to the deployed owner record (cloud id plus external id). Stage B's fixed per-room draft id and the hotfix's verified-owner safety net are both kept.
- **Kept intact:** every deployed security and preservation change.
  - Shared League membership and write checks, the Auth and suite-id commissioner fix, hidden-not-deleted copies, strict invite flows.
  - The non-destructive Library clean-up, the seat-only Shared saves, verified-owner saves, and the developer-only caption.
- **Recovery:** the seat is now matched by the session's own Auth id or suite account id (`46bfd3a`).

## Does Stage B need the primary-key migration? No; it can be deferred.
The migration (`SUITE_APP_CURRENT_STATE_ISOLATION_PLAN.md`) answers one risk: `suite_app_current_state` is keyed by `app` alone, so a **plain upsert** by one account under a key another account holds replaces that row, `user_id` included.

**Stage B does not create that risk; it removes it for Baseball:**
| Baseball writer | On Stage B |
|---|---|
| Account state saves (autosave, Library save, board, recovery) | Always compare-and-set (`_save_guarded_state` → `_save_state_if_revision`). The `PATCH` is filtered by `app`, revision and `user_id`, so it cannot match another account's row. A first insert that collides gets a duplicate-key refusal, reported as "not written". |
| Reads | Filtered by `user_id`, or refused when sign-in is on and no account resolves |
| Account preferences (`suite_user_settings`) | Written with the account's `user_id`; that table's key is `(user_id, app)` (per account) |
| Developer health check | Plain upsert, but only on its own shared probe key `baseball__health_probe`, never an account row |
| Admin Library repair | Secret-gated. Its direct write imports a function that does not exist, so it cannot write. |

- **Schema:** Stage B adds no table, column, index, function or policy.
- **What the migration would still add, and why it can wait:**
  - It protects Baseball rows from **other** suite apps' plain upserts (for example the Command Center). That exposure exists today with or without Stage B; no cross-account write is recorded since 2026-07-20.
  - Its "Phase 1" trigger (refuse any update that changes `user_id`) is the smallest database-side guard, if wanted later. It changes no data and needs its own approval and review.
- **Cost of deferring:** if two accounts ever share one key (a demo preset, or the shared `user_unidentified` fallback), the second account's saves are refused, not written over the first. The autosave warning shows it.

## Smallest safe deployment candidate
Stage B code only, on `stageb/library-recovery`, with no database change. It ships only after:
1. the heavy browser-level suites pass, or their failures are explained against the baseline;
2. the owner reviews the candidate.

Excluded: Shared Draft layout, icons, room exit, Draft Strategy, the hybrid queue, historical queue snapshots and billing.
