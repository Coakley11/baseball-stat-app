"""Focused P8 gate artifact replay — FOCUSGATE1–13 (harness)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FOCUSGATE1 = "FOCUSGATE1 — FOCUSED QUERY PARAMETER NOT PRESENT"
FOCUSGATE2 = "FOCUSGATE2 — HARNESS RUN ID ABSENT OR MISMATCHED"
FOCUSGATE3 = "FOCUSGATE3 — DIAGNOSTIC/DEVELOPER AUTHORIZATION FAILED"
FOCUSGATE4 = "FOCUSGATE4 — BUILD-SUPPORT CHECK FAILED"
FOCUSGATE5 = "FOCUSGATE5 — FOCUSED MODE EFFECTIVE AT BOOTSTRAP BUT LOST ON RERUN"
FOCUSGATE6 = "FOCUSGATE6 — FOCUSED MODE EFFECTIVE AT OBSERVATION BUT PRIMARY STOP NOT EXECUTED"
FOCUSGATE7 = "FOCUSGATE7 — PRIMARY STOP MISSED AND FLUSH DEFENSE DID NOT BLOCK"
FOCUSGATE8 = "FOCUSGATE8 — PRE-CLAIM DEFENSE DID NOT BLOCK"
FOCUSGATE9 = "FOCUSGATE9 — STOP/BLOCK EVENT EMITTED BUT EXECUTION CONTINUED"
FOCUSGATE10 = "FOCUSGATE10 — FOCUSED STATE READ FROM WRONG SESSION/RUN/ROOM"
FOCUSGATE11 = "FOCUSGATE11 — QUERY PARAMETER REMOVED DURING NAVIGATION OR RERUN"
FOCUSGATE12 = "FOCUSGATE12 — GUARDS WIRED TO A DIFFERENT FLUSH/CLAIM PATH"
FOCUSGATE13 = "FOCUSGATE13 — OTHER"

BINDALIGN4 = "BINDALIGN4 — FOCUSED MODE ALLOWED ACTIONABLE FLUSH, CLAIM, AUTO-PICK, AND COMMIT"

FOCUSED_EVENTS = (
    "production_stage1_p8_focused_mode_requested",
    "production_stage1_p8_focused_mode_authorized",
    "production_stage1_p8_focused_mode_effective",
    "production_stage1_p8_focused_binding_stop_before_claim",
    "production_stage1_p8_focused_flush_blocked",
    "production_stage1_p8_focused_preclaim_blocked",
    "production_stage1_p8_focused_handoff_terminal",
    "production_stage1_delivery_only_observation_completed",
    "production_stage1_post_bind_actionable_flush",
    "production_stage1_try_claim_about_to_call",
    "production_stage1_try_claim_accepted",
    "production_stage1_auto_pick_entered",
    "production_stage1_pick_committed",
)


def _collect_ledger_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "event" in o and ("event_id" in o or "run_id" in o or "script_run_seq" in o):
                rows.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(artifact)
    for src in (
        (artifact.get("production_setup") or {}).get("start_audit_reconcile") or {},
        (artifact.get("production_setup") or {}).get("latch_ledger_export") or {},
        artifact.get("bindalign_replay") or {},
    ):
        if isinstance(src, dict):
            extra = src.get("rows")
            if isinstance(extra, list):
                rows.extend([r for r in extra if isinstance(r, dict)])
    dedup: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict) or not r.get("event"):
            continue
        key = str(r.get("event_id") or f"{r.get('event')}:{r.get('ts')}:{r.get('script_run_seq')}")
        dedup[key] = r
    return sorted(dedup.values(), key=lambda x: (float(x.get("ts") or 0), int(x.get("script_run_seq") or 0)))


def _row_app_run(r: dict[str, Any]) -> str:
    return str(r.get("run_id") or r.get("diagnostic_run_id") or "")[:32]


def build_focused_mode_timeline(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    harness = str(artifact.get("harness_run_id") or artifact.get("diagnostic_run_id") or "")
    app_run = str(artifact.get("application_diagnostic_run_id") or "")
    rows = _collect_ledger_rows(artifact)
    app_rows = [r for r in rows if not app_run or _row_app_run(r) == app_run or not _row_app_run(r)]
    timeline: list[dict[str, Any]] = []
    for r in app_rows:
        ev = str(r.get("event") or "")
        if ev not in FOCUSED_EVENTS and "focused" not in ev and ev not in (
            "production_stage1_post_bind_actionable_flush",
            "production_stage1_try_claim_about_to_call",
            "production_stage1_try_claim_accepted",
        ):
            continue
        extra = r if isinstance(r.get("extra"), dict) else r
        timeline.append(
            {
                "ts": r.get("ts"),
                "script_run_seq": r.get("script_run_seq"),
                "callback_invocation_id": r.get("callback_invocation_id")
                or extra.get("callback_invocation_id")
                or extra.get("observation_invocation_id"),
                "harness_run_id": harness,
                "application_diagnostic_run_id": _row_app_run(r) or app_run,
                "streamlit_session_id": r.get("streamlit_session_id") or extra.get("streamlit_session_id"),
                "room_id": r.get("room_id"),
                "pick_index": r.get("pick_index"),
                "token": str(r.get("token") or r.get("bound_token") or extra.get("bound_token") or "")[:120],
                "event": ev,
                "focused_requested": extra.get("focused_param_requested"),
                "focused_authorized": extra.get("focused_authorized"),
                "focused_effective": extra.get("focused_effective"),
                "authorization_result": extra.get("authorization_result"),
                "denial_reason": extra.get("denial_reason"),
                "processing_source": extra.get("processing_source"),
                "stop_reason": extra.get("stop_reason"),
            }
        )
    return timeline


def classify_focused_gate_boundary(artifact: dict[str, Any]) -> dict[str, Any]:
    from p8_binding_align_classify import build_focused_invariant_report

    harness = str(artifact.get("harness_run_id") or "")
    app_run = str(artifact.get("application_diagnostic_run_id") or "")
    rows = _collect_ledger_rows(artifact)
    app_scoped = [r for r in rows if app_run and _row_app_run(r) == app_run]
    inv = build_focused_invariant_report(app_scoped or rows)
    timeline = build_focused_mode_timeline(artifact)

    auth_rows = [r for r in app_scoped if str(r.get("event") or "") == "production_stage1_p8_focused_mode_authorized"]
    eff_rows = [r for r in app_scoped if str(r.get("event") or "") == "production_stage1_p8_focused_mode_effective"]
    req_rows = [r for r in app_scoped if str(r.get("event") or "") == "production_stage1_p8_focused_mode_requested"]

    def _extra(r: dict[str, Any]) -> dict[str, Any]:
        return r if not isinstance(r.get("extra"), dict) else {**r, **r.get("extra")}

    ever_authorized = any(_extra(r).get("focused_authorized") is True for r in auth_rows)
    ever_effective = bool(eff_rows) or any(_extra(r).get("focused_effective") is True for r in auth_rows + req_rows)
    denial_counts: dict[str, int] = {}
    for r in auth_rows:
        reason = str(_extra(r).get("denial_reason") or "")
        if reason:
            denial_counts[reason] = denial_counts.get(reason, 0) + 1

    stop_n = inv.get("focused_stop_before_claim_events", 0)
    flush_n = inv.get("actionable_flush_count", 0)
    claim_n = inv.get("try_claim_call_count", 0)

    audit = {
        "harness_run_id": harness,
        "application_diagnostic_run_id": app_run,
        "focused_requested_events": len(req_rows),
        "focused_authorized_events": len(auth_rows),
        "focused_effective_events": len(eff_rows),
        "ever_authorized_true": ever_authorized,
        "ever_effective": ever_effective,
        "denial_reason_counts": denial_counts,
        "invariants": inv,
        "bindalign_observed": BINDALIGN4 if claim_n else "",
    }

    setup_url = str(
        artifact.get("url")
        or (artifact.get("p8_ldr_surface") or {}).get("url")
        or (artifact.get("production_setup") or {}).get("url")
        or ""
    )
    if "solo_p8_focused_binding" not in setup_url and not req_rows:
        return _out(FOCUSGATE1, audit, "no_focused_param_in_url_or_ledger")

    if "solo_p8_harness_run_id" not in setup_url and not any(
        str(r.get("harness_transaction_id") or "") for r in auth_rows
    ):
        return _out(FOCUSGATE2, audit, "harness_run_id_missing")

    if denial_counts.get("developer_diagnostic_not_authorized") and not ever_effective:
        if ever_authorized:
            return _out(FOCUSGATE5, audit, "authorized_then_lost")
        return _out(FOCUSGATE3, audit, "developer_diagnostic_not_authorized")

    if not ever_effective and req_rows and not ever_authorized:
        return _out(FOCUSGATE11, audit, "requested_never_authorized_likely_qp_lost")

    if ever_effective and flush_n and not stop_n:
        return _out(FOCUSGATE6, audit, "effective_but_no_stop_before_flush")

    if flush_n and claim_n and not stop_n:
        return _out(FOCUSGATE7, audit, "flush_without_stop_or_flush_block")

    if claim_n and not any(
        str(r.get("event") or "") == "production_stage1_p8_focused_preclaim_blocked" for r in app_scoped
    ):
        return _out(FOCUSGATE8, audit, "claim_without_preclaim_block_event")

    if stop_n and claim_n:
        return _out(FOCUSGATE9, audit, "stop_emitted_but_claim_ran")

    if claim_n:
        return _out(FOCUSGATE12, audit, "claim_on_production_path_without_effective_focused")

    return _out(FOCUSGATE13, audit, "unmapped")


def replay_4c7d5ee7(path: Path | None = None) -> dict[str, Any]:
    p = path or Path(__file__).resolve().parent.parent / "data" / "production_p8_binding_diagnostic.json"
    artifact = json.loads(p.read_text(encoding="utf-8"))
    if str(artifact.get("harness_run_id") or "") != "4c7d5ee7b1324a8a":
        raise ValueError(f"expected harness 4c7d5ee7, got {artifact.get('harness_run_id')}")
    gate = classify_focused_gate_boundary(artifact)
    return {
        "harness_run_id": artifact.get("harness_run_id"),
        "application_diagnostic_run_id": artifact.get("application_diagnostic_run_id"),
        "focused_gate_classification": gate,
        "bindalign_observed": gate.get("audit", {}).get("bindalign_observed") or BINDALIGN4,
        "focused_mode_timeline": build_focused_mode_timeline(artifact),
        "invariants": gate.get("audit", {}).get("invariants") or {},
    }


def _out(code: str, audit: dict[str, Any], detail: str) -> dict[str, Any]:
    return {"classification": code, "detail": detail, "audit": audit, "bindalign_observed": BINDALIGN4}


def main() -> int:
    out = replay_4c7d5ee7()
    dest = Path(__file__).resolve().parent.parent / "data" / "p8_replay_4c7d5ee7_focused_gate.json"
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"classification": out["focused_gate_classification"]["classification"], "artifact": str(dest)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
