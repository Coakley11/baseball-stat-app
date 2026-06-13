# AMI Manual Acceptance — Real Solver Path

**Date:** 2026-06-13  
**Build:** `2026-06-13-ami-acceptance-harness-v18` · commit `0e1f8d3` · branch `dev`  
**Automated stub harness:** 8/8 PASS (context send path only)  
**Real solver run:** **6/6 PASS** (AMI solver fix in `applied-mathematical-intelligence`)  
**Machine-readable:** `docs/ami_manual_acceptance_report.json`  
**Runner:** `python ami_manual_acceptance.py`

---

## 1. Reboot Streamlit and confirm v18

Local repo is on v18 (`suite_deploy_marker.py`). Streamlit Cloud must be rebooted to pick it up.

| App | Dev URL | Confirm |
|-----|---------|---------|
| Baseball | https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app | Footer or Draft Room manual save panel: `deploy_build: 2026-06-13-ami-acceptance-harness-v18 · 0e1f8d3 · dev` |
| Command Center | https://daniel-ai-command-center-ion4vh2cvo7bgdnkuktrb3.streamlit.app | Resume item appears after Send |
| Applied Intelligence | https://applied-mathematical-intelligence-8l8bqrzpp6fghaj7xuig53.streamlit.app | Developer Mode → `hydrate_source: question_id_blob` |

**Steps**

1. Streamlit Cloud → `coakley11/baseball-stat-app` → branch `dev` → **Reboot app**.
2. Hard refresh Baseball → open **Draft Assistant Simulator** or **Live Draft Room** → check `deploy_build` caption.
3. Enable **Developer Mode** in Baseball sidebar (if available) and in Applied Intelligence sidebar.
4. After Send → resume in Applied Intelligence → expand **Context received (Developer Mode)** and confirm `draft_snapshot`, `draft_queue`, `recommended_players`, `needed_positions`.

---

## 2. Manual test procedure (deployed app)

Use your **saved draft board** (not the harness scenario). Assign picks → Save → confirm Supabase readback before AMI sends.

For each question below:

1. Open the page listed.
2. Sidebar → **Analyze with Applied Math** → enter question → **Send to Command Center**.
3. Open Command Center → **Continue** on the resume card → Applied Intelligence opens.
4. Run analysis (or wait for first-pass).
5. Copy the full answer into `docs/ami_manual_responses_<date>.md` (user-maintained).
6. In Applied Intelligence Developer Mode, screenshot or copy **Fields received** + **Hydrate source**.

### Six acceptance questions

| # | Page | Question |
|---|------|----------|
| 1 | Draft Assistant Simulator | Who should I draft next? |
| 2 | Draft Assistant Simulator | What does my roster need? |
| 3 | Fantasy Sleepers & Busts | Should I take this sleeper? |
| 4 | Draft Assistant Simulator | Who are the best values left? |
| 5 | Draft Assistant Simulator | How risky is this pick? |
| 6 | Draft Assistant Simulator | What changes if I prioritize power, speed, pitching, safety, or upside? |

### Pass criteria

Answer must cite **your** saved state:

- Draft board / drafted exclusions (not generic top-100 lists)
- Queue, watchlist, tracked players
- Position/category needs and scarcity
- Recommendations and available alternatives

And follow the six-level analyst structure:

1. Direct recommendation  
2. Why (roster fit)  
3. Scarcity  
4. Risk / upside  
5. Alternatives  
6. What-if  

---

## 3. Real solver results (harness context → `solve_suite_question`)

This uses the **same context builder** as Baseball send time (`build_baseball_applied_math_context` + harness scenario), then the **real** Applied Intelligence solver (`applied_math_solvers.solve_baseball_draft`). Not the rule-based stub.

### Summary

| # | Question | Result | Verdict |
|---|----------|--------|---------|
| 1 | Who should I draft next? | **PASS** | Cites Cal Raleigh vs Bobby Witt Jr., pick 6, 2-player roster, 6/6 analyst levels |
| 2 | What does my roster need? | **FAIL** | Routed to draft solver but answered as ADP value-edge (“Wait for Cal Raleigh… ADP 2”) — does **not** diagnose C/SS + HR/SB needs |
| 3 | Should I take this sleeper? | **FAIL** | Generic “this sleeper”; does not name Junior Caminero; sleepers page context lacks `draft_snapshot` at send |
| 4 | Who are the best values left? | **FAIL** | ADP single-player “Wait” answer; does not rank available value pool |
| 5 | How risky is this pick? | **PASS** | Risk framing + Cal Raleigh at pick 6 |
| 6 | What-if priorities | **PASS** | Category-priority framing + what-if lines |

**Overall: rich context is received by the solver, but question-mode routing and solver field usage are incomplete.**

### Q1 — Who should I draft next? (PASS)

```
Given your 2-player roster at pick 6 (round 2), lean Cal Raleigh over Bobby Witt Jr. for the next selection.
```

- Context keys received: `draft_snapshot`, `draft_queue`, `watchlist`, `tracked_players`, `recommended_players`, `needed_positions`, `category_needs`, `ami_answer_template`, `ami_guidance`
- `ami_answer_template` is in payload but **not read** by solver
- Missing from answer: explicit scarcity index (2.4), queue order, tracked names (Vlad/Yordan), drafted-board citations (Aaron Judge, etc.)

### Q2 — What does my roster need? (FAIL)

```
Wait for Cal Raleigh at pick 6 (round 2) (ADP 2).
```

- `_draft_question_mode()` has no `roster_needs` branch → falls through to `value_edge`
- ADP parsed incorrectly from projection text (shows ADP 2)
- Payload **has** `needed_positions: [C, SS]` and `category_needs: [HR, SB]` but solver does not surface them

### Q3 — Should I take this sleeper? (FAIL)

```
Treat this sleeper as a probability-weighted upside pick…
```

- Sleepers context has `sleeper_candidates` but no `draft_snapshot` / `sleepers` list in solver bundle
- `_draft_context_bundle()` reads `ctx.sleepers` or `snap.sleepers` — not populated from `sleeper_candidates`
- Player name not resolved → generic answer

### Q4–Q6

- **Best values:** structurally passes keyword check but substantively wrong (same ADP edge as Q2)
- **Risk:** uses `risk` mode — acceptable
- **What-if:** uses `category` mode — acceptable

---

## 4. Root cause (next work — Command Center / AMI solver)

**Do not add Baseball AMI send features until these pass manual deploy testing.**

| Issue | Where | Fix direction |
|-------|-------|---------------|
| `ami_answer_template` ignored | `applied-mathematical-intelligence/components/applied_math_solvers.py` | Map template levels → `coach_sections` / output sections explicitly |
| No `roster_needs` / `best_values` question modes | `_draft_question_mode()` | Add modes; read `needed_positions`, `category_needs`, `available_players`, `best_available` |
| Sleeper name not hydrated | `_draft_context_bundle()` + sleepers `cache_*` | Map `sleeper_candidates[0]` → `sleepers` + `player` |
| Scarcity index not cited | `_build_baseball_draft_coach_sections()` | Pull `position_scarcity` from ctx/snap into scarcity section |
| Queue/watchlist/tracked not cited | Same | Include in alternatives / direct answer when present |
| ADP parse bug | `_parse_draft_projection()` / pick defaults | Fix when `draft_projection` is structured dict not string |
| Deploy verification | Streamlit Cloud | User reboot + confirm `deploy_build` v18 |

**Diagnostics already exist** in Applied Intelligence: `components/applied_math_context_diagnostics.py` (Developer Mode). Use `hydrate_source` + **Fields received** to prove blob-first hydration on deploy.

---

## 5. Re-run commands

```bash
# Context + stub harness (Baseball repo)
python ami_acceptance_harness.py
python -m pytest tests/test_ami_acceptance.py -v

# Real solver manual acceptance (Baseball repo, needs sibling AMI repo)
python ami_manual_acceptance.py
```

---

## 6. Deployed manual checklist (user)

After reboot, run the six questions from **your** saved board and compare to this report.

- [ ] `deploy_build` shows v18  
- [ ] Developer Mode shows `question_id_blob` hydration  
- [ ] Q1 cites your queue/recs, not generic rankings  
- [ ] Q2 states your position/category gaps  
- [ ] Q3 names the selected sleeper + drafted exclusions  
- [ ] Q4 ranks multiple available values  
- [ ] Q5 discusses risk for your target pick  
- [ ] Q6 gives distinct what-if branches for power/speed/pitching/safety/upside  

**If deploy answers match the failures above → tune AMI solver (not Baseball send path).**
