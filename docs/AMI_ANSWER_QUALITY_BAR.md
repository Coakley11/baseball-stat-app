# Baseball Insight — Answer Quality Bar

**Last updated:** 2026-06-14

Draft persistence, import validation, and Quick Guide cleanup are in good shape. **Primary focus is now answer quality**, not routing alone.

## North star

> **Would a knowledgeable fantasy baseball player trust this answer?**

A case that routes correctly but produces a generic, ungrounded, or irrelevant answer is **still a failure**.

## Nine trust criteria

Each scenario in `ami_answer_quality_audit.py` is scored on:

1. Did it understand the actual question?
2. Did it use the correct page context?
3. Did it use the draft board and roster when relevant?
4. Did it use the available player pool when relevant?
5. Did it mention real players and real data?
6. Did it explain why?
7. Did it compare alternatives when appropriate?
8. Did it avoid generic filler and invented facts?
9. Would a knowledgeable fantasy baseball player trust the answer?

## Pipeline (A → F)

| Stage | What we check |
|-------|----------------|
| **A** | Baseball sends the right context (keys, draft snapshot, pool) |
| **B** | AMI classifies the question (`problem_type_id`) |
| **C** | AMI selects reasoning mode (`draft_mode`, solver branch) |
| **D** | Answer contains meaningful analysis (evidence, names, stats) |
| **E** | Answer is explained clearly (why, tradeoffs) |
| **F** | Composite fantasy-player trust |

**Routing-only failure:** `route_id` is set but `player_trustworthy` is false.

## Question families under test

| Family | Example questions |
|--------|-------------------|
| Draft Assistant | Steals priority, roster weakness, best values, draft next |
| Draft Market | Next catcher, closer run, wait timing, make it back |
| Player Evaluation | Olson vs Schwarber, Jose Ramirez why, hitter roster fit |
| Sleepers | Take this sleeper?, worth the risk? |
| Trend | Meaningful vs noise, improve next season, doubles trend |
| Valuation | Why rated highly?, is it justified? |
| Comparison | Power value, why A over B |
| Historical Explorer | Bonds filters, filter causes, what comparison shows |

## How to run

```bash
cd baseball-stat-app
python ami_answer_quality_audit.py
python ami_hardening_pass.py   # stages A–G include quality as stage G
python -m pytest tests/test_ami_answer_quality.py -v
```

Reports: `docs/ami_answer_quality_report.json`

## Current baseline (2026-06-16)

**27/32 passed · 27 trustworthy · 5 routing-only failures**

Six new quality cases added for Comparison AMI, Trend AMI, and Sleepers/Busts (manual testing
gate). Three of the six pass immediately; three expose AMI-side answer-quality gaps (noted below).
Two pre-existing failures (Olson vs Schwarber player contamination, Team needs no recommendation)
are AMI-side issues, not Baseball-side.

| Family | Trustworthy | Routing-only fail | Notes |
|--------|-------------|-------------------|-------|
| Draft Market | 5/5 | 0 | |
| Draft Assistant | 5/6 | 1 | `team_needs` — no recommendation (AMI) |
| Player Evaluation | 2/3 | 1 | `olson_vs_schwarber` — Juan Soto contamination (AMI) |
| Sleepers | 2/3 | 1 | `bust_risk_section` — missing bust language (AMI) |
| Trend | 4/5 | 1 | `trend_named_player` — no sustain/regress language (AMI) |
| Valuation | 2/2 | 0 | |
| Comparison | 4/5 | 1 | `comparison_draft_pick_qs` — no draft/pick language (AMI) |
| Historical Explorer | 3/3 | 0 | |

### Open AMI-side quality gaps (routing-only failures)

| Case | Symptom | Fix locus |
|------|---------|-----------|
| `olson_vs_schwarber` | Answer mentions Juan Soto; doesn't address "better" or "draft" | AMI solver — comparison_draft_pick / player contamination |
| `team_needs` | Routes to roster_weakness but produces no concrete recommendation | AMI solver — roster_weakness mode missing actionable conclusion |
| `comparison_draft_pick_qs` | Comparison answer lacks "draft" / "pick" language | AMI solver — comparison_draft_pick mode doesn't frame as draft decision |
| `trend_named_player` | Trend answer doesn't address sustainability or regression | AMI solver — trend mode missing "sustain"/"regress" framing |
| `bust_risk_section` | Bust review answer missing "bust" and "risk" terms | AMI solver — bust_risk_review mode doesn't use bust-specific language |

Fix priority when a **new** case fails: context → classification → solver → explanation. No hard-coded per-question answers.

## What we are not doing

- Hard-coding answers to individual questions
- Changing Draft Room architecture or Live Draft workflows
- Treating routing pass as sufficient acceptance

## Fix priority when a case fails

1. **Context** — Does Baseball send board, roster, pool, page snapshot?
2. **Classification** — Does AMI route to the right solver/mode?
3. **Solver** — Does the solver use context keys and name real players?
4. **Explanation** — Coach sections, tradeoffs, evidence — not filler

Manual deployed checks remain required; local audit is necessary but not sufficient.
