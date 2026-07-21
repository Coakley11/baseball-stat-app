# Live Draft state owners (Phase 1 audit)

**Last updated:** 2026-07-21  
**Authoritative room:** `session["live_draft_room"]` — `current_pick_index`, `draft_board`, `status`, `timer_deadline`, `revision`.  
**Canonical paint (read-only for UI):** `live_draft_canonical_snapshot.get_live_draft_paint_snapshot(session)` — frozen per page paint via `begin_live_draft_paint()`.

## Write owners (mutations)

| Concern | Primary writer | Notes |
|--------|----------------|-------|
| Pick commit / advance | `live_draft_pick_commit.commit_live_draft_pick` | All manual picks |
| Auto-pick (button) | `live_draft_autopick.live_draft_auto_pick` → `live_draft_make_pick` + `finalize_live_draft_pick_transition` | |
| Timer expire (Solo) | `live_draft_solo_timer.expire_current_pick_and_advance` | Idempotent guard `SOLO_EXPIRE_APPLIED_KEY` |
| Timer expire (Shared) | `live_draft_expired_pick` / poll CAS paths | |
| Timer deadline | `live_draft_timer_logic.live_draft_reset_timer`, `live_draft_resume_timer` | Never derive next deadline from expired value |
| Pause / resume | `live_draft_timer_logic.live_draft_pause_timer`, `live_draft_resume_timer` | |
| Board / rosters | `live_draft_pick_engine.live_draft_make_pick` | Called only via commit/autopick/expire |
| Queue | `draft_state`, `draft_ui`, queue persist helpers | Must not block timer fragment |
| Recommendation cache | `live_draft_ui_cache`, post-pick patch in `finalize_live_draft_pick_transition` | |
| Paint snapshot | `begin_live_draft_paint`, invalidated by `invalidate_live_draft_paint` after pick/control | |

## Read surfaces (must use paint or `draft_action_context`)

| Surface | Module | Status |
|---------|--------|--------|
| Page header pick/team | `streamlit_app.py` Live Draft Room | **Fixed** — paint → slot, removed `picks_done + 1` |
| Sidebar status | `draft_ui.render_draft_sidebar_status` → `draft_status_summary` | Uses paint via `draft_actions` |
| On-the-clock banner | `live_draft_on_clock_ui` | Solo: **static JS countdown** (one paint per pick); Shared: fragment repaints only on pick/deadline change |
| Sidebar timer | `draft_ui._render_live_draft_room_sidebar_snapshot` | Live Draft Room: snapshot copy only — **no fragment** |
| Draft authorization | `draft_actions.draft_action_context` | Paint-first |
| Queue caption | `draft_actions` / `draft_ui` | Paint team |
| Control center Auto Pick | `live_draft_control_center_ui` | Paint `team_on_clock` |
| Timer display | `live_draft_timer_ui`, paint `timer_remaining` | |

## Obsolete / redirected resolvers

| Resolver | Action |
|----------|--------|
| `picks_done + 1` header fallback | **Removed** in `streamlit_app.py` (2026-07-20) |
| `build_shared_live_draft_snapshot` in Solo fragment | Fallback only when paint import fails |
| Independent `live_draft_current_slot` for headers | Replaced by paint-aligned slot dict |
| Board-length-derived pick number | Must not be used for display when paint exists |

## Deferred batch guards

- `SOLO_EXPIRE_APPLIED_KEY` — idempotent expire per pick index  
- `auto_pick_idempotency_key` — fragment double-fire  
- `commit_live_draft_pick` — asserts board +1, idx +1  
- Slow persist must not block local mutation (`fast_path`, optimistic paths)

## Persistence (Cloud latency)

- `persist_applied_pick` — async-tolerant; local room updates before return  
- Queue autosave — **not** in 1Hz timer fragment (`live_draft_on_clock_ui`)  
- Pause — no `force_live_draft_expensive_recompute` on click (`live_draft_safe_mode`)

## Timer expiration ownership (Solo)

| Surface | Calls `expire_current_pick_and_advance`? | Role |
|---------|------------------------------------------|------|
| Solo heartbeat fragment (`live_draft_solo_heartbeat`) | **Yes** — sole Solo production owner | 1 Hz expire-only loop; **does not** remount banner HTML |
| On-the-clock banner (`live_draft_on_clock_ui`) | **No** (Solo) | Paints once per pick with JS deadline countdown |
| Sidebar timer (`draft_ui.render_draft_sidebar_timer`) | **No** | Live Draft Room: canonical snapshot caption only |
| Draft Control Center Auto Pick Now | Uses `live_draft_auto_pick` (manual path, not timer expire) | User-initiated, not timer-driven |
| Page script fallback (`run_solo_expire_if_needed`) | Only when heartbeat inactive | First paint / no-fragment canary mode |

**Production invariant:** exactly **one** effective Solo 1 Hz fragment (`solo_heartbeat`). Banner HTML must not repaint every second (Cloud ghost timers). Sidebar and blue card both derive remaining time from the same deadline/snapshot during each full-page paint.

## AppTest sidebar timer skip (test harness only)

Full-page AppTests set `_fp_sidebar_timer_skipped=True` (or `_live_draft_apptest_skip_sidebar_timer`) so tests avoid duplicate widgets. **Production Live Draft Room** also skips the sidebar timer fragment — snapshot copy only (2026-07-21).

## Remaining known limitations

1. Shared multiplayer fragment still uses `build_shared_live_draft_snapshot` when paint unavailable (by design for poll sync).  
2. Full `streamlit_app.py` Live Draft Room is only partially covered by AppTest fixture — harness covers logic; fixture covers major widgets.  
3. Cloud egress poll (8s) not simulated in unit tests — slow-persist tests use 150ms stub.
