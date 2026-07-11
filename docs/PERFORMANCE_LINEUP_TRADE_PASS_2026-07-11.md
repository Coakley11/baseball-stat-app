# Fantasy Lineup + app-wide performance pass (2026-07-11)

## Fantasy Lineup timings (script: `scripts/profile_lineup_assistant_baseline.py`)

| Phase | Before (uncached / repeated) | After (warm cache) |
|-------|-------------------------------|-------------------|
| Active context + shared sync (per rerun) | Repeated each `resolve_lineup_page_context` call | **0 ms** (once per page run) |
| Board payload build | ~1518 ms first build | **6 ms** payload cache hit |
| Photo faces in payload | Full HTML per player each build | Compact `{url, initials}` + session memo |
| Draft persist (unchanged drop) | Full `force_save_baseball_state` | **Skipped** when assignment dict unchanged |
| Persist repeat call | ~0.8 ms | **0.3 ms** (early return) |

Primary slowdown sources addressed:
- Repeated context resolution / shared sync on same run
- Large component payloads with rebuilt photo HTML
- Redundant global state save after identical drops

Developer Mode shows phase breakdown via `page_perf_phases` (`lineup_shared_sync`, `lineup_board_payload`, `lineup_photo_faces`, etc.).

## Five slowest pages / interactions (ranked, low-risk notes)

1. **Fantasy Lineup Assistant** — board payload + photo resolution; mitigated with per-run caches.
2. **Fantasy Standings Tracker** — standings + roster stat rebuild; existing `fantasy_perf_cache` standings key.
3. **Live Draft Room** — multiplayer poll + board render; see `profile_live_draft_*` scripts.
4. **Draft Assistant Simulator** — recommendation table + player actions; scatter/ML inference on wide tables.
5. **Saved Draft Library** — archive list scan + cloud profile reads; batch list already paginated.

## Trade Player Actions audit

Player Actions **Trade / Acquire** shortcuts now use **active eligible shared league only** (`player_trade_shortcut_eligible`).

- Handoff keys: `_fantasy_trade_handoff.league_context_id`, `player_name`, `mode`, `owner_team` → `lineup_trade_*` prefill.
- Temp live/simulator boards no longer fall back to active league ID in `_resolve_league_context_id`.
- Proposals/notifications still use `get_active_league_context()` at consume time.
