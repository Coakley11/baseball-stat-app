# Shared fantasy interfaces (for AMI and other read-only consumers)

The fantasy calculations that used to live only inside `streamlit_app.py` are now importable
modules. The page imports them back, so the page and any consumer run the same code.

**Use `fantasy_read_api` first.** It is the stable surface. Every number it returns comes from
the modules listed below. It never writes the session, fetches data or changes a league.

## Rules for consumers

1. **Two kinds of standings, never mixed.**
   - **Official standings** (`kind="official"`, label "League Standings (official)") are the
     sum of finalized weeks. These are the league's standings.
   - **Current Roster Snapshot** (`kind="current_roster_snapshot"`, label "Current Roster
     Snapshot (not official standings)") scores today's rosters on season-to-date stats.
     It is for analysis only. Always say it is not the standings.
2. **No network.**
   - Read the stats a page already loaded (`loaded_roster_stats`). If they are missing,
     tell the user to open Fantasy Standings Tracker.
   - Never call `fetch_*`, `eligibility_for_season` or the shared-league sync.
3. **Team access.** Before showing team-private data or advice from a team's point of view,
   check `team_access(session, team).can_manage`. That covers the owner, or the commissioner
   acting for an unclaimed team (`.is_proxy`). `evaluate_trade_for_team` enforces this itself.
4. **No writes.** Lineup saves, waivers, trades and finalization stay in their UI flows.
   Each has a canonical function and authorization checks; see
   `docs/FANTASY_LEAGUE_DATA_MODEL.md`.

## `fantasy_read_api` contracts

| Function | Inputs | Returns | Source of truth | Authorization |
|---|---|---|---|---|
| `active_league(session)` | session | `LeagueSummary` or None: id, name, my team, team names, scoring format, lineup slots, `has_season_calendar`, `finalized_weeks`, `source_kind`, `context_fingerprint`, `coherent` | `fantasy_league_peek` (the page resolvers, isolated) | none (own session only) |
| `official_standings_view(session)` | session | `StandingsView(kind="official")`: table, `finalized_weeks`, `note` (no calendar / no final week) | `fantasy_season_results.official_standings` | league member (own session) |
| `current_roster_standings_view(roster_stats, scoring_format)` | roster frame with `Team`, `Player`, HR/RBI/R/SB/BA/OPS (+H/AB for team BA) | `StandingsView(kind="current_roster_snapshot")` | `fantasy_standings_snapshot.score_current_roster_standings` | league member |
| `loaded_roster_stats(session)` | session | `(frame, loaded_at)`; empty frame if no page loaded stats | session key `fantasy_current_roster_stats` (written by Standings) | own session |
| `team_access(session, team)` | session, team | `TeamControl`: `mode` owner / commissioner_proxy / none, `can_manage`, `is_proxy`, `reason` | `fantasy_team_control.resolve_team_control` | n/a (it *is* the check) |
| `evaluate_trade_for_team(session, my_team=, partner_team=, give=, receive=, roster_stats=, scoring_format=)` | names, loaded roster stats | `TradeEvaluation`: `allowed`/`reason`, `category_table`, `verdict`, `weighted_gain`, `verdict_text`, `proposal_ok`/`proposal_message`, `legality_warnings`, `acting_as`, `basis` | `fantasy_trade_evaluation` (value), `fantasy_trade_proposals.validate_proposal_players` (rules), `fantasy_trade_legality.trade_roster_warnings` (roster/lineup consequences) | **enforced:** `my_team` must be manageable, otherwise `allowed=False` and nothing is computed |
| `lineup_report(team_roster_stats, slots=, scoring_format=, custom_weights=, rate_col=, league_roster_df=)` | one team's roster frame | dict: `scored`, `recommended`, `missing_slots`, `slot_warnings`, `diagnosis`, `basis` | `fantasy_lineup_scoring` | caller scopes frames |
| `explain_slot_eligibility(player_row, slot)` | roster row (needs `Eligible Positions` for multi-position players) | dict: `eligible`, `eligible_positions`, `rule`, `reason` | `fantasy_weekly_lineup.player_eligible_for_slot` (the rule Save Lineup enforces) | none |
| `check_lineup(slots, assignments, roster_df)` | slots, slot→player, roster frame | `validate_weekly_lineup` result: `ok`, `missing_slots`, `ineligible_slots`, `duplicate_players`, `unfillable_slots`, `messages` | `fantasy_weekly_lineup.validate_weekly_lineup` | none (week lock rules are separate: `save_period_lineup`) |

## Lower-level modules

These are moved verbatim from `streamlit_app.py`. The app imports every name back, and the
caching stays in the app.

| Module | Public functions | Notes |
|---|---|---|
| `fantasy_standings_snapshot` | `score_current_roster_standings`, `summarize_team_category_needs`, `SNAPSHOT_KIND`, `SNAPSHOT_LABEL` | Was `score_fantasy_rosters_from_stats`; the page keeps that name as an `@st.cache_data` wrapper |
| `fantasy_trade_evaluation` | `evaluate_trade`, `build_trade_verdict_text` | BA/OPS are the plain average of each side's players (unchanged page behavior). Value only; no legality |
| `fantasy_lineup_scoring` | `build_lineup_assistant_scores`, `build_position_aware_lineup`, `lineup_diagnosis_report`, `roster_position_slot_list` | Scores are 0–1 relative to the roster passed in. The page keeps a cached wrapper for the scores |
| `fantasy_slot_eligibility` | `player_eligible_for_slot_strict` (fantasy rule = Save Lineup's), `player_eligible_for_slot` (older research rule), `enrich_lineup_roster_positions`, `filter_players_by_fantasy_position(..., strict=)`, `split_primary_positions`, `parse_custom_lineup_slots`, `LINEUP_DEFAULT_HITTING_SLOTS` | Fantasy screens use the strict rule; only the research pages' position filters keep the older one (see the module note) |
| `stat_helpers` | `normalize_series`, `safe_numeric_series`, `fmt_int`, `fmt_rate_3` | Shared helpers |
| `fantasy_league_peek` | `peek_resolved_fantasy_context`, `peek_active_league_context`, `isolated_session_view` | Runs the page resolvers on a copy-on-read view: deep copies in, writes stay in the view |

Dependency direction: page → `fantasy_read_api` → modules. No module imports `streamlit_app`
or `streamlit` (`tests/test_shared_fantasy_functions.py` checks this).

## Already-importable authoritative functions (unchanged)

- Season and lineups:
  - `fantasy_season_ledger.list_periods`, `get_period`, `period_status`;
  - `fantasy_season_ledger.current_period_number`, `get_period_lineup`;
  - `fantasy_season_results.official_standings`, `period_result`, `period_category_table`.
- Rosters: `fantasy_roster_validation.evaluate_team_roster`, `fantasy_lineup_fill.unfilled_slots`.
- Waivers:
  - `fantasy_waiver_wire.recommend_adds_personalized`, `recommend_drops_current`;
  - `fantasy_waiver_wire.analyze_current_team_needs`, `waiver_roster_transaction_mode`.
- Trades: `fantasy_trade_proposals.get_incoming_trade_proposals` /
  `get_outgoing_trade_proposals`. These are team-private: scope them with `team_access`.

## Proof that nothing changed

1. `tests/test_shared_fantasy_functions.py` pins the outputs of every moved function. The
   expected values were generated by the original `streamlit_app.py` code at `38d1e3e` and
   include tie-split roto points and hit/at-bat team BA.
2. A randomized parity run (scratch harness, not committed) compared the originals,
   rebuilt from `git show 38d1e3e:streamlit_app.py`, with the modules:
   - 300 random leagues of real 2026 MLB hitters, all three scoring formats, missing columns
     and NaNs, every slot layout, both rate modes, every position filter;
   - **5,492 comparisons, 0 differences**, using exact frame equality;
   - a negative control (a 1.5 → 1.6 weight change, an AB+1 rate change) was detected.
3. `tests/test_fantasy_league_peek.py` and `tests/test_fantasy_read_api.py` show:
   - results equal the page resolvers';
   - the session is byte-identical afterwards, including for a non-dict, proxy-like session;
   - no shared-store sync or stats fetch happens;
   - team access is enforced.
