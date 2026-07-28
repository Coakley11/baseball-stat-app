# Stage 1A parent receipt diagnostic report (db6092e)

**Last updated:** 2026-07-28  
**Accepted run:** Stage 1A on Cloud **`db6092e`**, room **`45E1C703`**, token **`45E1C703|0|1785274579.549`**, overall **`FAIL_STAGE1A_COMPONENT_VALUE_NOT_BOUND`**.

No delivery-owner / bind / timer / autopick code changes were made for this report (diagnostic instrumentation only in repo; not required to interpret db6092e artifacts).

---

## 1. Authoritative receipt levels (db6092e)

| Level | Meaning | db6092e |
|-------|---------|---------|
| **LEVEL 1 — IFRAME_SEND_EXECUTED** | Iframe ran `postMessage` / send path for expiration | **PASS** — `transport_before_postMessage`, `expiration_send_claimed`, `transport_postmessage_invoked` (`ok:true`), `component_value_sent` @ iframe `solo_1785274518856_66g4d456`, `bse_1_1785274579595` |
| **LEVEL 2 — TOP_PARENT_MESSAGE_RECEIVED** | Parent `MessageEvent` with exact token in `streamlit:setComponentValue` | **FAIL** — zero logical SCV events in `immediate_parent_messages` or harness top scrape |
| **LEVEL 3 — CURRENT_COMPONENT_SOURCE_MATCH** | `event.source` = registered production iframe | **NOT REACHED** (no SCV at parent) |
| **LEVEL 4 — STREAMLIT_PROTOCOL_ACCEPTED** | Runtime accepted value for current component instance | **NOT REACHED** |
| **LEVEL 5 — PYTHON_VALUE_BOUND** | Direct return or Session State + claim | **FAIL** — coalesced empty, 0 accepted native callbacks, 0 claims |

**Refined boundary (replaces generic A5a):** **`A5a1 — SEND_EXECUTED_BUT_PARENT_DID_NOT_RECEIVE`**

Not A5a2–A5a6: no parent SCV to attribute to stale source (A5a2), no protocol rejection after receipt (A5a3), no wrong component redeclare with bound value (A5a4), Python state empty (A5a5), and post-send `tick_cancelled`/`streamlit_render` occurred **with** a proven iframe send (A5a6 applies only when LEVEL 1 is false).

---

## 2. Why the harness showed “two deduped parent receipts” but no SCV

Legacy metric `deduped_parent_receipt_count` used:

```python
len({str(m.get("token") or m.get("value") or m) for m in parent_msgs})
```

When `token`/`value` are empty, each row dedupes to **`str(entire_message_dict)`**, so **non-value** parent messages inflate the count.

On db6092e, the only two immediate-parent rows were:

1. **`solo:rvCountdownRegister`** (`has_set_component_value: false`) @ +~4.2s after send (post-remount registration)
2. **`streamlit:setFrameHeight`** (`has_set_component_value: false`)

Neither is a value receipt. **Logical SCV receipt count = 0.** The “2” was a **harness classification bug**, not evidence of duplicate value delivery.

---

## 3. First divergence from passing RV3 path

| Step | RV3 (`754131DE`, PASS binding) | Stage 1A db6092e |
|------|--------------------------------|------------------|
| Browser send | 1× SCV transport | 1× SCV transport (same shape) |
| Parent SCV (instrumented) | Harness counted 1 logical parent event | **0** SCV; only register + frame-height |
| Post-send rerun | `script_run_seq` 3 + RV ledger `session_state_after` = token | `tick_cancelled` / remounts; **no** token in Session State / return |
| Python claim | Accepted via RV audit / session bind path | **0** `try_claim_token_delivery` accepts |

**First divergence:** **LEVEL 2+** — RV3 path shows token in **Session State on post-send script run**; Stage 1A never receives SCV at the instrumented parent and never binds at LEVEL 5.

RV3 ledger must not be used as proof that the **normal** Stage 1A parent accepted SCV; RV3 uses a different post-send re-entry (`POST_DELIVERY`, room hydrate).

---

## 4. Send ↔ rerun correlation (db6092e)

| Event | Timestamp (ms) |
|-------|------------------|
| `browser_deadline_crossed` | 1785274579588 |
| `transport_before_postMessage` / send | 1785274579595–9596 |
| `solo:rvCountdownRegister` (parent) | 1785274583838 |
| `streamlit:setFrameHeight` (parent) | 1785274583840 |

Post-send render (`tick_cancelled`, remounts) is **~1.35s after send** per harness. That row alone **does not prove** Streamlit accepted `setComponentValue`; it is consistent with **ordinary rerender / iframe remount** while LEVEL 2 failed.

---

## 5. Smallest correction justified **after** diagnostic instrumentation deploy

**Evidence-bound target:** prove **where** SCV disappears (LEVEL 2 on immediate parent vs top vs Streamlit host frame) using:

- Pre-iframe top observer (`live_draft_stage1_parent_observer.py`)
- Harness top observer + merged server ledger (`stage1_parent_observer_probe.py`, ledger merge by `event_id`)
- Separate immediate vs top receipt counts (`stage1_receipt_levels.py`)

**Do not ship a delivery fix** until one instrumented Cloud run confirms:

- Whether SCV never hits **any** observed window (**A5a1** confirmed), or
- Hits a non-current iframe (**A5a2**), or
- Hits parent but Streamlit rejects (**A5a3**).

**Leading hypothesis for db6092e (A5a1):** `postMessage` returned success from the component document, but **no instrumented parent received `streamlit:setComponentValue` with the expiration token** — consistent with send on a **detached or non-host parent chain** during remount churn (register/frame-height observed only after remount ~4s later).

**Not justified yet:** changing payload, adding polling/callback owners, or altering `return_value_session_bind` without LEVEL 2–3 proof from the new observer.

---

## 6. Repo changes (diagnostic only)

- Receipt levels + A5a1–A5a6 classifiers: `scripts/stage1_receipt_levels.py`
- Early parent observer + ledger merge/export: `live_draft_stage1_parent_observer.py`, `live_draft_stage1_production_ledger.py`
- Harness: top observer, merged ledger scrape, fixed receipt metrics: `scripts/stage1_parent_observer_probe.py`, `scripts/run_production_stage1_authenticated.py`
- Tests: `tests/test_stage1_receipt_levels.py`, ledger merge test
- Queue seed harness: broader `Add to Queue` click (for **next** expiration run; no app queue logic change)

**Next steps (per directive):** deploy diagnostics → one instrumented Stage 1A on current Cloud SHA → if A5a1 holds, minimal fix at proven frame/target boundary → one fresh Stage 1A with queue seed recorded. No Stage 1B / soak.
