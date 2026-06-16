# AMI Manual Responses — Session 1 (Tier 1)

**Date:** 2026-06-13  
**Build expected:** `2026-06-13-ami-hardening-pass · a2a0575 · dev`  
**Board:** _(describe your saved draft — pick count, your roster, queue, known gaps)_

**Tier 1 bar:** Would a fantasy player use this to make a draft decision?

**Five questions (all must be yes for PASS):**

1. Understood my draft?
2. Understood my roster?
3. Understood the actual players involved?
4. Used the available player pool?
5. Helped me make a decision?

**No new features, audits, harnesses, or Draft Room work in Session 1.** Real deployed answers on a real saved board are the source of truth.

**On FAIL:** Diagnose A→F → one bucket → fix only the first broken stage.

**Session rule:** Tier 1 only. Do not proceed to Tier 2 until all four pass.

**Five-question gate (all yes = PASS):**

- [ ] Understood my draft
- [ ] Understood my roster
- [ ] Understood actual players involved
- [ ] Used available player pool
- [ ] Helped me make a decision

---

## Pre-flight

- [ ] Cloud app rebooted on `dev`
- [ ] `deploy_build` confirmed on Draft Room manual save panel
- [ ] Draft board saved — Supabase readback shows correct picks/players
- [ ] Developer Mode enabled (Baseball + Applied Intelligence)

**Board snapshot (fill before testing):**

| Field | Value |
|-------|-------|
| Your pick # / round | |
| Your roster so far | |
| Queue | |
| Position gaps | |
| Category gaps | |

---

## Q1 — Who should I draft next?

**Page:** Draft Assistant Simulator  
**Draft awareness:** PASS | FAIL  
**Decision help:** Would this help me decide right now? YES | NO  
**Notes:** _(ugly but board-aware and actionable = PASS)_

**Checklist:**

- [ ] Knows who I already drafted
- [ ] Knows who is available
- [ ] Knows my queue/recommendations
- [ ] Recommendation fits my roster and helps me decide

**Full answer:**

```
(paste)
```

**Developer Mode:**

| Field | Value |
|-------|-------|
| hydrate_source | |
| problem_type_id | |
| draft_mode | |
| question_player | |
| draft_snapshot | present / missing |
| draft_queue | present / missing |
| needed_positions | |
| recommended_players | |

**Diagnosis (if FAIL):**

| Field | Value |
|-------|-------|
| First broken stage (A–F) | |
| Failure bucket | Send/Hydration · Classification/Routing · Solver/Reasoning · Explanation/Quality |
| What a trustworthy answer should have said | |

---

## Q2 — What is my biggest roster weakness?

**Page:** Draft Assistant Simulator  
**Question asked:** What is my biggest roster weakness right now?  
**Result:** FAIL  
**First broken stage:** B — Classification  
**Primary bucket:** Classification/Routing  
**Secondary check:** Send/Hydration  

**Observed failure:** AMI restated as *"You're asking who is better today on attached stats: Player A vs Player B."* Then ADP / pick 1 / rank edge / fair price / value-edge language — not a roster weakness answer.

**Expected route:** `roster_weakness` · roster construction · team needs · category/position needs  
**Expected answer:** Actual weaknesses from board (position depth, category gaps, roster imbalance, players who fix gaps). No Player A vs B, fair price, rank edge, ADP, or pick 1 unless directly relevant.

### Developer Mode capture (required before fix)

```
hydrate_source:
problem_type_id:
draft_mode:
question classification / math_purpose:
question_player:
draft_snapshot: present / missing
needed_positions:
category_needs:
player_a:
player_b:
ctx["player"] (if shown):
recommended_players: present / missing
canonical_draft_board: present / missing
Applied Intelligence commit/build:
Baseball deploy_build:
```

### Decision rules (classify one owner)

| Condition | Owner bucket |
|-----------|--------------|
| `draft_snapshot` / `needed_positions` / `category_needs` missing | **Send/Hydration** primary |
| Context present but `draft_mode=value_edge` | **Classification/Routing** primary · **Solver/Reasoning** secondary |
| `problem_type_id=baseball_player_comparison` | **Classification/Routing** primary |
| Applied Intelligence build older than local fixed build | **Deployment/Version mismatch** |

**Status:** Awaiting Developer Mode fields — no code changes until one owner is confirmed.

**Full answer:**

```
(paste deployed answer)
```

---

## Q3 — Why Jose Ramirez?

**Page:** Draft Assistant Simulator  
**Question asked:** Why is Jose Ramirez the best player to draft right now?  
**Result:** FAIL  
**First broken stage:** D — Enough information available  
**Primary bucket:** Send/Hydration  
**Secondary bucket:** Solver/Reasoning  

**Five-question gate:** draft PARTIAL · roster FAIL · players PARTIAL · pool FAIL · decision help FAIL  

**Observed failure:** Names Jose Ramirez but does not explain why he's best for *this* draft. Framework placeholders: "balanced coverage", "position n/a", "not in your top cached available slice", "0 available names in context", "see available_players". What-if broken: "Jose Ramirez HR/OBP vs Jose Ramirez" — no comparison candidates.

**Working theory:** Route/mode likely correct (`player_why`). Solver received incomplete player-pool context → template fallback.

**Code trace (local, not a fix):**
- `"0 available names in context"` → `_draft_scarcity_line()` when `bundle["available"]` is empty
- `"position n/a"` → `player_why` mode when `question_player_row` missing/incomplete
- `"see available_players"` → tradeoffs when `avail_names` is empty
- `"Jose vs Jose"` → what-if uses `alt or top`; when recs/available empty, `top` falls back to `player` (Jose)

**Expected route:** `player_why` · `baseball_draft_decision`  
**Expected answer:** Why Jose fits *your* board vs named alternatives (queue/recs), with real position/stats — not placeholder language.

### Developer Mode capture (required before fix)

```
hydrate_source:
problem_type_id:
draft_mode:
question_player:
question_player_row: present/missing
available_players: present/missing (count)
recommended_players: present/missing
draft_snapshot: present/missing
needed_positions:
category_needs:
canonical_draft_board: present/missing
player_pool_count:
Applied Intelligence commit/build:
Baseball deploy_build:
```

### Decision rules (classify one owner)

| Condition | Owner bucket |
|-----------|--------------|
| `available_players` missing/empty in Dev Mode | **Send/Hydration** primary |
| `available_players` present but answer still says 0 in context | **Solver/Reasoning** primary (bundle not reading sent pool) |
| `question_player_row` missing but player in question text | **Send/Hydration** (row lookup failed at send) |
| Applied Intelligence build stale | **Deployment/Version mismatch** |

**Key confirm question:** Why does the answer say "0 available names in context" — is `available_players` actually in Developer Mode?

**Status:** Awaiting Developer Mode fields — no code changes until one owner is confirmed.

**Full answer:**

```
(paste deployed answer)
```

---

## Q4 — Who is likely to be the next catcher drafted?

**Page:** Draft Assistant Simulator  
**Question asked:** Who is the most likely catcher to be drafted next?  
**Result:** FAIL  
**First broken stage:** A — Context sent / hydration  
**Primary bucket:** Send/Hydration  
**Secondary bucket:** Classification/Routing (wrong compare restatement)  

**Five-question gate:** draft PARTIAL · roster N/A · players FAIL · pool FAIL · decision help FAIL  

**What worked:** Did not hallucinate a catcher — honestly said insufficient Catcher pool data in context.

**What failed:** Did not answer the question. Solver in `draft_market_prediction` / `position_next` knew what it needed but pool did not arrive position-tagged.

**Observed solver messages (matches code):**
- `"I do not have enough Catcher pool data in context"`
- `"Attach available_players with Primary Position"`
- `"Cannot rank alternatives without position-tagged available players in context"`

**Wrong restatement (secondary):** *"You're asking who is better today… Player A vs Player B"* — interpreter `unknown` → `compare` default, same as Q2.

### Baseball send-path investigation (code trace, no fix yet)

| # | Question | Finding |
|---|----------|---------|
| 1 | Is `available_players` sent? | Yes, when Draft Assistant caches AMI context — but **only top 12** by Expected Fantasy Value (`Streamlit_app.py` → `cache_draft_assistant_ami_context`) |
| 2 | Includes Primary Position? | **Yes** when source `available` dataframe has `Primary Position` — `compact_recommendation_rows` copies `AMI_REC_COLUMNS` including `Primary Position` |
| 3 | Excludes drafted players? | **Yes** — `available = draft_df[~draft_df["fullName"].isin(drafted_or_owned_players)]` before cache |
| 4 | Catchers in top slice? | **Not guaranteed** — if no C in top 12 EV, **zero catchers** reach AMI |
| 5 | Pool too small? | **Yes — root cause** — `available_df.head(12)`, `best_available_df.head(6)`, `recs` limit 6; no position-stratified sampling |
| 6 | Field naming mismatch? | **No** — Baseball sends `Primary Position`; solver reads `Primary Position` / `position` / `pos` |
| 7 | Solver vs Baseball field gap? | Unlikely when rows sent; `draft_room_board` alone lacks position (enrichment via `_enrich_row_from_canon` only helps if player appears in tagged pool) |
| 8 | Recs only vs full pool? | Sends **top-EV slice**, not position-representative pool — draft-market questions need position-tagged rows across positions |

**Also explains Q3:** `"0 available names in context"` when top-12 slice omits question player and alternatives.

**Expected fix direction (when approved):** General context improvement — position-tagged available pool with enough rows per position for draft-market / player-why questions; not a one-off catcher patch. Fix draft-market restatement in interpreter.

### Developer Mode capture (required before fix)

```
hydrate_source:
problem_type_id:
draft_mode:
math_purpose:
draft_snapshot: present/missing
available_players: present/missing (count + sample positions)
recommended_players: present/missing
canonical_draft_board: present/missing
drafted_players:
current_pick:
Applied Intelligence commit/build:
Baseball deploy_build:
```

**Status:** Investigation complete — awaiting Dev Mode confirm, then one owner before fix.

**Full answer:**

```
(paste deployed answer)
```

---

## Session 1 summary

| # | Question | Draft awareness | Decision help | Notes | First broken stage | Bucket |
|---|----------|-----------------|---------------|-------|-------------------|--------|
| 1 | Who should I draft next? | | | | | |
| 2 | What is my biggest roster weakness? | FAIL | | B | Classification/Routing · check Send/Hydration | |
| 3 | Why Jose Ramirez? | FAIL | | D | Send/Hydration · Solver/Reasoning secondary | |
| 4 | Who is likely to be the next catcher drafted? | FAIL | | A | Send/Hydration · Classification/Routing secondary | |

**Tier 1 gate:** BLOCKED — Q2/Q3/Q4 fail · context pipeline investigation complete · awaiting Dev Mode confirm before fixes

**Investigation doc:** `docs/AMI_CONTEXT_PIPELINE_INVESTIGATION.md`

**Notes:**
