# Fantasy league data model

Where a fantasy league's state lives, which copy is authoritative, and the rules every
page relies on. Read this before changing Saved Draft Library, Lineup, Waiver Wire,
Trade Center or Standings code.

## One league = one league context

All fantasy pages read a **league context**, stored in the session under
`fantasy_league_context_state` (`fantasy_league_context.py`):

```
fantasy_league_context_state = {
  "contexts": { <league_context_id>: <context>, ... },
  "active_league_context_id": <league_context_id> | None,
}
```

A context:

| Field | Meaning |
|---|---|
| `league_context_id` | Stable id. Saved drafts use `archive:<draft_id>`. Ids starting `__ephemeral_` are temporary board views and are never saved. |
| `context_type` | `real_league` (imported or shared league), `live_draft_result`, `mock_draft_simulation`. |
| `my_team_name` | The team this account manages in the league. |
| `league_rosters` | `{team_name: {team_name, is_user_team, players: [...]}}` — **the source of truth for who owns whom.** Each player: `player_name`, `player_key`, `player_id`, `positions`, `pick`, `round`, `source_row`, `team_name`. |
| `ownership_map` | `{player_key: {owner_team, ...}}`, **derived** from `league_rosters` by `build_ownership_map` on every `upsert_league_context`. Never edit it directly. |
| `roster_settings` | Starting positions (below). |
| `workflow` | League history: `weekly_lineups`, `weekly_lineup_drafts`, `trade_proposals`, `trade_alerts_seen`, `league_activity` (add/drop log, last 50). |
| `metadata` | `source_draft_id`, `commissioner_user_id`, `shared_revision`, timestamps. |

Write through `upsert_league_context(session, context)` only; it rebuilds `ownership_map`
and stamps `metadata.updated_at`.

## Starting positions (`roster_settings`)

```
roster_settings = {
  "roster_slots":  {"C":1,"1B":1,"2B":1,"3B":1,"SS":1,"OF":3,"DH":1,"P":0,"BN":0},
  "slot_instances": [{"position","label","slot_index"}, ...],   # frozen order, e.g. OF 1..3, UTIL
  "lineup_format": {"lineup_slots": [...], "roster_capacity": 10, "configured_by", "configured_at", "configuration_source", "league_id"},
}
```

* **Utility is stored as `DH`** in `roster_slots` and shown as `UTIL`. `apply_lineup_format_to_context`
  converts `UTIL → DH` before freezing slots (`live_draft_roster_slots` only knows
  `C/1B/2B/3B/SS/OF/DH/P/BN`; anything else is dropped).
* `lineup_slots` keeps the commissioner's choice in display form (`UTIL`).
* `roster_capacity` = drafted roster size. Leagues without a saved format (e.g. from a
  Live/Shared Draft) use starters + `BN` from `roster_slots`
  (`roster_capacity_from_format`). Waiver moves are add-only below it, add+drop at it,
  and blocked above it (`waiver_roster_transaction_mode`).
* An imported league has **no** starting positions until the commissioner saves them
  (`needs_lineup_format_setup`). Nothing is fabricated: until then rosters stay as drafted
  and position checks are skipped. Setup starts from a standard lineup (C, 1B, 2B, 3B,
  SS, 3×OF, UTIL), capped at the drafted roster size; players beyond the starters are bench.

## Roster, lineup and bench are different things

* **Roster** — every player in `league_rosters[team].players`.
* **Lineup** — this week's starters, one per slot, saved in `workflow.weekly_lineups`
  (locked) or `weekly_lineup_drafts` (in progress), keyed by team and week.
* **Bench** — roster players not in the lineup (`not_starting_players`).

An empty lineup slot is not a missing roster position. The lineup board offers the
waiver wire only when no unused rostered player is eligible for the open slot
(`build_open_slot_prompts(..., team_roster)`). Position coverage of the *roster* is
`evaluate_team_roster` / `resolve_context_open_position_needs`.

## Saved Draft Library and the Active League

* Saved drafts: `draft_archive_teams` (list), active pointer `active_draft_archive_id`
  (`draft_archive_state.py`). Each archive links its context through `league_context_id`
  and carries a copy of `league_rosters` that waiver moves keep in sync
  (`save_draft_archive_with_league_context`).
* The archive pointer and `active_league_context_id` must agree;
  `saved_draft_library_selection.repair_incoherent_active_library_selection` repairs drift.
* A lone saved draft becomes the Active League automatically
  (`workflow_persist_guard`, `single_visible_draft_auto_active`). User-facing messages
  must say so rather than "(not active)". Deleting the Active League with one other
  saved draft left makes that one active by the same rule.
* Renaming a saved league renames the archive and the context's `display_name`,
  `league_name` and `draft_name`; fantasy page headings read `league_name` first.

### Which league a page sees

`get_active_league_context(session)` resolves by priority
(`fantasy_context_source.resolve_fantasy_context_source`):

1. a Live Draft in progress or paused;
2. a temporary Live/Simulator override chosen in the library;
3. the saved Active League;
4. the natural simulator board, else generic.

Sources 1, 2 and 4 are rebuilt from the board every run (`persist=False`) — anything
written to them is lost. Pass `respect_source_priority=False` to read only the saved
Active League (Library, activation, lineup storage).

Pages read the league through two session caches: the workflow source descriptor
(`resolve_fantasy_workflow_source_descriptor`) and the resolved page context
(`resolve_fantasy_context_for_page`). Both cache keys include the active league's
rosters (and name), so a waiver move, trade or rename is visible on the next render.
Roster frames for Lineup/Standings are rebuilt from `league_rosters` plus the current
stats feed (`build_roster_stats_from_league_context`); positions missing from an
imported board come from the feed.

## Shared leagues

Multi-user leagues mirror the context into a shared league document
(`fantasy_shared_league_store`, Supabase when configured, else a local file store).
`push_league_context_to_shared` writes rosters, roster settings, trade proposals,
team ownership, invites and activity, merging with the stored copy.
`sync_context_with_shared_store` pulls on page reads (soft-cached ~12 s). Local
installs without Supabase must not fail on a push: callers wrap it in `try`.

## Transactions

* **Waiver add/drop** — `apply_waiver_move_pairs`: up to two matched pairs; rejects an
  add that is already rostered anywhere, a drop not on your roster, add = drop, a
  missing drop when the roster is full, and a pitcher in a league with no pitcher
  spots. Applies to `league_rosters`, logs `league_activity`, syncs the archive, and
  returns `position_warnings` (e.g. "Missing catcher") when the move opens a hole.
* **Trades** — `fantasy_trade_proposals`: both teams must be in the league and differ,
  each side 1–3 players (5 total), every player owned by the side giving him, and
  the recipient team must have an account owner. Acceptance revalidates (stale offers
  are refused) and swaps players between the two rosters with rollback on failure.
  `fantasy_trade_legality.trade_roster_warnings` tells both sides (Trade Center and the
  Accept form) when the trade leaves a required lineup slot unfillable or moves a roster
  over/under capacity; it warns, it does not block.
* **Lineup fill** — `fantasy_lineup_fill.unfilled_slots` assigns one player per slot
  (UTIL/DH takes any hitter, BN anyone). Waiver need weights and trade warnings use it.

## Persistence

The whole session (including `fantasy_league_context_state` and the archives) is saved
per workspace by `suite_user_persistence` — on local installs to
`data/workspaces/<workspace>/baseball_user_state.json`, with cloud storage enabled to
the account's cloud blob. On startup the newer of cloud/disk is applied; if nothing
was applied, autosave is blocked so a failed read cannot overwrite real data. A local
install with an empty disk store is a new workspace and saves normally.

## Invariants (tested)

* A player appears on at most one roster; `ownership_map` matches `league_rosters`.
* Saving a lineup format keeps every chosen slot, including UTIL.
* Roster changes (waiver, trade) are visible on Lineup, Waiver Wire, Trade Center and
  Saved Draft Library in the same session and after reload.
* Standings: roto category ties split the points (3.5 / 3.5); team BA/OBP/SLG/OPS are
  built from summed hits and at-bats when the stats carry them.

## Weekly scoring (audit, October 2026)

`fantasy_weekly_hitter_scoring.py` is a working hitter-only engine:

* Locking a team's weekly lineup snapshots each rostered player's **season-to-date**
  stats as the week's baseline (`create_weekly_baseline_on_lock`).
* `refresh_weekly_scoring` re-reads current season-to-date stats; a player's week =
  current − baseline. Starters count; bench is tracked but not scored. Rates (AVG, OBP,
  OPS) come from summed component deltas (H, AB, BB, HBP, SF, TB).
* `finalize_week_for_league` requires every team's lineup to be locked and stats ready,
  freezes the week, adds team totals into `hitter_weekly_standings_cumulative`, and
  advances the active week.

Gaps — documented, not built:

1. **No week calendar.** "Week N" is a label. Deltas use whatever season-to-date stats
   are loaded at refresh time, so finalizing late counts games played after the week.
   Needs per-week date ranges and as-of stats (the MLB Stats API supports
   `byDateRange`).
2. **Mid-week roster moves.** A starter dropped after the lock is looked up on the
   current roster, not found, and his week's stats vanish; a mid-week add scores nothing
   until the next lock. Needs scoring by the locked lineup's player ids.
3. **Every team must lock.** In a solo imported league the other teams are never locked,
   so a week can never be finalized. Needs commissioner/auto-lock for unmanaged teams.
4. **No head-to-head.** There is no schedule or matchup model; only cumulative roto.
5. **Two standings definitions.** Standings Tracker scores current rosters on full
   season-to-date stats; weekly finalization sums starters' weekly deltas. They will
   disagree after any roster move. The product needs to pick which one is "the standings".
6. Hitters only by design; pitching categories are not scored.

## Live / Shared Draft → league handoff (audit, October 2026)

`live_draft_shared_league.save_live_draft_shared_league_context` turns a completed room
into a `real_league` context: rosters from the board, `roster_settings` from the room's
slot config (Utility as `DH`), the creator claims their team and becomes commissioner,
and other seats stay reserved until their invite is accepted. No lineup-format setup is
needed. Findings:

* Fixed: roster capacity counted only starters, so a league drafted with bench spots was
  "over capacity" and every waiver add was refused.
* Trades need an owner on both teams, so trades wait until invites are accepted.
* Lineup writes require a signed-in account (`fantasy_lineup_scope`); a local install
  with auth disabled cannot save weekly lineups ("Sign in to save lineup changes.").
