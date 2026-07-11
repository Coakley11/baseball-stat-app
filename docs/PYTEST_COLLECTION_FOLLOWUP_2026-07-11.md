# Pytest collection follow-up (2026-07-11)

## Symptom

Broad `pytest` runs appear to hang when started without a narrow path filter. An early background run was killed after ~240s with no result output.

## What is healthy

Focused commands complete quickly:

```bash
python -m pytest tests/test_fantasy_weekly_hitter_scoring.py -q
# 28 passed in ~3s

python -m pytest --collect-only -q tests/test_fantasy_weekly_hitter_scoring.py
# 28 collected in ~1.4s
```

Equivalent `unittest` module also passes in ~1–2s.

## Reproducible root cause

Importing `streamlit_app.py` outside `streamlit run` is very slow and noisy:

```bash
python -c "import time; t=time.time(); import streamlit_app; print(round(time.time()-t,2))"
# observed ~210s on Windows, with thousands of ScriptRunContext warnings
```

Several test modules import helpers from `streamlit_app` at collection time (for example `test_fantasy_league_lineup_format.py`, `test_live_draft_recommendations.py`, `test_draft_lab_state.py`). Full-suite `pytest --collect-only` therefore stalls while those modules import the monolithic app module.

This is **not** caused by the weekly hitter scoring module itself.

## Recommended commands

```bash
# Weekly scoring only (preferred for this feature)
python -m pytest tests/test_fantasy_weekly_hitter_scoring.py -q

# Or unittest equivalent
python -m unittest tests.test_fantasy_weekly_hitter_scoring -v
```

Avoid unscoped `pytest` / `pytest --collect-only` in CI until `streamlit_app` import side effects are reduced or isolated.

## Follow-up work (not blocking deploy)

1. Extract shared helpers imported by tests out of `streamlit_app.py` into small modules.
2. Convert `from streamlit_app import ...` test imports to lazy imports inside test bodies where possible.
3. Add a CI job that runs the focused weekly-scoring pytest path plus other fast modules, not full collection.
