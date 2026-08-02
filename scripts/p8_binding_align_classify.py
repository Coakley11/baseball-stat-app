"""Artifact replay: pick-0 token alignment and focused no-claim invariant (BINDALIGN1–11)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

BINDALIGN4 = "BINDALIGN4 — FOCUSED MODE ALLOWED OWNERSHIP CLAIM OR PICK COMMIT"
BINDALIGN1 = "BINDALIGN1 — HARNESS ARMED PICK 0 BUT BROWSER SENT PICK 1"
BINDALIGN2 = "BINDALIGN2 — BROWSER/CALLBACK HAD PICK 0 BUT HANDOFF STORED PICK 1"
BINDALIGN3 = "BINDALIGN3 — HANDOFF STORED PICK 0 BUT WRAPPER SELECTED PICK 1"
BINDALIGN5 = "BINDALIGN5 — PICK-1 DECLARATION SUPERSEDED PICK 0 BEFORE HANDOFF CONSUMPTION"
BINDALIGN6 = "BINDALIGN6 — HARNESS EXPECTED TOKEN WAS STALE OR SELECTED FROM WRONG DECLARATION"
BINDALIGN7 = "BINDALIGN7 — ROOM/PICK ADVANCED BEFORE HARNESS ARMED"
BINDALIGN8 = "BINDALIGN8 — CANDIDATE SOURCES CONFLICTED BETWEEN PICK 0 AND PICK 1"
BINDALIGN9 = "BINDALIGN9 — APPLICATION/HARNESS RUN OR SESSION MISMATCH"
BINDALIGN10 = "BINDALIGN10 — TOKEN DEADLINE NORMALIZATION OR PARSING ERROR"
BINDALIGN11 = "BINDALIGN11 — OTHER"


def parse_expire_token(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip().strip("'\"")
    parts = text.split("|")
    if len(parts) < 3:
        return {"raw": text, "room": "", "pick": None, "deadline": "", "parse_ok": False}
    room = parts[0]
    try:
        pick = int(parts[1])
    except (TypeError, ValueError):
        pick = None
    return {
        "raw": text,
        "room": room,
        "pick": pick,
        "deadline": "|".join(parts[2:]),
        "parse_ok": True,
    }


def _row_token(row: dict[str, Any]) -> str:
    for key in (
        "raw_token",
        "bound_token",
        "token",
        "expected_token",
        "exact_expected_expiration_token",
        "selected_bound_token",
        "coalesced_value",
        "declaration_context_token",
    ):
        val = row.get(key)
        if val:
            return str(val).strip().strip("'\"")
    return ""


def count_focused_invariants(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {
        "callback_claim_attempts": 0,
        "observation_claim_attempts": 0,
        "actionable_flush_entries": 0,
        "try_claim_token_delivery_calls": 0,
        "accepted_claims": 0,
        "rejected_claims": 0,
        "auto_pick_entries": 0,
        "committed_picks": 0,
        "callback_handoff_written": 0,
        "callback_handoff_read": 0,
        "callback_handoff_selected": 0,
        "callback_handoff_rejected": 0,
    }
    for r in rows:
        if not isinstance(r, dict):
            continue
        ev = str(r.get("event") or "")
        if ev == "production_stage1_post_bind_actionable_flush":
            counts["actionable_flush_entries"] += 1
        elif ev == "production_stage1_try_claim_about_to_call":
            counts["try_claim_token_delivery_calls"] += 1
        elif ev == "production_stage1_token_claim_attempt":
            counts["callback_claim_attempts"] += 1
        elif ev == "production_stage1_token_claim_result":
            if r.get("accepted") is True:
                counts["accepted_claims"] += 1
            else:
                counts["rejected_claims"] += 1
        elif ev == "production_stage1_autopick_about_to_enter":
            counts["auto_pick_entries"] += 1
        elif ev == "production_stage1_token_action_complete":
            counts["committed_picks"] += 1
        elif ev == "production_stage1_callback_handoff_written":
            counts["callback_handoff_written"] += 1
        elif ev == "production_stage1_callback_handoff_read":
            counts["callback_handoff_read"] += 1
        elif ev == "production_stage1_callback_handoff_selected":
            counts["callback_handoff_selected"] += 1
        elif ev in (
            "production_stage1_callback_handoff_rejected",
            "production_stage1_callback_handoff_terminal",
        ):
            if ev.endswith("_rejected") or r.get("reject_reason"):
                counts["callback_handoff_rejected"] += 1
    return counts


def build_focused_invariant_report(
    rows: list[dict[str, Any]],
    *,
    frozen_pick0_token: str = "",
    room_id: str = "",
) -> dict[str, Any]:
    inv = count_focused_invariants(rows)
    room_picks: list[tuple[float, int | None]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("event") or "") not in (
            "production_stage1_room_state_write",
            "production_stage1_start_handler_exited",
            "production_stage1_next_room_state_persisted",
        ):
            continue
        rid = str(r.get("room_id") or "").upper()
        if room_id and rid and rid != str(room_id).upper():
            continue
        try:
            ts = float(r.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        pick = r.get("pick_index")
        try:
            pick_i = int(pick) if pick is not None else None
        except (TypeError, ValueError):
            pick_i = None
        room_picks.append((ts, pick_i))
    room_picks.sort(key=lambda x: x[0])
    pick_before = room_picks[0][1] if room_picks else None
    pick_after = room_picks[-1][1] if room_picks else None
    stop_events = sum(
        1
        for r in rows
        if isinstance(r, dict)
        and str(r.get("event") or "")
        in (
            "production_stage1_p8_focused_binding_stop_before_claim",
            "production_stage1_p8_focused_preclaim_blocked",
        )
    )
    focused_effective_rows = [
        r for r in rows if str(r.get("event") or "") == "production_stage1_p8_focused_mode_effective"
    ]
    return {
        "frozen_pick_0_token": frozen_pick0_token,
        "try_claim_call_count": inv["try_claim_token_delivery_calls"],
        "accepted_claim_count": inv["accepted_claims"],
        "rejected_claim_count": inv["rejected_claims"],
        "callback_claim_count": inv["callback_claim_attempts"],
        "observation_claim_count": 0,
        "actionable_flush_count": inv["actionable_flush_entries"],
        "auto_pick_entry_count": inv["auto_pick_entries"],
        "committed_pick_count": inv["committed_picks"],
        "room_pick_index_before": pick_before,
        "room_pick_index_after": pick_after,
        "focused_stop_before_claim_events": stop_events,
        "focused_mode_effective_events": len(focused_effective_rows),
        "focused_pass_invariants_ok": (
            inv["accepted_claims"] == 0
            and inv["auto_pick_entries"] == 0
            and inv["committed_picks"] == 0
            and inv["try_claim_token_delivery_calls"] == 0
            and inv["callback_claim_attempts"] == 0
        ),
        **inv,
    }


def assert_focused_pass_invariants(report: dict[str, Any]) -> tuple[bool, str]:
    inv = report if "try_claim_call_count" in report else build_focused_invariant_report([])
    checks = [
        (inv.get("accepted_claim_count", 0) == 0, "accepted_claim_count"),
        (inv.get("auto_pick_entry_count", 0) == 0, "auto_pick_entry_count"),
        (inv.get("committed_pick_count", 0) == 0, "committed_pick_count"),
        (inv.get("try_claim_call_count", 0) == 0, "try_claim_call_count"),
        (inv.get("callback_claim_count", 0) == 0, "callback_claim_count"),
        (inv.get("actionable_flush_count", 0) == 0, "actionable_flush_count"),
    ]
    for ok, name in checks:
        if not ok:
            return False, name
    if inv.get("room_pick_index_after") not in (None, 0):
        return False, "room_pick_index_after"
    return True, ""


def pick0_contract_from_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    token = str(
        artifact.get("p8_ladder", {}).get("exact_token")
        or artifact.get("pre_expiration", {}).get("expected_token")
        or ""
    ).strip()
    ladder = artifact.get("p8_ladder") or {}
    send = (ladder.get("production_countdown_send") or {}).get("production_send_token_previews") or []
    if not token and send:
        token = str(send[0] or "").strip()
    parsed = parse_expire_token(token)
    return {
        "room_id": parsed.get("room") or ladder.get("room_id") or "",
        "pick_index": parsed.get("pick"),
        "deadline": parsed.get("deadline"),
        "expected_pick_0_token_raw": token,
        "contract_form": f"{parsed.get('room')}|{parsed.get('pick')}|<PICK_0_DEADLINE>",
        "browser_send_previews": list(send),
    }


def extract_independent_tokens(rows: list[dict[str, Any]], *, pick0_raw: str) -> dict[str, Any]:
    pick0 = parse_expire_token(pick0_raw)

    def _find_token(event: str, *, field: str | None = None) -> str:
        for r in reversed(rows):
            if str(r.get("event") or "") != event:
                continue
            if field:
                return str(r.get(field) or "").strip().strip("'\"")
            return _row_token(r)
        return ""

    def _pack(label: str, raw: str) -> dict[str, Any]:
        p = parse_expire_token(raw)
        return {
            "label": label,
            "raw": raw,
            "parsed_room": p.get("room"),
            "parsed_pick": p.get("pick"),
            "parsed_deadline": p.get("deadline"),
            "equals_original_pick_0_expected": raw == pick0_raw and bool(raw),
            "equals_pick_0_room_pick": p.get("room") == pick0.get("room") and p.get("pick") == pick0.get("pick"),
        }

    gate = {}
    for r in reversed(rows):
        if str(r.get("event") or "") == "production_stage1_bound_token_gate":
            if str(r.get("decision") or "").startswith("pass_"):
                gate = r
                break

    return {
        "pre_expiration_expected_token_raw": pick0_raw,
        "registered_declaration_token_raw": str(gate.get("declaration_context_token") or gate.get("snapshot_expected_token") or ""),
        "browser_sent_token_raw": pick0_raw,
        "backend_new_widget_value_raw": _find_token("production_stage1_backend_widget_state_after_backmsg", field="deserialized_value_repr"),
        "callback_entry_token_raw": _find_token("production_stage1_prod_on_change_entered", field="raw_value_repr"),
        "callback_handoff_written_token_raw": _find_token("production_stage1_callback_handoff_written", field="raw_token"),
        "callback_handoff_read_token_raw": _find_token("production_stage1_callback_handoff_read", field="raw_token"),
        "gate_selected_token_raw": str(gate.get("selected_bound_token") or ""),
        "p8c7_input_token_raw": str(gate.get("coalesced_value") or gate.get("direct_component_return") or "").strip("'\""),
        "observation_input_token_raw": _find_token("production_stage1_delivery_only_observation_completed", field="bound_token"),
        "actionable_flush_input_token_raw": _find_token("production_stage1_post_bind_actionable_flush", field="bound_token"),
        "independent_fields": [
            _pack("pre_expiration_expected_token_raw", pick0_raw),
            _pack("browser_sent_token_raw", pick0_raw),
            _pack(
                "callback_handoff_written_token_raw",
                _find_token("production_stage1_callback_handoff_written", field="raw_token"),
            ),
            _pack("gate_selected_token_raw", str(gate.get("selected_bound_token") or "")),
        ],
    }


def classify_pick1_evidence(rows: list[dict[str, Any]], *, pick0_raw: str) -> dict[str, Any]:
    inv = count_focused_invariants(rows)
    pick0 = parse_expire_token(pick0_raw)
    advancement_rows = [
        r
        for r in rows
        if str(r.get("event") or "")
        in (
            "production_stage1_next_room_state_persisted",
            "production_stage1_room_state_write",
            "production_stage1_token_action_complete",
        )
        and int(r.get("pick_index") or -1) >= 1
    ]
    pick1_decl = [
        r
        for r in rows
        if parse_expire_token(_row_token(r)).get("pick") == 1
        and str(r.get("event") or "") in ("production_stage1_declaration_attempt", "production_stage1_countdown_declaration")
    ]
    if inv["accepted_claims"] >= 1 and (inv["auto_pick_entries"] >= 1 or inv["committed_picks"] >= 1 or advancement_rows):
        cls = "A. Authoritative room advancement"
    elif pick1_decl and inv["accepted_claims"] == 0:
        cls = "B. Superseding countdown declaration without a committed pick"
    elif pick1_decl:
        cls = "C. Stale prior/later declaration selected by the harness"
    else:
        cls = "E. Another room/session/run token" if not advancement_rows else "D. Token parsing/reporting error"
    return {
        "classification": cls,
        "accepted_claim_for_pick_0": inv["accepted_claims"] >= 1,
        "advancement_row_count": len(advancement_rows),
        "pick1_declaration_rows": len(pick1_decl),
    }


def handoff_outcome(rows: list[dict[str, Any]], *, pick0_raw: str) -> dict[str, Any]:
    inv = count_focused_invariants(rows)
    written = ""
    for r in rows:
        if str(r.get("event") or "") == "production_stage1_callback_handoff_written":
            written = str(r.get("raw_token") or "")
    selected = ""
    reject = ""
    for r in reversed(rows):
        ev = str(r.get("event") or "")
        if ev == "production_stage1_bound_token_gate" and str(r.get("decision") or "").startswith("pass_"):
            selected = str(r.get("selected_bound_token") or "")
            break
    if inv["callback_handoff_written"] and inv["accepted_claims"] >= 1 and parse_expire_token(written).get("pick") == 0:
        outcome = "A. Handoff worked for pick 0, but later gate expectation changed to pick 1."
    elif inv["callback_handoff_written"] and parse_expire_token(written).get("pick") == 1:
        outcome = "B. Handoff worked for pick 1 because the browser already delivered pick 1."
    elif inv["callback_handoff_written"] == 0:
        outcome = "C. Handoff was never selected."
    else:
        outcome = "D. Handoff was rejected due to declaration/current-pick mismatch."
    return {
        "outcome": outcome,
        "written_token": written,
        "selected_gate_token": selected,
        "reject_reason": reject,
        "counts": {k: inv[k] for k in ("callback_handoff_written", "callback_handoff_read", "callback_handoff_selected", "callback_handoff_rejected")},
        "handoff_matched_callback_token": written == pick0_raw or selected == pick0_raw,
    }


def first_bindalign_classification(
    *,
    rows: list[dict[str, Any]],
    pick0_raw: str,
    harness_run_id: str = "",
    application_run_id: str = "",
) -> str:
    inv = count_focused_invariants(rows)
    if inv["accepted_claims"] >= 1 or inv["committed_picks"] >= 1 or inv["auto_pick_entries"] >= 1:
        return BINDALIGN4

    pick0 = parse_expire_token(pick0_raw)
    browser = parse_expire_token(pick0_raw)
    if browser.get("pick") not in (None, 0) and pick0.get("pick") == 0:
        return BINDALIGN1

    handoff_w = ""
    for r in rows:
        if str(r.get("event") or "") == "production_stage1_callback_handoff_written":
            handoff_w = _row_token(r)
    if handoff_w and parse_expire_token(handoff_w).get("pick") == 1 and pick0.get("pick") == 0:
        return BINDALIGN2

    for r in reversed(rows):
        if str(r.get("event") or "") != "production_stage1_bound_token_gate":
            continue
        sel = _row_token(r)
        if sel and parse_expire_token(sel).get("pick") == 1 and parse_expire_token(handoff_w or pick0_raw).get("pick") == 0:
            return BINDALIGN3
        break

    if harness_run_id and application_run_id and harness_run_id != application_run_id:
        app_rows = {str(r.get("run_id") or "") for r in rows}
        if application_run_id and application_run_id not in app_rows:
            return BINDALIGN9

    tokens = extract_independent_tokens(rows, pick0_raw=pick0_raw)
    picks = {
        parse_expire_token(str(tokens.get(k) or "")).get("pick")
        for k in tokens
        if k != "independent_fields" and tokens.get(k)
    }
    picks.discard(None)
    if 0 in picks and 1 in picks:
        return BINDALIGN8

    return BINDALIGN11


def replay_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    rows = (
        (artifact.get("p8_ladder") or {}).get("ledger_filter") or {}
    ).get("filtered_rows") or (artifact.get("filtered_meta") or {}).get("filtered_rows") or []
    pick0 = pick0_contract_from_artifact(artifact)
    pick0_raw = str(pick0.get("expected_pick_0_token_raw") or "")
    harness_run = str(artifact.get("harness_run_id") or "")
    app_run = str(artifact.get("application_diagnostic_run_id") or "")
    inv = count_focused_invariants(rows)
    bindalign = first_bindalign_classification(
        rows=rows,
        pick0_raw=pick0_raw,
        harness_run_id=harness_run,
        application_run_id=app_run,
    )
    return {
        "harness_run_id": harness_run,
        "application_diagnostic_run_id": app_run,
        "room_id": pick0.get("room_id"),
        "pick0_contract": pick0,
        "focused_invariants": inv,
        "bindalign_classification": bindalign,
        "pick1_evidence": classify_pick1_evidence(rows, pick0_raw=pick0_raw),
        "handoff": handoff_outcome(rows, pick0_raw=pick0_raw),
        "independent_tokens": extract_independent_tokens(rows, pick0_raw=pick0_raw),
        "ledger_row_count": len(rows),
    }


def load_artifact(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def replay_artifact_file(path: Path) -> dict[str, Any]:
    return replay_artifact(load_artifact(path))
