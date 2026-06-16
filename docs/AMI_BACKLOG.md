# AMI Backlog — Known Issues (not yet fixed)

**Last updated:** 2026-06-16

Tracked AMI quality issues that are **deferred behind the Phone ↔ Dell sync audit**. These
stay open until the sync audit closes and the non-draft AMI infrastructure work begins.
Do not silently drop these from scope; re-verify each on a real deployed board.

| ID | Issue | Side | Stage | Status |
|----|-------|------|-------|--------|
| B1 | Nathan Lukes parser — trailing fragment leak, missing "good pick" pattern | **Baseball** `applied_math_context.py` | A (send) | **Fixed 2026-06-16** |
| B2 | Market Bust Risks routing falls into generic Draft Value mode | **AMI solver** | C (mode) | Open — Baseball send is wired; AMI-side fix needed |
| B3 | Team 2 roster-needs logic | **AMI solver** | E (reasoning) | Open — Baseball send is wired; AMI-side fix needed |
| B4 | Team 2 weakest-pick explanation quality | **AMI solver** | F (explanation) | Open — Baseball send is wired; AMI-side fix needed |

---

## B1 — Nathan Lukes parser — ✅ Fixed 2026-06-16

**Root cause (two issues):**

1. `_clean_question_player_capture` never stripped trailing fragments, so phrasings like
   "Should I take Nathan Lukes with this pick?" extracted `"Nathan Lukes with this pick"`.
2. "Is Nathan Lukes a good pick?" matched no pattern (only "a good sleeper" was listed), so
   the player was not extracted at all — downstream solver had no `question_player`.

**Fix applied:**
- Added `_PLAYER_CAPTURE_TRAILING_FRAGMENTS` and `_PLAYER_CAPTURE_TRAILING_NUMBERED` stripping
  to `_clean_question_player_capture` (mirrors the earlier comparison-parser fix).
- Added `"a good pick"`, `"a safe pick"`, `"a risky pick"`, `"a bust risk"` to the
  `is (.+?)` pattern alternatives.
- Extended `should i draft/pick/target` pattern to handle "pick" and "target" verbs, plus
  `" with "` and `" despite "` as trailing terminators.
- Added 6 regression tests in `tests/test_ami_player_pool.py::test_jose_question_player_row_bound_after_send`.

**Remaining (AMI-side):** sleeper-take solver quality polish when `question_player_row` is
missing (player not in cached pool) — tracked separately under solver quality.

---

## B2 — Market Bust Risks routing — Baseball side complete; AMI-side open

**Baseball send is fully wired (verified 2026-06-16):**
- `detect_sleepers_send_intent` → `bust_risk_review` for bust-section questions
- `finalize_sleepers_context_for_send` clears stale `sleeper_focus`, sets
  `routing_hint="bust_risk_review"`, `intent="bust_risk_analysis"`,
  `market_section="Market Bust Risks"`, promotes `bust_risks` rows
- Covered by `tests/test_sleepers_ami_send.py` (all pass)

**Remaining issue (AMI-side):** The `bust_risk_review` routing hint arrives at AMI but the
solver/router falls through to generic Draft Value mode. Fix locus:
- `applied-mathematical-intelligence` → `applied_math_problem_router` or `applied_math_solvers`
  → must recognize `routing_hint="bust_risk_review"` / `intent="bust_risk_analysis"` before
  reaching the draft-value fallback

**Dev Mode confirm steps:**
1. Ask "Are there any players in Market Bust Risks I should consider drafting?"
2. Applied Intelligence Dev Mode → `routing_hint` should show `bust_risk_review`
3. `problem_type_id` / `draft_mode` — if these show a value/comparison mode → AMI routing fix
4. If `routing_hint` is missing → Baseball send not running (check `source_page` routing)

---

## B3 — Team 2 roster-needs — Baseball side complete; AMI-side open

**Baseball send is fully wired (verified 2026-06-16):**
- `attach_draft_team_to_context` resolves "Team 2" → canonical team name, binds that team's
  roster with positions (`roster_by_position`, `filled_roster_display_lines`,
  `roster_position_index`, `user_roster_detail`)
- Tested in `tests/test_ami_player_pool.py::TestDraftTeamReview::test_attach_draft_team_after_finalize_uses_team_two_roster`
  (passes — positions arrive, user team not contaminated)

**Remaining issue (AMI-side):** The solver's `roster_needs` / `roster_weakness` branch must
read the team-scoped context keys (`roster_by_position`, `team_roster_with_positions`,
`filled_roster_display_lines`) rather than defaulting to the user's own roster.

**Dev Mode confirm steps:**
1. Ask "What does Team 2 need?" or "What are Team 2's roster needs?"
2. Applied Intelligence Dev Mode → `roster_display_lines` / `roster_by_position` should
   show Team 2's players (not your players)
3. If context shows Team 2's players but answer is about your team → **AMI solver** reads wrong key

---

## B4 — Team 2 weakest-pick explanation — Baseball side complete; AMI-side open

**Baseball send is fully wired:** `attach_draft_team_to_context` sends the team board, roster
detail, and position index. The draft board rows include `Market Rank` and `Fantasy Edge` when
the pool was built from `available_df` with those columns.

**Remaining issue (AMI-side):** Draft review mode explanation quality — the solver must:
- Identify which of Team 2's picks was lowest-value relative to alternatives available at that slot
- Name the better alternative that was available
- Explain the value-edge gap

Fix locus: `applied-mathematical-intelligence` → `applied_math_solvers` draft review mode,
stage F explanation quality. Requires `market_rank`, `fantasy_edge` on board rows — confirm
these travel in the sent context via Dev Mode.

---

## Cross-reference

- Acceptance bar & nine trust criteria: `docs/AMI_ANSWER_QUALITY_BAR.md`
- Manual deployed validation procedure: `docs/AMI_MANUAL_ACCEPTANCE.md`
- Context pipeline root-cause analysis: `docs/AMI_CONTEXT_PIPELINE_INVESTIGATION.md`
- Non-draft infrastructure plan: `docs/AMI_NON_DRAFT_PAGE_INFRASTRUCTURE.md`
