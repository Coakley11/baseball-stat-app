"""One-off artifact analysis for S3 unrouted routing (does not modify artifact)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "data" / "production_bridge_s3_server_registry_gate.json"
TARGET_SID = "637317da-027a-4f75-81c1-672a2e7e45ca"


def _find_unrouted_rows(d: dict) -> list[dict]:
    oe = d.get("observability_evidence") or {}
    if isinstance(oe.get("unrouted_rows"), list):
        return list(oe["unrouted_rows"])
    payload = (d.get("s3_server_diag_after_pause") or {}).get("payload") or {}
    if isinstance(payload.get("unrouted_rows"), list):
        return list(payload["unrouted_rows"])

    def walk(obj: object, found: list[list[dict]]) -> None:
        if isinstance(obj, dict):
            rows = obj.get("unrouted_rows")
            if (
                isinstance(rows, list)
                and rows
                and isinstance(rows[0], dict)
                and "routing_failure_reason" in rows[0]
            ):
                found.append(rows)
            for v in obj.values():
                walk(v, found)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, found)

    found: list[list[dict]] = []
    walk(d, found)
    return list(found[0]) if found else []


def _merged_rows(d: dict, sid: str) -> list[dict]:
    out: list[dict] = []
    sources = [
        d.get("observability_evidence") or {},
        (d.get("s3_server_diag_after_pause") or {}).get("payload") or {},
        d.get("authoritative_server_evidence") or {},
    ]
    for section in sources:
        if not isinstance(section, dict):
            continue
        for key in (
            "merged_authoritative_rows",
            "authoritative_server_rows",
            "module_rows",
            "critical_rows",
            "module_ledger_rows",
        ):
            for r in section.get(key) or []:
                if not isinstance(r, dict):
                    continue
                rsid = str(
                    r.get("streamlit_session_id")
                    or r.get("runtime_session_id")
                    or r.get("appsession_id")
                    or ""
                )
                if rsid == sid:
                    out.append(r)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in out:
        key = (r.get("phase"), r.get("ts"), r.get("event_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def _click_window_audit(rows: list[dict], sibling_ts: float | None, pause_ts: float | None, *, window_s: float = 3.0) -> dict:
    phases = (
        "RUNTIME_BACKMSG_ENTRY",
        "APPSESSION_BACKMSG_ENTRY",
        "APPSESSION_REQUEST_RERUN_ENTRY",
        "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
        "SERVER_RECEIVE_ENTRY",
        "SERVER_STATE_APPLIED",
    )
    audit: dict[str, Any] = {}
    for phase in phases:
        hits = [r for r in rows if r.get("phase") == phase]
        sibling_hits = [r for r in hits if sibling_ts and abs(float(r["ts"]) - float(sibling_ts)) <= window_s]
        pause_hits = [r for r in hits if pause_ts and abs(float(r["ts"]) - float(pause_ts)) <= window_s]
        if not hits:
            status = "row_missing"
        elif not sibling_hits and not pause_hits:
            status = "present_outside_click_windows"
        else:
            def _classify(window_hits: list[dict]) -> str:
                if not window_hits:
                    return "row_missing"
                if any(r.get("pause_present") or r.get("pause_sibling_present") for r in window_hits):
                    return "row_present_trigger_matched"
                return "row_present_trigger_matcher_failed"

            status = {
                "sibling": _classify(sibling_hits),
                "pause": _classify(pause_hits),
            }
        audit[phase] = {
            "total_count": len(hits),
            "ts_min": min((r["ts"] for r in hits), default=None),
            "ts_max": max((r["ts"] for r in hits), default=None),
            "sibling_window_count": len(sibling_hits),
            "pause_window_count": len(pause_hits),
            "audit_status": status,
        }
    return audit


def main() -> int:
    d = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    rows = _find_unrouted_rows(d)
    binding = d.get("s3_diag_binding_pre_click") or {}
    pause_ts = (d.get("pause_positive_control") or {}).get("pause_server_proof", {}).get("click_ts")
    sibling_ts = (d.get("sibling_strict_transport") or {}).get("finished_ts")

    def click_window(ts: float | None) -> str:
        if ts is None:
            return "unknown"
        if sibling_ts and abs(float(ts) - float(sibling_ts)) < 3.0:
            return "sibling"
        if pause_ts and abs(float(ts) - float(pause_ts)) < 3.0:
            return "pause"
        return "setup_or_other"

    bound_under = binding.get("underlying_sessionstate_object_id")
    bound_wrap = binding.get("context_session_state_object_id")

    report = {
        "target_sid": TARGET_SID,
        "unrouted_count": len(rows),
        "binding_pre_click": {
            k: binding.get(k)
            for k in (
                "streamlit_session_id",
                "context_session_state_object_id",
                "underlying_sessionstate_object_id",
                "sessionstate_wrapper_bound_streamlit_session_id",
                "underlying_sessionstate_bound_streamlit_session_id",
                "sessionstate_binding_ok",
                "sessionstate_wrapper_binding_ok",
            )
        },
        "sibling_click_ts": sibling_ts,
        "pause_click_ts": pause_ts,
        "unrouted_rows": [],
        "groups": {},
        "hypothesis": "",
    }

    target_rows = [
        r
        for r in rows
        if r.get("ctx_streamlit_session_id") == TARGET_SID or r.get("attempted_sid") == TARGET_SID
    ]
    other_rows = [r for r in rows if r not in target_rows]

    for i, r in enumerate(rows, 1):
        und = r.get("underlying_sessionstate_object_id") or r.get("sessionstate_object_id")
        if und == bound_under:
            vs_bound = "same_as_bound_underlying"
        elif und:
            vs_bound = "different_underlying"
        else:
            vs_bound = "no_id"
        report["unrouted_rows"].append(
            {
                "index": i,
                "event_id": r.get("event_id"),
                "ts": r.get("ts"),
                "phase": r.get("phase"),
                "routing_failure_reason": r.get("routing_failure_reason"),
                "ctx_streamlit_session_id": r.get("ctx_streamlit_session_id"),
                "attempted_sid": r.get("attempted_sid"),
                "thread_id": r.get("thread_id"),
                "object_type": r.get("object_type"),
                "sessionstate_object_id": r.get("sessionstate_object_id"),
                "safe_sessionstate_object_id": r.get("safe_sessionstate_object_id"),
                "underlying_sessionstate_object_id": r.get("underlying_sessionstate_object_id"),
                "pause_present": r.get("pause_present"),
                "pause_sibling_present": r.get("pause_sibling_present") or r.get("sibling_present"),
                "activated_triggers": r.get("activated_triggers"),
                "incoming_widget_count": r.get("incoming_widget_count"),
                "click_window": click_window(r.get("ts")),
                "vs_bound_underlying": vs_bound,
            }
        )

    report["groups"] = {
        "phase": dict(Counter(r.get("phase") for r in rows)),
        "routing_failure_reason": dict(Counter(r.get("routing_failure_reason") for r in rows)),
        "target_session_count": len(target_rows),
        "other_ctx_count": len(other_rows),
        "target_underlying_oids": dict(
            Counter(r.get("underlying_sessionstate_object_id") for r in target_rows)
        ),
        "target_safe_wrapper_unique": len(
            {r.get("safe_sessionstate_object_id") for r in target_rows if r.get("safe_sessionstate_object_id")}
        ),
        "target_threads": dict(Counter(r.get("thread_id") for r in target_rows)),
        "click_window": dict(Counter(click_window(r.get("ts")) for r in target_rows)),
    }

    routed = _merged_rows(d, TARGET_SID)
    report["routed_target_session"] = {
        "count": len(routed),
        "phases": dict(Counter(r.get("phase") for r in routed)),
        "runtime_appsession_audit": {},
        "click_window_audit": _click_window_audit(routed, sibling_ts, pause_ts),
    }
    for phase in (
        "RUNTIME_BACKMSG_ENTRY",
        "APPSESSION_BACKMSG_ENTRY",
        "APPSESSION_REQUEST_RERUN_ENTRY",
        "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
        "SERVER_RECEIVE_ENTRY",
        "SERVER_STATE_APPLIED",
    ):
        hits = [r for r in routed if r.get("phase") == phase]
        last = hits[-1] if hits else {}
        report["routed_target_session"]["runtime_appsession_audit"][phase] = {
            "present": bool(hits),
            "count": len(hits),
            "last_pause_present": last.get("pause_present"),
            "last_pause_sibling_present": last.get("pause_sibling_present"),
            "last_routing_resolved": last.get("routing_resolved"),
        }

    # Hypothesis classification for target session
    target_under = {r.get("underlying_sessionstate_object_id") for r in target_rows} - {None}
    if bound_under and target_under == {bound_under}:
        report["hypothesis"] = "S3_ROUTING_MAP_LOOKUP_INCONSISTENT"
    elif bound_under and target_under and bound_under not in target_under:
        report["hypothesis"] = "S3_ROUTING_SESSIONSTATE_INSTANCE_MISMATCH"
    elif other_rows and not any(r.get("ctx_streamlit_session_id") == TARGET_SID for r in target_rows):
        report["hypothesis"] = "S3_ROUTING_CROSS_SESSION_ATTRIBUTION"
    elif not target_under:
        report["hypothesis"] = "S3_ROUTING_IDENTITY_INSUFFICIENT"
    else:
        report["hypothesis"] = "S3_ROUTING_MAP_LOOKUP_INCONSISTENT"

    out = ROOT / "data" / "s3_unrouted_routing_analysis.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(out), "hypothesis": report["hypothesis"], "unrouted": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
