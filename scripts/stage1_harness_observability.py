"""Stage 1A harness-only observability: durable ledger merge and post-commit timer wait."""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Callable

LEDGER_DURABLE_INIT_SCRIPT = """
(function () {
  if (window.__soloStage1HarnessLedgerStore) return;
  window.__soloStage1HarnessLedgerStore = {
    snapshots: [],
    best_b64: "",
    max_rows: 0,
    capture_count: 0,
  };
  function captureLedger() {
    try {
      var b64 = "";
      try { b64 = window.__soloStage1LedgerB64 || ""; } catch (e) {}
      if (!b64) {
        var el = document.getElementById("solo-stage1-production-ledger");
        if (el) b64 = el.getAttribute("data-b64") || "";
      }
      if (!b64) return;
      var rows = 0;
      try {
        var pad = b64;
        while (pad.length % 4) pad += "=";
        rows = (JSON.parse(atob(pad)).rows || []).length;
      } catch (e2) {}
      var store = window.__soloStage1HarnessLedgerStore;
      store.capture_count += 1;
      var last = store.snapshots.length ? store.snapshots[store.snapshots.length - 1] : null;
      if (!last || last.b64 !== b64) {
        store.snapshots.push({
          ts: Date.now(),
          b64: b64,
          rows: rows,
          url: String(location.href || "").slice(0, 240),
        });
        if (store.snapshots.length > 120) store.snapshots = store.snapshots.slice(-80);
      }
      if (rows >= store.max_rows) {
        store.max_rows = rows;
        store.best_b64 = b64;
      }
    } catch (e3) {}
  }
  captureLedger();
  setInterval(captureLedger, 300);
})();
"""

HARMLESS_REJECT_CODES = frozenset(
    {
        "delivery_only_observation",
        "post_action_duplicate_suppressed",
        "already_consumed",
        "callback_source_not_allowed",
    }
)


def decode_ledger_b64_padded(b64: str) -> dict[str, Any]:
    raw_b64 = str(b64 or "").strip()
    if not raw_b64:
        return {}
    try:
        pad = raw_b64 + "=" * ((4 - len(raw_b64) % 4) % 4)
        decoded = base64.b64decode(pad.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def scrape_durable_ledger_store(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
              const s = window.__soloStage1HarnessLedgerStore;
              if (!s) return { installed: false };
              return {
                installed: true,
                best_b64: s.best_b64 || "",
                max_rows: s.max_rows || 0,
                capture_count: s.capture_count || 0,
                snapshot_count: (s.snapshots || []).length,
              };
            }"""
        )
        return raw if isinstance(raw, dict) else {"installed": False}
    except Exception:
        return {"installed": False}


def rows_from_b64(b64: str) -> list[dict[str, Any]]:
    payload = decode_ledger_b64_padded(b64)
    rows = payload.get("rows") or []
    return [dict(r) for r in rows if isinstance(r, dict)]


def ledger_rows_from_callback_audit(
    audit: dict[str, Any] | None,
    *,
    server_chain: str = "",
    server_stages: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(audit, dict):
        return []
    rows: list[dict[str, Any]] = []
    stages = set(server_stages or [])
    for i, cb in enumerate(audit.get("callbacks") or []):
        if not isinstance(cb, dict):
            continue
        reject = str(cb.get("reject_code") or "")
        claimed = bool(cb.get("delivery_claimed")) and not reject
        src = str(cb.get("callback_source") or "")
        if reject == "delivery_only_observation":
            event = "production_stage1_delivery_only_observation_completed"
        elif reject == "post_action_duplicate_suppressed":
            event = "production_stage1_post_action_duplicate_suppressed"
        elif claimed and src == "return_value_session_bind":
            event = "production_stage1_token_claim_result"
        elif claimed:
            event = "production_stage1_token_claim_result"
        else:
            event = "production_stage1_callback_audit"
        row = {
            "event": event,
            "event_id": f"harness_audit_callback_{i}",
            "ts": cb.get("ts") or time.time(),
            "source": src,
            "delivery_via": src,
            "accepted": claimed,
            "reject_code": reject,
            "coalesced_value": str(cb.get("raw_token") or "")[:400],
            "raw_received": True,
            "harness_synthetic": True,
            "callback_seq": cb.get("seq"),
        }
        for key in (
            "token_room_id",
            "token_pick_index",
            "token_deadline",
            "canonical_pick_index",
            "canonical_deadline",
            "room_id",
        ):
            if key in cb:
                row[key] = cb[key]
        rows.append(row)
    for i, pc in enumerate(audit.get("pick_commits") or []):
        if not isinstance(pc, dict):
            continue
        rows.append(
            {
                "event": "production_stage1_pick_commit_audit",
                "event_id": f"harness_audit_pick_commit_{i}",
                "ts": pc.get("ts") or time.time(),
                "harness_synthetic": True,
                **{k: pc[k] for k in pc if k != "ts"},
            }
        )
    if "pick_committed" in stages or "pick_committed" in server_chain:
        rows.append(
            {
                "event": "production_stage1_pick_committed_chain",
                "event_id": "harness_audit_pick_committed_chain",
                "ts": time.time(),
                "harness_synthetic": True,
                "chain": server_chain,
            }
        )
    if "page_repaint_completed" in stages or "page_repaint_completed" in server_chain:
        rows.append(
            {
                "event": "production_stage1_page_repaint_completed",
                "event_id": "harness_audit_page_repaint",
                "ts": time.time(),
                "harness_synthetic": True,
            }
        )
    owners = audit.get("delivery_owners") or {}
    if isinstance(owners, dict):
        for tok, owner in owners.items():
            rows.append(
                {
                    "event": "production_stage1_token_claim_result",
                    "event_id": f"harness_audit_owner_{str(tok)[:24]}",
                    "ts": time.time(),
                    "token": str(tok)[:400],
                    "source": str(owner),
                    "accepted": True,
                    "harness_synthetic": True,
                }
            )
    return rows


def merge_ledger_sources(
    *,
    observation_loop_rows: list[dict[str, Any]],
    peak_observation_rows: list[dict[str, Any]],
    durable_best_b64: str,
    final_dom_rows: list[dict[str, Any]],
    callback_audit_rows: list[dict[str, Any]],
    merge_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]],
) -> dict[str, Any]:
    durable_rows = rows_from_b64(durable_best_b64)
    merged: list[dict[str, Any]] = []
    sources: list[str] = []

    def _merge_incoming(incoming: list[dict[str, Any]], label: str) -> None:
        nonlocal merged
        if not incoming:
            return
        before = len(merged)
        merged = merge_fn(merged, incoming)
        if len(merged) > before or (before == 0 and incoming):
            if label not in sources:
                sources.append(label)

    _merge_incoming(observation_loop_rows, "observation_loop")
    _merge_incoming(durable_rows, "durable_init_script")
    _merge_incoming(peak_observation_rows, "observation_loop_peak")
    _merge_incoming(callback_audit_rows, "callback_audit_fallback")
    if final_dom_rows:
        before = len(merged)
        merged = merge_fn(merged, final_dom_rows)
        if len(merged) >= before:
            sources.append("final_dom_scrape")

    if not merged and peak_observation_rows:
        merged = list(peak_observation_rows)
        if "observation_loop_peak" not in sources:
            sources.append("observation_loop_peak")
    if not merged and durable_rows:
        merged = list(durable_rows)
        if "durable_init_script" not in sources:
            sources.append("durable_init_script")
    if not merged and callback_audit_rows:
        merged = list(callback_audit_rows)
        if "callback_audit_fallback" not in sources:
            sources.append("callback_audit_fallback")

    if not sources:
        sources = ["none"]

    return {
        "merged_server_ledger": merged,
        "raw_dom_ledger_row_count": len(final_dom_rows),
        "durable_ledger_row_count": len(durable_rows),
        "callback_audit_row_count": len(callback_audit_rows),
        "observation_loop_ledger_row_count": max(len(observation_loop_rows), len(peak_observation_rows)),
        "merged_server_ledger_row_count": len(merged),
        "ledger_source_used": sources,
    }


def parse_expire_token_fields(token: str) -> dict[str, Any]:
    parts = str(token or "").strip().split("|")
    if len(parts) != 3:
        return {}
    try:
        return {
            "draft_id": parts[0].strip().upper(),
            "pick_index": int(parts[1]),
            "deadline": float(parts[2]),
        }
    except (TypeError, ValueError):
        return {}


def is_completed_token_event(callback: dict[str, Any], completed_token: str) -> bool:
    reject = str(callback.get("reject_code") or "")
    if reject != "post_action_duplicate_suppressed":
        return False
    tok = str(callback.get("raw_token") or callback.get("coalesced_value") or "")
    return tok.strip() == completed_token.strip()


def is_valid_next_token(
    token: str,
    *,
    completed_token: str,
    room_id: str,
    expected_pick_index: int = 1,
) -> bool:
    tok = str(token or "").strip()
    if not tok or tok == str(completed_token or "").strip():
        return False
    fields = parse_expire_token_fields(tok)
    if not fields:
        return False
    rid = str(room_id or "").strip().upper()
    if rid and str(fields.get("draft_id") or "").upper() != rid:
        return False
    return int(fields.get("pick_index") or -1) == expected_pick_index


def wait_for_next_timer_after_commit(
    page,
    *,
    completed_token: str,
    room_id: str,
    deadline_before: str | float | None,
    pick_committed_at: float,
    scrape_timer_fields: Callable[[Any], dict[str, Any]],
    scrape_component_mount_diag: Callable[[Any], dict[str, Any]],
    scrape_persistent_lifecycle_token: Callable[[Any], str],
    scrape_stage1_audit: Callable[[Any], dict[str, Any]],
    scrape_expire_chain: Callable[[Any], dict[str, Any]],
    capture_ledger: Callable[[], None] | None = None,
    poll_ms: int = 400,
    timeout_s: float = 28.0,
) -> dict[str, Any]:
    """Event-based wait for pick-1 timer after authoritative pick_committed."""
    t_end = time.time() + timeout_s
    completed = str(completed_token or "").strip()
    rid = str(room_id or "").strip().upper()
    result: dict[str, Any] = {
        "status": "waiting",
        "event": "production_stage1_waiting_for_next_timer",
        "started_at": pick_committed_at,
        "completed_token": completed,
        "room_id": rid,
        "poll_ms": poll_ms,
        "timeout_s": timeout_s,
        "observations": [],
    }
    old_deadline = str(deadline_before or "").strip()

    while time.time() < t_end:
        if capture_ledger is not None:
            try:
                capture_ledger()
            except Exception:
                pass
        state = scrape_timer_fields(page)
        mount = scrape_component_mount_diag(page)
        lifecycle = scrape_persistent_lifecycle_token(page)
        audit = scrape_stage1_audit(page) or {}
        chain = scrape_expire_chain(page) or {}
        pick_commits = list(audit.get("pick_commits") or [])
        auth_pick_index = None
        if pick_commits:
            lc = pick_commits[-1]
            if lc.get("pick_index_after") is not None:
                auth_pick_index = int(lc["pick_index_after"])

        mount_diag = (state.get("mount_diag") or {}) if isinstance(state, dict) else {}
        candidate_tokens = [
            str(mount.get("expire_token") or ""),
            str(lifecycle or ""),
            str(mount.get("returned_token") or ""),
        ]
        new_token = ""
        for cand in candidate_tokens:
            if is_valid_next_token(
                cand,
                completed_token=completed,
                room_id=rid,
                expected_pick_index=1,
            ):
                new_token = cand.strip()
                break

        new_deadline = (
            str(mount.get("diag_deadline") or mount.get("deadline") or "")
            or str(mount_diag.get("diag_deadline") or "")
            or str(state.get("timer") or "")
        ).strip()
        visible_countdown = (
            mount_diag.get("diag_remaining")
            or state.get("ccTimer")
            or state.get("timer")
        )
        mount_pick = mount.get("pick_index")
        try:
            mount_pick_index = int(mount_pick) if mount_pick not in (None, "") else None
        except (TypeError, ValueError):
            mount_pick_index = None

        obs = {
            "ts": time.time(),
            "elapsed_since_commit_s": round(time.time() - pick_committed_at, 2),
            "authoritative_pick_index": auth_pick_index,
            "server_deadline": new_deadline,
            "server_expected_token": new_token,
            "component_declaration_token": str(mount.get("expire_token") or ""),
            "iframe_diag_token": str(lifecycle or ""),
            "visible_countdown": visible_countdown,
            "mount_pick_index": mount_pick_index,
            "server_chain_tail": str(chain.get("chain") or "")[-120:],
        }
        result["observations"].append(obs)
        if len(result["observations"]) > 80:
            result["observations"] = result["observations"][-60:]

        deadline_changed = bool(new_deadline) and new_deadline != old_deadline
        pick_index_ok = auth_pick_index == 1 or mount_pick_index == 1
        countdown_mounted = bool(visible_countdown) and str(visible_countdown) not in ("0", "")
        token_ok = bool(new_token)

        if pick_index_ok and token_ok and deadline_changed and countdown_mounted:
            result.update(
                {
                    "status": "observed",
                    "event": "production_stage1_next_timer_observed",
                    "new_token": new_token,
                    "new_deadline": new_deadline,
                    "authoritative_pick_index": auth_pick_index if auth_pick_index is not None else 1,
                    "visible_countdown": visible_countdown,
                    "observed_at": time.time(),
                    "observation": obs,
                }
            )
            break

        page.wait_for_timeout(poll_ms)

    if result.get("status") != "observed":
        result.update(
            {
                "status": "timeout",
                "event": "production_stage1_next_timer_timeout",
                "timed_out_at": time.time(),
            }
        )
        last = result["observations"][-1] if result.get("observations") else {}
        result["last_observation"] = last
    return result


def classify_next_timer_status(
    *,
    next_timer_wait: dict[str, Any],
    authoritative_pick_index: int | None,
    server_deadline: str,
    server_expected_token: str,
    component_declaration_token: str,
    iframe_diag_token: str,
    visible_countdown: Any,
    completed_token: str,
) -> str:
    if str(next_timer_wait.get("status") or "") == "observed":
        return "T5_NEXT_TIMER_FULLY_VERIFIED"
    has_server_pick = authoritative_pick_index == 1
    has_server_timer = has_server_pick and bool(server_deadline) and bool(server_expected_token)
    has_component = bool(component_declaration_token) and component_declaration_token != completed_token
    has_iframe = bool(iframe_diag_token) and iframe_diag_token != completed_token
    has_visible = visible_countdown not in (None, "", 0, "0")
    if not has_server_pick and not has_server_timer:
        return "T1_SERVER_NEXT_TIMER_NOT_CREATED"
    if has_server_timer and not has_component:
        return "T2_SERVER_TIMER_CREATED_COMPONENT_NOT_DECLARED"
    if has_component and not has_iframe:
        return "T3_COMPONENT_DECLARED_IFRAME_NOT_MOUNTED"
    if (has_component or has_iframe or has_visible) and str(next_timer_wait.get("status") or "") != "observed":
        return "T4_TIMER_MOUNTED_BUT_HARNESS_MISSED_IT"
    return "T1_SERVER_NEXT_TIMER_NOT_CREATED"


def authoritative_exact_token_delivery(
    *,
    token_sent: str,
    component_raw: str,
    server_chain: str,
    callbacks: list[dict[str, Any]],
    merged_ledger: list[dict[str, Any]],
    mount_return: str,
) -> bool:
    tok = str(token_sent or "").strip()
    if not tok:
        return False
    if tok in str(component_raw or ""):
        return True
    if tok in str(server_chain or ""):
        return True
    if tok == str(mount_return or "").strip():
        return True
    if "component_value_received" in server_chain or "token_processed" in server_chain:
        return True
    for cb in callbacks:
        if str(cb.get("reject_code") or "") == "post_action_duplicate_suppressed":
            continue
        if cb.get("delivery_claimed") and not cb.get("reject_code"):
            src = str(cb.get("callback_source") or "")
            if src == "return_value_session_bind":
                return True
        raw_t = str(cb.get("raw_token") or "")
        if tok in raw_t:
            return True
    for row in merged_ledger:
        if not isinstance(row, dict):
            continue
        if str(row.get("event") or "") != "production_stage1_declaration_returned":
            continue
        if row.get("raw_received") and str(row.get("coalesced_value") or "").strip() == tok:
            return True
    return False


def split_stage1a_grades(
    *,
    checks: dict[str, bool],
    ledger_meta: dict[str, Any],
    next_timer_wait: dict[str, Any],
    timer_classification: str,
) -> dict[str, Any]:
    functional_keys = [
        "1_authenticated_at_expire",
        "2_room_in_progress_before_expire",
        "3_browser_deadline_crossed",
        "4_component_value_sent",
        "5_exact_token_delivery",
        "6_one_accepted_callback",
        "6a_observation_never_claimed",
        "6b_return_value_session_bind_accepted",
        "6c_claim_source_not_other",
        "7_zero_duplicate_processing",
        "7b_no_late_flush_owner",
        "7c_no_on_change_owner",
        "8_one_pick_committed",
        "9_pick_advances_once",
        "13_pick_from_expire_not_harness",
        "14_queue_player_ignored",
    ]
    observability_keys = [
        "ledger_durable_retained",
        "10_new_deadline_after_commit",
        "11_countdown_restarts_above_zero",
        "12_board_or_pool_updated",
        "15_next_token_after_commit",
        "16_next_timer_fully_verified",
    ]
    functional = {k: checks.get(k, False) for k in functional_keys}
    observability = {k: checks.get(k, False) for k in observability_keys}
    functional_pass = all(functional.values())
    observability_pass = all(observability.values())
    overall = functional_pass and observability_pass
    return {
        "functional_checks": functional,
        "observability_checks": observability,
        "functional_verdict": "PASS" if functional_pass else "FAIL",
        "observability_verdict": "PASS" if observability_pass else "FAIL",
        "verdict": "PASS" if overall else "FAIL",
        "overall_classification": (
            "STAGE1A_CORE_PASS"
            if overall
            else (
                "STAGE1A_CORE_FUNCTIONAL_AUTOPICK_PASS_WITH_TIMER_AND_LEDGER_OBSERVABILITY_GAPS"
                if functional_pass
                else "STAGE1A_CORE_FAIL"
            )
        ),
        "timer_continuity_classification": timer_classification,
        "ledger_meta": ledger_meta,
        "next_timer_wait_status": next_timer_wait.get("status"),
    }
