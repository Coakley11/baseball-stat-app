# Stage 1A vs RV3 delivery path comparison

**Last updated:** 2026-07-28

## Accepted baselines

| Lane | Result |
|------|--------|
| Draft-start reliability | `PASS_DRAFT_START_LATCHED` |
| RV3 run `44848096-e2a0-401c-976f-4fd07a4384e2` | `PASS_WITH_OBSERVABILITY_WARN` (browser + Python binding + room continuity) |
| Stage 1A room `9B3551A7` | **FAIL** — first boundary **A. DELIVERY_NOT_ACCEPTED** (refined **A5** below) |

## Side-by-side (expiration delivery)

| Dimension | RV3 `754131DE` | Stage 1A `9B3551A7` |
|-----------|----------------|---------------------|
| Cloud SHA | `d986cda` | `d986cda` |
| `suite_sid` | `a38d0369-9c8f-48ed-b2be-e10237e9349b` | same harness session |
| Active page | Live Draft Room + `solo_rv_ladder=RV3` | Live Draft Room + `solo_component_diag=1` |
| Expected token | `754131DE\|0\|1785268338.297` | `9B3551A7\|0\|1785272249.697` |
| Widget key | `solo_countdown_wake_solo_persistent` | same |
| Iframe instance | `solo_1785268332702_a0fr44va` | `solo_1785272190029_s5sgmxln` |
| Browser send | 1× `transport_before_postMessage` (`bse_1_1785268338364`) | 1× (`bse_1_1785272249787`) |
| Parent deduped receipt (harness) | 1 logical parent event | **0** in Stage 1A summary scrape |
| Post-send Streamlit rerun | `script_run_seq` 3, `tick_cancelled` (render) | `tick_cancelled` @ +1.35s (`streamlit_render`, remounts=3) |
| RV ledger / server trace | Full RV declaration + room checkpoints | **None** (normal production path) |
| Post-send placement | `rv3_production_placement_entered` **POST_DELIVERY** | not instrumented (no RV3 phase) |
| Session State widget after send | **`754131DE\|0\|1785268338.297`** on run 3 (`real_room_hydrated`) | **empty** (harness scrape) |
| `coalesced_component_value` | PASS via ledger (`session_state_after` / binding grade) | **empty** |
| `try_claim_token_delivery` | accepted (RV3 audit path) | **0** callbacks |
| Auto-pick handler | disabled in RV3 ladder | **not entered** |

## First divergence from RV3

**First RV3-only event after browser send with no Stage 1A equivalent:** post-send **`script_run_seq: 3`** ledger sequence where **`real_room_hydrated`** records **`session_state_before/after`** already containing the **exact expiration token**, followed by **`rv3_production_placement_entered`** with phase **`POST_DELIVERY`** and **`live_draft_room` / canonical room present** through **`after_prepare_rv3_production_mount`**.

Stage 1A shows the same browser send and rerun signal (`tick_cancelled` after send) but **no Python-side token in Session State**, **no declaration_returned scrape**, and **`process_production_expire_token_entry_inferred: false`**.

## Stage 1A post-send rerun trace (harness)

| Timestamp (rel) | Event |
|-----------------|--------|
| T+0 | `transport_before_postMessage` + `component_value_sent` |
| T+1.35s | `tick_cancelled` (`reason=streamlit_render`, remounts=3) |
| Observation window | 46.5s — no accepted callback, no pick delta |

Session continuity: same authenticated page URL/`suite_sid`; room **in_progress** before expire (Stage 1A grade check 2 passed).

## Refined boundary classification: **A5 — COMPONENT_REDECLARED_VALUE_EMPTY**

Not **A1** (rerun/remount evidence exists). Not **A6** (claim never attempted). Not **A7** alone (browser + chain prove send; absence is real binding, not only scrape gap).

**A5:** Streamlit reran after send, room remained active for observation, but **early persistent-wake return-value path did not surface the expiration token** in direct component return or Session State before claim — consistent with **early LDR mount running before widget value bind** while **`flush_persistent_wake_delivery` is a no-op when return-value delivery is active**.

## RV3-only lifecycle (does not copy to production wholesale)

| RV3-only | Affects delivery how |
|----------|---------------------|
| `solo_rv_ladder=RV3` phase machine (`POST_DELIVERY`) | Ensures post-send script re-enters production mount with browser_send_seen |
| Pre-app bootstrap + room restore + duplicate `prepare_live_draft_state` skip | Room + canonical state survive reruns |
| `mount_with_rv_control_declaration` + RV ledger | Proves `session_state_after` token for grading |
| RV3 mount block / diag countdown gating | Does not apply to Stage 1A URL |
| `pick_processing_disabled` in RV3 | RV3 only; unrelated to binding |

**Conclusion:** RV3 passed Python binding because **post-send runs still had the token in Session State and room continuity on the RV-instrumented path**, not because the browser path differed. Stage 1A uses the **same widget key and return-value mode** but **lacks a post-bind delivery hook** when early mount sees an empty return.

## Normal production declaration owner (Stage 1A)

- Key: `solo_countdown_wake_solo_persistent`
- `on_change=None` under return-value delivery
- `process_production_expire_token` → `try_claim_token_delivery` in `_production_deliver_callback`
- Non-RV3 mount: `render_micro_isolation_once` (not `mount_with_rv_control_declaration`)

## Smallest proposed correction (post-report)

Allow **one post-page-bind Session State delivery** for return-value mode in `flush_persistent_wake_delivery` when the token is present and not yet claimed (same claim authority; new source label `return_value_session_bind`). **Do not** re-enable generic `on_change` or RV3 phase guards.

## Instrumentation added (diag-only)

Events: `production_stage1_script_begin`, `production_stage1_room_checkpoint`, `production_stage1_persistent_wake_eligibility`, `production_stage1_declaration_*`, `production_stage1_token_claim_*`, `production_stage1_autopick_handler_entered` — see `live_draft_stage1_production_ledger.py`.
