# Tier 1 — Deployed Context Pipeline Investigation

**Date:** 2026-06-13  
**Scope:** Baseball → Command Center → AMI send/hydration for Draft Assistant  
**Status:** Investigation only — no fixes applied

---

## Shared root issue

Q2, Q3, and Q4 point to the same underlying problem: **AMI often does not receive the draft player-pool context it needs to reason from your board.**

| Question | Symptom | Likely pool state at solver |
|----------|---------|----------------------------|
| Q2 Roster weakness | Player A vs B + value-edge | Wrong route; pool may be present but unused |
| Q3 Jose Ramirez | `0 available names`, `position n/a`, Jose vs Jose | **Empty or useless pool** — no alternatives |
| Q4 Next catcher | Explicit "not enough Catcher pool data" | **Pool missing catchers** or untagged |

---

## Pipeline (deployed path)

```
Draft Assistant render
  └─ cache_draft_assistant_ami_context()     ← pool built here
       └─ available_df.head(12) by EV         ← truncation point
       └─ session["_ami_draft_snapshot"]

User clicks Send (sidebar)
  └─ build_submit_context()
       ├─ build_context_from_session()       ← queue, round, workflow
       └─ build_baseball_applied_math_context() ← reads _ami_draft_snapshot
  └─ submit_analytical_question()
       └─ _store_question_context_blob()      ← full context by question_id

Command Center → Continue

Applied Intelligence
  └─ hydrate_applied_intelligence_session()
       └─ question_id_blob → ctx (preferred)
  └─ dispatch_solver(ctx)
       └─ _draft_context_bundle() → bundle["available"]
```

**Hydration:** Blob-first by `question_id` is correct design (`suite_analytical_question.hydrate_applied_intelligence_session`). If `hydrate_source=question_id_blob`, truncation happened **before send**, not during hydration.

---

## Answers to the 9 investigation questions

### 1. Is `available_players` actually being sent?

**Sometimes.** It is populated only when `cache_draft_assistant_ami_context()` runs during Draft Assistant render **and** the available dataframe is non-empty.

If the user sends before the page caches, or from a page without cache, `gather_draft_ami_snapshot()` alone does **not** build `available_players` — only queue, board, drafted names.

### 2. How many rows are being sent?

| Source | Limit |
|--------|-------|
| `cache_draft_assistant_ami_context` | **12** (`available_df.head(12)`) |
| `best_available_players` | **6** |
| `recommended_players` | **6** |
| `build_baseball_applied_math_context` copy | up to **24** from snap (but snap already capped at 12) |

Local proof: 12 OF rows sent, 0 catchers, when catchers rank 13th+ by EV.

### 3. Does `available_players` include catcher rows?

**Not guaranteed.** Only if a catcher is in the top 12 by `Expected Fantasy Value`. Catchers often rank lower → **omitted from payload**.

### 4. Does `available_players` include a position field?

**Yes, when rows exist.** `compact_recommendation_rows` copies `Primary Position` from the Draft Assistant dataframe (`draft_ami_helpers.AMI_REC_COLUMNS`).

### 5. Position field naming?

| Layer | Field name |
|-------|------------|
| Baseball sends | `Primary Position` |
| AMI solver reads | `Primary Position`, `position`, `pos` (`_player_metric`) |
| **No schema mismatch** when rows are sent | |

`draft_room_board` records are **Round/Pick/Team/Player only** — no position. Enrichment via `_enrich_row_from_canon` only helps if the player appears in a tagged pool row.

### 6. AMI expecting different schema than Baseball?

**No**, when pool rows exist. Failure is **missing rows**, not wrong field names.

Audit/harness tests pass because they **inject** catcher rows into `available_players` explicitly (`ami_answer_quality_audit.py`, `build_draft_market_catcher_context`).

### 7. Recommendations only vs broader pool?

**Both are sent, both truncated:**
- `recommended_players` = top 6 from recs (fit-scored)
- `available_players` = top 12 by EV (not position-representative)

Neither is a full undrafted pool. Draft-market and player-why questions need **position coverage**, not just top overall EV.

### 8. Pool truncated before catchers enter payload?

**Yes — primary root cause for Q4.** Confirmed locally:

```
12 rows sent, positions: all OF, catchers: 0
Full undrafted pool has 3 catchers (Cal Raleigh, William Contreras, Adley Rutschman)
head(24) would include catchers; head(12) does not
```

### 9. Do all context keys arrive in deployed sessions?

| Key | Expected when cache runs | Often missing when |
|-----|-------------------------|-------------------|
| `draft_snapshot` | Yes | Send without visiting Draft Assistant |
| `roster` / `user_roster` | Yes | Cache not run |
| `queue` / `draft_queue` | Usually (workflow merge) | — |
| `watchlist` | If set | — |
| `recommended_players` | Yes (6 rows) | Cache not run |
| **`available_players`** | **12 rows max** | Cache not run **or** empty avail df |
| `needed_positions` | Yes | Cache not run |
| `category_needs` | Yes | Cache not run |
| `drafted_players` | From board | — |
| `Primary Position` on pool rows | Per row | Missing if pool empty or board-only |

**Q3 `"0 available names in context"`** = solver sees `len(bundle["available"]) == 0` — stricter than Q4 (no catchers). Suggests **empty pool at solve time**, not just missing catchers. Dev Mode must confirm whether `available_players` is absent, `[]`, or present without useful rows.

---

## Where the pool is lost

| Stage | What happens |
|-------|--------------|
| **A. Cache build (Baseball)** | `head(12)` by EV drops position groups (catchers, often Jose if not top-12) |
| **B. Cache not run** | No `_ami_draft_snapshot` → no `available_players` at all |
| **C. Send** | Context blob stores whatever cache built (no expansion at send) |
| **D. Hydration** | Blob-first should preserve payload — loss unlikely if `hydrate_source=question_id_blob` |
| **E. Solver bundle** | Reads `ctx.available_players` / `snap.available_players` — honest "0 names" if empty |

---

## Secondary issue (Q2/Q4 restatement)

Interpreter maps `unknown` intent → default `compare` purpose → *"Player A vs Player B"* restatement (`applied_math_problem_interpreter._intent_to_purpose`). Wrong for roster weakness and draft-market questions. **Secondary to pool issue.**

---

## Expected fix direction (when approved)

General Baseball context improvement — **not** catcher-only, **not** new AMI reasoning:

1. Send a **position-representative** available pool (top N per position or larger stratified slice)
2. Include **Market Rank / Fantasy Edge** on each row (already supported when present)
3. Ensure cache runs reliably before send (or build pool at send time from full undrafted dataframe)
4. Optionally add `position_pool_summary` or expand limits for draft-market questions
5. Fix interpreter restatement for draft-market / roster / player-why (secondary)

---

## Dev Mode checklist (confirm on deploy)

```
hydrate_source:                    (expect question_id_blob)
context.available_players count:
context.available_players positions:
draft_snapshot.available_players count:
recommended_players count:
needed_positions:
category_needs:
draft_queue:
watchlist:
drafted_players count:
canonical_draft_board count:
question_player_row present:       (Q3)
Applied Intelligence build:
Baseball deploy_build:
```

**Key decision:**
- `available_players` **missing/empty** → Send/Hydration (cache or hydration)
- `available_players` **present, no catchers, no Primary Position tags** → Send/Hydration (truncation/tagging)
- `available_players` **present with catchers tagged, solver still fails** → Solver/Reasoning

---

## Local diagnostic scripts

- `scripts/_debug_context_pipeline.py` — pool truncation simulation
- `scripts/_debug_tier1_q2_routing.py` — routing vs context scenarios
