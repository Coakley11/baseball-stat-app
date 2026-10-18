# AMI shared readers and integration-readiness checkpoint

**Branch:** `quality/ami-shared-readers`, from the accepted `api/web-m2-contracts @ 5ca7a26`.

**Commits:**
- `c658c27`: `team_access` refuses teams not in the league; capability → plan-feature metadata.
- `56ee64d`: Lineup, Waiver Wire and Trade Center compute through shared, page-free helpers.
- `32a6fef`: `fantasy_read_api` readers.

**Scope:** read-only. No cross-branch consolidation was performed. Nothing was pushed, merged
or deployed, and `dev` was not moved. The AMI, web and billing branches were read only through
git objects.

## 1. Readers (`fantasy_read_api`)

Every reader runs on the isolated session peek (`fantasy_league_peek`): copy-on-read, with
writes kept in a private overlay. Results are frozen dataclasses of plain, bounded values. No
DataFrames are returned, except the existing `TradeEvaluation.category_table`.

- **Network:** none of the readers can sync, fetch or reach the network (tested with the shared
  store, the lineup stats loader and `requests` patched to fail).
- **Mutation:** none of them can change state. Dict and proxy-like sessions stay byte-identical,
  and an audit hook records no file writes.

| Reader | Input | Output (main fields) | Authorization | Page parity source | Tests |
|---|---|---|---|---|---|
| `player_owner(session, player)` | a name (any case or accents) | `status` (your_team / other_team / free_agent / no_league), `owner_team`, `my_team`, `player`, `rostered`, `in_loaded_pool` | league-wide; rosters are public within the league | `build_ownership_map` (trade proposals' owner lookup) + `fantasy_waiver_wire.is_player_rostered` (Confirm Waiver Move's check), with accepted trades reconciled | equals both validators for every pool player; follows a real waiver move; the validator then rejects the same player |
| `week_lineup_status(session, team="", week=None, roster_stats=None)` | team (default yours), week (default: the Lineup page's week) | `status` ("Not saved yet" / "Draft (not submitted)" / "Saved and locked" / "Locked"), `record_status`, `locked`, `edit_message`, `period_status`, `slots`, `assignments`, `open_positions`, `from_bench`, `needs_waiver_or_trade`, `not_eligible`, `assigned_twice`, `complete`, `headline` / `body` / `tone`, `roster_loaded`, `acting_as` | `team_access().can_manage` | `fantasy_weekly_lineup.lineup_week_state` + `lineup_status_answer`, which the Lineup page now calls | all three statuses; equals the page answer for three boards; ineligible starters match `check_lineup`; proxy; claimed; season-calendar week; no stats loaded |
| `waiver_recommendations_view(session, team="", position="All positions", limit=3)` | team, the page's position filter, 1–15 cards | `headline` (needs) and `body` (as on the page), `weak_categories`, `category_ranks`, `team_count`, `open_roster_spots`, `adds` (rank, player, positions, eligible_positions, mlb_team, why, stat_line, comparison, fills_open_spot, stats), `drops` (rank, player, positions, why, stats) | `can_manage` | `fantasy_waiver_wire.waiver_team_frames` / `compute_waiver_recommendations` / `waiver_open_slots` / `waiver_card_fields` / `apply_waiver_position_filter`, which the Waiver Wire page now calls | equals what the **real Waiver Wire page** passes its answer card (captured) for All, C and OF; every add is unrostered; proxy; claimed; no stats loaded |
| `loaded_player_pool(session, position=, query=, unrostered_only=True, limit=25)` | filter, name search, at most 100 rows | `total`, `rows` (player, mlb_team, positions, stats), `loaded_at` | own session | `loaded_waiver_stats_pool` + `build_waiver_pool` | equals `build_waiver_pool`; bounded; position and name filters; no stats loaded |
| `evaluate_trade_for_team(...)` (extended) | as before, plus optional `standings` | adds `verdict_label`, `value_label`, `verdict_headline`, `verdict_body`, `verdict_tone`, `roster_issues` (team, kind, slot, message), `required_position_issues`, `roster_size_issues`, `open_roster_spots`, `other_team_notes`, `category_changes`, `helps` / `hurts`, `positions_lost` / `positions_gained`, `analysis` | `can_manage` (unchanged) | `build_trade_analysis_package` + `trade_roster_issues` + `u3_answers.trade_verdict`, on Trade Center's own inputs (loaded standings and hitter pool) | equals **Trade Center's** card, built from its own `_trade_workspace` / `_trade_roster_issues`, on 4 trades; existing fields unchanged without loaded standings |
| `pending_trade_draft(session, team="")` | team (default yours) | `give`, `receive`, effective `partner`, `source` (builder / saved_state / none), `pending_update`, `is_complete`, `last_analysis` | `can_manage`; only your own builder (commissioner proxy trades live in Commissioner Tools) | `fantasy_trade_builder_state.trade_scope_fingerprint` / `trade_scope_state_key` / `read_builder_selection` (Trade Center now uses the same key functions) | the key equals Trade Center's own `_resolve_trade_scope`; widget and saved-state paths; feeds `evaluate_trade_for_team` |
| `week_view(session, number=None, team="")` | week (default current), team | `label`, `dates`, `status` / `status_label`, `finalized`, `current_week`, `last_finalized_week`, `weeks`, `categories`, `category_table`; for a team: `team_lineup` (starters with slot, eligibility and owner at snapshot; bench; empty slots; set_after_lock), `team_result` (totals, rates, starters with `matched_by`) | another team's lineup only after its week starts; no user ids or audit log | `fantasy_season_ledger` + `fantasy_season_results` | equals `period_result`, `period_category_table` and `get_period_lineup`; `matched_by` explains a no-games starter; private before the start; unknown team; no calendar |

**`team_access` fix.** `resolve_team_control` gave commissioner proxy to any unknown name, which
fell through to the unclaimed-team rule. A team must now be one of the league's roster keys
(`league_team_names`). A league with no rosters yet falls back to its own team and its
ownership records. Otherwise the result is `mode=none`, "X is not a team in this league".

The fix is in the shared layer, so lineup saves, waiver moves and trades inherit it. Tested:

| Case | Result |
|---|---|
| Owned team | manageable (owner) |
| Unclaimed team, commissioner | manageable (proxy) |
| Team claimed by another manager | refused |
| Invite-reserved team | refused |
| Nonexistent team | refused, including in a mock league where everyone is commissioner |
| Waiver move for a nonexistent team | refused, rosters unchanged |

**Plan-feature metadata** (`baseball_monetization`). Nothing is enforced.
- `ENFORCED_FEATURES` is an empty frozenset.
- `enforced_features()` returns the page features plus the feature-level ones.
- `CAPABILITY_FEATURES` maps shared capabilities to existing `FeatureId`s:
  - draft recommendations, recommendation explanation and team needs → advanced draft
    intelligence;
  - Draft Lab simulation → Draft Lab;
  - ML predictions → ML Predictions.
- `entitlement_for_capability()` applies the page gate's `can_use_feature` only while a feature
  is enforced, and fails closed when the snapshot isn't ready.
- AMI already reads `ENFORCED_FEATURES` via `getattr`.
- The fantasy readers are not plan features.

## 2. WEB-M2 contract

Unchanged:
- `git diff 5ca7a26 32a6fef -- baseball_api baseball_history.py u1_answers.py
  rate_stat_qualification.py draft_player_names.py requirements-api.txt` is empty.
- The OpenAPI document this branch serves equals the web branch's pinned
  `web/openapi/baseball-api.json` (`api_commit 5ca7a26`, web tip `3a5ca94`).

## 3. Regression against `5ca7a26`

The run covered the focused suites: fantasy, trade, waiver, lineup, monetization/billing, read
API, peek, team control, season, U1–U4, web_m2 / web_prep, draft, live, ownership, workspace,
commissioner, standings, roster, eligibility, position. Each file ran in its own process, on
scratch checkouts with the no-op storage shim.

| Side | Files | Passed | Failed | Crashed files |
|---|---|---|---|---|
| `5ca7a26` | 326 | 2,665 | 155 | 5 |
| this branch | 327 (+ `test_ami_shared_readers.py`) | 2,685 | 151 | 5 |

- **150 fail on both sides:** pre-existing.
- **Reported new on this branch (4):**
  - three Live Draft files whose XML was unparseable (the process crashed);
  - one Live Draft latency stress test (pick blocked 3.96 s, limit 3 s).
  - This slice touches no Live Draft code, and both suites ran under memory pressure. Re-run
    on a quiet machine, both sides give **identical** results on those four files: the same 2
    pre-existing `setup_validation` failures, and the stress test passes on both.
  - These are timing and environment flakes, not regressions.
- **Reported fixed on this branch (5):** the same fluctuation in reverse (AppTest timeouts,
  latency budgets, setup_validation).
- **API:** `test_web_m2_api` (21) + `test_web_prep_api` (15) = the **36 accepted API contract
  tests pass on both sides**, as do `test_web_prep_api_parity` (6, AppTest) and
  `test_web_prep_history_parity` (5). No endpoint code changed, so no endpoint behaviour
  changed.

## 4. Behavioral integration

Combined scratch tree: this branch + `feature/ami-foundation @ ff46ff6` + `web/nextjs-foundation
@ 3a5ca94` + billing `72d36c6`, built in a detached scratch worktree. The `streamlit_app.py`
conflict was resolved there only, by keeping the regular side of its 5 hunks. The same 96
selected test files (AMI, read API, shared fantasy, monetization/billing, web_prep/web_m2,
U1–U4, team control, waivers, trades, lineups, season) ran on each tree.

| Tree | Passed | Failed / errors |
|---|---|---|
| Combined | 968 | 53 + 1 error |
| AMI alone (`ff46ff6`) | 867 | 45 + 1 |
| Billing alone (`72d36c6`) | 555 | 39 + 1 |
| Readers alone (`32a6fef`) | 852 | 45 + 1 |

Of the 54 combined failures:
- **40 are pre-existing:** they fail on every line that has the test. Trade-offer inbox,
  AMI blob persistence and position pool, Lineup render-structure and weekly-lineup smoke,
  waiver persistence, and others.
- **0 exist only in the combined tree.**
- **14 pass on some line but fail combined.** Every one is explained:

| Test(s) | Line it passes on | Cause | Owner |
|---|---|---|---|
| `test_ami_assistant_fantasy::test_a_team_must_exist_before_access_is_trusted` | AMI | It asserts the old bug (`team_access(..., "Nope").can_manage` is True). Its `UNKNOWN_TEAM` guard checks still pass. | AMI: flip that one assertion |
| `test_ami_assistant_help::` every_how_to_step / every_listed_control / home_help_buttons (3) | AMI | U4.5 label changes: "Set Lineup", "Waiver Wire", "League Standings". Already listed in `docs/U4_UI_CONSOLIDATION.md` §AMI reconciliation | AMI page help (exists at `5ca7a26` + AMI already) |
| `test_ami_assistant_help::test_load_data_delegates_to_lahman_data` | AMI | pins AMI's `load_data` body; the scratch resolution kept `baseball_history` | consolidation (§5) |
| `test_ami_assistant_tools::` leaderboard / position-leaderboard parity (2) | AMI | AMI's `monolith_functions` compiles `safe_round_rate_stats` out of `streamlit_app.py`; WEB-PREP1 moved it to `baseball_history` | consolidation (§5) |
| `test_fantasy_league_lineup_format::WaiverPositionFilterTests` (6) | billing only | test-order pollution. In one shared pytest process a leaked `st` mock reaches `app_tutorial.py:258` (`TypeError`) on every U1+ tree (AMI alone and readers alone too). Alone the file passes **27/27** in the combined tree, and per-file it passes on `5ca7a26` and on this branch | test isolation (pre-existing), not a merge conflict |
| `test_web_prep_api_parity::test_leaderboards` | readers | AppTest found no table while the machine ran two suites; passes on a clean re-run in the combined tree (1 passed, 12 subtests) | timing flake |

No state or persistence test changed outcome because of merging. The persistence failures
(`test_ami_blob_persistence`, `test_fantasy_in_season_persistence`, waiver filter persistence)
fail identically on their own lines.

**Ancestry and textual conflicts** (`git merge-tree`, nothing written):
- shared-functions `ec1dfcd`, U4/WEB-PREP `a9a80f7`, the API `5ca7a26`, `dev` (`56820e6`) and
  `origin/dev` (`763001b`) are ancestors of this branch.
- AMI diverged at `4bc3d30` (7 vs 13 commits); web diverged at `4bc3d30`; billing `72d36c6` is
  one commit on `2f083eb`, already in this line.

| Pair | Textual conflicts |
|---|---|
| readers + AMI | `streamlit_app.py`, 5 hunks. The same set exists at `5ca7a26`; this slice adds none |
| readers + web, readers + billing, AMI + web, AMI + billing, web + billing | none |

Web changes only `web/` and docs.

**Ownership/auth.** The `team_access` fix agrees with AMI's own `UNKNOWN_TEAM` guard (AMI checks
the league first). No other ownership or auth code differs between the lines.

**Integration base:** `quality/ami-shared-readers`, which contains shared-functions, U1–U4,
WEB-PREP, the accepted API and these readers. Merge AMI into it with the §5 resolution, then
web, then billing `72d36c6`. All three merge cleanly apart from `streamlit_app.py`.

## 5. Lahman/history layer: `lahman_data.py` (AMI) vs `baseball_history.py` (regular)

Both were extracted from the same `streamlit_app.py` code. AMI did it in `dea3bdc`, the
regular line in WEB-PREP1 `711daa7`.

**Responsibility.**

| Concern | `lahman_data.py` (256 lines) | `baseball_history.py` (448 lines) |
|---|---|---|
| Data loading | `build_lahman_frames(read_csv, base_dir)` + `read_lahman_csv(base_dir)` | `load_history_frames(base_dir, *, read_csv=None)`, with a default reader |
| Lahman tables | People, Batting, Fielding, Hall of Fame (via `hall_of_fame_data`) | the same |
| Schema normalization | team-id mapping, historical names, numeric coercion, grouped positions, season/career primary position, `teamName` / `teamLeague` | identical code |
| Season aggregation | `yearly` grouped `dropna=False` (keeps Negro Leagues and unknown-birth players), primary team, PH/PR rows dropped | identical code |
| Derived columns | `add_rate_stats` (1B, BA, OBP, SLG, OPS), `add_missing_numeric_columns` | identical |
| Player lookup | none | `build_clean_player_label_map` (labels disambiguated by career span) |
| Filtering | none | `historical_rows` (Historical Explorer filters), `apply_stat_minimums`, `STAT_MINIMUM_COLUMNS` |
| Aggregation helpers | none | `aggregate_player_year_team`, `aggregate_player_year_primary_team`, `safe_round_rate_stats`, `add_leaderboard_score`, `RATE_STATS` |
| Caching | none (AMI caches in `ami_assistant/data.py`: `lru_cache(maxsize=1)` + a fingerprinted dict) | none (the app wraps it in `st.cache_data`; the API caches it in `HistoryStore`: a process-level lock, a preload thread, 503 + Retry-After while loading) |
| Streamlit dependency | none | none |
| Errors (missing file) | `FileNotFoundError` from `pd.read_csv` | `HistoryDataMissing`, a `FileNotFoundError` subclass the API maps to 503 |

**Consumer graph.**

| Module | Accepted consumers |
|---|---|
| `baseball_history` | `streamlit_app.py` (`load_data`, Historical Explorer `historical_rows`, Leaderboards `add_leaderboard_score`, label map, minimums, aggregators); **`baseball_api/services.py`, the accepted WEB-M2 path**; `tests/test_web_prep_history_parity.py` |
| `lahman_data` | AMI only: `ami_assistant/data.py` (the standalone loader), `tools/stats.py`, `tools/value.py` (`add_rate_stats`), `glossary.py` (source strings), AMI's `streamlit_app.py` `load_data`, `tests/ami_assistant_fixtures.py`, `test_ami_assistant_help.py`, `test_ami_assistant_tools.py` |

No background helper imports either module.

**Output parity on the real Lahman data.** Each loader ran in its own process (scratch
`qa/lahman_parity.py`).

| Case | Result |
|---|---|
| `batting` (128,598 × 43), `yearly` (118,184 × 38), `people` (24,270 × 11) | **byte-identical**: same content hash, `assert_frame_equal(check_exact=True)` |
| Modern hitter `judgeaa01`, pitcher `kershcl01`, long career `henderi01` (25 seasons, 29 stints), two-way `ohtansh01` | byte-identical (seasons and stints) |
| Missing demographics `acea01`, `adams01`, `addiske01` | byte-identical |
| Negro Leagues `charlos99` (27 seasons), `paigesa01` (24) | byte-identical |
| 2020 shortened season (1,289 rows) | byte-identical |
| 2015–2020 range totals + `add_rate_stats` (2,688 players) | byte-identical |
| All 3,613 team-id/year pairs through `team_league` / `historical_team_name`; every constant | identical |
| Nonexistent id `nobody99zz` | 0 rows from both |
| Ambiguous name ("Frank Thomas") | only `baseball_history` has a lookup: "Frank Thomas (1951-1966)", "Frank Thomas (1990-2008)" |

**Unique functionality.**
- `baseball_history` is a strict superset of `lahman_data`'s behaviour.
- `lahman_data`'s only unique items are two names:
  - `build_lahman_frames(read_csv, base_dir)`: the same body as
    `load_history_frames(base_dir, read_csv=read_csv)`;
  - `read_lahman_csv(base_dir)`: a plain reader, already covered by the default reader.
- Neither carries real unique logic. Both belong in the canonical module as, at most,
  compatibility names.

**Cache and performance.** One load takes 24.1 s (regular) vs 25.6 s (AMI), with 177 MB RSS
after load for both, measured on the loaded machine. Neither module caches or imports
Streamlit. Consolidating changes no cache: the app's `st.cache_data`, the API's `HistoryStore`
and AMI's own dataset cache stay where they are. In the app, AMI gets the already-loaded
`yearly_df`, so there is no second load.

**Dependency direction and recommendation.** Make **`baseball_history` the canonical
history/Lahman layer.**
- It is the data/source layer under both the Streamlit pages and the accepted, frozen API.
- It is a strict superset of `lahman_data`.
- It has the typed missing-data error the API relies on.

`lahman_data` exists only for AMI's needs. Keeping it as a second implementation would leave
two places to change the same loader.

**API impact of consolidating:** none. The API already uses `baseball_history` and its code is
untouched. Endpoint values, OpenAPI, `/catalog`, CSV, qualification, player ids, ordering and
serialization are unaffected. Moving AMI's imports changes no frame (shown byte-identical
above).

**AMI changes needed later** (not made here):
1. `ami_assistant/data.py`: `_frames` calls `baseball_history.load_history_frames(Path(base_dir))`
   instead of `build_lahman_frames(read_lahman_csv(...), ...)`. A missing file then raises
   `HistoryDataMissing`, still a `FileNotFoundError`.
2. `ami_assistant/tools/stats.py`, `tools/value.py`, `tests/ami_assistant_fixtures.py`,
   `tests/test_ami_assistant_help.py`, `tests/test_ami_assistant_tools.py`: import
   `add_rate_stats` from `baseball_history`.
3. `ami_assistant/glossary.py`: the four source strings become `baseball_history.add_rate_stats`.
4. `tests/ami_assistant_fixtures.monolith_functions`: names moved out of `streamlit_app.py`
   (`safe_round_rate_stats` and the other WEB-PREP1 moves) come from `baseball_history`, not
   from the app source.
5. `test_load_data_delegates_to_lahman_data` becomes a pin on
   `return _history.load_history_frames(BASE_DIR, read_csv=read_required_csv)`.

No AMI prompt or tool depends on a different normalized shape, since the frames are
identical.

**Exact future `streamlit_app.py` resolution** (5 hunks, AMI merged into this branch):

| Hunk | Region | Resolution |
|---|---|---|
| 1, 2 | the import block | keep `import baseball_history as _history` and `from baseball_history import (...)` with the regular name list (it includes `build_clean_player_label_map`, `safe_round_rate_stats`); drop `from lahman_data import (...)` |
| 3 | leftover blank lines / the team-context comment after the imports | take AMI's side (the comment documents constants that now live in the module) |
| 4 | blank lines before `apply_stat_min_filters` | either side (whitespace) |
| 5 | `load_data` | keep `return _history.load_history_frames(BASE_DIR, read_csv=read_required_csv)` |

Keep every other AMI change in the file, which merges without conflict (for example
`from page_guides import PAGE_GUIDES` and the AMI panel wiring). Retire `lahman_data.py` only
after AMI's suites pass on the canonical module. It can briefly stay as a re-export shim
(`build_lahman_frames = lambda read_csv, base_dir: load_history_frames(base_dir, read_csv=read_csv)`
plus re-exported names), but it must not stay a second copy.

## 6. Remaining integration blockers

1. The Lahman consolidation (§5) and its 3 AMI test updates.
2. AMI page help for the U4.5 labels: 3 tests.
3. AMI's `team_access` test asserts the old bug: 1 assertion.
4. Not a merge problem:
   - `WaiverPositionFilterTests`' order-dependence in a shared pytest process (an `st` mock
     leaking into `app_tutorial`);
   - the other 40 pre-existing failures, unchanged from their own lines.
