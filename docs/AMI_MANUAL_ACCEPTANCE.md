# AMI Manual Acceptance — Real User Validation

**Last updated:** 2026-06-13  
**Build:** `2026-06-13-ami-hardening-pass` · commit `a2a0575` · branch `dev`  
**Audit gate:** 26/26 trustworthy · 0 routing-only failures (`docs/AMI_ANSWER_QUALITY_BAR.md`)  
**This doc:** deployed manual acceptance — audit is necessary, not sufficient

---

## North star

> **Would a knowledgeable fantasy baseball player trust this answer?**

The question is no longer "Did the audit pass?" Harnesses and audits are the safety net. Deployed answers on real saved draft boards are the product.

### Session 1 (Tier 1) — real deployed answers are the source of truth

**Do not build new AMI features, audits, harnesses, or Draft Room functionality in this phase.**

Session 1 success is **not**: audit passes · routing passes · context exists · template structure exists.

Session 1 success **is**: a fantasy baseball player would actually use the answer to make a draft decision.

For every Tier 1 answer, ask:

1. Did it understand my draft?
2. Did it understand my roster?
3. Did it understand the actual players involved?
4. Did it use the available player pool?
5. Did it help me make a decision?

**Yes to all → PASS.** Any no → **FAIL.**

The ultimate test: Does Baseball Insight behave like a fantasy analyst looking at **my** draft board — not a generic fantasy baseball article?

| Priority | Rule |
|----------|------|
| Draft awareness | > answer polish |
| Actionable advice | > template structure |
| Correct context | > fancy wording |

Ugly but decision-helpful = **PASS**. Intelligent-sounding but board-agnostic = **FAIL**.

### Long-term trust bar (Tier 2+)

- answers the actual question
- uses the correct page context
- cites real players and data; explains why; compares alternatives when appropriate
- avoids generic filler and invented facts
- sounds like a fantasy analyst, not a template

**Do not expand harness coverage in this phase.** Validate deployed behavior with real boards and real questions.

---

## 1. Deploy setup (once per session)

| App | Dev URL | Confirm |
|-----|---------|---------|
| Baseball | https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app | `deploy_build: 2026-06-13-ami-hardening-pass · a2a0575 · dev` |
| Command Center | https://daniel-ai-command-center-ion4vh2cvo7bgdnkuktrb3.streamlit.app | Resume item appears after Send |
| Applied Intelligence | https://applied-mathematical-intelligence-8l8bqrzpp6fghaj7xuig53.streamlit.app | Developer Mode → `hydrate_source: question_id_blob` |

**Steps**

1. Streamlit Cloud → `coakley11/baseball-stat-app` → branch `dev` → **Reboot app**.
2. Hard refresh Baseball → **Draft Room Simulator** → assign picks → **Save draft board** → confirm Supabase readback.
3. Enable **Developer Mode** in Baseball and Applied Intelligence sidebars.
4. Do **not** proceed to Tier 2 until all Tier 1 questions pass.

---

## 2. Test tiers

Run one tier at a time. Do not test every family in a single session.

### Tier 1 — must pass before anything else

These four questions test draft board context, roster needs, player binding, and draft-market reasoning. **If Tier 1 fails, stop. Do not move to Historical, Trend, or other families.**

| # | Page | Question | What it tests |
|---|------|----------|---------------|
| 1 | Draft Assistant Simulator | Who should I draft next? | Board, queue, recs, pick slot |
| 2 | Draft Assistant Simulator | What is my biggest roster weakness? | Position/category needs diagnosis |
| 3 | Draft Assistant Simulator | Why Jose Ramirez? | Question-player binding, roster fit |
| 4 | Draft Assistant Simulator | Who is likely to be the next catcher drafted? | Draft-market timing, position scarcity |

### Tier 2 — after Tier 1 passes

| # | Page | Question |
|---|------|----------|
| 5 | Draft Assistant Simulator | Matt Olson vs Kyle Schwarber |
| 6 | Draft Assistant Simulator | Who are the best values available? |
| 7 | Draft Assistant Simulator | Should I prioritize steals right now? |
| 8 | Fantasy Sleepers & Busts | Is this sleeper worth the risk? |

### Tier 3 — after Tier 2 passes

| # | Page | Question |
|---|------|----------|
| 9 | Trend Value | Is this trend meaningful or noise? |
| 10 | Valuation | Why is this player rated highly? |
| 11 | Comparison Tool | Why is Player A ahead of Player B? |
| 12 | Historical Explorer | Why does Barry Bonds keep appearing? |

---

## 3. Procedure (each question)

1. Open the page listed (with your **saved draft board**, not the harness scenario).
2. Sidebar → **Baseball Insight** → enter question → **⚾ Baseball Insight**.
3. Command Center → **Continue** → Applied Intelligence runs analysis.
4. Read the answer as a fantasy player would — trust, not checklist keywords.
5. Record in `docs/ami_manual_responses_<date>.md` (see §6 template).
6. In Applied Intelligence Developer Mode, copy **Hydrate source** + key fields.

---

## 4. Failure diagnosis — diagnose before fixing

**If a question fails draft awareness, do not immediately change code.**

Walk through stages A–F in order. Identify the **first broken stage**, then assign **exactly one bucket**. Only then implement a fix.

| Stage | Question | Where to look |
|-------|----------|---------------|
| **A** | Context sent? | Baseball send payload: `draft_snapshot`, `draft_queue`, `needed_positions`, `question_player` |
| **B** | Classification correct? | Applied Intelligence: `problem_type_id` |
| **C** | Route/mode correct? | Applied Intelligence: `draft_mode` or solver branch |
| **D** | Enough data available? | Developer Mode fields present but unused in answer |
| **E** | Reasoning correct? | Context and mode correct, but conclusion contradicts board/roster |
| **F** | Explanation useful? | Reasoning OK, but answer generic or not decision-helpful |

### Failure classification — exactly one bucket

| Bucket | When to use | Fix locus |
|--------|-------------|-----------|
| **Send/Hydration** | Stage A — missing/wrong board, queue, player binding | `applied_math_context.py`, `suite_analytical_question.py`, page caches |
| **Classification/Routing** | Stage B or C — wrong `problem_type_id` or `draft_mode` | `applied_math_problem_router.py`, `_draft_question_mode()` |
| **Solver/Reasoning** | Stage D or E — context present, wrong conclusion or ignored fields | `applied_math_solvers.py` |
| **Explanation/Quality** | Stage F — reasoning OK, answer untrustworthy or generic | Solver output formatting, coach sections, evidence citation |

Do not patch symptoms. Fix the bucket that owns the first broken stage.

---

## 5. Session 1 — Tier 1 bar (actionable draft decisions)

**Ultimate test:** Can AMI act like a fantasy analyst looking at **my** draft instead of a generic article?

**PASS if:** Would help me make a draft decision right now — understands my draft, uses roster/board, uses actual players, actionable reasoning.

**FAIL if:** Generic advice, any-team answer, unrelated players, ignores roster/pool, doesn't help me decide.

Do not require perfect analyst prose. Ugly but decision-helpful = PASS. Polished but board-agnostic = FAIL.

### Per-question judgment

| # | Question | Pass if it helps me decide by showing… | Fail if… |
|---|----------|---------------------------------------|----------|
| 1 | Who should I draft next? | Who I drafted; who's available; queue/recs; a recommendation that fits my roster | Generic rankings, wrong pool, no decision I can act on |
| 2 | What is my biggest roster weakness? | A real weakness on *my* roster with explanation I can draft around | ADP wait copy, no roster mention, advice I'd ignore |
| 3 | Why Jose Ramirez? | Jose named; fit for *my* team; alternatives I could take instead | Wrong player, generic star copy, no decision framing |
| 4 | Who is likely to be the next catcher drafted? | Real catchers; timing/scarcity on *my* board I can use | Wrong position, unrelated names, no draft-market insight |

**Session 1 result:** PASS = all four help me decide from my board · FAIL = any do not · PARTIAL = note which helped vs which did not

### When an answer fails (no draft awareness)

Capture before any code change:

- Exact question
- Full answer
- Developer Mode fields: `hydrate_source`, `problem_type_id`, `draft_mode`, `question_player`, `draft_snapshot` present/missing
- First broken stage (A–F)
- Failure bucket: Send/Hydration · Classification/Routing · Solver/Reasoning · Explanation/Quality

Then diagnose root cause. Do not patch symptoms.

---

## 6. Response log template

Create `docs/ami_manual_responses_<date>.md` and append one block per question:

```markdown
## Tier 1 · Q1 — Who should I draft next?

**Result:** PASS | FAIL  
**Trust verdict:** Would a knowledgeable drafter believe this? YES | NO

**Full answer:**
(paste)

**Developer Mode:**
- hydrate_source:
- problem_type_id:
- draft_mode:
- draft_snapshot present: Y/N
- draft_queue present: Y/N
- needed_positions:
- question_player: (if applicable)

**Diagnosis (if FAIL):**
- First broken stage (A–F):
- Classification bucket:
- What a good answer should have said:
```

---

## 7. Regression gate (local, not acceptance)

Run before/after fixes — not as substitute for deployed manual validation:

```bash
python ami_answer_quality_audit.py
python ami_manual_acceptance.py
python -m pytest tests/test_ami_answer_quality.py -v
```

---

## 8. Historical notes (harness-era failures)

These informed fixes; deployed Tier 1 re-validates them on real boards:

| Issue | Symptom | Fix direction |
|-------|---------|---------------|
| Roster needs → value_edge | "Wait for Cal Raleigh… ADP 2" instead of C/SS + HR/SB gaps | `roster_weakness` mode |
| Sleeper generic | "This sleeper" with no name | `sleeper_candidates` + player binding |
| Jose Ramirez generic | Wrong `player` from queue[0] | `attach_question_player_to_context()` |
| Best values single-player | ADP wait, no pool ranking | `best_values` mode |

Expected Jose Ramirez pattern on deployed board:

> **Jose Ramirez** is a good player, but **[your top rec]** is the better fit because [your needs]…

(or "strong pick" if Jose is top recommendation; or "already drafted" if on board)
