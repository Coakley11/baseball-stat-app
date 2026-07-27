# P6 callback registration investigation (Cloud baseline 9ce1262)

**Accepted boundary:** `VALID_FAIL_CALLBACK_REGISTRATION` on dedicated P6 entrypoint `9ce1262`.

## 1. Declaration diff (B2 parity ladder vs production LDR mount)

Both paths call `solo_countdown_wake_micro_core.render_micro_isolation_once` → `solo_countdown_component.mount_solo_countdown_wake_with_token` → `mount_solo_countdown_wake_direct` → `components.declare_component("solo_countdown_wake")` with `on_change=_prod_on_change` (closure that reads `st.session_state[key]` and invokes `deliver_callback`).

| Field | B2 (`_mount_b2_style`) | Production (`try_solo_persistent_wake_ldr_entry`) |
|--------|-------------------------|---------------------------------------------------|
| Wrapper | `render_micro_isolation_once` | `render_micro_isolation_once` (via `_mount_persistent_wake_micro_controlled`) |
| Component entry | `mount_solo_countdown_wake_with_token` | Same |
| Widget key | Caller-supplied (P6: `solo_countdown_wake_solo_persistent`) | Same permanent key |
| `default` | `None` (via `_COMPONENT`) | Same |
| Streamlit `on_change` | `_prod_on_change` closure | Same closure pattern |
| Deliver target | Parity ladder `deliver` / P6: `_production_deliver_callback` | `_production_deliver_callback` |
| `suppress_immediate_session_on_change` | **`True`** | **`True`** (R0) |
| `production_delivery_only` | **`False`** | **`False`** (typical P6 mount) |
| `persistent` | `True` only for P3–P5; **B2 uses `False`** | **`True`** |
| `session_prefix` | `_solo_parity_micro_b2_` | `_solo_persistent_wake_` |
| `placement` | Control id (e.g. `B2`) | `PROD` |
| `location` | `parity_ladder_b2` | `ldr_page_entry_early_persistent` |
| `draft_id` / room | Synthetic `PARITY` room from token deadline | Run-scoped `PARITY_<run8>` synthetic room |
| Conditional omit `on_change` | Only if `isolated == "minimal"` (separate branch) | Same (not taken on P6 dedicated path) |

Runtime snapshots are written to session `declaration_diff` and ledger stage `declaration_diff_recorded` on each P6 mount (`live_draft_solo_p6_declaration_audit.py`).

## 2. Declaration audit ledger stages

Immediately before component invoke: `declaration_attempt` (key, default, token, callback metadata, suppress flag, session_state before).

Immediately after: `declaration_returned` (component return, session_state after, `PRODUCTION_CALLBACK_FLAG` count).

## 3. One-variable controls

Query param: `solo_p6_callback_control=R0|R1|R2|R3` (latched in session).

| Control | Change |
|---------|--------|
| **R0** | Exact production (`suppress_immediate_session_on_change=True`) |
| **R1** | Same declaration; **only** `suppress_immediate_session_on_change=False` |
| **R2** | Sentinel wrapper around `_production_deliver_callback` → ledger `sentinel_callback_entry` |
| **R3** | `_mount_b2_style` helper with **same** production key, token, deliver callback |

Runner: `python scripts/run_solo_p6_callback_registration_controls.py` (stops at first outcome change vs R0).

## 4. Smallest-fix report (pending Cloud control matrix)

After the control run artifact `data/solo_p6_callback_registration_controls.json` is produced:

- **If R1 → `PASS_CALLBACK_REGISTERED`:** boundary is post-mount immediate callback suppression (`suppress_immediate_session_on_change=True` at `solo_countdown_wake_micro_core.py` ~278–279); Streamlit native `on_change` may not fire for parent iframe delivery on Cloud while suppress blocks the synchronous poll path.
- **If R2 sentinel enters, production ledger does not:** original `_production_deliver_callback` binding is not the Streamlit-registered target (wrapper identity).
- **If R3 passes, R0 fails:** differences in `session_prefix` / `persistent` / `placement` / `location` alter mount lifecycle or callback registration despite identical `_COMPONENT` kwargs.
- **If all fail callback:** dedicated route context prevents Streamlit from triggering registered `on_change` after browser `setComponentValue` (not a declaration-arg typo).

**Do not implement production fixes until the control artifact confirms which row applies.**

## 5. Relevant tests

- `tests/test_live_draft_solo_p6_declaration_audit.py` — control resolution, diff storage, sentinel wrap.
- Existing P6 dedicated entrypoint tests unchanged.
