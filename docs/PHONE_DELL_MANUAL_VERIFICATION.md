# Phone ↔ Dell Manual Verification Checklist

**Purpose:** Confirm that every cloud-backed state field actually round-trips between devices on
a real deployed app — not just verified at the infrastructure level.

**Last updated:** 2026-06-16  
**App:** https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app  
**Branch:** `dev`

**How to use this doc:**
1. Pick a workflow below.
2. Make the change on **Device A** and save (use the Save button or trigger a force-save by editing).
3. Open (or hard-refresh) the app on **Device B** without making any changes first.
4. Confirm the expected value appears.
5. Mark **PASS / FAIL / PARTIAL** and note any discrepancy.

**Pre-flight:**
- [ ] Both devices are logged in as the same Supabase user
- [ ] `deploy_build` confirmed in Baseball sidebar (both devices)
- [ ] Developer Mode ON (`?dev=1`) so "Workspace sync trace" is visible in sidebar
- [ ] Sync trace shows `cloud_first: true` on cold open

---

## Status legend

| Mark | Meaning |
|------|---------|
| ✅ PASS | Confirmed working cross-device |
| ❌ FAIL | State does not round-trip — document exact discrepancy |
| ⚠️ PARTIAL | Syncs on one direction or only sometimes |
| ⬜ NOT TESTED | Not yet manually verified |

---

## 1. Draft settings

**Cloud keys:** `room_format`, `room_team_count`, `room_rounds` (full blob authoritative)

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 1a | Set Draft Format to "Roto" → Save draft board | Cold open → confirm Format shows "Roto" | ⬜ | |
| 1b | Set Draft Format to "H2H" → Save | Cold open → confirm "H2H" | ⬜ | |
| 1c | Change team count to 10 → Save | Cold open → confirm 10 teams | ⬜ | |
| 1d | Change rounds to 23 → Save | Cold open → confirm 23 rounds | ⬜ | |
| 1e | Set "Your Team" name → Save | Cold open → confirm team name | ⬜ | `room_your_team` |

**Expected on FAIL:** Report which field is wrong and whether the sync trace shows `apply_reason: draft_room_state_blob`.

---

## 2. Draft queue

**Cloud keys:** `draft_state.queue`, `draft_workflow.queue`

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 2a | Add 3 players to queue in specific order → Save | Cold open → confirm same 3 players in same order | ⬜ | |
| 2b | Phone: reorder queue (move player 3 to position 1) → Save | Dell refresh → confirm new order | ⬜ | Reverse direction |
| 2c | Remove a player from queue → Save | Other device → confirm player absent | ⬜ | |

**Key field to check in sync trace:** `draft_queue_length`

---

## 3. Watchlist (focus players)

**Cloud keys:** `draft_assistant_focus_players`, `draft_workflow.watchlist_players`

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 3a | Add a player to watchlist → Save | Other device → confirm player in watchlist | ⬜ | |
| 3b | Remove a watchlist player → Save | Other device → confirm player gone | ⬜ | |

---

## 4. Comparison Tool selections

**Cloud keys:** `comparison_state.player_a`, `comparison_state.player_b`, `sig_player_a_clean`, `sig_player_b_clean`

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 4a | Set Player A = Juan Soto, Player B = Aaron Judge → trigger save (`comparison_edit`) | Cold open Comparison page → confirm same A/B slots | ⬜ | |
| 4b | Change stat axis to "HR" → save | Other device → confirm "HR" selected | ⬜ | `comparison_state.chart` |
| 4c | Phone changes Player A → save | Dell refresh → Player A updated | ⬜ | Reverse direction |

**Failure mode to watch:** `comparison_state_dirty` flag blocks cloud overwrite while editing — do not save mid-interaction.

---

## 5. Trend selections

**Cloud keys:** `trend_state.chart_player`, `single_trend_dashboard_player`, `trend_state.chart`, `trend_state.filters`

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 5a | Select player for trend chart → save (`trend_edit`) | Cold open Trend page → same player selected | ⬜ | `trend_chart_player` in envelope (v21+) |
| 5b | Change stat metric → save | Other device → same metric | ⬜ | |
| 5c | Add a player to multi-player list → save | Other device → same list | ⬜ | `trend_state.players_multi` |
| 5d | Change lag / min-G filters → save | Other device → same filters | ⬜ | `trend_state.filters` |

---

## 6. Sleepers / Busts filters

**Cloud keys:** `fantasy_state.sleepers.filters`, `page_filter_state`

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 6a | Set position filter to "OF" → save (`fantasy_edit`) | Cold open Sleepers page → filter shows "OF" | ⬜ | |
| 6b | Set age range → save | Other device → same age range | ⬜ | |
| 6c | Phone changes filter → Dell refresh | Dell shows Phone's filter | ⬜ | Reverse direction |

**Known issue to retest:** Multiselect filter can revert if `mark_fantasy_local_edit` doesn't fire before cloud hydration. Confirm the sync trace shows `apply_reason: fantasy_state` on restore.

---

## 7. Historical Explorer filters

**Cloud keys:** `historical_state.filters`

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 7a | Set era/year range → save (`historical_edit`) | Other device → same year range | ⬜ | |
| 7b | Set sort column → save | Other device → same sort | ⬜ | |
| 7c | Set hand filter (L/R/S) → save | Other device → same hand filter | ⬜ | |
| 7d | Set team filter → save | Other device → same team | ⬜ | |

---

## 8. Career Explorer filters

**Cloud keys:** `career_state.filters`

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 8a | Set year range → save (`career_edit`) | Other device → same range | ⬜ | |
| 8b | Set min PA threshold → save | Other device → same threshold | ⬜ | |
| 8c | Set team filter → save | Other device → same team | ⬜ | |

---

## 9. Workspace restore

**Cloud keys:** `active_page`, per-page canonical state, `_ami_pending_insight`, `_ami_dismissed_insight_ids`

| Step | Device A (make change) | Device B (verify) | Status | Notes |
|------|------------------------|-------------------|--------|-------|
| 9a | Navigate to Comparison Tool, set players, save | Cold open other device → lands on Comparison with same players | ⬜ | `active_page` + comparison state |
| 9b | Navigate to Trend Value, set player, save | Cold open → lands on Trend with same player | ⬜ | |
| 9c | Generate an insight → card appears | Other device refresh → same insight card visible | ⬜ | `_ami_pending_insight` + activity |
| 9d | Dismiss an insight on Phone | Dell refresh → insight no longer shown | ⬜ | `_ami_dismissed_insight_ids` via `persist_insight_dismissal_to_cloud` |
| 9e | Open Full Analysis (Command Center continue) on one device | Other device Command Center → same continue item | ⬜ | Activity API |

---

## Failure triage

When a workflow fails, record these fields before any code change:

| Field | Where to find |
|-------|--------------|
| `apply_reasons` | Baseball sidebar → "Workspace sync trace" (dev mode) |
| `cloud_first` | Same trace |
| Last force-save reason | Trace → `last_save_reason` |
| State key present in cloud blob | Supabase `full_session` → JSON viewer |
| State key present in local disk | `data/baseball_user_state.json` |

**Common failure patterns:**

| Symptom | Likely cause |
|---------|-------------|
| State syncs Dell → Phone but not Phone → Dell | Dirty flag (`*_state_dirty`) blocking cloud overwrite |
| State syncs sometimes but not on cold open | `cloud_first` logic not running — check `pick_restore_session` return |
| Field present in sync trace as key but wrong value | Envelope omit — full blob is authoritative; envelope is summary only |
| Filter reverts immediately | `mark_*_local_edit` not called before Streamlit reruns widget |
| Insight not showing on second device | Same-run local until cloud hydrate — give it 1–2 reruns after save |

---

## Results log

Fill in after each manual session:

| Date | Device A | Device B | Workflow | Result | Notes |
|------|----------|----------|----------|--------|-------|
| | | | | | |
