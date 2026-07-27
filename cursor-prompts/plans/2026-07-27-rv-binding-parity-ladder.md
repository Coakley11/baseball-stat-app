# Return-value binding parity ladder (R4 vs Stage 1A Class A)

**Last updated:** 2026-07-27

## Accepted baseline

- Cloud **`a2aaa8e`**: Stage 1A **Failure Class A** — browser expiration, no Python return / Session State binding.
- **Hypothesis:** component-instance identity loss on full-page remounts.

## Ladder (one variable at a time)

| Step | What changes | Expected if hypothesis wrong |
|------|----------------|------------------------------|
| **RV0** | Synthetic room, dedicated shell, R4 mount, `st.stop` | `PASS_RETURN_VALUE_DELIVERY` (R4 control) |
| **RV1** | Real Solo room token/state, same shell | Fail → real-room token/state; Pass → not room |
| **RV2** | RV1 + full page continues after mount | Fail → full-page remount destroys binding |
| **RV3** | Production persistent-wake placement + full LDR | Fail → placement/order/routing |

Pick processing **disabled** on RV1–RV3. **No** production delivery fix, retries, flush, or Supabase transport.

## Instrumentation (diag-only)

- **Frontend:** immutable `IFRAME_INSTANCE_ID`, `browser_send_event_id`, `solo:rvCountdownRegister`, structured lifecycle in persist log.
- **Parent:** `live_draft_solo_rv_instance_registry.py` — logical vs raw postMessage counts; delivery only if `event.source` is current registered instance.
- **Python:** `live_draft_solo_rv_declaration_audit.py` — before/after mount snapshots + `#solo-rv-declaration-audit` probe.
- **Entry:** `live_draft_solo_rv_dedicated_entrypoint.py` + query params `solo_rv_ladder`, `solo_rv_run_id`.

## Run (authenticated Cloud)

```bash
REQUIRED_CLOUD_SHA=a2aaa8e  # deploy must match
python scripts/run_solo_rv_binding_ladder_auth.py
```

Output: `data/solo_rv_binding_ladder.json` — stops at first **FAIL** or **INVALID**.

## Root-cause classes (after valid control)

- **A** Stale/disconnected sending iframe  
- **B** Current iframe, no post-delivery redeclaration  
- **C** Same declaration, widget/component ID changes  
- **D** Same widget ID, empty return → manual postMessage vs official `setComponentValue` at production site  

## Do not run

Real pick-processing Stage 1A until first RV boundary is identified.
