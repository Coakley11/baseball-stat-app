"""Stage 1A harness-only observability: durable ledger merge and post-commit timer wait."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
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
    get_ledger_rows: Callable[[], list[dict[str, Any]]] | None = None,
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
        iframe_probe = scrape_countdown_iframe_connectivity(page)
        if iframe_probe.get("countdown_iframe"):
            mount = {**mount, "iframe_connected": bool((iframe_probe.get("countdown_iframe") or {}).get("connected"))}
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
            "iframe_probe": iframe_probe,
        }
        if get_ledger_rows is not None:
            ledger_rows = list(get_ledger_rows() or [])
            timer_hint = ledger_server_next_timer(
                ledger_rows,
                room_id=rid,
                completed_token=completed,
            )
            hint_tok = str(timer_hint.get("server_expected_token") or "")
            if not new_token and hint_tok:
                new_token = hint_tok
            if not new_deadline:
                new_deadline = str(timer_hint.get("server_deadline") or "")
            pick1_mount = extract_pick1_post_commit_mount_observation(
                ledger_rows,
                expected_pick1_token=new_token or hint_tok,
                room_id=rid,
                mount_diag=mount,
                lifecycle_token=str(lifecycle or ""),
                visible_countdown=visible_countdown,
            )
            obs["pick1_post_commit_mount"] = pick1_mount
            result["pick1_post_commit_mount"] = pick1_mount
            result["ledger_rows_peak_count"] = len(ledger_rows)
        result["observations"].append(obs)
        if len(result["observations"]) > 80:
            result["observations"] = result["observations"][-60:]

        deadline_changed = bool(new_deadline) and new_deadline != old_deadline
        pick_index_ok = auth_pick_index == 1 or mount_pick_index == 1
        countdown_mounted = bool(visible_countdown) and str(visible_countdown) not in ("0", "")
        token_ok = bool(new_token)
        pick1_mount = dict(result.get("pick1_post_commit_mount") or {})
        same_session_mount_pass = bool(
            pick_index_ok
            and token_ok
            and deadline_changed
            and (
                pick1_mount.get("pick1_component_mount_proven")
                or (
                    pick1_mount.get("declaration_pick1_proven")
                    and pick1_mount.get("component_mount_token_match")
                    and pick1_mount.get("iframe_connected") is not False
                )
            )
        )

        if same_session_mount_pass or (pick_index_ok and token_ok and deadline_changed and countdown_mounted):
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
                    "pick1_same_session_mount_pass": same_session_mount_pass,
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


def scrape_countdown_iframe_connectivity(page: Any) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
              const out = { iframes: [], countdown_iframe: null, any_connected: false };
              for (const f of document.querySelectorAll('iframe')) {
                let connected = false;
                let href = '';
                try {
                  connected = !!f.contentDocument && f.contentDocument.readyState === 'complete';
                  href = String(f.src || '').slice(0, 280);
                } catch (e) { connected = false; }
                const row = { href, connected };
                out.iframes.push(row);
                if (/solo_countdown|countdown_wake/i.test(href)) out.countdown_iframe = row;
                if (connected) out.any_connected = true;
              }
              return out;
            }"""
        )
        return raw if isinstance(raw, dict) else {"iframes": []}
    except Exception:
        return {"iframes": [], "any_connected": False}


def build_pick1_same_session_mount_bundle(
    *,
    next_timer_wait: dict[str, Any],
    merged_ledger: list[dict[str, Any]],
    room_id: str,
    application_run_id: str = "",
    iframe_probe: dict[str, Any] | None = None,
    mount_diag: dict[str, Any] | None = None,
    timer_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Same-session capture after token_action_complete (persist before leaving room)."""
    rid = str(room_id or "").upper()
    timer_hint = ledger_server_next_timer(merged_ledger, room_id=rid, completed_token="")
    expected_pick1 = str(timer_hint.get("server_expected_token") or next_timer_wait.get("new_token") or "")
    pick1_obs = extract_pick1_post_commit_mount_observation(
        merged_ledger,
        expected_pick1_token=expected_pick1,
        room_id=rid,
        run_id=application_run_id,
        mount_diag=mount_diag or {},
        visible_countdown=(timer_fields or {}).get("timer") or (timer_fields or {}).get("ccTimer"),
    )
    if iframe_probe:
        pick1_obs["iframe_probe"] = iframe_probe
        if iframe_probe.get("countdown_iframe"):
            pick1_obs["iframe_connected"] = bool((iframe_probe.get("countdown_iframe") or {}).get("connected"))
    commit_row: dict[str, Any] = {}
    for row in merged_ledger:
        if str(row.get("event") or "") == "production_stage1_token_action_complete":
            commit_row = dict(row)
    live_ctx = {
        "room_id": rid,
        "pick_index": pick1_obs.get("server_corroboration_rows", [{}])[-1].get("pick_index")
        if pick1_obs.get("server_corroboration_rows")
        else None,
        "deadline": timer_hint.get("server_deadline"),
        "room_status": "in_progress",
    }
    classification = classify_pick1_mount(
        expected_pick1_token=expected_pick1,
        expected_room_id=rid,
        observation=pick1_obs,
        live_context=live_ctx,
    )
    return {
        "captured_in_same_browser_session": True,
        "persist_before_room_leave": True,
        "expected_pick1_token": expected_pick1,
        "expected_pick1_deadline": timer_hint.get("server_deadline"),
        "token_action_complete_row": commit_row,
        "countdown_declaration_pre_pick1": pick1_obs.get("countdown_declaration_pre_pick1") or {},
        "countdown_declaration_post_pick1": pick1_obs.get("countdown_declaration_post_pick1") or {},
        "registration_snapshots_pick1": pick1_obs.get("registration_snapshots_pick1") or [],
        "component_widget_id": pick1_obs.get("component_widget_id"),
        "iframe_connected": pick1_obs.get("iframe_connected"),
        "iframe_probe": iframe_probe or {},
        "browser_mount_token": pick1_obs.get("browser_mount_token"),
        "visible_countdown_text": pick1_obs.get("visible_countdown_text"),
        "server_corroboration_rows": pick1_obs.get("server_corroboration_rows") or [],
        "next_timer_wait_status": next_timer_wait.get("status"),
        "pick1_post_commit_mount": pick1_obs,
        **classification,
    }


def persist_pick1_same_session_mount_capture(path: Path, bundle: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**bundle, "persisted_at": time.time()}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def extract_pick1_post_commit_mount_observation(
    merged_ledger: list[dict[str, Any]],
    *,
    expected_pick1_token: str = "",
    run_id: str = "",
    room_id: str = "",
    mount_diag: dict[str, Any] | None = None,
    lifecycle_token: str = "",
    visible_countdown: Any = None,
) -> dict[str, Any]:
    """Harness-only: pick-1 mount evidence after token_action_complete (ledger + optional UI)."""
    rows = filter_ledger_for_run(merged_ledger, run_id=run_id, room_id=room_id)
    expected = normalize_expire_token(expected_pick1_token)
    decl_pre: list[dict[str, Any]] = []
    decl_post: list[dict[str, Any]] = []
    registration_snapshots: list[dict[str, Any]] = []
    server_reads: list[dict[str, Any]] = []
    commit_ts: float | None = None
    for row in rows:
        ev = str(row.get("event") or "")
        if ev == "production_stage1_token_action_complete":
            commit_ts = float(row.get("ts") or 0) or commit_ts
        if ev == "production_countdown_declaration_pre" and int(row.get("pick_index") or -1) == 1:
            decl_pre.append(row)
        if ev == "production_countdown_declaration_post" and int(row.get("pick_index") or -1) == 1:
            decl_post.append(row)
        if ev in (
            "production_stage1_internal_widget_metadata_registered",
            "production_stage1_callback_registration",
        ):
            if int(row.get("pick_index") or -1) == 1 or expected in normalize_expire_token(
                row.get("expected_token") or ""
            ):
                registration_snapshots.append(row)
        if ev in (
            "production_stage1_room_state_read",
            "production_stage1_next_room_state_persisted",
            "production_stage1_cloud_ledger_pipeline_canary",
        ):
            tok = normalize_expire_token(row.get("expected_token") or row.get("canonical_token") or "")
            if int(row.get("pick_index") or -1) == 1 or (expected and tok == expected):
                server_reads.append(row)
    mount = dict(mount_diag or {})
    browser_mount_token = normalize_expire_token(
        mount.get("expire_token") or mount.get("returned_token") or lifecycle_token or ""
    )
    md = mount.get("mount_diag") if isinstance(mount.get("mount_diag"), dict) else {}
    widget_id = str(mount.get("widget_id") or mount.get("authoritative_widget_id") or md.get("widget_id") or "")
    iframe_connected = mount.get("iframe_connected")
    if iframe_connected is None:
        iframe_connected = mount.get("document_connected")
    visible = visible_countdown if visible_countdown not in (None, "") else md.get("diag_remaining")
    declaration_proven = bool(decl_post) or bool(decl_pre)
    component_token_match = bool(expected) and browser_mount_token == expected
    server_token_proven = bool(expected) and any(
        normalize_expire_token(r.get("expected_token") or r.get("canonical_token") or "") == expected
        for r in server_reads
    )
    pick1_component_mount_proven = (
        (declaration_proven and server_token_proven)
        or component_token_match
        or (
            server_token_proven
            and bool(browser_mount_token)
            and browser_mount_token == expected
        )
    )
    return {
        "expected_pick1_token": expected,
        "commit_observed_ts": commit_ts,
        "countdown_declaration_pre_pick1": decl_pre[-1] if decl_pre else {},
        "countdown_declaration_post_pick1": decl_post[-1] if decl_post else {},
        "registration_snapshots_pick1": registration_snapshots[-3:],
        "server_corroboration_rows": server_reads[-3:],
        "component_widget_id": widget_id,
        "iframe_connected": iframe_connected,
        "browser_mount_token": browser_mount_token,
        "visible_countdown_text": visible,
        "declaration_pick1_proven": declaration_proven,
        "server_pick1_token_proven": server_token_proven,
        "component_mount_token_match": component_token_match,
        "pick1_component_mount_proven": pick1_component_mount_proven,
        "remaining_boundary": (
            ""
            if pick1_component_mount_proven
            else "COREN7-4 — PICK-1 SERVER TOKEN/DEADLINE EXISTS, BUT COUNTDOWN COMPONENT MOUNT WAS NOT PROVEN IN THE SAVED ARTIFACT"
        ),
    }


PICK1MOUNT_PASS = "PICK1MOUNT_PASS — PICK-1 COUNTDOWN DECLARED AND MOUNTED"
PICK1MOUNT1 = "PICK1MOUNT1 — SERVER TOKEN EXISTS BUT DECLARATION NOT CAPTURED"
PICK1MOUNT2 = "PICK1MOUNT2 — DECLARATION EXISTS BUT COMPONENT NOT CONNECTED"
PICK1MOUNT3 = "PICK1MOUNT3 — COMPONENT CONNECTED BUT TOKEN MISMATCHED"
PICK1MOUNT4 = "PICK1MOUNT4 — MOUNT PRESENT BUT UI TEXT NOT CAPTURED"
PICK1MOUNT5 = "PICK1MOUNT5 — ROOM/PICK/DEADLINE CONTEXT MISMATCH"
PICK1MOUNT6 = "PICK1MOUNT6 — OTHER"


def classify_pick1_mount(
    *,
    expected_pick1_token: str,
    expected_room_id: str,
    observation: dict[str, Any],
    live_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Targeted pick-1 mount classification (harness only)."""
    expected = normalize_expire_token(expected_pick1_token)
    exp_fields = parse_expire_token_fields(expected)
    obs = dict(observation or {})
    ctx = dict(live_context or {})
    live_room = str(ctx.get("room_id") or obs.get("live_room_id") or "").upper()
    live_pick = ctx.get("pick_index")
    decl_pre = obs.get("countdown_declaration_pre_pick1") or {}
    decl_post = obs.get("countdown_declaration_post_pick1") or {}
    has_decl = bool(decl_pre) or bool(decl_post)
    server_ok = bool(obs.get("server_pick1_token_proven"))
    iframe_connected = obs.get("iframe_connected")
    browser_tok = normalize_expire_token(obs.get("browser_mount_token") or "")
    visible = obs.get("visible_countdown_text")
    mount_proven = bool(obs.get("pick1_component_mount_proven"))
    rid = str(expected_room_id or "").upper()
    try:
        live_pick_i = int(live_pick) if live_pick not in (None, "") else None
    except (TypeError, ValueError):
        live_pick_i = None
    room_mismatch = bool(rid and live_room and live_room != rid)
    pick_mismatch = (
        live_pick_i is not None
        and exp_fields.get("pick_index") is not None
        and live_pick_i != int(exp_fields["pick_index"])
    )
    if room_mismatch or pick_mismatch:
        return {
            "pick1mount_classification": PICK1MOUNT5,
            "reason": "room_or_pick_mismatch",
            "live_room_id": live_room,
            "live_pick_index": live_pick_i,
        }
    if mount_proven or (has_decl and iframe_connected is not False and browser_tok == expected and server_ok):
        return {
            "pick1mount_classification": PICK1MOUNT_PASS,
            "mount_proven": True,
            "visible_countdown_optional": not bool(str(visible or "").strip()),
        }
    if server_ok and not has_decl:
        return {"pick1mount_classification": PICK1MOUNT1, "server_token_proven": True}
    if has_decl and iframe_connected is False:
        return {"pick1mount_classification": PICK1MOUNT2, "declaration_captured": True}
    if iframe_connected and browser_tok and expected and browser_tok != expected:
        return {"pick1mount_classification": PICK1MOUNT3, "browser_mount_token": browser_tok}
    if browser_tok == expected and has_decl and not str(visible or "").strip():
        return {"pick1mount_classification": PICK1MOUNT4, "visible_countdown_missing": True}
    if not live_room and not server_ok:
        return {"pick1mount_classification": PICK1MOUNT5, "reason": "no_live_pick1_context"}
    return {"pick1mount_classification": PICK1MOUNT6, "reason": obs.get("remaining_boundary") or "unclassified"}


def build_stage1a_core_status_model(
    *,
    functional_verdict: str,
    observability_verdict: str,
    timer_classification: str,
    server_next_timer: dict[str, Any] | None,
    pick1_mount: dict[str, Any] | None,
    overall_classification: str,
    queue_independence: str = "",
) -> dict[str, Any]:
    """Separate functional vs observability outcomes for accepted CORE runs."""
    functional_outcome = "PASS" if functional_verdict == "PASS" else "FAIL"
    server_timer = dict(server_next_timer or {})
    mount = dict(pick1_mount or {})
    server_timer_ok = bool(server_timer.get("server_expected_token")) and bool(
        server_timer.get("server_deadline")
    )
    if functional_outcome != "PASS":
        obs_outcome = "FAIL"
        overall = "FAIL"
    elif mount.get("pick1_component_mount_proven"):
        obs_outcome = "PASS"
        overall = "PASS"
    elif server_timer_ok:
        obs_outcome = "PICK1_COMPONENT_MOUNT_NOT_PROVEN"
        overall = "PASS_WITH_OBSERVABILITY_GAP"
    elif observability_verdict == "PASS":
        obs_outcome = "PASS"
        overall = "PASS"
    else:
        obs_outcome = "PARTIAL"
        overall = "PASS_WITH_OBSERVABILITY_GAP"
    pick1_server_timer = "PASS" if server_timer_ok else "NOT_PROVEN"
    pick1_mount_status = "PASS" if mount.get("pick1_component_mount_proven") else "NOT_PROVEN"
    return {
        "stage1a_core_functional_outcome": functional_outcome,
        "stage1a_core_observability_outcome": obs_outcome,
        "stage1a_core_overall": overall,
        "stage1a_core_overall_classification": overall_classification,
        "stage1a_core_pick1_server_timer": pick1_server_timer,
        "stage1a_core_pick1_component_mount": pick1_mount_status,
        "stage1a_core_timer_continuity": timer_classification,
        "queue_independence": queue_independence or "NOT EXERCISED — EMPTY QUEUE",
        "phase_status": {
            "stage1a_core_functional": functional_outcome,
            "pick1_server_timer": pick1_server_timer,
            "pick1_component_ui_mount": pick1_mount_status,
            "stage1a_queue": "NOT RUN",
            "stage1b": "NOT RUN",
            "soak": "NOT RUN",
        },
        "ui_scrape_must_not_override_functional_pass": True,
    }


def normalize_expire_token(raw: Any) -> str:
    s = str(raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] == "'":
        s = s[1:-1].strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1].strip()
    return s


def filter_ledger_for_run(
    rows: list[dict[str, Any]],
    *,
    run_id: str = "",
    room_id: str = "",
) -> list[dict[str, Any]]:
    rid = str(room_id or "").strip().upper()
    app_run = str(run_id or "").strip()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if app_run:
            row_run = str(row.get("run_id") or row.get("diagnostic_run_id") or "")
            if row_run and row_run != app_run:
                continue
        if rid:
            row_room = str(row.get("room_id") or row.get("token_room_id") or "").upper()
            if row_room and row_room != rid:
                continue
        out.append(row)
    return out


def ledger_claim_metrics(
    merged_ledger: list[dict[str, Any]],
    *,
    run_id: str = "",
    room_id: str = "",
) -> dict[str, Any]:
    rows = filter_ledger_for_run(merged_ledger, run_id=run_id, room_id=room_id)
    try_claim = 0
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    bind_accepted: list[dict[str, Any]] = []
    for row in rows:
        ev = str(row.get("event") or "")
        if ev == "production_stage1_try_claim_about_to_call":
            try_claim += 1
        if ev != "production_stage1_token_claim_result":
            continue
        src = str(row.get("source") or row.get("delivery_via") or "")
        acc = row.get("accepted") is True or str(row.get("accepted") or "").lower() == "true"
        if acc:
            accepted.append(row)
            if src == "return_value_session_bind":
                bind_accepted.append(row)
        else:
            rejected.append(row)
    return {
        "try_claim_call_count": try_claim,
        "accepted_claim_count": len(accepted),
        "accepted_return_value_session_bind_count": len(bind_accepted),
        "rejected_claim_count": len(rejected),
        "duplicate_claim_count": max(0, len(accepted) - 1),
        "accepted_bind_rows": bind_accepted,
    }


def ledger_pick_commit_reconciliation(
    merged_ledger: list[dict[str, Any]],
    *,
    run_id: str = "",
    room_id: str = "",
) -> dict[str, Any]:
    rows = filter_ledger_for_run(merged_ledger, run_id=run_id, room_id=room_id)
    commit_row: dict[str, Any] | None = None
    post_commit: dict[str, Any] | None = None
    next_persisted: dict[str, Any] | None = None
    for row in rows:
        ev = str(row.get("event") or "")
        if ev == "production_stage1_token_action_complete":
            commit_row = row
        if ev == "production_stage1_post_commit_state_entered":
            post_commit = row
        if ev == "production_stage1_next_room_state_persisted":
            next_persisted = row
    pick_index_before = None
    pick_index_after = None
    player = ""
    if commit_row:
        pick_index_before = commit_row.get("pick_index_before")
        pick_index_after = commit_row.get("pick_index_after")
        player = str(commit_row.get("committed_player") or "")
    if post_commit and pick_index_after is None:
        pick_index_after = post_commit.get("pick_index")
    if pick_index_before is None and post_commit:
        pick_index_before = 0 if int(post_commit.get("pick_index") or 0) == 1 else None
    delta = None
    if pick_index_before is not None and pick_index_after is not None:
        delta = int(pick_index_after) - int(pick_index_before)
    one_commit = delta == 1 or (
        commit_row is not None and int(commit_row.get("pick_index_after") or -1) == 1
    )
    return {
        "pick_index_before": pick_index_before,
        "pick_index_after": pick_index_after,
        "pick_index_delta": delta,
        "one_durable_pick": one_commit,
        "committed_player": player,
        "commit_row": commit_row,
        "post_commit_row": post_commit,
        "next_persisted_row": next_persisted,
    }


def ledger_server_next_timer(
    merged_ledger: list[dict[str, Any]],
    *,
    run_id: str = "",
    room_id: str = "",
    completed_token: str = "",
) -> dict[str, Any]:
    rows = filter_ledger_for_run(merged_ledger, run_id=run_id, room_id=room_id)
    completed = normalize_expire_token(completed_token)
    best_token = ""
    best_deadline = ""
    pick_index: int | None = None
    declaration_post_pick1 = False
    for row in rows:
        ev = str(row.get("event") or "")
        if ev == "production_stage1_next_room_state_persisted":
            tok = normalize_expire_token(row.get("expected_token") or row.get("canonical_token") or "")
            if is_valid_next_token(tok, completed_token=completed, room_id=room_id, expected_pick_index=1):
                best_token = tok
                pick_index = 1
                best_deadline = str(row.get("deadline") or row.get("canonical_deadline") or "")
        if ev == "production_stage1_cloud_ledger_pipeline_canary" and int(row.get("pick_index") or -1) == 1:
            if not best_deadline:
                best_deadline = str(row.get("deadline") or "")
            tok = normalize_expire_token(row.get("expected_token") or "")
            if tok and is_valid_next_token(tok, completed_token=completed, room_id=room_id, expected_pick_index=1):
                best_token = tok
            pick_index = 1
        if ev == "production_countdown_declaration_post" and int(row.get("pick_index") or -1) == 1:
            declaration_post_pick1 = True
    return {
        "authoritative_pick_index": pick_index,
        "server_expected_token": best_token,
        "server_deadline": best_deadline,
        "pick1_countdown_declaration_post": declaration_post_pick1,
    }


def authoritative_room_in_progress_at_send(
    merged_ledger: list[dict[str, Any]],
    *,
    token_sent: str,
    send_ts: float | None,
    room_id: str,
    run_id: str = "",
) -> dict[str, Any]:
    rows = filter_ledger_for_run(merged_ledger, run_id=run_id, room_id=room_id)
    tok = normalize_expire_token(token_sent)
    rid = str(room_id or "").strip().upper()
    best: dict[str, Any] | None = None
    for row in rows:
        ev = str(row.get("event") or "")
        if ev not in (
            "production_stage1_room_state_read",
            "production_stage1_cloud_ledger_pipeline_canary",
            "production_countdown_declaration_post",
        ):
            continue
        row_room = str(row.get("room_id") or "").upper()
        if rid and row_room and row_room != rid:
            continue
        row_ts = float(row.get("ts") or 0)
        if send_ts and row_ts > float(send_ts) + 2.0:
            continue
        status = str(row.get("room_status") or "")
        pick_idx = row.get("pick_index")
        row_tok = normalize_expire_token(row.get("expected_token") or row.get("token") or "")
        if status == "in_progress" and (pick_idx == 0 or pick_idx == "0"):
            if not best or row_ts >= float(best.get("ts") or 0):
                best = {
                    "ts": row_ts,
                    "event": ev,
                    "room_id": row_room or rid,
                    "room_status": status,
                    "pick_index": pick_idx,
                    "deadline": row.get("deadline"),
                    "expected_token": row_tok or tok,
                    "source_priority": ev,
                }
    in_progress = best is not None and str(best.get("room_status") or "") == "in_progress"
    token_match = bool(tok) and normalize_expire_token(best.get("expected_token") if best else "") == tok
    return {
        "server_in_progress_at_send": in_progress,
        "server_room_snapshot": best,
        "expected_token_match_at_send": token_match,
    }


def token_boundary_report(
    merged_ledger: list[dict[str, Any]],
    frozen_token: str,
    *,
    run_id: str = "",
) -> dict[str, Any]:
    rows = filter_ledger_for_run(merged_ledger, run_id=run_id)
    frozen = normalize_expire_token(frozen_token)
    fields = parse_expire_token_fields(frozen)

    def _row_token(row: dict[str, Any], *keys: str) -> str:
        for key in keys:
            if key in row and row.get(key) not in (None, ""):
                return normalize_expire_token(row.get(key))
        return ""

    mapping = {
        "backend_widget_token_raw": ("production_stage1_backend_widget_state_after_backmsg", "coalesced_value", "value"),
        "callback_handoff_written_token_raw": ("production_stage1_callback_handoff_written", "token", "raw_token"),
        "handoff_selected_token_raw": ("production_stage1_callback_handoff_selected", "token", "raw_token"),
        "p8c7_input_token_raw": ("production_stage1_declaration_returned", "coalesced_value", "direct_component_return"),
        "actionable_flush_token_raw": ("production_stage1_post_bind_actionable_flush", "token", "normalized_token"),
        "try_claim_token_raw": ("production_stage1_try_claim_about_to_call", "normalized_token", "token"),
    }
    report: dict[str, Any] = {"frozen_expected_token_raw": frozen}
    for label, (event, *keys) in mapping.items():
        val = ""
        for row in rows:
            if str(row.get("event") or "") != event:
                continue
            val = _row_token(row, *keys)
            if val:
                break
        parsed = parse_expire_token_fields(val) if val else {}
        report[label] = {
            "raw": val,
            "equals_frozen": val == frozen if val else False,
            "parsed": parsed,
        }
    # browser send from iframe is not always in merged ledger; caller may inject
    return report


def build_core_binding_timeline(
    merged_ledger: list[dict[str, Any]],
    *,
    frozen_token: str,
    run_id: str = "",
    room_id: str = "",
) -> list[dict[str, Any]]:
    rows = filter_ledger_for_run(merged_ledger, run_id=run_id, room_id=room_id)
    watch = {
        "production_stage1_declaration_returned",
        "production_stage1_callback_handoff_written",
        "production_stage1_callback_handoff_read",
        "production_stage1_callback_handoff_selected",
        "production_stage1_delivery_only_observation_completed",
        "production_stage1_post_bind_actionable_flush",
        "production_stage1_try_claim_about_to_call",
        "production_stage1_token_claim_result",
        "production_stage1_autopick_about_to_enter",
        "production_stage1_token_action_complete",
        "production_stage1_post_commit_state_entered",
        "production_stage1_next_pick_state_computed",
        "production_stage1_next_room_state_persisted",
        "production_stage1_callback_handoff_terminal",
        "production_stage1_room_state_read",
        "production_stage1_room_state_write",
        "production_countdown_declaration_post",
        "production_countdown_declaration_pre",
    }
    timeline: list[dict[str, Any]] = []
    frozen = normalize_expire_token(frozen_token)
    for row in sorted(rows, key=lambda r: float(r.get("ts") or 0)):
        ev = str(row.get("event") or "")
        if ev not in watch:
            continue
        tok = normalize_expire_token(
            row.get("token")
            or row.get("normalized_token")
            or row.get("coalesced_value")
            or row.get("raw_token")
            or row.get("expected_token")
            or ""
        )
        timeline.append(
            {
                "ts": row.get("ts"),
                "script_run_seq": row.get("script_run_seq"),
                "callback_invocation_id": row.get("callback_invocation_id") or "",
                "event": ev,
                "room_id": row.get("room_id") or row.get("token_room_id") or "",
                "pick_index": row.get("pick_index"),
                "deadline": row.get("deadline") or row.get("token_deadline"),
                "raw_token": tok,
                "processing_source": row.get("source") or row.get("delivery_via") or row.get("canonical_source") or "",
                "claim_result": row.get("accepted") if ev == "production_stage1_token_claim_result" else "",
                "player": row.get("committed_player") or "",
                "handoff_status": row.get("status") or row.get("clear_reason") or "",
                "equals_frozen": tok == frozen if tok else None,
            }
        )
    return timeline


def classify_core_reconciliation(
    *,
    exp: dict[str, Any],
    draft_valid: dict[str, Any],
    merged_ledger: list[dict[str, Any]],
    frozen_token: str,
    run_id: str = "",
    room_id: str = "",
    legacy_grade: dict[str, Any] | None = None,
) -> dict[str, Any]:
    legacy = legacy_grade or {}
    claims = ledger_claim_metrics(merged_ledger, run_id=run_id, room_id=room_id)
    pick = ledger_pick_commit_reconciliation(merged_ledger, run_id=run_id, room_id=room_id)
    timer = ledger_server_next_timer(
        merged_ledger, run_id=run_id, room_id=room_id, completed_token=frozen_token
    )
    send_ts = exp.get("value_sent_at")
    room_auth = authoritative_room_in_progress_at_send(
        merged_ledger,
        token_sent=frozen_token,
        send_ts=float(send_ts) if send_ts else None,
        room_id=room_id,
        run_id=run_id,
    )
    token_report = token_boundary_report(merged_ledger, frozen_token, run_id=run_id)
    obs: list[str] = []
    if legacy.get("functional_checks", {}).get("2_room_in_progress_before_expire") is False and room_auth.get(
        "server_in_progress_at_send"
    ):
        obs.append("COREOBS1 — SERVER STATUS PASSED; UI SCRAPE STALE")
    if legacy.get("token_match") is False or legacy.get("functional_checks", {}).get("5_exact_token_delivery") is False:
        if claims.get("accepted_return_value_session_bind_count", 0) >= 1:
            obs.append("COREOBS2 — TOKEN DELIVERY PASSED; GRADER MISCOUNTED")
    if int(legacy.get("return_value_session_bind_accepted_count") or 0) == 0 and claims.get(
        "accepted_return_value_session_bind_count", 0
    ) >= 1:
        obs.append("COREOBS3 — ACCEPTED CLAIM PRESENT; GRADER COUNTED ZERO")
    if pick.get("pick_index_delta") == 1 and legacy.get("functional_checks", {}).get("9_pick_advances_once") is False:
        obs.append("COREOBS4 — PICK ADVANCE PRESENT; GRADER MISSED IT")
    if legacy.get("functional_checks", {}).get("8_one_pick_committed") is False and pick.get("one_durable_pick"):
        obs.append("CORECOMMIT2 — PICK COMMITTED BUT SUMMARY EXTRACTOR COUNTED ZERO")
    n7 = ""
    if timer.get("server_expected_token") and timer.get("server_deadline"):
        if not timer.get("pick1_countdown_declaration_post"):
            n7 = "COREN7-4 — PICK-1 TOKEN/DEADLINE ON SERVER BUT COUNTDOWN MOUNT NOT PROVEN"
        elif legacy.get("timer_continuity_classification", "").startswith("T1"):
            n7 = "COREN7-2 — N7 RAN AND CREATED TIMER; SUMMARY EXTRACTOR MISGRADED IT"
    elif pick.get("one_durable_pick"):
        n7 = "COREN7-5 — NO AUTHORITATIVE FRESH PICK-1 TIMER STATE"
    exactly_once = {
        "callback_handoff_writes": sum(
            1 for r in merged_ledger if str(r.get("event") or "") == "production_stage1_callback_handoff_written"
        ),
        "handoff_selections": sum(
            1 for r in merged_ledger if str(r.get("event") or "") == "production_stage1_callback_handoff_selected"
        ),
        "actionable_flush_entries": sum(
            1 for r in merged_ledger if str(r.get("event") or "") == "production_stage1_post_bind_actionable_flush"
        ),
        "try_claim_calls": claims.get("try_claim_call_count", 0),
        "accepted_claims": claims.get("accepted_claim_count", 0),
        "auto_pick_entries": sum(
            1 for r in merged_ledger if str(r.get("event") or "") == "production_stage1_autopick_about_to_enter"
        ),
        "durable_commits": 1 if pick.get("one_durable_pick") else 0,
        "handoff_terminal": sum(
            1 for r in merged_ledger if str(r.get("event") or "") == "production_stage1_callback_handoff_terminal"
        ),
    }
    return {
        "coreobs_classifications": obs,
        "corecommit_classification": (
            "CORECOMMIT2 — PICK COMMITTED BUT SUMMARY EXTRACTOR COUNTED ZERO"
            if pick.get("one_durable_pick") and legacy.get("functional_checks", {}).get("8_one_pick_committed") is False
            else (
                "CORECOMMIT5 — COMMIT EVIDENCE MISSING FROM AVAILABLE ARTIFACT"
                if not pick.get("one_durable_pick")
                else ""
            )
        ),
        "coren7_classification": n7,
        "claim_metrics": claims,
        "pick_reconciliation": pick,
        "room_at_send": room_auth,
        "server_next_timer": timer,
        "token_boundary_report": token_report,
        "binding_timeline": build_core_binding_timeline(
            merged_ledger, frozen_token=frozen_token, run_id=run_id, room_id=room_id
        ),
        "exactly_once_counts": exactly_once,
    }


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
        ev = str(row.get("event") or "")
        if ev == "production_stage1_declaration_returned":
            if row.get("raw_received") and normalize_expire_token(row.get("coalesced_value")) == tok:
                return True
            continue
        if ev == "production_stage1_token_claim_result" and row.get("accepted"):
            if normalize_expire_token(row.get("token")) == tok:
                return True
        if ev in (
            "production_stage1_try_claim_about_to_call",
            "production_stage1_callback_handoff_selected",
            "production_stage1_callback_handoff_written",
        ):
            if normalize_expire_token(row.get("token") or row.get("normalized_token")) == tok:
                return True
    return False


def split_stage1a_grades(
    *,
    checks: dict[str, bool],
    ledger_meta: dict[str, Any],
    next_timer_wait: dict[str, Any],
    timer_classification: str,
    harness_observability_corrected: bool = False,
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
    harness_observability_corrected = bool(harness_observability_corrected)
    if overall:
        overall_label = "STAGE1A_CORE_PASS"
    elif functional_pass and harness_observability_corrected:
        overall_label = "STAGE1A_CORE_PASS — WITH HARNESS OBSERVABILITY CORRECTIONS"
    elif functional_pass:
        overall_label = "STAGE1A_CORE_FUNCTIONAL_AUTOPICK_PASS_WITH_TIMER_AND_LEDGER_OBSERVABILITY_GAPS"
    else:
        overall_label = "STAGE1A_CORE_FAIL"
    return {
        "functional_checks": functional,
        "observability_checks": observability,
        "functional_verdict": "PASS" if functional_pass else "FAIL",
        "observability_verdict": "PASS" if observability_pass else "FAIL",
        "verdict": "PASS" if overall else "FAIL",
        "overall_classification": overall_label,
        "timer_continuity_classification": timer_classification,
        "ledger_meta": ledger_meta,
        "next_timer_wait_status": next_timer_wait.get("status"),
    }
