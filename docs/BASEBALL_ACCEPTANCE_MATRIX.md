# Baseball Final Acceptance Matrix

**Last updated:** 2026-06-08  
**Sweep status:** Phase 2 reference implementation — **PASS** (with documented partials)  
**Automated tests:** 147 passed (`test_*state*`, persistence, AMI scope)  
**Manual sign-off:** Sprints 2–6 accepted on phone + Dell

Legend: **PASS** · **PARTIAL** (works, known gap) · **FAIL** · **N/A**

---

## Per-page matrix

| Page | Canonical module | A Local | B Phone↔Dell | C Cloud | D Nav | E AMI | Insight scope | Dismiss | Tests |
|------|------------------|---------|--------------|---------|-------|-------|---------------|---------|-------|
| Historical Explorer | `historical_state` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 11 |
| Career Totals | `career_totals_state` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 13+ |
| Leaderboards | `leaderboards_state` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 11 |
| Comparison Tool | `comparison_state` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 15+ |
| Trend Value | `trend_state` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 12+ |
| Valuation | `valuation_state` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 11 |
| ML Predictions | `projections_state` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 12 |
| Fantasy Sleepers & Busts | `fantasy_state.sleepers` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 12 |
| Fantasy Standings Tracker | `fantasy_state.standings` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 12 |
| Fantasy Lineup Assistant | `fantasy_state.lineup` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 12 |
| Draft Assistant Simulator | `draft_state` + registry | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 13 |
| Draft Room Simulator | `draft_state` + registry | PASS | PASS | PASS | PASS | PARTIAL | PASS | PASS | 13 |
| Draft Simulation Test Mode | `draft_state` + registry | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 13 |
| Live Draft Room | `draft_state` + registry | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 13 |

**Overall:** 14/14 PASS · 1 PARTIAL (Draft Room AMI uses draft-cluster relaxed scope only)

---

## Cross-cutting verification

| Goal | Status | Evidence |
|------|--------|----------|
| 1. Every page audited | PASS | 14/14 in `PAGE_OPTIONS`, registry, streamlit blocks |
| 2. Canonical ownership | PASS | 9 modules; draft uses global + registry (documented) |
| 3. Phone ↔ Dell sync | PASS | Manual Sprints 2–6; envelope + force-save |
| 4. Cloud restore | PASS | `apply_cloud_*_if_allowed`, dirty flags, `test_page_state_cloud_restore` |
| 5. Manual navigation ownership | PASS | `claim_user_page_ownership`; CC `test_page_navigation_ownership` (43) |
| 6. AMI source_state + return | PASS | All pages in `build_source_state` / `apply_source_state_to_session` |
| 7. Insight page scoping | PASS | `INSIGHT_ELIGIBLE_PAGES` all 14 pages; scope tests |
| 8. Dismiss behavior | PASS | `_ami_dismissed_insight_ids` in blob; hydrate skips dismissed |
| 9. No page bounce / stale overwrite | PASS | Sprint 1 nav ownership; manual accepted |

---

## Pattern classification

| Pattern | Pages | Notes |
|---------|-------|-------|
| **Full** prepare/flush/on_change | Historical, Career, Leaderboards, Valuation, ML, Fantasy×3 | Reference for new pages |
| **On-change-only** | Comparison, Trend | No page-end flush; canonical via handlers |
| **Global workflow** | Draft×4 | Sidebar `draft_state`; page filters via registry |
| **Generic registry only** | — | None remaining as sole persistence |

---

## Remaining bugs (ranked)

### P0 — None

No open blockers for suite port gate. Fantasy Standings AMI fixed (`ab8faef` / `990c25e`).

### P1 — Should fix before suite port

| ID | Issue | Pages | Fix |
|----|-------|-------|-----|
| P1-1 | Draft pages lack per-widget `on_change` → immediate force-save | Draft×4 | Add `draft_filter_changed` on room/live widgets or document global flush as accepted |
| P1-2 | No `test_page_navigation_ownership.py` in baseball repo | Global | Port CC test file or run CC tests in CI matrix |
| P1-3 | `build_baseball_applied_math_context` sparse for Career/Leaderboards/Valuation/ML/Fantasy | AMI solver context | Extend rich context builders (optional for display-only v1) |
| P1-4 | `sync_suite_cloud_modules.py` can revert baseball `suite_user_persistence` bypass list | Global | Add CC bypass reasons to sync source; post-sync diff check in CI |

### P2 — Cleanup / polish

| ID | Issue | Fix |
|----|-------|-----|
| P2-1 | ~~Draft Room missing `PAGE_STATE_DEBUG_PREFIXES`~~ | Fixed 2026-06-08 (`draft_room_`, `room_`) |
| P2-2 | Dual persistence (`save_page_state` + canonical flush) on all pages | Document in protocol; optional consolidation later |
| P2-3 | Baseball `*_state.py` not in sync script | Add `sync_baseball_state_modules.py` or document manual port |
| P2-4 | Draft pages: no page-scoped `render_draft_state_debug` | Global sidebar panel only |
| P2-5 | Comparison/Trend: no page-end flush debug trace | Add optional trace rows in dev panel |

---

## Not migrated (intentional)

| Item | Reason |
|------|--------|
| ML projection DataFrames | Local-only derived data |
| Fantasy roster/standings fetch results | Re-fetched each session |
| Ephemeral transfer keys | One-hop navigation payloads |
| Upload widget state | Streamlit limitation |

---

## Suite port readiness

**Gate: PASS** — Baseball is approved as reference implementation.

Next: port shared protocol to Music, NBA, Investment, Applied Intelligence per [BASEBALL_PAGE_STATE_PROTOCOL.md](./BASEBALL_PAGE_STATE_PROTOCOL.md).

---

## Verification commands

```bash
cd baseball-stat-app
python -m pytest tests/test_comparison_state.py tests/test_trend_state.py \
  tests/test_career_totals_state.py tests/test_historical_state.py \
  tests/test_leaderboards_state.py tests/test_valuation_state.py \
  tests/test_projections_state.py tests/test_fantasy_state.py \
  tests/test_draft_state.py tests/test_baseball_persistence.py \
  tests/test_page_state_cloud_restore.py tests/test_insight_page_scope.py \
  tests/test_fantasy_cluster_ami_return.py tests/test_applied_math_context.py -q

cd ../daniel-ai-command-center
python -m pytest tests/test_page_navigation_ownership.py tests/test_insight_page_scope_decision.py -q
```

Manual smoke: deploy `dev`, append `?dev=1`, walk all 14 sidebar pages, confirm canonical debug panel + filter persistence.
