# Baseball Explorer: combined integration candidate

**Branch:** `integration/baseball-final-candidate`, worktree
`C:\Users\danie\Documents\GitHub\baseball-integration-final`.

**State:** local only. Nothing was pushed, nothing merged into `dev`, nothing deployed. No
subscription restriction is enabled, and no production or customer data was touched.

## 1. Branches and SHAs (verified 2026-10-19)

| Line | Branch @ SHA | Relationship |
|---|---|---|
| Phase C/D + shared functions | `quality/shared-functions @ ec1dfcd` | ancestor of the candidate |
| U1 | `ui/u1-foundation @ 06acd43` | ancestor |
| U2/U3 | `ui/u2-u3-simplification @ 4bc3d30` | ancestor |
| U4 + WEB-PREP | `ui/u4-migration-readiness @ a9a80f7` | ancestor |
| WEB-M2 API (accepted, frozen) | `api/web-m2-contracts @ 5ca7a26` | ancestor |
| Shared readers (accepted, frozen) | `quality/ami-shared-readers @ 633538f` | ancestor |
| AMI integration | `integration/ami-readers-u4 @ 674055b` (= `633538f` + `feature/ami-foundation @ 8c58804`) | the candidate's base |
| Billing/auth | `fix/baseball-auth-workspace-persistence @ 75bd43f` (= billing `72d36c6` + auth fixes `17f6269`, `75bd43f`) | merged |
| Web | `web/nextjs-foundation @ 3e4de76` (WEB-M2 validation `c978652` + docs) | merged |
| `dev` / `origin/dev` | `56820e6` / `763001b` | both ancestors; unchanged |

**Every other line is already contained:**
- Live Draft quality pass, release candidate, presentation, mobile, monetization M1–M3, and
  `quality/rest-of-app`: 0 commits outside the candidate.

**Duplicate auth branches.** `integration/baseball-auth-dev @ edeb8b3` and
`integration/baseball-billing-auth-current-dev @ df6f9b6` carry the same auth and billing
patches (equal `git patch-id`) re-applied onto `origin/dev`. The candidate takes the copy on the
`2f083eb` lineage it already contains (`75bd43f`), so the duplicates must **not** also be merged.

## 2. How the candidate was built

| Commit | What |
|---|---|
| `674055b` | base: the AMI/regular integration |
| `011c0d5` | merge billing/auth `75bd43f`. No conflicts. Its overlap with the regular line, `baseball_monetization.authenticated_subject` and the `streamlit_app` sidebar guards, sits in hunks separate from the regular changes (reviewed) |
| `9ec360d` | merge web `3e4de76`. No conflicts: web changes only `web/` and docs |

The `streamlit_app.py` / Lahman conflict was already resolved in `674055b`: `baseball_history`
is canonical and `lahman_data.py` is retired (see `docs/AMI_READERS_U4_INTEGRATION.md`). No new
resolution was needed.

**API contract:**
- `git diff 5ca7a26 HEAD` over `baseball_api`, `baseball_history.py`, `u1_answers.py`,
  `rate_stat_qualification.py`, `draft_player_names.py` and `requirements-api.txt` is empty.
- The candidate's OpenAPI document equals the web branch's pinned
  `web/openapi/baseball-api.json` (`api_commit 5ca7a26`).

## 3. Tests

All 653 Python test files ran, each in its own process, on the candidate, with the no-op
storage shim and scratch data.
- **Candidate:** 5,145 passed, 251 failed; 13 files crash on import (modules missing from this
  checkout, e.g. `music_resume_payload`).
- **Baselines:** the 129 files with any candidate failure were re-run on clean checkouts of
  `674055b` and `75bd43f`.

| Category | Count | Detail |
|---|---|---|
| Also failing on `674055b` | 245 | pre-existing |
| Passing on `674055b`, failing on billing `75bd43f` | 1 | `test_live_draft_mixed_matrix_rendered` (a timing assertion). Re-run fresh, it fails the same way on the candidate **and** on `674055b`, so it's load-dependent |
| Failing on neither baseline | 5 | all resolved, see below |
| Crashing files | 13 | the same 13 on all three trees |
| **Introduced regressions** | **0** | |

How the 5 were resolved:
- **`test_workflow_persist_guard` (4):** these depend on files a full run leaves in the
  checkout. In three fresh runs each, the candidate and `674055b` fail the **identical 8 tests**.
- **`test_draft_mode_selector_apptest` (1):** an AppTest 3-second timeout under load. Fresh, it
  passes 8/8 on both trees.

**By area** (candidate; every failure here is in the pre-existing set):

| Area | Files | Passed | Failed |
|---|---|---|---|
| Historical stats, trends, valuation, comparison | 19 | 211 | 0 |
| Shared fantasy calculations + readers | 4 | 58 | 0 |
| AMI (read-only) | 7 | 144 | 0 |
| API contract (WEB-M2) | 5 | 50 | 0 |
| Fantasy league, rosters, permissions | 23 | 246 | 9 |
| Weekly lineups, finalized results | 20 | 209 | 7 |
| Trades, waivers, official standings | 28 | 297 | 14 |
| Auth, subscription, billing | 50 | 388 | 9 |
| Persistence, hosted autosave | 50 | 305 | 32 |
| UI (U1–U4, navigation, mobile) | 28 | 305 | 7 |
| Draft tools, Draft Room, Live Draft | 263 | 1,888 | 117 |

**Key suites, all green:**
- the 36 accepted API contract tests;
- API page parity (6) and history parity (5);
- the 32 shared-reader tests;
- the 10 new `test_baseball_auth_workspace_regression` tests.

**Not reproduced.** `docs/AMI_READERS_U4_INTEGRATION.md` reported a sibling-repo import leak
(`test_ami_shared_readers` → `test_u1_navigation_home`). That pair passes here in one process,
48/48.

## 4. Browser acceptance

Candidate server: local, QA workspace `qa_perf`, no cloud storage.

**Layout sweep:**
- All 17 pages at 1280, 430, 390 and 360: **0 exceptions, 0 horizontal overflow, 0 clipped
  visuals.**
- Every page's answer is on the first screen except Home on phones (below).
- Median time to idle 21–38 s per page on the shared, loaded machine.

**Functional flows** (1280 and 390):
- **Draft Room:** Draft Player, Save Draft, Import Draft.
- **Saved Draft Library:** rename and cancel.
- **Valuation:** choose a player, then Show top player.
- **Lineup:** commissioner proxy for Team 2 with "Needs a waiver or trade".
- **Trade Center:**
  - trade ideas show 5 cards with "why" lines;
  - Analyze Exact Trade gives "Creates roster issue · value favors the other team" with the two
    roster warnings.
- **Live Draft:** navigation by switcher, sidebar, Home card and browser Back.

All pass with no exceptions or overflow. One 390 re-run of the Draft Room step was skipped by the
probe, because the 1280 run had already drafted its player onto that QA board.

**AMI, read-only** (7 questions at 1280 and 390, about 2 s each, no errors):
- "What can I do here?"
- the 2022 home-run leaders (Judge 62);
- official standings: "no season calendar yet", never the snapshot;
- "Is my lineup saved?" gives the Lineup page's own "Draft (not submitted)";
- waiver adds, from the Waiver Wire's own cards;
- "Who owns Juan Soto?" gives Team 2;
- "Drop Aaron Judge" is refused as read-only, with the steps to do it in the app.

## 5. UI/UX status

**Done and integrated:**
- **U1:** Home, grouped navigation, answer-first pages (Historical Explorer, Leaderboards,
  Standings, Waiver Wire), Use Suggested Lineup.
- **U2:** answer-first Compare, Career, Trend, Valuation, Sleepers & Busts, ML Predictions.
- **U3:** draft-tool purposes, the Lineup answer and Commissioner Tools panel, the Trade verdict
  card.
- **U4:** draft answer cards, Lineup warning consolidation, Trade Center cleanup, Valuation
  player selection, one name per page.
- **WEB-M2:** the Next.js Historical Explorer and Leaderboards (`web/`, not deployed).

**Not done:**
- **U5, a single Ask AMI entry (AMI session).** On phones the AMI panel sits at the bottom of the
  collapsed sidebar, about 5,800 px down, so it needs the planned phone header entry. Home still
  points to the old Baseball Insight box.
- **Home on phones.** The task cards start 1,110–1,240 px down (430/390/360), below the first
  screen, under the brand banner and heading. The offsets are identical in the U4 sweep, so this
  is not a regression. It is the clearest small UX follow-up.
- **Plan enforcement.** The product decision on which features to enforce is open. The metadata
  and gates exist and nothing is enforced.

## 6. Remaining before final integration and deployment

1. Your authorization to move `dev` to the candidate and push. Cloud deploys from `dev`, so a
   push is a deploy.
2. The billing/auth owner confirms `75bd43f` is the final auth fix, and the two `origin/dev`
   rebases are retired rather than merged.
3. A hosted smoke run of auth, billing and autosave in the real deployment (Supabase, Stripe
   sandbox). It cannot be exercised locally.
4. U5 (AMI session) and the Home-on-phones fix, if you want them before release.
5. A plan-enforcement decision.
6. Optional hygiene, all pre-existing: about 245 failing tests (mostly Live Draft, persistence
   and Command Center pipeline suites), the waiver test-order pollution, and state-dependent
   persist-guard tests.
7. Web deployment and the API service host (WEB-M3 needs separate authorization).
