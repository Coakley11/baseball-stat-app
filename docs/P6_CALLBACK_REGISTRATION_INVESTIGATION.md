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

## 4. Cloud control matrix (`bf7cbef`, `data/solo_p6_callback_registration_controls.json`)

| Control | P6 overall | Browser send + parent | Python callback | Sentinel |
|---------|------------|----------------------|-----------------|----------|
| **R0** (suppress=True) | flaky mount timer on one run | often **no** crossing (tick cancelled) | 0 | no |
| **R1** (suppress=False) | `VALID_FAIL_CALLBACK_REGISTRATION` | yes | 0 | no |
| **R2** (sentinel wrap) | `VALID_FAIL_CALLBACK_REGISTRATION` | yes | 0 | **no** |
| **R3** (B2 helper, same key/token) | `VALID_FAIL_CALLBACK_REGISTRATION` | yes | 0 | no |

**First control that changes callback outcome:** none — R1/R2/R3 match R0 failure mode when browser delivery completes.

**Classification (when mount + browser established):** `VALID_FAIL_CALLBACK_NOT_TRIGGERED` for all of R1–R3.

- **Not** `VALID_FAIL_SUPPRESS_FLAG` — R1 (`suppress_immediate_session_on_change=False`) did not produce a Python callback.
- **Not** `VALID_FAIL_ORIGINAL_CALLBACK_BINDING` — sentinel never entered (`sentinel_callback_entry` absent).
- **Not** fixed by R3 — B2 micro-wrapper at the same P6 location does not restore callback.

Post-expiration probe consistently shows `session_state_raw: "None"` despite parent `setComponentValue` with matching token.

## 5. Smallest-fix report (evidence only — no production patch applied)

| Item | Detail |
|------|--------|
| **Failing line (registration surface)** | `solo_countdown_wake_micro_core.py` → `mount_solo_countdown_wake_with_token(..., on_change=_prod_on_change)` inside `render_micro_isolation_once` (production path uses `suppress_immediate_session_on_change=True` at `live_draft_solo_persistent_wake.py` → `_mount_persistent_wake_micro_controlled`). |
| **Passing B2 line (parity)** | Same `mount_solo_countdown_wake_with_token` + same `_prod_on_change` pattern via `_mount_b2_style`; differs only in **micro-wrapper kwargs** (`session_prefix`, `persistent`, `placement`, `location`, synthetic room id). |
| **Differing args that matter for diagnosis** | Not `on_change` name, key, default, or `_COMPONENT` kwargs (identical). Differs: `persistent` (False for B2 vs True for production), `session_prefix`, `placement`/`location`. **R3 copied B2 helper with production key/token and still no callback** → those kwargs are not sufficient to explain Cloud behavior alone. |
| **Why on_change does not run (observed)** | Browser delivers token via component iframe; Streamlit parent receives postMessage; **`st.session_state[widget_key]` stays unset** and **no Streamlit `on_change` callback fires** (production or sentinel). Immediate post-mount poll is intentionally skipped when `suppress=True`; setting `suppress=False` (R1) still did not produce a callback after deadline delivery. |
| **Smallest proposed correction (for a follow-up change, not implemented)** | Treat as **Streamlit custom-component callback delivery gap on Cloud** after iframe `setComponentValue`, not a wrong function reference in the declaration. Likely needs an **explicit Python-side delivery hook** wired from the same transport boundary already observed (without altering ownership/timer/frontend contract) — design TBD after confirming with local vs Cloud Streamlit version. |
| **Tests** | `tests/test_live_draft_solo_p6_declaration_audit.py`; extend with unit test asserting audit rows on mock mount; re-run `scripts/run_solo_p6_callback_registration_controls.py` after any fix. |

## 6. R4 / R5 — V1 return-value path (not implemented as production fix)

See `docs/STREAMLIT_V1_CUSTOM_COMPONENT_API_1.59.1.md`.

| Control | Behavior |
|---------|----------|
| **R4** | P6 dedicated route; production frontend + key + token; **`on_change=None`**; `raw = mount_solo_countdown_wake_with_token(...)`; ledger **`r4_component_return_value`** every script run; **redeclare on each rerun** (no post-first-run early stop); **no clear-after-first-mount**. |
| **R5** | Only if R4 ≠ PASS; **`solo_p6_v1_template_component`** uses **`Streamlit.setComponentReady` / `RENDER_EVENT` / `Streamlit.setComponentValue`**; ledger **`r5_component_return_value`**. |

Runner: `python scripts/run_solo_p6_v1_return_value_r4_r5_auth.py` → `data/solo_p6_v1_return_value_r4_r5.json`.

**Grades:** `PASS_RETURN_VALUE_DELIVERY`, `VALID_FAIL_RETURN_VALUE_NOT_DELIVERED`, `INVALID` (per spec §3).

**Countdown frontend note:** production iframe calls **`window.parent.postMessage({type:"streamlit:setComponentValue"})`** — not the component-library API. Parent capture alone ≠ Streamlit widget state.


- `tests/test_live_draft_solo_p6_declaration_audit.py` — control resolution, diff storage, sentinel wrap.
- Existing P6 dedicated entrypoint tests unchanged.
