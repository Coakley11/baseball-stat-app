"""P8 focused diagnostic ledger observability (harness only — no production bind logic)."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_PRE = ROOT / "data" / "p8_ledger_pre_expiration.json"
OUT_AFTER_SEND = ROOT / "data" / "p8_ledger_after_send.json"
OUT_FINAL = ROOT / "data" / "p8_ledger_final.json"

PRE_CANARY_EVENTS = frozenset(
    {
        "production_stage1_script_begin",
        "production_stage1_countdown_declaration_registered",
        "production_stage1_countdown_about_to_mount",
        "production_stage1_actionable_declaration_about_to_mount",
        "production_stage1_next_countdown_declaration_about_to_mount",
        "production_stage1_declaration_attempt",
        "production_stage1_declaration_returned",
        "production_stage1_p8_observability_canary",
    }
)


class P8LedgerHarnessCollector:
    """Python-side durable merge; never replace nonempty with an empty late scrape."""

    def __init__(self) -> None:
        self.merged: list[dict[str, Any]] = []
        self.peak_len = 0
        self.capture_log: list[dict[str, Any]] = []

    def absorb_capture(self, capture: dict[str, Any], *, label: str) -> None:
        from stage1_parent_observer_probe import merge_ledger_rows

        incoming = list(capture.get("merged_incoming") or [])
        before = len(self.merged)
        if incoming or not self.merged:
            self.merged = merge_ledger_rows(self.merged, incoming)
        after = len(self.merged)
        if after > self.peak_len:
            self.peak_len = after
        self.capture_log.append(
            {
                "label": label,
                "ts": time.time(),
                "incoming_count": len(incoming),
                "merged_before": before,
                "merged_after": after,
                "source_counts": capture.get("source_counts") or {},
            }
        )

    def peak_rows(self) -> list[dict[str, Any]]:
        return list(self.merged)


def capture_all_ledger_sources(page, *, audit: dict[str, Any] | None = None) -> dict[str, Any]:
    from stage1_frame2_parent_boundary import scrape_stage1_ledger_all_frames
    from stage1_harness_observability import (
        ledger_rows_from_callback_audit,
        rows_from_b64,
        scrape_durable_ledger_store,
    )
    from stage1_parent_observer_probe import merge_ledger_rows, scrape_stage1_production_ledger

    dom_all = scrape_stage1_ledger_all_frames(page)
    hits = list(dom_all.get("hits") or [])
    raw_dom_rows: list[dict[str, Any]] = []
    for hit in hits:
        b64 = str(hit.get("b64") or "")
        raw_dom_rows = merge_ledger_rows(raw_dom_rows, rows_from_b64(b64))

    top_dom = scrape_stage1_production_ledger(page)
    final_dom_rows = list(top_dom.get("rows") or [])
    if final_dom_rows:
        raw_dom_rows = merge_ledger_rows(raw_dom_rows, final_dom_rows)

    durable_store = scrape_durable_ledger_store(page)
    durable_rows = rows_from_b64(str(durable_store.get("best_b64") or ""))

    snapshot_rows: list[dict[str, Any]] = []
    try:
        snaps = page.evaluate(
            """() => {
              const s = window.__soloStage1HarnessLedgerStore;
              if (!s || !s.snapshots) return [];
              return s.snapshots.slice(-20).map(x => ({ rows: x.rows, ts: x.ts }));
            }"""
        )
        if isinstance(snaps, list):
            for snap in snaps:
                if isinstance(snap, dict) and int(snap.get("rows") or 0) > 0:
                    snapshot_rows.append(snap)
    except Exception:
        pass

    audit = audit or {}
    callback_rows = ledger_rows_from_callback_audit(
        audit,
        server_chain=str(audit.get("server_chain") or ""),
        server_stages=list(audit.get("server_stages") or []),
    )

    parent_sink_rows: list[dict[str, Any]] = []

    merged_incoming: list[dict[str, Any]] = []
    merged_incoming = merge_ledger_rows(merged_incoming, raw_dom_rows)
    merged_incoming = merge_ledger_rows(merged_incoming, durable_rows)
    merged_incoming = merge_ledger_rows(merged_incoming, callback_rows)

    probe_found = any(h.get("probe_found") for h in hits)
    window_b64 = any(h.get("window_b64") for h in hits)

    return {
        "source_counts": {
            "raw_dom_rows_before_filter": len(raw_dom_rows),
            "durable_store_rows_before_filter": len(durable_rows),
            "observation_loop_rows_before_filter": 0,
            "callback_audit_rows_before_filter": len(callback_rows),
            "parent_sink_rows_before_filter": len(parent_sink_rows),
            "dom_frame_hits": len(hits),
            "durable_store_installed": bool(durable_store.get("installed")),
            "durable_store_max_rows": int(durable_store.get("max_rows") or 0),
            "durable_store_capture_count": int(durable_store.get("capture_count") or 0),
            "ledger_probe_found_any_frame": probe_found,
            "window_b64_found_any_frame": window_b64,
            "durable_snapshot_nonempty_count": len(snapshot_rows),
        },
        "merged_incoming": merged_incoming,
        "dom_hits": hits,
        "durable_store": durable_store,
        "application_ledger_run_id": str((dom_all.get("best") or {}).get("run_id") or ""),
    }


def summarize_filter_rejections(filter_meta: dict[str, Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    missing_identity_kept = 0
    for item in filter_meta.get("rejected") or []:
        if not isinstance(item, dict):
            continue
        for reason in item.get("reasons") or []:
            counts[str(reason)] += 1
    for row in filter_meta.get("filtered_rows") or []:
        if not isinstance(row, dict):
            continue
        if filter_meta.get("filter_run_id") and not str(row.get("run_id") or "").strip():
            missing_identity_kept += 1
    return {
        "rows_rejected_by_run_id": counts.get("run_id_mismatch", 0),
        "rows_rejected_by_room_id": counts.get("room_id_mismatch", 0),
        "rows_rejected_by_deployment_sha": counts.get("deployment_sha_mismatch", 0),
        "rows_rejected_by_token": counts.get("token_room_mismatch", 0)
        + counts.get("exact_token_mismatch", 0),
        "rows_rejected_for_missing_identity_fields": 0,
        "rows_retained_with_missing_run_id": missing_identity_kept,
        "rejection_reason_counts": dict(counts),
    }


def pre_expiration_canary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ev = str(row.get("event") or "")
        if ev in PRE_CANARY_EVENTS:
            out.append(row)
    return out


def observability_validity_gate(
    *,
    setup_valid: bool,
    browser_send_ok: bool,
    collector: P8LedgerHarnessCollector,
    unfiltered_rows: list[dict[str, Any]],
    filter_meta: dict[str, Any],
) -> dict[str, Any]:
    rows = list(unfiltered_rows or [])
    filtered = list(filter_meta.get("filtered_rows") or [])
    pre_canary = pre_expiration_canary_rows(rows)
    post_send = [
        r
        for r in filtered
        if str(r.get("event") or "")
        in (
            "production_stage1_bound_token_gate",
            "production_stage1_declaration_returned",
            "production_stage1_post_bind_actionable_flush",
            "production_stage1_delivery_only_observation_completed",
        )
    ]
    total_before = int(filter_meta.get("rows_before") or len(rows))
    total_after = int(filter_meta.get("rows_after") or len(filtered))
    ok = bool(
        setup_valid
        and browser_send_ok
        and len(pre_canary) >= 1
        and total_before > 0
        and (total_after > 0 or len(post_send) > 0 or len(collector.peak_rows()) > 0)
    )
    return {
        "valid": ok,
        "pre_canary_count": len(pre_canary),
        "pre_canary_events": [r.get("event") for r in pre_canary[:20]],
        "post_send_row_count": len(post_send),
        "total_rows_before_filter": total_before,
        "total_rows_after_filter": total_after,
        "collector_peak_rows": len(collector.peak_rows()),
    }


def classify_observability_failure(
    *,
    capture_final: dict[str, Any],
    filter_meta: dict[str, Any],
    exp: dict[str, Any],
    harness_run_id: str,
    app_run_id: str,
) -> str:
    sc = capture_final.get("source_counts") or {}
    raw_dom = int(sc.get("raw_dom_rows_before_filter") or 0)
    durable = int(sc.get("durable_store_rows_before_filter") or 0)
    callback = int(sc.get("callback_audit_rows_before_filter") or 0)
    obs_loop = int(
        (exp.get("ledger_meta") or {}).get("observation_loop_ledger_row_count")
        or sc.get("observation_loop_rows_before_filter")
        or 0
    )
    total_before = int(filter_meta.get("rows_before") or 0)
    reject_summary = summarize_filter_rejections(filter_meta)
    if reject_summary.get("rows_rejected_by_run_id") and total_before > int(filter_meta.get("rows_after") or 0):
        return "OBS1C — RUN_ID_FILTER_REJECTED_VALID_ROWS"
    probe = bool(sc.get("ledger_probe_found_any_frame"))
    window_b64 = bool(sc.get("window_b64_found_any_frame"))
    if not probe and not window_b64 and raw_dom == 0 and durable == 0:
        if sc.get("durable_store_installed") and int(sc.get("durable_store_max_rows") or 0) == 0:
            return "OBS1F — LEDGER_RENDERING_DISABLED_ON_DEPLOYED_BUILD"
        return "OBS1A — APPLICATION_LEDGER_NEVER_EMITTED"
    peak = int((exp.get("ledger_meta") or {}).get("observation_loop_ledger_row_count") or 0)
    if (raw_dom or durable or obs_loop or peak) and total_before == 0:
        return "OBS1B — HARNESS_NEVER_COLLECTED_EXISTING_ROWS"
    if peak > total_before and total_before == 0:
        return "OBS1D — PAGE_RERUN_ERASED_UNPRESERVED_ROWS"
    if harness_run_id and app_run_id and harness_run_id != app_run_id and total_before == 0:
        return "OBS1E — WRONG_DIAGNOSTIC_PAGE_OR_COMPONENT_INSTANCE"
    return "OBS1B — HARNESS_NEVER_COLLECTED_EXISTING_ROWS"


def write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def enrich_expiration_ledger(
    page,
    exp: dict[str, Any],
    collector: P8LedgerHarnessCollector,
    *,
    label: str,
) -> dict[str, Any]:
    audit = dict(exp.get("stage1_audit") or exp.get("audit") or {})
    capture = capture_all_ledger_sources(page, audit=audit)
    collector.absorb_capture(capture, label=label)

    from stage1_harness_observability import merge_ledger_sources
    from stage1_parent_observer_probe import merge_ledger_rows

    loop_rows = list(exp.get("merged_server_ledger") or [])
    peak_rows = list(exp.get("peak_merged_server_ledger") or loop_rows)
    meta_in = dict(exp.get("ledger_meta") or {})
    merged_meta = merge_ledger_sources(
        observation_loop_rows=loop_rows,
        peak_observation_rows=peak_rows,
        durable_best_b64=str((capture.get("durable_store") or {}).get("best_b64") or ""),
        final_dom_rows=list(capture.get("merged_incoming") or []),
        callback_audit_rows=[],
        merge_fn=merge_ledger_rows,
    )
    harness_peak = collector.peak_rows()
    merged = merge_ledger_rows(list(merged_meta.get("merged_server_ledger") or []), harness_peak)
    if len(harness_peak) > len(merged):
        merged = harness_peak

    sc = dict(capture.get("source_counts") or {})
    sc["observation_loop_rows_before_filter"] = max(
        len(loop_rows),
        len(peak_rows),
        int(meta_in.get("observation_loop_ledger_row_count") or 0),
    )
    sc["harness_collector_peak_rows"] = len(harness_peak)

    out = {
        "merged_server_ledger": merged,
        "ledger_meta": {**merged_meta, **sc, "harness_collector_log": collector.capture_log[-30:]},
        "observability_sources": sc,
        "application_ledger_run_id": capture.get("application_ledger_run_id") or "",
    }
    exp.update(out)
    return out


def audit_stored_diagnostic_artifact(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    li = data.get("ledger_integrity") or {}
    ladder = data.get("p8_ladder") or {}
    lf = ladder.get("ledger_filter") or {}
    return {
        "artifact": str(path),
        "cloud_sha": data.get("cloud_sha"),
        "classification_accepted": "INVALID_DIAGNOSTIC_OBSERVABILITY_EMPTY",
        "failure_boundary": "OBS1 — PRODUCTION_LEDGER_NOT_CAPTURED",
        "raw_sources_reported": {
            "rows_before_filtering": li.get("rows_before_filtering"),
            "ledger_source_used": li.get("ledger_source_used"),
            "merged_row_count": li.get("merged_row_count"),
        },
        "ledger_filter": lf,
        "python_binding_chain": ladder.get("python_binding_chain"),
        "durable_sink_scv_count": ladder.get("durable_sink_scv_count"),
        "primary_observability_class": "OBS1B — HARNESS_NEVER_COLLECTED_EXISTING_ROWS"
        if li.get("ledger_source_used") == ["none"]
        else "OBS1A — APPLICATION_LEDGER_NEVER_EMITTED",
    }
