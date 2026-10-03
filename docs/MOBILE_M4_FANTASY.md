# Baseball Mobile M4 — Fantasy Team (roster, standings, waiver, trades)

Base: M3 checkpoint `cdf6b9b` on `mobile/m1-foundation`. Widths: 360 / 390 / 430
(phone) and 1280 (desktop reference). Presentation only: no roster ownership, scoring,
standings, projections, transaction, waiver-priority, trade, persistence, workspace,
Live Draft, M2 navigation or M3 composition logic changed.

## 1. Architecture found

| Surface | Render path | State scope |
|---|---|---|
| Fantasy page header + nav (Active League card, 2–3 page buttons) | `draft_archive_ui.render_active_saved_draft_chip` → `render_fantasy_page_header` → `render_fantasy_page_navigation` | display; reads the active league context |
| Standings | `streamlit_app.py` page branch → `build_roster_stats_from_league_context` → `score_fantasy_rosters_from_stats` → `render_output_table` | league scoped; current-season stats are workspace scoped (in-season snapshot) |
| Lineup Management | Lineup Assistant tab → `fantasy_lineup_management_ui` → `fantasy_weekly_lineup_ui` (drag-and-drop board component, open-slot prompts, Save/Reset) | team scoped; weekly lineup saves are a mutation |
| Lineup format | `fantasy_league_lineup_format_ui` (commissioner) | league scoped; mutation |
| Waiver / add-drop | `fantasy_waiver_wire_ui.render_waiver_wire_page`: category snapshot, transaction multiselects, recommended add/drop cards, pool table, manual planner | team scoped; `apply_waiver_move_pairs` mutates the league roster |
| Trade Center | Lineup Assistant tab → `fantasy_trade_center_ui`: builder, analysis, propose/confirm, Offers & Activity | team ownership via `resolve_trade_team_for_session`; proposals live in the shared-league store |
| Ownership / claims | `fantasy_league_team_ownership`, `fantasy_workspace_team_identity` | account scoped (`local:<id>` without cloud) |

No Fantasy renderer uses `st.fragment`, so wrapping existing rows in keyed containers
does not affect fragment identity. All moved widgets are explicitly keyed.

## 2. Deterministic fixture

`scripts/mobile_fantasy_fixture.py` seeds the local `test_user` workspace through
production paths only:

1. **Draft.** A 6-team × 12-round Solo draft over the real prewarmed pool (699
   hitters). Every pick goes through `expire_current_pick_and_advance`, the
   production timer-expiry autopick.
2. **League.** `save_imported_league_context(assign_team=True)` creates a
   `real_league` plus its library archive, activates it, and claims **Dingers**
   for this account.
3. **Second owner.** `claim_team_in_league_context` has a second account claim
   **Bat Flips**. Trades need two distinct owners.
4. **Format.** `save_league_lineup_format` sets 8 starters with a 12-player roster
   capacity, which leaves a 4-player bench.
5. **Save.** The app's own `force_save_baseball_state`.

The script also writes a stats CSV built from each pool player's latest-season
line. The browser loads it through the Standings page's real **Upload CSV**
source, so the run is deterministic and offline.

Why these paths:
- **Import path instead of Live Draft "Save Draft".** A locally saved Live Draft
  league resolves its team to blank when there's no signed-in account (§6.3), so
  Trade Center is unreachable from it.
- **Lineup format saved by function.** The fixture calls the same function the
  "Save League Lineup Format" form calls, because the Edit Lineup Format button
  is broken in the baseline (§6.1).

The script refuses to run when cloud or auth configuration is present. Everything
it writes is gitignored or untracked runtime data:
- `data/workspaces/test_user/`
- `data/tb_probe/mobile_fantasy_*`

Open the app with `?suite_workspace=test_user`.

## 3. Phone changes

| Area | Change (phone ≤ 640px only; desktop unchanged) |
|---|---|
| Fantasy nav buttons | 3 full-width buttons → 2-up tiles (M1 `mobile_wrap_row`) |
| Standings tables | **Team + Player** (roster) / **Fantasy Team** (standings) frozen while category columns scroll (`st.column_config.Column(pinned=True)`, opt-in `render_output_table(pin_columns=…)`) |
| Lineup tables | **Fantasy slot + Player** frozen (Recommended Starters, Bench / Sit / Watch) |
| Lineup open slots | "Missing X" label and its Waiver Wire button share one row (M1 `mobile_inline_row`); Save Lineup / Reset side by side |
| Waiver player cards | one compact row per player: 48px photo left, name / team · pos / why / stats beside it, action button under the details (was photo, text and full-width button stacked) |
| Trade actions | Find Ideas / Analyze / Propose / Clear / Reset → 2-up tiles that fill their cells |

Pinning only freezes a **leading** run of identity columns. Pinned columns are
always drawn first, so pinning a non-leading column would reorder it. For that
reason the Waiver available-player table (player column isn't first) is left
unpinned (§7). Nothing is hidden on phones, and all actions stay visible.

Not changed: the lineup drag-and-drop board. It already has phone CSS and the
`docs/FANTASY_LINEUP_MOBILE_DND_RUNBOOK.md` touch path, and no new interaction
was added.

## 4. Results

The M3 baseline and M4 were run from the same clean fixture, with the same
upload and the same steps. Values are main-column heights in px.

| Screen | 1280 (M3 → M4) | 430 | 390 | 360 |
|---|---|---|---|---|
| Standings | 2301 → 2301 | 2365 → 2305 | 2410 → 2360 | 2407 → 2358 |
| Lineup Management | 5154 → 5154 | 5975 → 5695 | 6017 → 5737 | 6062 → 5782 |
| Trade Center | 1570 → 1570 | 2154 → 1961 | 2173 → 1979 | 2191 → 1998 |
| Waiver Wire | 7274 → 7274 | 10923 → 8241 | 10964 → 8369 | 10983 → 8410 |

- **Desktop 1280:** every measured element has the same position and size on M3
  and M4 for all four screens (13/33/20/39 elements, 0 differences).
- **All widths:** 0 horizontal page overflow, 0 exceptions.
- **Waiver cards:** about 370 → 240px each.

### Workflows exercised in the browser (390px)

- **Standings.** CSV upload scores all 6 teams. Scrolled fully right, the frozen
  identity columns stay readable next to Total Roto Points and League Rank.
- **Add/drop.**
  - Added the top recommended player (José Caballero) through the
    "Players to ADD" multiselect.
  - Dropped Michael Harris through "Players to DROP", then pressed
    **Confirm Waiver Move**.
  - The product reported "Added: José Caballero / Dropped: Michael Harris".
  - The saved roster has the add and not the drop, at 12 players with no
    duplicates, and the other 5 teams are unchanged.
  - The saved state survives a refresh. Quick nav away to Standings and back
    works, and the drop list then reflects the new roster (see §6.2).
  - Before the format was configured, the same move was correctly refused as
    over capacity (§6.4), and a mismatched add/drop count was correctly refused.
- **Trades.**
  - Partner and one player per side, then **Analyze Exact Trade**: verdict,
    category comparison table and roster impact all render at 390.
  - **Propose Trade** opens the "Confirm trade proposal" panel, and
    **Confirm and send proposal** returns "Proposal sent".
  - Offers & Activity renders. Cross-account delivery couldn't be checked
    locally (§6.5).
- **Navigation.**
  - M2 quick nav switches between Fantasy pages.
  - Fresh-session deep links restore the league, team and stats.
  - Desktop shows no mobile-only controls.

## 5. Tests

- **New:** `tests/test_fantasy_mobile_layout.py`. Covers:
  - CSS is phone-scoped and hides nothing;
  - the card overlap regression;
  - leading-only pinning and Streamlit `pinned` support;
  - row helpers, including tolerance of minimal `st` doubles;
  - wiring and widget keys unchanged.
- **Fantasy regression set:** 111 files covering Fantasy roster/lineup,
  standings, waiver/add-drop, transactions, trades, league context,
  ownership/workspace/persistence, the M1/M2/M3 mobile tests and every importer
  of the changed modules. Run on M4 and on `cdf6b9b` from parked, identical
  runtime data.

| Run | Passed | Failed test cases | Of which: collection errors |
|---|---|---|---|
| M4 | 1012 | 76 | 3 |
| `cdf6b9b` baseline | 994 | 76 | 3 |

The failure sets are identical, so **M4 introduces no regressions**. The 18
extra passing tests on M4 are the new presentation tests. The 3 collection
errors are pre-existing test modules that import names this branch doesn't have:
- `_merge_full_session_preserve_richer_draft`
- `_resolve_account_user_id_cached`
- `music_resume_payload`

## 6. Product issues found (all reproduce on the M3 baseline; not changed)

1. **"Edit Lineup Format" does nothing.** It fails at 390 and 1280 on `cdf6b9b`:
   after the click, neither the editing warning nor the form appears, even after
   20s and a second click. An existing league's lineup format and roster
   capacity can't be changed from the UI.
2. **The Waiver drop list is stale after a browser refresh.** After a successful
   add/drop, a refresh shows the pre-transaction roster in "Players to DROP"
   (still stale after an extra wait), although the saved roster is correct.
   Visiting Standings and returning corrects it. This is likely the restored
   in-season roster-stats snapshot.
3. **Locally saved Live Draft leagues lose "my team".** Saved with no signed-in
   account, the context gets a canonical league id and is treated as shared, so
   the team overlay blanks `my_team_name`. The claim panel only exists for
   `real_league` contexts, so Trade Center shows "Claim your team" with no way
   to do it.
4. **Bench isn't counted toward roster capacity by default.** With no saved
   lineup format, capacity falls back to the starting-slot count. A 12-player
   roster with 8 starters is "over capacity" and every add/drop is refused.
   Together with (1), an existing league has no UI fix.
5. **Trade proposals: local environment limits.**
   - "Proposal sent" was shown, but Outgoing Offers stays empty because
     proposals live in the shared-league store, which is Supabase in the
     running app. Not verifiable without cloud.
   - A proposal to an unowned team is allowed after a warning.
6. A "Sign in to save lineup changes" notice shows in local (no-auth) mode.

## 7. Deferred (M5+)

- **Waiver available-player table:** the player column isn't first, so it can't
  be pinned without reordering the desktop table. Needs a phone column set.
- **Waiver list length:** 15 add plus 15 drop cards are still long on phones;
  "show more" or a disclosure would need a Python render change.
- **Shared page chrome on phones:** hero, Start Tutorial, Quick Guide and the
  Active League card still take about 900px before Fantasy content.
- **Lineup drag-and-drop:** real-device check (iOS Safari / Android Chrome) of
  the board.
- **Accessibility:** visual order of reflowed card grids versus DOM order
  (same note as M3).
- **Analytics/charts, player-explorer redesign, final stabilization:** M5 and
  later slices.
