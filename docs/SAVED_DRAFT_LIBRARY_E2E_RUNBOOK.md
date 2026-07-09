# Saved Draft Library — E2E verification runbook

**Last updated:** 2026-07-09

Use **Developer Mode** on deployed `dev`. After each save, open **Saved Draft Library → Persistence diagnostics** and confirm the checklist.

## Uploaded 4-team shared league (Daniel acceptance)

1. Sign in as **Daniel** (Real Account).
2. **Draft Room Simulator** → upload fresh **4-team** league CSV → validate → **Save to Saved Drafts**.
3. Confirm redirect to **Saved Draft Library** (not Historical Explorer).
4. Library card: **4 teams** · note `draft_id`.
5. **Hard refresh** browser (F5).
6. Still on **Saved Draft Library**; same `draft_id`; card still **4 teams**.
7. **Set Active** → Active Draft caption still **4 teams**.
8. **Persistence probe** (library panel): session/disk/cloud draft counts all **≥ 1**; no `workflow_library_sanitized` wipe.

Automated regression:

```bash
python -m pytest tests/test_uploaded_league_refresh_persistence.py -q
```

### Where drafts are lost (diagnostic order)

| Stage | Symptom | Check in Developer Mode |
|-------|---------|-------------------------|
| Immediately after save | Flash warns persist did not verify | Save diagnostics → cloud readback |
| Cloud write | `cloud_write_ok` false | `cloud_blocked_reason`, workspace `cloud_app_key` |
| Startup restore | Session 0, cloud > 0 before hydrate | `_suite_startup_restore_snapshot`, hydrate source |
| Visibility sanitize | `workflow_library_sanitized`, tombstones | Commissioner/ownership ids vs `_suite_cloud_user_id` |
| Page restore | Lands on Historical Explorer | `active_page` in cloud blob; `_suite_page_overwrite_source` |

Common root cause (2026-07-09 fix): upload saved with `local:daniel` ownership while refresh resolves cloud UUID — visibility prune treated league as foreign. Repair now maps local ↔ cloud ids before prune.

## Automated local check

```bash
python scripts/verify_saved_draft_library_e2e.py
python -m unittest tests.test_draft_library_save_trace tests.test_draft_library_cloud_fixes -v
```

### Shared league invite + trade (two accounts)

```bash
python scripts/smoke_shared_league_invite_trade_manual.py
python -m pytest tests/test_fantasy_league_invites.py tests/test_fantasy_league_invite_trade_e2e.py -q
```

See [SHARED_LEAGUE_INVITE_TRADE_SMOKE_RUNBOOK.md](./SHARED_LEAGUE_INVITE_TRADE_SMOKE_RUNBOOK.md) for manual UI steps.

## Draft Room Simulator

1. Complete a mock draft (picks on board).
2. **Rosters** tab → **Save Active League Context** → enter league name → Save.
3. **Persistence diagnostics** (Developer Mode):
   - ✅ Save request received
   - ✅ Archive id written (`draft_id`)
   - ✅ Archive count increased (before → after)
   - ✅ Cloud write / Disk write (when signed in + cloud enabled)
   - ✅ Session has archive
   - ✅ Cloud readback has archive (after cloud write)
4. Navigate to **Saved Draft Library** — draft appears immediately (metric count increments).
5. **Refresh browser** — draft still listed; **Library load diagnostics** shows session/disk/cloud counts.
6. **Set Active League Context** → **Restore diagnostics** shows `draft_id`, player/team counts.
7. Open **Fantasy Standings Tracker** or **Lineup Assistant** — full league data loads from active context.

## Live Draft Room

Same steps using **Save completed draft → Save Active League Context** after draft completes.

## If a step fails

| Failed step | Likely cause |
|-------------|----------------|
| Archive count did not increase | Save handler error; check board has picks |
| Cloud write failed | Autosave block, auth, or `_FORCE_SAVE_CLOUD_REASONS` |
| Cloud readback missing draft | Cloud merge wiped blob; check `cloud_blocked_reason` in diagnostics |
| Refresh wipes draft | Restore picked stale cloud over disk; check restore source |
| Restore empty | `activate_archive_league_context` or missing `league_rosters` |

Copy **Save diagnostics** JSON from Developer Mode when reporting issues.
