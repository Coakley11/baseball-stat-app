# Deploy validation — Draft persistence & completion (ec05dc0+)

**App:** https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app  
**Branch:** `dev`  
**Last updated:** 2026-07-06

## Pre-check

```bash
python scripts/probe_live_deploy.py
```

Confirm `github_origin_dev` includes `ec05dc0` (or later) and deploy marker matches after Streamlit Cloud rebuild.

## Manual checklist

1. **Complete Live Draft** — run a short solo draft to final pick.
2. **Save Draft** — enter name (e.g. `David vs Barry`) → **Save Draft** → success toast / no persist error.
3. **Refresh** — hard refresh browser; open **Saved Draft Library** → draft listed with full board.
4. **Analyze Draft** — from completion panel → **Analyze Draft** → **Draft Lab / Simulation** opens with board, rosters, and grades preloaded (no manual reload).
5. **Set Active Draft** (optional) — confirm Active Draft chip updates.

## Developer Mode (if save fails)

- Saved Draft Library → **Save Diagnostics** / persistence panel
- Verify `persist_ok`, cloud readback draft count, restore source

## Local E2E (no UI)

```bash
python scripts/verify_saved_draft_library_e2e.py
python -m unittest tests.test_draft_library_persist_roundtrip -v
```
