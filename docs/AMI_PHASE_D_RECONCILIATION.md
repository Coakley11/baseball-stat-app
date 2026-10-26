# AMI ↔ Phase D / shared functions / U1 reconciliation

Branch `feature/ami-foundation`. Starting point `6ef7471`. This checkpoint is **read-only**:
it adds no tool that saves, drafts, queues, adds, drops, trades, finalizes or acts as
commissioner.

## 1. What was merged, and how

| Step | Commit | Source | Method | Conflicts |
|---|---|---|---|---|
| 1 | `233e9c0` | `quality/shared-functions @ ec1dfcd` (Phase D up to `38d1e3e`, plus the shared-function extraction and integration review) | `git merge --no-ff` | none (`git show --remerge-diff` is empty) |
| 2 | `c5f3e08` | `ui/u1-foundation @ 06acd43` (U1A–U1D) | `git merge --no-ff` | none |
| 3 | this checkpoint | AMI-side reconciliation (this document) | normal commit | — |

History was not rewritten. No other branch was changed: `dev`, `quality/shared-functions` and
`ui/u1-foundation` are where they were.

## 2. The four known merge-test fixes (from `docs/PHASE_CD_INTEGRATION_REVIEW.md`)

| Test | Fix |
|---|---|
| `test_ami_assistant_help::test_every_listed_control_exists_on_its_page` | The Standings help entry now lists the real D5/U1 controls: **League Standings (official)**, **Completed week**, **Set lineup / Check waivers / Explore trades**, and **How current rosters would rank (not official standings)**. Its sources now include `league_home_ui.py`, `fantasy_season_results_ui.py` and `fantasy_standings_snapshot.py`. |
| `test_ami_assistant_help::test_every_how_to_step_uses_real_controls` | The "Check league standings" how-to was rewritten around official standings first, with the current-roster what-if under Explore more. |
| `test_ami_assistant_tools::test_valuation_page_pipeline` | `tools/value.valuation_pool` now calls `valuation_scores.valuation_hitter_pool`, the same function the Valuation page calls (D7: window AB ≥ 10). |
| `PagePipelineStrictPinTests::test_valuation_pipeline_is_exactly_known` | The strict pin was re-frozen from the page source: `agg_value = valuation_hitter_pool(agg_value[agg_value["G"] >= min_g_value])`. |

The pins are not hand-edited numbers. They are the page's own step lines, and the parity tests
re-run the page's functions (extracted from `streamlit_app.py`) next to AMI:

- `test_valuation_scores_equal_the_page_pipeline`: Valuation, Current and Trend scores are equal
  to 1e-12 for two windows and weightings. The pool rows match in count, and ranks are equal
  (`rank(method="min")` on Valuation_Score).
- `test_hitter_pool_excludes_pitchers_and_keeps_two_way_ohtani`: the D7 rule drops more than 100
  players with fewer than 10 window AB, and none of them is in AMI's pool. Every pool row has
  AB ≥ 10. `ohtansh01` stays in the pool. A dropped pitcher gets `not_in_pool`, and the
  message cites both games and at-bats.

Old names are still understood: "Open Fantasy Standings", "fantasy standings tracker",
"live fantasy standings" and "League Standings" all resolve to the `Fantasy Standings Tracker`
key. AMI shows the page under its current label, **League Standings**.

## 3. Shared interfaces AMI now consumes

AMI computes no fantasy statistic of its own. Every tool reads the league through
`fantasy_league_peek` (an isolated copy of the session), either directly or via
`fantasy_read_api`.

| AMI tool | Authoritative source |
|---|---|
| `get_active_league` | `fantasy_read_api.active_league`, `team_access`; the current week from `fantasy_season_ledger` (on the peeked copy) |
| `get_official_standings` | `fantasy_read_api.official_standings_view`; the strengths and closest-gain phrases come from `u1_answers.category_strengths_and_gaps`, the League Standings chips; categories from `fantasy_season_results.scoring_categories` |
| `get_current_roster_standings` | `fantasy_read_api.loaded_roster_stats` + `current_roster_standings_view` |
| `get_week` | `fantasy_season_ledger.get_period / period_status / period_date_label`, `fantasy_season_results.period_result / period_category_table` |
| `get_week_lineup` | `fantasy_season_ledger.get_period_lineup` (the immutable weekly snapshot) |
| `explain_player_week` | `get_period_lineup` + `period_result` (who started, `matched_by`, bench) |
| `get_lineup_report` | `fantasy_read_api.lineup_report` |
| `check_slot_eligibility` | `fantasy_read_api.explain_slot_eligibility` |
| `find_eligible_players` | `explain_slot_eligibility` per rostered player + the current week's saved snapshot |
| `evaluate_trade` | `fantasy_read_api.evaluate_trade_for_team`; the optional slot check uses `explain_slot_eligibility` |
| `get_waiver_recommendations` | **not wired** (see §8) |

Help and metadata sources: `nav_groups.NAV_LABELS / PAGE_SECTION / HOME_PAGE`, `home_page.TASKS`,
`ui_hierarchy` page headings (pinned by tests), `page_guides.PAGE_GUIDES`,
`fantasy_read_api.OFFICIAL_BASIS / SNAPSHOT_BASIS / ELIGIBILITY_RULE`,
`fantasy_standings_snapshot.SNAPSHOT_LABEL`, the `suggested_lineup.py` docstring, and the
Waiver Wire "Consider add" caption (quoted verbatim and pinned).

## 4. Supported fantasy questions

| Kind | Examples | Tool |
|---|---|---|
| Official standing | "Where am I in the standings?", "What place am I in?", "How far am I from first?" | `get_official_standings` |
| Gains | "Where could I gain a roto point?", follow-up "Where can I gain points?" | `get_official_standings` (closest gaps) |
| Category strengths | "What categories am I strongest / weakest in?" | `get_official_standings` |
| Current-roster what-if | "How would my current roster rank right now?" | `get_current_roster_standings` |
| Official vs current | "What's the difference between official standings and current roster rankings?" | glossary (`OFFICIAL_BASIS` / `SNAPSHOT_BASIS`) |
| Week | "What happened last week?", "Has this week been finalized?", "How did I do in Week 1?" | `get_week` |
| Week lineup | "Who was in my Week 1 lineup?" | `get_week_lineup` |
| Player in a week | "Why didn't Juan Soto count last week?" | `explain_player_week` |
| Lineup | "Who should I start this week?", "What's on my bench?" | `get_lineup_report` |
| Empty slots | "Which positions are empty?", "Which position needs the most help?" | `get_lineup_report` |
| Eligibility | "Can Springer play 3B?", "Why can't Springer play this slot?", "Can this player play shortstop?" | `check_slot_eligibility` |
| Who can fill a slot | "Do I have an eligible shortstop?", "Anyone on my bench who can help at shortstop?" | `find_eligible_players` |
| Trade effect | "Would trading Cal Raleigh for Kyle Tucker leave me without a catcher?", "What does trading X for Y do to my roster?" | `evaluate_trade` |
| League | "Which league am I in?", "Am I the commissioner?" | `get_active_league` |

Follow-ups reuse the same league and team, resolved fresh every turn. The conversation
remembers the slot, the player discussed and the week: "this player", "this slot" and
"What about waivers?" (which carries the slot over).

## 5. Behaviour rules

**Official vs current roster.** "Standings", "place", "rank" and "how far from first" always
mean the **official** standings (sum of finalized weeks). Only an explicit "current roster" or
"would rank" question gets the snapshot. Each result carries the API's `kind` and `label`, and
the answer's source line repeats that label. With no finalized week, the answer says
"No week is final yet." and *offers* the current-roster what-if; it never substitutes it.

**Weeks.** "Last week" means the most recent finalized week, and the answer says so. A week's
status is the ledger's own (upcoming / active / locked / finalized). Finalized weeks are
described as unchangeable. Another team's lineup for a week that hasn't started stays private.

**Commissioner access.** Every team-perspective tool resolves `team_access` and reports
`mode`:

- owner: no extra line;
- `commissioner_proxy`: "You're viewing Team C as commissioner; the team is currently
  unclaimed." The answer says "Team C is…", never "You're…";
- none: lineups, trades, the per-player week explanation and slot search are refused
  (`not_your_team`). League-wide data (standings, a started week's lineup) stays readable.

The shared `team_access` treats an unknown team name like an unclaimed one, so AMI first checks
that the team is in the league (`unknown_team`).

**Eligibility.** Only `explain_slot_eligibility` / `check_lineup` decide. A test checks every
rostered player × every slot against `check_lineup` (Save Lineup's validator). Nothing is
inferred: Raleigh (C, 1B) can play 1B and can't play 3B; Judge can't play SS.

**Trades.** Evaluation only. The answer gives the verdict, the proposal rule check, roster and
lineup warnings, and optionally who could still fill a slot afterwards. It ends with "AMI only
evaluates; propose trades in Trade Center." "This trade", meaning the one being built in Trade
Center, can't be read yet (§8), so AMI asks for the player names.

**Instructions are refused.** "Use suggested lineup for me", "Finalize week 2", "Lock my
lineup", "Drop Aaron Judge" and "Trade Judge for Tucker" are refused, with the steps to do it
in the UI. "What does Use Suggested Lineup do?" is answered with: *fills the editable lineup
with the recommended starters; does not save, lock or finalize; review it, then press Save
Lineup.*

## 6. Context object

`AmiPageContext.league` exists on Home, League Standings, Lineup, Waiver Wire and Saved Draft
Library only. It holds `{league_name, my_team, access_mode, week_label, week_status}`, comes
from `league_brief` (via the peek) and is secret-screened. The "Looking at:" line shows, for
example, "League Standings · QA · Team A · Week 2 locked". A commissioner viewing an unclaimed
team gets "(commissioner view, unclaimed)". No session dump, tokens, billing IDs or raw
storage objects reach the context. Standings positions are not cached in the context; they are
read fresh on each question.

## 7. U1 awareness and suggested questions

- **Home** has its own help entry. It lists the task cards from `home_page.TASKS` (title, line,
  button) and the league actions. Example questions: "What can I do here?", "Where should I go
  to compare players?", "How do I manage my league?", "Where do I start a draft?"
  (`manage_league` / `start_draft` how-tos).
- **Navigation** names the U1 section and label ("In the sidebar, under **My League**, choose
  **League Standings**"; phone: the Section pills, then "Jump to page"). Page identity is the
  page key, never a heading.
- **Explore more** is described for Historical Explorer, Leaderboards, League Standings and
  Waiver Wire. Each of those pages' `headline` is pinned to its source.
- **League Standings**: official first, then Set lineup / Check waivers / Explore trades, then
  the current-roster what-if under Explore more.
- **Waiver Wire**: the recommendation cards (**Consider add**, **Compare**, **See trend**).
  Consider add only puts the player in the move planner.
- **Suggested questions**: `PageHelp.questions`, read through `ui.suggested_questions(page)`.
  They already drive the panel placeholder and are meant for the future sidebar Ask AMI box,
  the phone header entry and question chips. A test routes every suggested question on every
  page and fails on any "please rephrase".
- Not changed (U5 owner): Home's "Ask a question" card still says to use the **Baseball
  Insight** box. Once the single Ask AMI UI lands, it should point to Ask AMI.

## 8. Interfaces still missing (needed from the regular branch)

AMI does not parse persistence internals to fill these gaps. The U2/U3 slice adds
`week_lineup_status` and `roster_issues` to this list; the current list is in
`docs/AMI_U2_U3_RECONCILIATION.md` §7.

1. **Waiver reader.** `fantasy_read_api.waiver_recommendations_view(session, team, position=None)`
   returning the Waiver Wire's own ranked adds and drops
   (`fantasy_waiver_wire.recommend_adds_personalized` / `recommend_drops_current` on the
   page's waiver pool), each card's reason text, and the team's biggest need; plus
   `loaded_player_pool(session)` for the unrostered players the page loaded. Until then,
   "Why is this waiver player recommended?" and "What about waivers?" say AMI can't read the
   recommendations and give the page steps. These answers are labelled **App help**, since no
   league data was read. Roster needs (empty slots, weakest areas) are answered from
   `lineup_report`.
2. **Trade Center draft.** `fantasy_read_api.pending_trade_draft(session, team)`, for the
   give/receive lists currently built in Trade Center. It would let "Would this trade leave me
   without a catcher?" work without naming players. Gate it on `team_access(...).can_manage`.
3. **Week view.** `fantasy_read_api.week_view(session, number, team)`, returning period info,
   the category table, the team's totals and rates, the lineup snapshot and per-starter
   `matched_by`. AMI currently calls the ledger's public read functions on the peeked copy,
   which ties it to the shape of `period_result`.
4. **Player ownership.** `fantasy_read_api.player_owner(session, player)`
   (= `fantasy_league_context.build_ownership_map`). AMI derives "on Team B's roster now" from
   the peeked `league_rosters`, because AMI's safety test bans importing `fantasy_league_context`.
5. **Small API notes:** `team_access` could reject team names that aren't in the league. The
   `loaded_roster_stats` hint still says "Open Fantasy Standings Tracker"; AMI shows its own
   wording, "League Standings … How current rosters would rank".

## 9. Read-only guarantees and tests

- No tool name contains save / use_suggested / draft_player / queue / add_waiver / drop /
  accept / propose / execute / finalize / commission / claim / set_ / submit / delete / rename
  / activate (`test_no_tool_can_change_the_app`). `ToolRegistry.register` still refuses
  `mutates=True`.
- The package may not import `fantasy_league_context`, `resolved_fantasy_context`,
  `fantasy_weekly_lineup`, `suggested_lineup`, `fantasy_team_control`, `fantasy_trade_legality`,
  `draft_archive_state`, or any storage, auth, billing, network or model SDK (static AST
  test). League state goes only through the peek and the read API.
- Side effects: every fantasy tool, on a dict session and on a `SessionStateProxy`-like
  mapping, leaves the session byte-identical (pickle). So do twelve fantasy questions,
  including the refused instructions; only the conversation key changes.
- Missing states are tested: no active league, no season calendar, no finalized week, no
  loaded roster stats, unknown team, another manager's team, commissioner viewing an
  unclaimed team.

## 10. Verification

- **AMI + shared + U1 suites** (`test_ami_assistant_*`, `test_fantasy_read_api`,
  `test_fantasy_league_peek`, `test_shared_fantasy_functions`, `test_valuation_scores`,
  `test_u1_*`): 182 passed.
- **Full suite** (`pytest tests --continue-on-collection-errors`): 4,915 passed, 257 failed,
  13 collection errors. Baseline at `06acd43`: 4,807 passed, 263 failed, 13 errors. No test
  fails here that passed in the baseline; six baseline failures pass here. The 13 collection
  errors are modules missing from this checkout (e.g. `music_resume_payload`) in both runs.
- **Browser** (Playwright, 1280 / 430 / 390 / 360 px, zero page or sidebar horizontal overflow):
  - the full app: 25 questions (Home, standings, official vs current, gains, eligibility, Use
    Suggested Lineup, "this trade", waivers, Compare Judge and Soto, Valuation). Its local
    workspace held a league with no season calendar, so standings answered "no official
    standings yet" honestly.
  - a scratch harness rendering the real AMI panel over the 3-team test league: 40 questions
    with real standings, gains, the what-if, eligibility, follow-ups and trade answers.
  - About 1–2.5 s per question end to end in the browser, after a one-time ~20 s cold load of
    the dataset. In the engine itself, fantasy tools take 70–250 ms and help answers under 10 ms.
