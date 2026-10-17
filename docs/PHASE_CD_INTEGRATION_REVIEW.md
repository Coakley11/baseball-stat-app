# Phase C/D integration review (October 2026)

Branch under review: `quality/shared-functions`, built on Phase D `quality/rest-of-app` @ `38d1e3e`.
Everything below was done in disposable detached checkouts. Nothing was merged into `dev`,
pushed or deployed.

## References verified (2026-10-16)

| Ref | SHA | Notes |
|---|---|---|
| `quality/rest-of-app` | `38d1e3e` | Phase D tip (D1–D7) |
| local `dev` | `56820e6` | ancestor of `38d1e3e`: Phase C/D is 17 commits ahead, 0 behind |
| `origin/dev` | `763001b` | ancestor of `dev` |
| `feature/ami-foundation` | `6ef7471` | AMI audit; `dea3bdc` (foundation) is its parent. Branched from `0e588e0` |
| `billing-test-deploy` | `72d36c6` | one commit not in `dev` (sandbox Stripe price) |

## Rehearsal 1: Phase C/D onto `dev`

`dev` is an ancestor, so it would be a fast-forward with no conflicts.

## Rehearsal 2: Phase C/D + AMI + billing

`38d1e3e` + `6ef7471` + `72d36c6`:
- **Textual:** clean auto-merge, including `streamlit_app.py`.
- **Behavioral:** full suite (629 files) compared with the `38d1e3e` full suite (624 files).

| | passed | failed | files that can't collect here |
|---|---|---|---|
| `38d1e3e` | 4,739 | 252 | 13 |
| merged | 4,809 | 261 | 13 |

The 10 tests failing only on the merged tree:

| Test | Cause | Owner |
|---|---|---|
| `test_ami_assistant_help::test_every_listed_control_exists_on_its_page`, `::test_every_how_to_step_uses_real_controls` | D5 renamed "Live Fantasy Standings" to "League Standings (official)" and "Current Roster Snapshot (not official standings)" | AMI (help entry + sources) |
| `test_ami_assistant_tools::test_valuation_page_pipeline`, `PagePipelineStrictPinTests::test_valuation_pipeline_is_exactly_known` | D7 inserted `valuation_hitter_pool` into the Valuation pipeline; the strict pin was built to flag exactly this | AMI (`tools/value.valuation_pool` should call `valuation_scores.valuation_hitter_pool`) |
| `test_workflow_persist_guard` ×3 | environment-dependent: fails on clean `38d1e3e` in isolation too (8 failures) and flips between runs. One more (`test_startup_restore_snapshot_flags_restore_failure`) failed only in the checkout where the full suite had already run: an earlier test left `data/suite_active_workspace.json` = `ws1`. It passes in a fresh merged checkout | pre-existing / test pollution |
| `test_draft_mode_selector_apptest`, `test_live_draft_accelerated_full_draft::test_local_action_latency`, `test_live_draft_full_page_rendered` | timing under parallel load; all pass in isolation on both trees | flaky (load) |

## Rehearsal 3: this branch + AMI + billing

`quality/shared-functions` + `6ef7471` + `72d36c6`:
- **Textual:** clean. The merged `streamlit_app.py` parses and contains both AMI's moves
  (`lahman_data`, `page_guides`) and this branch's.
- **AMI + new tests on the merged tree:** 119 passed, 4 failed. The 4 are the two D5
  help-text tests and the two D7 valuation pins above. The extraction adds no new conflicts.

## Phase C/D functionality reviewed

| Area | State | Notes |
|---|---|---|
| League creation/import, management, library | OK | C1/C5 |
| Rosters, capacity, ownership | OK | |
| Position eligibility (D3) | **Fixed here** (`1e8af77`) | Recommended Starters and the Waiver Wire position filter still used the old primary-only rule with 1B↔3B / 2B↔SS shortcuts |
| Weekly lineup snapshots, lock rules (D1) | OK | |
| Commissioner controls / proxy (D2) | **Fixed here** (`d7e8a86`) | Hosted installs: a signed-in owner resolved to "nobody" because `current_user_id` only read dict sessions, and Streamlit's session is a `SessionStateProxy` |
| Weekly scoring + finalization (D4) | OK | |
| Official standings (D5) | OK | AMI help text must follow the rename |
| Waivers, trades (C2/C3, D2) | OK | Trade value is now shared (`fantasy_trade_evaluation`) |
| Draft functionality | OK | Live Draft untouched by Phase C/D and by this branch |
| Historical league results (D10) | OK | |
| Valuation (D7) | OK | AMI's value tool must adopt `valuation_hitter_pool` |

## Outdated assumptions and risks found

1. **`isinstance(session, dict)` in auth-relevant code.** In the running app the session is a
   `SessionStateProxy`, never a dict.
   - The one Phase C/D instance is fixed (`d7e8a86`).
   - Pre-existing instances remain in `fantasy_league_team_ownership` (July 2026), e.g.
     `resolve_trade_team_for_session` reads the session uid only for dicts and relies on
     other fallbacks.
   - They were not changed here (auth code outside this phase). Recommend auditing them
     with a hosted test session.
2. **Trade verdict with missing rate stats.** `evaluate_trade` averages BA/OPS. If a side has
   no BA/OPS values, the weighted gain is NaN, and `build_trade_verdict_text(NaN)` reads
   "Decline". The page feed always carries BA/OPS, so this is latent. Behavior was kept
   unchanged.
3. **Two eligibility rules remain by design.** The research pages' position filters
   (Valuation, Trend Value, draft research) keep the older shortcut rule, so their results
   don't move. Fantasy screens now all use the D3 rule.
4. **Test isolation.** The AMI audit's sibling-repo `sys.path` pollution is unchanged here.
   It explains part of the "baseline" failures when the AMI sibling folder is present.
5. **Hosted persistence.** A failed cloud read could lead to a destructive write. Safeguards
   are implemented here (`305aed7`); see `docs/HOSTED_AUTOSAVE_RELIABILITY_PROPOSAL.md`.
   Staging verification is still required.

## Recommended integration order (for approval; not done)

1. Accept Phase D + this branch.
2. Merge into `dev` in a dedicated integration worktree. It fast-forwards over `dev`.
3. The AMI branch merges `dev` and applies its three small updates (Standings help entry and
   sources, `valuation_hitter_pool`, re-frozen pins). It then wires its fantasy tools to
   `fantasy_read_api`.
4. `billing-test-deploy` (`72d36c6`) merges cleanly at any point.
5. Staging acceptance for hosted persistence before any production deploy of league
   features.
