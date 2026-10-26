# AMI integration with the shared readers, U4 and the canonical history layer

Integration branch `integration/ami-readers-u4`, starting from `feature/ami-foundation @ 8c58804`.
Regular base: `quality/ami-shared-readers @ 633538f`, frozen and unmodified. That base contains
U1–U4, WEB-M2 (API contract `5ca7a26`), the seven AMI shared readers, the `team_access` fix,
plan-feature metadata and `baseball_history.py`.

AMI stays **read-only**: no tool saves, drafts, queues, adds, drops, proposes, accepts, finalizes
or acts as commissioner.

## 1. Commits

| Commit | What |
|---|---|
| `94c2f6a` | Merge `633538f` (`--no-ff`; history not rewritten) |
| `b33b168` | AMI reads history through `baseball_history`; `lahman_data.py` retired |
| `1cede80` | AMI help follows U4 |
| `565604c` | AMI answers from the seven shared readers; plan gate on the shared capability metadata |
| (this doc) | docs |

## 2. The `streamlit_app.py` conflict

The only conflict, 5 hunks, came from both lines extracting the same Lahman layer. It was resolved
toward the regular architecture, following `docs/AMI_SHARED_READERS_CHECKPOINT.md` §5:

| Hunk | Region | Resolution |
|---|---|---|
| 1, 2 | import block | `import baseball_history as _history` + `from baseball_history import (...)` with the regular name list; `from lahman_data import` dropped |
| 3, 4 | leftover blank lines / orphaned team-context comment | dropped (the constants live in the module) |
| 5 | `load_data` | `return _history.load_history_frames(BASE_DIR, read_csv=read_required_csv)` |

Checked against both parents:
- **Against `633538f`:** the result differs only by AMI's own lines (the `page_guides` import and
  the AMI panel wiring) and by the two intended removals (the duplicate inline `PAGE_GUIDES` dict
  and the stray blank lines).
- **Against AMI:** every line AMI added on top of `4bc3d30` survives, except the four
  `lahman_data` lines that were deliberately replaced.
- **Guide text:** `page_guides.PAGE_GUIDES` equals `633538f`'s inline dict exactly, so no U4 guide
  edit was lost.

## 3. Canonical history layer

`baseball_history.py` is the one implementation, used by Streamlit, the WEB-M2 API and AMI. AMI's
consumers moved to it:

| File | Change |
|---|---|
| `ami_assistant/data.py` | `load_history_frames(Path(base_dir))` |
| `ami_assistant/tools/stats.py`, `tools/value.py` | `from baseball_history import add_rate_stats`; source strings |
| `ami_assistant/glossary.py` | OPS/OBP/SLG/BA source strings |
| `tests/ami_assistant_fixtures.py` | imports; `monolith_functions` takes the functions `streamlit_app.py` imports from `baseball_history` (e.g. `safe_round_rate_stats`) from that module |
| `tests/test_ami_assistant_help.py` | the `load_data` pin is now `_history.load_history_frames(...)` |
| `tests/test_ami_assistant_tools.py`, `tests/test_unknown_bio_players_kept.py` | imports / the module they read |

`lahman_data.py` is **removed**, not shimmed: after the move nothing imports it, so a shim would
have no callers. No second implementation remains. AMI's Valuation, Trend Value, leaderboard and
comparison parity tests pass on the canonical module, as do the regular
`test_web_prep_history_parity` tests.

## 4. Shared readers consumed

| Reader | AMI tool(s) | Questions |
|---|---|---|
| `player_owner` | `get_player_owner`; also resolves trade names and partners, and "on Team B's roster now" | "Who owns Juan Soto?", "Is Mike Trout available?" |
| `week_lineup_status` | `get_lineup_status`; `find_eligible_players` (this week's starters) | "Is my lineup saved?", "Which positions are still open?" |
| `waiver_recommendations_view` | `get_waiver_recommendations` | "Who should I consider adding?", "Why is X recommended?", "What position do I most need help at?", "Who should I drop?" |
| `loaded_player_pool` | `find_available_players` | "Who's available at catcher?" (never fetches) |
| `evaluate_trade_for_team` (extended) | `evaluate_trade` | the Trade Center card's label and body; roster issues answer "leave me without a catcher?" |
| `pending_trade_draft` | `evaluate_trade` with no players named | "What do you think of this trade?" |
| `week_view` | `get_week`, `get_week_lineup`, `explain_player_week`; `league_brief`'s current week; standings categories | "What happened in Week 1?", "Why did Adames count even though I dropped him later?" |

Superseded AMI-side logic was removed:
- the trade slot check that rebuilt "who can still play C";
- the direct ledger reads (`get_period`, `get_period_lineup`, `period_result`, …);
- the ownership map built from `league_rosters`.

The fantasy tools now import only `fantasy_read_api`. "This trade" follow-ups reuse the last named
trade, or the Trade Center draft.

## 5. Behaviour

- **Standings:** official (finalized weeks) vs "How current rosters would rank": the kinds and
  labels are unchanged and never mixed.
- **Weeks:** a finalized week is reported from its frozen lineup and result. After a drop, AMI
  says the player still counted and that the week doesn't change.
- **Another team's week:** visible once the week has started, private before (`week_view`'s
  rule).
- **Lineup status:** the Lineup page's own status, headline and body. AMI no longer only
  explains the statuses; it reads yours, and never infers it.
- **Access:** owner; commissioner acting for an unclaimed team ("You're viewing Team C as
  commissioner; the team is currently unclaimed."); claimed other team refused; invite-reserved
  team refused; nonexistent team refused. The shared `team_access` now refuses unknown teams
  (the stale AMI test asserting the old bug was flipped), and AMI's own `unknown_team` check is
  kept.
- **U4 help:**
  - re-cased actions (Set Lineup, Check Waivers, Explore Trades, League Standings, Waiver Wire);
  - the draft pages' answer cards (from `u4_answers`);
  - new controls: Draft Player, Import Draft, Save Draft, Open Saved Drafts, Open Draft Board,
    Simulation settings, Show top player.
  - A help source may name one top-level function of `streamlit_app.py`
    (`streamlit_app.py::<function>`), so controls rendered by U4's answer-card helpers are
    label-checked.

## 6. Plan gate

- **How a tool declares it:** a tool declares the shared capability it serves (`plan_capability`,
  a key of `baseball_monetization.CAPABILITY_FEATURES`):
  - `get_draft_recommendations` → `draft_recommendations`;
  - `explain_draft_recommendation` → `draft_recommendation_explanation`;
  - `get_team_needs` → `draft_team_needs`.
- **How it's decided:** by `bm.entitlement_for_capability` over `bm.enforced_features()`, the
  same gate the pages and API apply, on the snapshot the page gate already resolved. AMI never
  calls `resolve_trusted_entitlement`.
- **Fails closed:** a missing or still-loading snapshot is refused while the feature is enforced.
- **Draft Lab and ML Predictions:** AMI has no tool that serves them. Projection questions are
  declined, and a test requires any future tool that reads them to carry the matching tag.
- **Enforcement:** nothing is enforced today (tested). With enforcement switched on in tests,
  Free is refused, Pro passes, ungated tools work, and page-level enforcement reaches the same
  gate.

## 7. Web/API invariance

- `git diff 633538f HEAD` over `baseball_api`, `baseball_history.py`, `u1_answers.py`,
  `rate_stat_qualification.py`, `draft_player_names.py`, `requirements-api.txt`,
  `fantasy_read_api.py`, `fantasy_league_peek.py` and `baseball_monetization.py` is **empty**.
  The same API files are empty against `5ca7a26`.
- The OpenAPI document this tree serves **equals** `web/nextjs-foundation`'s pinned
  `web/openapi/baseball-api.json` (`api_commit 5ca7a26`): 8 paths, 40 schemas.
- **12 live requests are byte-identical** between `633538f` and this tree: same status,
  content type and SHA-256. They cover `/catalog`, search, an ambiguous resolve (409), a player,
  Ohtani's and Charleston's seasons, a season ranking, JSON and CSV leaderboards, a weighted
  score, and a missing id (404).
- The API does not import `ami_assistant`.

## 8. Verification

**Parity (`tests/test_ami_assistant_readers.py`, 17 tests):**
- **Trades:** AMI's card equals Trade Center's own card (`_trade_workspace` / `_trade_roster_issues`
  / `build_trade_analysis_package` / `trade_verdict`) for every label: Balanced, Favors your team
  (as the commissioner acting for Team C), Favors the other team and Creates roster issue. Roster
  issues are equal too. Also covered:
  - the Trade Center draft ("this trade") and the follow-up "Would this leave me without a
    catcher?";
  - an unknown player, a player not on your team, a claimed team, a nonexistent team, and no
    composed trade.
- **Lineup:** AMI's status, headline and body equal the Lineup page's own answer (`lineup_week_state`
  + `lineup_status_answer`) for Not saved yet, Draft (not submitted) with an open OF, and Saved
  and locked. Also covered:
  - ineligible placements equal `check_lineup`;
  - eligibility answers equal Save Lineup's validator;
  - the commissioner acting for Team C (the page's proxy wording);
  - claimed, invite-reserved and nonexistent teams are refused.
- **Waivers:** AMI's headline, card order, players, positions, MLB team, reason and
  starter-comparison equal what the real Waiver Wire page hands its answer card, for All, C and
  OF. Open roster spots are equal. Every add is a free agent by `player_owner`. "Why is X
  recommended?" quotes the card. A claimed team is refused.
- **Weeks:** Week 1 is finalized, then Aaron Judge is dropped. AMI still reports him as counted,
  from the frozen lineup, and says the week doesn't change. The week's table and lineup equal the
  ledger. Another team's finalized week is visible (Soto: no games → no stats). An unstarted week
  stays private.
- **Standings:** official and "How current rosters would rank" keep their own kind and label, and
  the answers never mix them.
- **Side effects:**
  - every fantasy tool and 12 fantasy questions (including refused write requests) leave dict
    and `SessionStateProxy`-like sessions byte-identical;
  - with the shared-store sync and push, the lineup stats loader and `requests` patched to fail,
    nothing is called;
  - an audit-hook subprocess records **no file writes**.

**Suites (fresh processes):**
- All `test_ami_assistant_*` suites, the regular reader tests (`test_ami_shared_readers`), U1–U4,
  shared-function, valuation, monetization and team-control suites, in one process: **354 passed,
  1 failed**.
- **The failure is pre-existing pollution:**
  `test_u1_navigation_home::test_old_and_new_labels_both_resolve_to_the_page_key` passes alone and
  in the full suite.
  - It fails only after `test_ami_shared_readers.py` (or this branch's readers module, which reuses
    its fixture) runs in the same process.
  - That leaves a sibling repo's `suite_analytical_question` (`daniel-ai-command-center`) on the
    import path (`ImportError: BASEBALL_INSIGHT_SECTION_TITLE`).
  - The same pair fails identically on a clean `633538f` checkout.
- API: `test_web_m2_api` 21 + `test_web_prep_api` 15 = **the 36 contract tests pass**;
  `test_web_prep_api_parity` 6 and `test_web_prep_history_parity` 5 pass.

**Full suite** (`pytest tests --continue-on-collection-errors`):

| Run | Passed | Failed | Collection errors |
|---|---|---|---|
| This branch | 5,114 | 254 | 13 |

| Category | Count | Detail |
|---|---|---|
| **True failures introduced here** | **0** | Every failing test also fails in the `06acd43` baseline run and in the earlier `ff46ff6` AMI run |
| Pre-existing | 254 + 13 | Includes the older Command Center pipeline tests (`test_ami_blob_persistence`, `test_ami_player_pool`, `test_ami_hardening`), Live Draft, workspace and persistence suites. The 13 collection errors are modules missing from this checkout (e.g. `music_resume_payload`) |
| Test pollution / isolation | 6 (+1) | `test_fantasy_league_lineup_format::WaiverPositionFilterTests`: a leaked `st` mock in the shared process; the file passes **27/27** on its own, as the regular review found. (+1: the U1 label test above, in the focused combined run only) |
| Flakes | 0 this run | The Leaderboards AppTest and the Live Draft timing tests passed this run; they are known load flakes |

**Browser** (Playwright; 1280 / 430 / 390 / 360; zero page or sidebar overflow):
- **Readers harness** (the real AMI panel over the regular reader fixture: Week 1 final, a trade
  composed in Trade Center): 18 questions × 4 widths = 72 answers. Covers history, standings,
  lineup, waivers, trades, weeks and help. Median 0.83 s; the first question 11.7 s while the
  dataset loads.
- **Full app:** 9 help questions × 4 = 36 answers; median 1.0 s.
- **Fixed after the first pass:** the lineup heading truncated the page's week text, and an
  unrostered name was called "a free agent now".

## 9. Remaining before the final combined integration

- Merge order (`docs/AMI_SHARED_READERS_CHECKPOINT.md` §4): this branch into the integration base,
  then web, then billing `72d36c6`. Web and billing have no textual conflicts with AMI.
- Regular-side test hygiene, unchanged:
  - `WaiverPositionFilterTests`' leaked `st` mock;
  - `test_ami_shared_readers`' sibling-repo import path, which then breaks a U1 test in the same
    process.
- Product decision: whether to enforce any plan feature. AMI follows `enforced_features()` and
  needs no change.
- U5 (the single Ask AMI entry, the phone header button, retiring the Baseball Insight box): not
  started.
