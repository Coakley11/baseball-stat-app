# Hotfix: player_trade_context startup ImportError (2026-07-11)

## Observed failure (Streamlit Cloud)

```text
File "/mount/src/baseball-stat-app/streamlit_app.py", line 32, in <module>
    from player_trade_context import (
ImportError: ...
```

Streamlit Cloud redacts the nested exception in the browser UI. Manage app → Logs contains the full traceback.

## Local diagnosis (commit `ad50968`)

- `player_trade_context.py` is tracked on `origin/dev` (blob `1de34b6`, 19,263 bytes).
- All seven symbols imported by `streamlit_app.py` exist on `origin/dev`.
- Direct import contract passes locally in <1s.
- Simulated `streamlit_app` prefix import chain passes.
- Full `import streamlit_app` succeeds locally (~70–210s due to monolithic app init, unrelated).
- No duplicate/shadow `player_trade_context` module; filename is lowercase on `origin/dev`.
- No circular import from `player_trade_context` → `streamlit_app` at module level.

**Most likely Cloud cause:** nested import failure while initializing `player_trade_context` (or a dependency) during cold startup, surfaced at the `streamlit_app` import line. Eager top-level import made this startup-blocking.

## Fix

1. `player_trade_constants.py` — zero-dependency trade constants.
2. `player_trade_bridge.py` — startup-safe lazy loader used by `streamlit_app.py`.
3. `player_trade_context.py` — defers `player_actions` import to call sites.
4. `tests/test_player_trade_startup.py` + `scripts/startup_import_smoke.py` — fast regression.

Trade shortcuts remain enabled; failures return commissioner-facing disabled messages instead of crashing the app.
