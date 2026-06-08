# Baseball Page State Protocol

**Last updated:** 2026-06-08  
**Status:** Reference implementation (Phase 2 complete)  
**Repo:** `baseball-stat-app` · **Branch:** `dev`  
**Reference tag:** `baseball-sync-reference-v1` — suite sync architecture baseline for Sprint 7 port

This document defines the canonical page-state architecture used across all 14 Baseball sidebar pages. Other suite apps (Music, NBA, Investment, Applied Intelligence) should replicate this pattern with app-specific `{page}_state.py` modules.

---

## Goals

1. **Single ownership** — one canonical blob per page (or shared cluster) is the source of truth.
2. **Cross-device sync** — phone ↔ Dell via disk + Supabase `full_session`.
3. **Cloud protection** — local dirty flags block stale disk/defaults from erasing newer cloud state.
4. **Navigation stability** — manual sidebar selection beats stale cloud page overwrite.
5. **AMI return** — Applied Math Insight hydrates once, restores filters, renders only on source page, dismisses cleanly.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│  streamlit_app.py (per page)                                    │
│    prepare_*_page() / prepare_*_filters()  ← before widgets     │
│    on_change → mark_*_pending_sync → flush_*_edits (optional)   │
│    save_page_state()  ← generic PAGE_STATE_REGISTRY snapshot    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  {page}_state.py                                                │
│    write_canonical_*_state()  ← filters, entities, reason       │
│    is_*_locally_dirty / mark_*_local_edit / clear_*             │
│    restore_*_page_filters() / apply_cloud_*_if_allowed()        │
│    apply_*_source_state_from_ami()                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  baseball_persistent_state.py                                   │
│    build_baseball_disk_state() → disk + cloud blob              │
│    apply_baseball_disk_state() → atomic workspace restore       │
│    _WORKSPACE_KEYS + baseball_workspace_state envelope          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  suite_user_persistence.py + suite_cloud_state.py (shared)      │
│    sync_workspace_protocol(), force_autosave(), cloud compare   │
│    claim_user_page_ownership(), *_edit force-save bypass        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Lifecycle (per page rerun)

| Phase | Action |
|-------|--------|
| **Startup** | `prepare_baseball_workspace()` — cloud/disk restore before sidebar |
| **Before widgets** | `prepare_*_page()` + `prepare_*_filters()` — seed from canonical blob |
| **User edit** | `on_change` → `mark_*_pending_sync` → `flush_*_filter_edits` → `force_save_baseball_state(reason="*_edit")` |
| **Page leave** | `page_state.save_page_state()` → `page_filter_state[page]` |
| **Page return** | `restore_*_page_filters()` — blocked if `*_state_dirty` |
| **Cloud restore** | `apply_cloud_*_state_if_allowed()` — blocked if locally dirty |
| **AMI send** | `build_source_state(page, session)` in `applied_math_context.py` |
| **AMI return** | `apply_*_source_state_from_ami()` + insight hydrate; no re-nav after consume |

---

## Required module API

Each canonical `{page}_state.py` should export:

| Function | Purpose |
|----------|---------|
| `prepare_*_page(session)` | Reconcile widget vs canonical; respect dirty flag |
| `prepare_*_filters(session)` | Seed widget keys from canonical when unset |
| `write_canonical_*_state(session, *, filters, reason, local_edit, sync_widget_keys)` | Single write path |
| `gather_*_filters(session)` / `canonical_*_filters(session)` | Read paths for persistence + AMI |
| `mark_*_filter_pending_sync(session)` | Flag pending cross-device save |
| `flush_*_filter_edits(session, st, reason=)` | End-of-rerun or on_change flush |
| `restore_*_page_filters(session, store)` | From `page_filter_state`; return `False` if dirty |
| `is_*_locally_dirty(session)` | Dirty ownership |
| `mark_*_local_edit` / `clear_*_local_edit` | Local edit beats restore |
| `apply_cloud_*_state_if_allowed(session, cloud_blob)` | Cloud newer protection |
| `apply_*_source_state_from_ami(session, source_state)` | AMI return restore |
| `render_*_state_debug(st, session)` | `?dev=1` sidebar panel |

**Handler rule:** `on_change` callbacks must be **defined before** the page block in `streamlit_app.py` (module load order).

---

## Canonical modules (9 modules, 14 pages)

| Module | Pages | Session key | Envelope field |
|--------|-------|-------------|----------------|
| `historical_state.py` | Historical Explorer | `historical_state` | `historical_filters` |
| `career_totals_state.py` | Career Totals | `career_state` | `career_filters` |
| `leaderboards_state.py` | Leaderboards | `leaderboards_state` | `leaderboards_filters` |
| `comparison_state.py` | Comparison Tool | `comparison_state` | `comparison_players` |
| `trend_state.py` | Trend Value | `trend_state` | `trend_players` |
| `valuation_state.py` | Valuation | `valuation_state` | `valuation_filters` |
| `projections_state.py` | ML Predictions | `projections_state` | `projections_filters` |
| `fantasy_state.py` | Sleepers, Standings, Lineup | `fantasy_state` (sections) | `fantasy_*_filters` |
| `draft_state.py` | Draft×4 + queue/watchlist | `draft_state` | `draft_workflow` |

**Helper:** `year_range_state.py` — shared year-range widget seeding.

**Generic fallback:** `page_state.py` — `PAGE_STATE_REGISTRY`, `save_page_state()`, `restore_page_state()` for keys not yet in a canonical module.

---

## `_WORKSPACE_KEYS` (disk/cloud blob)

```python
_WORKSPACE_KEYS = (
    "comparison_state",
    "trend_state",
    "career_state",
    "draft_state",
    "historical_state",
    "valuation_state",
    "projections_state",
    "leaderboards_state",
    "fantasy_state",
)
```

Global keys (not per-page modules): `draft_room_table`, `room_your_team`, `room_team_count`, `room_rounds`, `room_format`.

---

## Force-save cloud bypass reasons

In `suite_user_persistence.py`, these reasons bypass blank-comparison cloud block and post-restore autosave cooldown:

`comparison_edit`, `trend_edit`, `career_edit`, `draft_edit`, `historical_edit`, `valuation_edit`, `projections_edit`, `leaderboards_edit`, `fantasy_edit`, `page_change`, `insight_persist`, `insight_hydrate`, `applied_math_send`

Each page module calls `force_save_baseball_state(st, reason="<page>_edit")` after meaningful filter edits.

---

## Ownership rules

| Rule | Mechanism |
|------|-----------|
| Local user edit beats restore | `*_state_dirty` + `*_last_local_edit_ts` |
| Newer cloud beats stale disk | `sync_workspace_protocol`, `cloud_newer_than_applied` |
| Manual nav beats cloud page | `claim_user_page_ownership`, `_suite_user_owned_page` |
| AMI return hydrates once | `_ami_insight_return_preserve`, `consume_ami_return_resume` |
| Insight renders on source page only | `INSIGHT_ELIGIBLE_PAGES` + `insight_page_scope_decision` |
| Dismiss persists cross-device | `_ami_dismissed_insight_ids` in disk blob |

---

## Applied Math Insight (AMI)

### Eligible pages (`INSIGHT_ELIGIBLE_PAGES["baseball"]`)

All 14 sidebar pages except none — full list:

Comparison Tool, Trend Value, Historical Explorer, Career Totals, Valuation, ML Predictions, Leaderboards, Fantasy Sleepers & Busts, Fantasy Standings Tracker, Fantasy Lineup Assistant, Draft Assistant Simulator, Draft Room Simulator, Draft Simulation Test Mode, Live Draft Room.

### Source state

- **Build:** `applied_math_context.build_source_state(page, session)` — uses canonical gather functions.
- **Apply:** `applied_math_context.apply_source_state_to_session()` — per-page `apply_*_source_state_from_ami`.
- **Return:** `applied_math_return_insight.apply_return_source_state()` — schedules nav only on first return; consume on first render.

### Page scoping

```python
should_render_insight_on_page(source_app, current_page, insight)
# True only when normalized source_page == current_page
# Draft pages: relaxed match when both contain "draft"
```

---

## Intentionally local-only keys

Do **not** persist to disk/cloud:

| Key / data | Reason |
|------------|--------|
| `ml_predictions_df`, projection DataFrames | Large derived data |
| `fantasy_current_roster_stats`, `fantasy_current_standings` | Fetched/uploaded each session |
| `lineup_context_category_needs` | Ephemeral transfer payload |
| Button/action widget keys (`*_button`) | Streamlit assignment errors |
| File upload buffers | Session-only |

---

## Dev diagnostics (`?dev=1`)

| Panel | Location |
|-------|----------|
| Cross-device sync trace | `render_cross_device_sync_debug` — sidebar |
| Insight sync trace | `render_insight_sync_debug` — sidebar |
| Page filter debug | `render_page_filters_debug(active_page)` — page bottom |
| Canonical state debug | `render_*_state_debug` — per page or global draft |
| Page State Debug | `render_page_state_debug` — sidebar |

---

## Sync workflow (shared modules)

After editing shared modules in **Command Center**:

```bash
cd daniel-ai-command-center
python scripts/sync_suite_cloud_modules.py
```

Copied to all suite apps: `suite_user_persistence.py`, `applied_math_return_insight.py`, `suite_cloud_state.py`, etc.

**Not synced automatically:** baseball `*_state.py`, `baseball_persistent_state.py`, `applied_math_context.py` — copy/adapt manually per app.

---

## Suite port — modules by app

### Copy from Command Center (`scripts/sync_suite_cloud_modules.py`)

All six sibling repos receive these on sync:

| Module | Role |
|--------|------|
| `activity_time.py` | UTC activity timestamps |
| `suite_storage_config.py` | Supabase config resolution |
| `suite_storage_supabase.py` | PostgREST client |
| `suite_activity_client.py` | Activity write path |
| `suite_user.py` | Suite user identity |
| `suite_account.py` | Account summary helpers |
| `suite_deep_links.py` | Resume / AMI return URLs |
| `suite_resume_launch.py` | Query-param resume handling |
| `suite_cloud_state.py` | Cloud `full_session` load/save |
| `suite_user_persistence.py` | Cross-device persistence protocol |
| `suite_analytical_question.py` | Applied Math sidebar |
| `applied_math_return_insight.py` | Insight hydrate, scope, dismiss |

### Adapt per app (pattern from Baseball)

| Module | Adapt as |
|--------|----------|
| `page_state.py` | `{app}_page_state.py` — PAGE_STATE_REGISTRY |
| `baseball_persistent_state.py` | `{app}_persistent_state.py` — APP_ID, envelope, `_WORKSPACE_KEYS` |
| `applied_math_context.py` | `{app}_applied_math_context.py` — build/apply source_state |
| `{page}_state.py` × N | One module per major page/cluster |

### Target apps (Sprint 7)

| App | Suggested first `{page}_state` modules |
|-----|--------------------------------------|
| **Music Practice Coach** | Studio session, song catalog, CPL bar state |
| **NBA Companion** | Legacy Tracker player, LGC matchup, team focus |
| **Investment Analyzer** | Portfolio health tab, holdings, scenario inputs |
| **Applied Intelligence** | Lesson session, question bank, progress |

### Baseball patterns worth copying (not synced)

| Module | Role |
|--------|------|
| `page_transfers.py` | Cross-page contextual transfers |
| `workflow_sidebar.py` | Global sidebar workflow (draft queue analog) |
| `year_range_state.py` | Shared slider seeding helper |

---

## Acceptance tests (A–E)

| Test | Description |
|------|-------------|
| **A** | Local persistence — edit, rerun, values remain |
| **B** | Phone ↔ Dell — edit on one device, refresh other |
| **C** | Cloud protection — stale local cannot erase cloud |
| **D** | Navigation — no bounce, manual nav wins |
| **E** | AMI — send, return, insight on source page only, filters preserved, dismiss works |

Automated: `tests/test_*_state.py` (per module), `tests/test_insight_page_scope.py`, `tests/test_fantasy_cluster_ami_return.py`.

Manual: phone + Dell with `?dev=1` after each sprint.

See [BASEBALL_ACCEPTANCE_MATRIX.md](./BASEBALL_ACCEPTANCE_MATRIX.md) for per-page PASS/FAIL.

---

## Pattern variants

### Full pattern (Historical, Career, Leaderboards, Valuation, ML, Fantasy)

`prepare` → widgets with `on_change` → `flush` at page end → canonical blob.

### On-change-only (Comparison, Trend)

No page-end `flush_*`; canonical sync via dedicated `on_change` handlers (`compare_settings_changed`, `trend_settings_changed`).

### Global workflow (Draft cluster)

`draft_state.py` manages queue + watchlist globally via sidebar `prepare_draft_workflow` / `flush_draft_workflow_edits`. Draft page filters use generic `PAGE_STATE_REGISTRY` + global flush.

---

## Adding a new page

1. Add keys to `PAGE_STATE_REGISTRY` in `page_state.py`.
2. Create `{page}_state.py` following Trend/Valuation template.
3. Add to `_WORKSPACE_KEYS` and `_build_workspace_envelope` in `baseball_persistent_state.py`.
4. Wire `prepare_*`, handlers **before** page block, `flush_*`, dev debug in `streamlit_app.py`.
5. Add AMI branches in `applied_math_context.py`.
6. Add to `INSIGHT_ELIGIBLE_PAGES` if insight cards desired.
7. Add `{page}_edit` to force-save bypass list.
8. Write `tests/test_{page}_state.py` with A–E coverage + handler order guard.
