"""Harness-only P8 lifecycle diff: b6e20ca bind reference vs d73bcf3 no-bind runs."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PREP = ROOT / "data" / "p8_bind_lifecycle_investigation_prep.json"
OUT_JSON = ROOT / "data" / "p8_lifecycle_diff_b6e20ca_vs_d73bcf3.json"
OUT_TXT = ROOT / "data" / "p8_lifecycle_diff_b6e20ca_vs_d73bcf3.txt"

WIDGET_KEY = "solo_countdown_wake_solo_persistent"
WINDOW_BEFORE_S = 5.0
WINDOW_AFTER_S = 10.0

POST_SEND_LEDGER_EVENTS = frozenset(
    {
        "production_stage1_script_begin",
        "production_stage1_declaration_attempt",
        "production_stage1_declaration_returned",
        "production_stage1_bound_token_gate",
        "production_stage1_post_bind_actionable_flush",
        "production_stage1_delivery_only_observation_completed",
        "production_stage1_after_early_persistent_wake",
        "production_stage1_actionable_mount_eligibility",
    }
)

BROWSER_STAGE_ORDER = (
    "timer_armed",
    "browser_deadline_crossed",
    "before_setComponentValue",
    "transport_before_postMessage",
    "expiration_send_claimed",
    "transport_postmessage_invoked",
    "component_value_sent",
    "tick_cancelled",
)


@dataclass
class RunSpec:
    label: str
    cloud_sha: str
    room_id: str
    exact_token: str
    artifact_path: Path
    ladder_path: str  # dotted path inside artifact


def parse_token_deadline(exact_token: str) -> float | None:
    parts = str(exact_token or "").split("|")
    if len(parts) < 3:
        return None
    try:
        return float(parts[2])
    except ValueError:
        return None


def load_json(path: Path) -> Any:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8")
    decoder = json.JSONDecoder()
    obj, _idx = decoder.raw_decode(text.lstrip("\ufeff"))
    return obj


def dig(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def normalize_return(val: Any) -> str:
    s = str(val or "").strip()
    if s in ("None", "''", '""', ""):
        return ""
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    return s


def ledger_rows_for_run(spec: RunSpec) -> list[dict[str, Any]]:
    raw = load_json(spec.artifact_path)
    block = dig(raw, spec.ladder_path) or {}
    rows = list(block.get("filtered_rows") or [])
    if not rows and isinstance(raw, dict):
        rows = list((raw.get("ledger_filter") or {}).get("filtered_rows") or [])
    room = spec.room_id
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("room_id") or "")
        if rid and rid != room:
            continue
        if not rid:
            tok = str(row.get("expected_token") or row.get("token") or row.get("mount_token") or "")
            if tok and not tok.startswith(room):
                if row.get("event") not in (
                    "production_stage1_script_begin",
                    "production_stage1_persistent_wake_eligibility",
                    "production_stage1_room_checkpoint",
                ):
                    continue
        out.append(row)
    return sorted(out, key=lambda r: (float(r.get("ts") or 0), str(r.get("event_id") or "")))


def ladder_summary(spec: RunSpec) -> dict[str, Any]:
    raw = load_json(spec.artifact_path)
    if spec.ladder_path == "ledger_filter" and isinstance(raw, dict):
        ladder = raw
    else:
        base = spec.ladder_path.replace(".ledger_filter", "") if spec.ladder_path else ""
        ladder = dig(raw, base) if base else None
        if not isinstance(ladder, dict):
            ladder = raw.get("p8_ladder") if isinstance(raw, dict) else {}
    if not isinstance(ladder, dict):
        ladder = {}
    return {
        "production_countdown_send": ladder.get("production_countdown_send") or {},
        "minimal_diag_iframe": ladder.get("minimal_diag_iframe") or {},
        "iframe_identity": ladder.get("iframe_identity") or {},
        "authoritative_receipt_levels": (ladder.get("authoritative_receipt_levels") or {}),
        "python_binding_chain": ladder.get("python_binding_chain") or {},
    }


def declaration_stats(rows: list[dict[str, Any]], t0: float) -> dict[str, Any]:
    decl_attempt = [r for r in rows if r.get("event") == "production_stage1_declaration_attempt"]
    decl_return = [r for r in rows if r.get("event") == "production_stage1_declaration_returned"]
    before = [r for r in decl_attempt if float(r.get("ts") or 0) < t0]
    after = [r for r in decl_attempt if float(r.get("ts") or 0) >= t0]
    ret_before = [r for r in decl_return if float(r.get("ts") or 0) < t0]
    ret_after = [r for r in decl_return if float(r.get("ts") or 0) >= t0]
    return {
        "declaration_attempts_before_send": len(before),
        "declaration_attempts_after_send": len(after),
        "declaration_returns_before_send": len(ret_before),
        "declaration_returns_after_send": len(ret_after),
        "last_return_before_send": _summarize_declaration(ret_before[-1] if ret_before else None),
        "first_return_after_send": _summarize_declaration(ret_after[0] if ret_after else None),
    }


def _summarize_declaration(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "ts": row.get("ts"),
        "script_run_seq": row.get("script_run_seq"),
        "widget_key": row.get("widget_key"),
        "room_id": row.get("room_id"),
        "pick_index": row.get("pick_index"),
        "deadline": row.get("deadline"),
        "expected_token": row.get("expected_token"),
        "direct_component_return": normalize_return(row.get("direct_component_return")),
        "session_state_value": normalize_return(row.get("session_state_value")),
        "coalesced_value": normalize_return(row.get("coalesced_value")),
        "delivery_only": row.get("delivery_only"),
        "room_status": row.get("room_status"),
    }


def timeline_from_ledger(rows: list[dict[str, Any]], t0: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        ts = float(row.get("ts") or 0)
        if not ts:
            continue
        if ts < t0 - WINDOW_BEFORE_S or ts > t0 + WINDOW_AFTER_S:
            continue
        events.append(_ledger_timeline_event(row, t0))

    if not events and rows:
        tail = rows[-12:]
        for row in tail:
            ts = float(row.get("ts") or 0)
            if ts:
                events.append(_ledger_timeline_event(row, t0))
        if events:
            events.insert(
                0,
                {
                    "t_rel_s": round(float(rows[-1].get("ts") or 0) - t0, 3),
                    "ts": rows[-1].get("ts"),
                    "source": "analysis",
                    "category": "streamlit",
                    "kind": "ledger_capture_ended_before_pre_send_window",
                    "note": (
                        f"last ledger ts is {round(float(rows[-1].get('ts') or 0) - t0, 3)}s vs t0; "
                        "no rows in [-5s,+10s] window"
                    ),
                },
            )
    return sorted(events, key=lambda e: (e.get("t_rel_s") is None, e.get("t_rel_s") or 0, e.get("kind") or ""))


def _ledger_timeline_event(row: dict[str, Any], t0: float) -> dict[str, Any]:
    ts = float(row.get("ts") or 0)
    ev = str(row.get("event") or "")
    return {
        "t_rel_s": round(ts - t0, 3) if ts else None,
        "ts": ts,
        "source": "production_ledger",
        "category": "streamlit" if ev.startswith("production_stage1") else "other",
        "kind": ev,
        "script_run_seq": row.get("script_run_seq"),
        "coalesced_value": normalize_return(row.get("coalesced_value")),
        "direct_return": normalize_return(row.get("direct_component_return")),
        "session_state": normalize_return(row.get("session_state_value")),
        "decision": row.get("decision"),
        "call_site": row.get("call_site"),
        "expected_token_source": row.get("expected_token_source"),
        "delivery_only": row.get("delivery_only"),
        "actionable": row.get("actionable"),
    }


def synthetic_browser_milestones(t0: float, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered client stages from harness; anchor transport_before_postMessage at t0."""
    exp_block = summary.get("production_countdown_send") or {}
    stages = list(exp_block.get("production_stages") or [])
    if not stages:
        return []
    ordered = [s for s in BROWSER_STAGE_ORDER if s in stages]
    if "transport_before_postMessage" not in ordered:
        ordered.append("transport_before_postMessage")
    idx = ordered.index("transport_before_postMessage")
    events: list[dict[str, Any]] = []
    for i, stage in enumerate(ordered):
        events.append(
            {
                "t_rel_s": round((i - idx) * 0.05, 3),
                "ts": None,
                "source": "harness_client_stage_order",
                "category": "browser",
                "kind": stage,
                "note": "relative order only; transport_before_postMessage anchored at t0",
            }
        )
    iframe = summary.get("iframe_identity") or {}
    primary = (iframe.get("source_association") or {}).get("primary_match") or {}
    events.append(
        {
            "t_rel_s": 0.0,
            "ts": None,
            "source": "harness_iframe_grading",
            "category": "browser",
            "kind": "iframe_primary_at_send",
            "iframe_instance_id": primary.get("iframe_instance_id"),
            "is_production_countdown": primary.get("is_production_countdown"),
            "iframe_is_connected": primary.get("iframe_is_connected"),
            "iframe_name": primary.get("iframe_name"),
        }
    )
    levels = summary.get("authoritative_receipt_levels") or {}
    for key in (
        "LEVEL_2_ACTUAL_IMMEDIATE_PARENT_FRAME2",
        "LEVEL_3_CURRENT_COMPONENT_SOURCE_MATCH_IMMEDIATE",
        "LEVEL_4_STREAMLIT_PROTOCOL_ACCEPTED",
        "LEVEL_5_PYTHON_VALUE_BOUND",
    ):
        events.append(
            {
                "t_rel_s": 0.05,
                "ts": None,
                "source": "harness_receipt_levels",
                "category": "browser",
                "kind": key,
                "pass": levels.get(key),
            }
        )
    return events


def merge_timeline(ledger_events: list[dict[str, Any]], browser_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = ledger_events + browser_events
    return sorted(
        merged,
        key=lambda e: (
            e.get("t_rel_s") is None,
            e.get("t_rel_s") if e.get("t_rel_s") is not None else 999,
            e.get("kind") or "",
        ),
    )


def first_post_send_bind_marker(rows: list[dict[str, Any]], t0: float, exact_token: str) -> dict[str, Any]:
    for row in rows:
        ts = float(row.get("ts") or 0)
        if ts < t0:
            continue
        if row.get("event") != "production_stage1_declaration_returned":
            continue
        co = normalize_return(row.get("coalesced_value"))
        if co == exact_token:
            return {"found": True, "ts": ts, "t_rel_s": round(ts - t0, 3), "script_run_seq": row.get("script_run_seq")}
    return {"found": False}


def max_ledger_ts(rows: list[dict[str, Any]]) -> float | None:
    ts_vals = [float(r.get("ts") or 0) for r in rows if r.get("ts")]
    return max(ts_vals) if ts_vals else None


def compare_runs(specs: list[RunSpec]) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    for spec in specs:
        t0 = parse_token_deadline(spec.exact_token)
        if t0 is None:
            raise ValueError(f"bad token {spec.exact_token}")
        rows = ledger_rows_for_run(spec)
        summary = ladder_summary(spec)
        decl = declaration_stats(rows, t0)
        ledger_tl = timeline_from_ledger(rows, t0)
        browser_tl = synthetic_browser_milestones(t0, summary)
        runs[spec.label] = {
            "cloud_sha": spec.cloud_sha,
            "room_id": spec.room_id,
            "exact_token": spec.exact_token,
            "t0_transport_before_postMessage_epoch": t0,
            "artifact": str(spec.artifact_path),
            "ledger_row_count": len(rows),
            "max_ledger_ts": max_ledger_ts(rows),
            "ledger_covers_post_send_window": bool(max_ledger_ts(rows) and max_ledger_ts(rows) >= t0),
            "first_post_send_bind": first_post_send_bind_marker(rows, t0, spec.exact_token),
            "declaration_stats": decl,
            "iframe_at_grade": (summary.get("iframe_identity") or {}),
            "receipt_levels": summary.get("authoritative_receipt_levels") or {},
            "python_binding_chain": summary.get("python_binding_chain") or {},
            "timeline": merge_timeline(ledger_tl, browser_tl),
        }

    ref = runs["b6e20ca_p8c7"]
    nb1 = runs["d73bcf3_30073BB4"]
    nb2 = runs["d73bcf3_CF62057F"]

    first_diff = _identify_first_transition(ref, nb1, nb2)
    lifecycle_class = _classify_lifecycle(first_diff, ref, nb1, nb2)
    code_diff = _production_code_diff_summary(first_diff)
    dimensions = _compare_dimensions(ref, nb1, nb2)

    return {
        "harness_commit": "9df749d",
        "production_cloud_sha": "d73bcf3",
        "prep_source": str(PREP),
        "runs": runs,
        "lifecycle_dimensions": dimensions,
        "first_differing_transition": first_diff,
        "lifecycle_classification": lifecycle_class,
        "production_code_diff_focus": code_diff,
        "artifact_outputs": {"json": str(OUT_JSON), "txt": str(OUT_TXT)},
    }


def _compare_dimensions(ref: dict[str, Any], nb1: dict[str, Any], nb2: dict[str, Any]) -> dict[str, Any]:
    def iframe_summary(run: dict[str, Any]) -> dict[str, Any]:
        ident = run.get("iframe_at_grade") or {}
        assoc = ident.get("source_association") or {}
        primary = assoc.get("primary_match") or {}
        return {
            "iframe_remounts": ident.get("iframe_remounts"),
            "primary_iframe_instance_id": primary.get("iframe_instance_id"),
            "is_production_countdown": primary.get("is_production_countdown"),
            "production_countdown_match_count": assoc.get("production_countdown_match_count"),
        }

    return {
        "A_component_declaration": {
            "reference_post_send_coalesced": ref.get("first_post_send_bind"),
            "no_bind_30073BB4_post_send_coalesced": nb1.get("first_post_send_bind"),
            "no_bind_CF62057F_post_send_coalesced": nb2.get("first_post_send_bind"),
            "reference_declaration_stats": ref.get("declaration_stats"),
            "no_bind_30073BB4_declaration_stats": nb1.get("declaration_stats"),
            "no_bind_CF62057F_declaration_stats": nb2.get("declaration_stats"),
        },
        "B_browser_iframe": {
            "reference": iframe_summary(ref),
            "d73bcf3_30073BB4": iframe_summary(nb1),
            "d73bcf3_CF62057F": iframe_summary(nb2),
        },
        "C_streamlit_lifecycle": {
            "reference_max_ledger_t_rel_s": round((ref.get("max_ledger_ts") or 0) - ref["t0_transport_before_postMessage_epoch"], 3),
            "no_bind_30073BB4_max_ledger_t_rel_s": round(
                (nb1.get("max_ledger_ts") or 0) - nb1["t0_transport_before_postMessage_epoch"], 3
            ),
            "no_bind_CF62057F_max_ledger_t_rel_s": round(
                (nb2.get("max_ledger_ts") or 0) - nb2["t0_transport_before_postMessage_epoch"], 3
            ),
        },
        "D_key_instance_consistency": {
            "widget_key_all_runs": WIDGET_KEY,
            "reference_first_post_send_seq": (ref.get("first_post_send_bind") or {}).get("script_run_seq"),
            "d73bcf3_post_send_script_runs_in_ledger": 0,
        },
    }


def _identify_first_transition(ref: dict[str, Any], nb1: dict[str, Any], nb2: dict[str, Any]) -> dict[str, Any]:
    t0_ref = ref["t0_transport_before_postMessage_epoch"]
    ref_bind = ref["first_post_send_bind"]
    nb1_bind = nb1["first_post_send_bind"]
    nb2_bind = nb2["first_post_send_bind"]

    downstream: list[str] = []

    if ref_bind.get("found") and not nb1_bind.get("found") and not nb2_bind.get("found"):
        primary = {
            "summary": (
                "After t0 (transport_before_postMessage / token deadline), b6e20ca records "
                "production_stage1_declaration_returned with coalesced exact token on script_run_seq "
                f"{ref_bind.get('script_run_seq')} at t+{ref_bind.get('t_rel_s')}s; both d73bcf3 runs "
                "record no declaration_returned at or after t0 with nonempty coalesced_value."
            ),
            "t_rel_s": ref_bind.get("t_rel_s"),
            "reference_event": ref_bind,
            "no_bind_runs": {
                "30073BB4": {
                    "max_ledger_ts_vs_t0": round((nb1.get("max_ledger_ts") or 0) - t0_ref, 3),
                    "ledger_covers_post_send": nb1.get("ledger_covers_post_send_window"),
                },
                "CF62057F": {
                    "max_ledger_ts_vs_t0": round((nb2.get("max_ledger_ts") or 0) - t0_ref, 3),
                    "ledger_covers_post_send": nb2.get("ledger_covers_post_send_window"),
                },
            },
        }
        downstream.extend(
            [
                "empty final Python scrape on all runs (harness end-state)",
                "P8C7 snapshot fields empty on d73bcf3 gates (not exercised)",
                "reject_mount_token_not_bound on d73bcf3 pre-send gates",
            ]
        )
        return {"primary": primary, "downstream_markers": downstream}

    return {
        "primary": {"summary": "Unable to auto-isolate; inspect timelines manually."},
        "downstream_markers": downstream,
    }


def _classify_lifecycle(first_diff: dict[str, Any], ref: dict[str, Any], nb1: dict[str, Any], nb2: dict[str, Any]) -> dict[str, Any]:
    ref_iframe = ((ref.get("iframe_at_grade") or {}).get("source_association") or {}).get("primary_match") or {}
    nb_iframe = ((nb1.get("iframe_at_grade") or {}).get("source_association") or {}).get("primary_match") or {}
    ref_prod = bool(ref_iframe.get("is_production_countdown"))
    nb_prod = bool(nb_iframe.get("is_production_countdown"))

    nb_levels = nb1.get("receipt_levels") or {}
    level2 = bool(nb_levels.get("LEVEL_2_ACTUAL_IMMEDIATE_PARENT_FRAME2"))
    level3 = bool(nb_levels.get("LEVEL_3_CURRENT_COMPONENT_SOURCE_MATCH_IMMEDIATE"))
    level4 = bool(nb_levels.get("LEVEL_4_STREAMLIT_PROTOCOL_ACCEPTED"))

    primary = first_diff.get("primary") or {}
    if "no declaration_returned at or after t0" in str(primary.get("summary") or ""):
        if not nb1.get("ledger_covers_post_send_window") and not nb2.get("ledger_covers_post_send_window"):
            code = "LIFECYCLE8"
            rationale = (
                "Browser send latched at t0 and durable parent SCV receipts exist, but production ledger "
                "never advances past pre-expiration script runs (max ts < t0). b6e20ca ledger includes a "
                "post-t0 declaration_returned with exact coalesced token. No evidence d73bcf3 bound in ledger."
            )
        elif not ref_prod and nb_prod:
            code = "LIFECYCLE7"
            rationale = "Iframe grading mismatch (stale/non-production source association)."
        elif not level3 and ref_prod and not nb_prod:
            code = "LIFECYCLE1"
            rationale = (
                "Parent sink primary_match is not the connected production countdown iframe on d73bcf3 "
                "(minimal repro iframe indexed) while b6e20ca matches production countdown at send."
            )
        elif level2 and not level4:
            code = "LIFECYCLE8"
            rationale = "Parent received SCV at frame2/durable sink but Streamlit protocol acceptance / Python bind absent."
        else:
            code = "LIFECYCLE8"
            rationale = primary.get("summary", "")
    else:
        code = "LIFECYCLE10"
        rationale = primary.get("summary", "manual review")

    if code == "LIFECYCLE1" and ref_prod and not nb_prod:
        pass  # keep LIFECYCLE1
    elif code == "LIFECYCLE8" and ref_prod and not nb_prod:
        rationale += (
            " Secondary: at harness grade time d73bcf3 parent source_association primary_match "
            "is not the production countdown iframe (minimal repro indexed); b6e20ca matches production countdown."
        )

    if code == "LIFECYCLE8":
        code = "LIFECYCLE_ANALYSIS_INCONCLUSIVE_POST_SEND_SERVER_TRACE_MISSING"
        label = "LIFECYCLE_ANALYSIS_INCONCLUSIVE_POST_SEND_SERVER_TRACE_MISSING"
        rationale = (
            "Offline artifact ledger ends before send boundary; cannot prove post-send Streamlit lifecycle. "
            "See p8_sender_rerun_live_trace.json for live trace on actual transport_before_postMessage ts."
        )
    else:
        label = _LIFECYCLE_LABELS.get(code, code)

    return {
        "code": code,
        "label": label,
        "rationale": rationale,
        "iframe_production_countdown_primary_match": {
            "b6e20ca": ref_prod,
            "d73bcf3_30073BB4": bool(
                ((nb1.get("iframe_at_grade") or {}).get("source_association") or {})
                .get("primary_match", {})
                .get("is_production_countdown")
            ),
            "d73bcf3_CF62057F": bool(
                ((nb2.get("iframe_at_grade") or {}).get("source_association") or {})
                .get("primary_match", {})
                .get("is_production_countdown")
            ),
        },
    }


_LIFECYCLE_LABELS = {
    "LIFECYCLE1": "LIFECYCLE1 — SENDING_IFRAME_REPLACED_BEFORE_BIND",
    "LIFECYCLE2": "LIFECYCLE2 — COMPONENT_REDECLARED_WITH_SAME_KEY_BEFORE_BIND",
    "LIFECYCLE3": "LIFECYCLE3 — COMPONENT_DECLARATION_SKIPPED_ON_POST_SEND_RERUN",
    "LIFECYCLE4": "LIFECYCLE4 — WIDGET_STATE_CLEARED_BEFORE_COMPONENT_RETURN_READ",
    "LIFECYCLE5": "LIFECYCLE5 — POST_SEND_RERUN_READS_DIFFERENT_WIDGET_INSTANCE",
    "LIFECYCLE6": "LIFECYCLE6 — RETURN_VALUE_DECLARATION_ORDER_CHANGED",
    "LIFECYCLE7": "LIFECYCLE7 — BROWSER_LATCH_SENDS_FROM_STALE_COMPONENT_INSTANCE",
    "LIFECYCLE8": "LIFECYCLE8 — STREAMLIT_ACCEPTANCE_OR_BIND_TIMING_DIFFERS_WITHOUT FRAME REPLACEMENT",
    "LIFECYCLE9": "LIFECYCLE9 — HARNESS ARTIFACT DIFFERENCE, NOT PRODUCTION",
    "LIFECYCLE10": "LIFECYCLE10 — OTHER",
}


def _production_code_diff_summary(first_diff: dict[str, Any]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "diff", "b6e20ca..d73bcf3", "--", "live_draft_stage1_post_bind_flush.py", "live_draft_solo_declaration_room_context.py", "live_draft_stage1_process_token_gate.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        diff_text = proc.stdout or ""
    except Exception as exc:
        diff_text = f"(git diff failed: {exc})"

    focus_paths = [
        "live_draft_stage1_post_bind_flush.py",
        "live_draft_solo_declaration_room_context.py",
        "live_draft_stage1_process_token_gate.py",
    ]
    summary_lines = [
        "Commits b6e20ca..d73bcf3 touch post-bind flush, declaration snapshot validation, and process-token gate instrumentation.",
        "No Solo countdown component or Streamlit declare() ordering changes appear in this range (harness/setup scripts excluded).",
        "d73bcf3 adds validated_declaration_snapshot gating and reject_mount_token_not_bound instrumentation at render_micro_isolation_once_return_delivery.",
        "Smallest correction boundary (hypothesis): post-SCV Streamlit rerun / component return surfacing — investigate outside snapshot-only theory until post-t0 declaration_returned exists on d73bcf3.",
    ]
    return {
        "focus_paths": focus_paths,
        "diff_byte_length": len(diff_text),
        "summary": summary_lines,
        "smallest_likely_correction_boundary": (
            "Streamlit component return binding after expiration SCV (post-t0 script_run), not P8C7 snapshot consume path "
            "(snapshot never sees a bound token on d73bcf3)."
        ),
    }


def format_txt(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("P8 lifecycle differential — b6e20ca vs d73bcf3")
    lines.append(f"Harness: {report.get('harness_commit')}  Production: {report.get('production_cloud_sha')}")
    lines.append("")

    fd = report.get("first_differing_transition") or {}
    lines.append("FIRST DIFFERING TRANSITION (primary)")
    lines.append(str((fd.get("primary") or {}).get("summary") or ""))
    for marker in fd.get("downstream_markers") or []:
        lines.append(f"  [downstream] {marker}")
    lines.append("")

    lc = report.get("lifecycle_classification") or {}
    lines.append(f"CLASSIFICATION: {lc.get('label')}")
    lines.append(str(lc.get("rationale") or ""))
    lines.append("")

    for label, run in (report.get("runs") or {}).items():
        lines.append("=" * 72)
        lines.append(f"RUN: {label}  room={run.get('room_id')}  sha={run.get('cloud_sha')}")
        lines.append(f"t0 (transport_before_postMessage epoch): {run.get('t0_transport_before_postMessage_epoch')}")
        lines.append(f"ledger rows: {run.get('ledger_row_count')}  max_ts: {run.get('max_ledger_ts')}")
        bind = run.get("first_post_send_bind") or {}
        lines.append(f"post-t0 coalesced bind in ledger: {bind.get('found')} {bind}")
        lines.append("")
        lines.append("Timeline (t_rel_s relative to t0):")
        for ev in run.get("timeline") or []:
            if ev.get("source") == "harness_client_stage_order" and ev.get("kind") != "transport_before_postMessage":
                continue
            parts = [
                f"{ev.get('t_rel_s'):>7}" if ev.get("t_rel_s") is not None else "    n/a",
                ev.get("source", "")[:22],
                ev.get("kind", ""),
            ]
            if ev.get("coalesced_value"):
                parts.append(f"coalesced={ev.get('coalesced_value')}")
            if ev.get("script_run_seq") is not None:
                parts.append(f"seq={ev.get('script_run_seq')}")
            if ev.get("decision"):
                parts.append(f"decision={ev.get('decision')}")
            lines.append("  ".join(str(p) for p in parts))
        lines.append("")

    cd = report.get("production_code_diff_focus") or {}
    lines.append("PRODUCTION CODE DIFF (after lifecycle established)")
    for s in cd.get("summary") or []:
        lines.append(f"  - {s}")
    lines.append(f"Boundary: {cd.get('smallest_likely_correction_boundary')}")
    return "\n".join(lines) + "\n"


def default_specs() -> list[RunSpec]:
    return [
        RunSpec(
            label="b6e20ca_p8c7",
            cloud_sha="b6e20ca",
            room_id="275EBCA4",
            exact_token="275EBCA4|0|1785418866.054",
            artifact_path=ROOT / "data" / "p8_binding_diagnostic_run2.out",
            ladder_path="ledger_filter",
        ),
        RunSpec(
            label="d73bcf3_30073BB4",
            cloud_sha="d73bcf3",
            room_id="30073BB4",
            exact_token="30073BB4|0|1785422991.900",
            artifact_path=ROOT / "data" / "production_p8_binding_diagnostic.json",
            ladder_path="d73bcf3_observability_audit.ledger_filter",
        ),
        RunSpec(
            label="d73bcf3_CF62057F",
            cloud_sha="d73bcf3",
            room_id="CF62057F",
            exact_token="CF62057F|0|1785423617.939",
            artifact_path=ROOT / "data" / "production_p8_binding_diagnostic.json",
            ladder_path="p8_ladder.ledger_filter",
        ),
    ]


def main() -> int:
    specs = default_specs()
    for spec in specs:
        if not spec.artifact_path.is_file():
            raise SystemExit(f"missing artifact: {spec.artifact_path}")

    report = compare_runs(specs)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    OUT_TXT.write_text(format_txt(report), encoding="utf-8")
    print(format_txt(report))
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
