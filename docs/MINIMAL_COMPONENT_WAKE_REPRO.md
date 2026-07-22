# Minimal component wake repro

Standalone Streamlit Cloud test for v1 custom component `setComponentValue` + `on_change`.

## Run locally

```bash
streamlit run minimal_component_wake_repro.py
MINIMAL_WAKE_REPRO_LOCAL=1 python scripts/run_minimal_component_wake_repro.py
```

## Deploy on Streamlit Cloud

Pick **one** option (do not point production Live Draft at the repro unless intentionally pausing it).

### Option A — second app (recommended)

1. Streamlit Cloud → **Create app** → repo `Coakley11/baseball-stat-app`, branch `dev`.
2. **Main file path:** `minimal_component_wake_repro.py` (not `streamlit_app.py`).
3. Python **3.12**, same `requirements.txt`.
4. After deploy, set `MINIMAL_WAKE_REPRO_URL` to the new app URL and run:

```bash
python scripts/run_minimal_component_wake_repro.py 406bddb
```

### Option B — temporary branch on existing app

1. Streamlit Cloud → **Manage app** → **Settings** → branch `minimal-wake-repro` (entry `streamlit_app.py` is the repro only).
2. Wait for redeploy (~2–5 min), then run against the existing URL:

```bash
MINIMAL_WAKE_REPRO_URL=https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app \
  python scripts/run_minimal_component_wake_repro.py 47634ff
```

3. Switch branch back to `dev` when finished.

Branch `minimal-wake-repro` SHA: `47634ff` (dev repro marker: `406bddb`).

## Pass criteria

- Four 5-second countdown expirations
- Four unique tokens received in Python (`on_change` and/or return value)
- No duplicate token deliveries
- Client chain includes `browser_deadline_crossed|component_value_sent`

Results: `data/minimal_component_wake_repro.json`
