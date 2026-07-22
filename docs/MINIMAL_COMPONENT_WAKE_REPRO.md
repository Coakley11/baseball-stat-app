# Minimal component wake repro

Standalone Streamlit Cloud test for v1 custom component `setComponentValue` + `on_change`.

## Run locally

```bash
streamlit run minimal_component_wake_repro.py
MINIMAL_WAKE_REPRO_LOCAL=1 python scripts/run_minimal_component_wake_repro.py
```

## Deploy on Streamlit Cloud (second app)

1. Streamlit Cloud → **Create app** → repo `Coakley11/baseball-stat-app`, branch `dev`.
2. **Main file path:** `minimal_component_wake_repro.py` (not `streamlit_app.py`).
3. Python **3.12**, same `requirements.txt`.
4. After deploy, set `MINIMAL_WAKE_REPRO_URL` to the new app URL and run:

```bash
python scripts/run_minimal_component_wake_repro.py <short_sha>
```

## Pass criteria

- Four 5-second countdown expirations
- Four unique tokens received in Python (`on_change` and/or return value)
- No duplicate token deliveries
- Client chain includes `browser_deadline_crossed|component_value_sent`

Results: `data/minimal_component_wake_repro.json`
