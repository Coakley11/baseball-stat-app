# Saved Draft Library — E2E verification runbook

**Last updated:** 2026-07-05

Use **Developer Mode** on deployed `dev`. After each save, open **Saved Draft Library → Persistence diagnostics** and confirm the checklist.

## Automated local check

```bash
python scripts/verify_saved_draft_library_e2e.py
python -m unittest tests.test_draft_library_save_trace tests.test_draft_library_cloud_fixes -v
```

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
