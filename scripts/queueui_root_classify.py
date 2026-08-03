"""Classify QUEUEUI root cause from predicate audit ledger rows."""

from __future__ import annotations

from typing import Any

QUEUEUIROOT1 = "QUEUEUIROOT1 — START-IN-FLIGHT FLAG NEVER CLEARED AFTER SUCCESSFUL ROOM CREATION"
QUEUEUIROOT2 = "QUEUEUIROOT2 — AUTHENTICATED BROWSER SESSION NOT RECOGNIZED ON POST-START RERUN"
QUEUEUIROOT3 = "QUEUEUIROOT3 — STALE AUTH_REQUIRED RESTORE BLOCK REMAINS DESPITE VALID AUTHENTICATION"
QUEUEUIROOT4 = "QUEUEUIROOT4 — ROOM OWNERSHIP/ACCESS CHECK REJECTS THE ACTIVE SOLO ROOM"
QUEUEUIROOT5 = "QUEUEUIROOT5 — LIFECYCLE REPORTS ACTIVE BUT FULL-BODY PREDICATE USES DIFFERENT STATE"
QUEUEUIROOT6 = "QUEUEUIROOT6 — FULL BODY ENTERED, BUT AN EARLY RETURN SUPPRESSES CONTROLS"
QUEUEUIROOT7 = "QUEUEUIROOT7 — FULL BODY DECLARATIONS EXECUTED, BUT FRONT-END MOUNT/SCRAPE MISSED THEM"
QUEUEUIROOT8 = "QUEUEUIROOT8 — OTHER"

EVENT = "production_stage1_queueui_predicate_audit"


def row_auth(row: dict[str, Any]) -> dict[str, Any]:
    a = row.get("auth")
    return dict(a) if isinstance(a, dict) else {}


def row_restore(row: dict[str, Any]) -> dict[str, Any]:
    r = row.get("restore")
    return dict(r) if isinstance(r, dict) else {}


def audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("event") or "") == EVENT]


def rows_by_script_seq(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for r in audit_rows(rows):
        seq = int(r.get("script_run_seq") or 0)
        if seq <= 0:
            continue
        out.setdefault(seq, []).append(r)
    return out


def checkpoints_seen(seq_rows: list[dict[str, Any]]) -> set[str]:
    seen: set[str] = set()
    for r in seq_rows:
        cp = str(r.get("checkpoint") or r.get("widget_key") or "")
        if cp:
            seen.add(cp)
    return seen


def _pred(row: dict[str, Any]) -> dict[str, Any]:
    p = row.get("predicates")
    return dict(p) if isinstance(p, dict) else {}


def classify_queueui_root(
    *,
    ledger_rows: list[dict[str, Any]],
    dom_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return classification from merged stage-1 ledger after room latch."""
    dom = dict(dom_observation or {})
    by_seq = rows_by_script_seq(ledger_rows)
    post_start_seqs = sorted(k for k in by_seq if k >= 1)
    timeline: list[dict[str, Any]] = []
    for seq in post_start_seqs[-6:]:
        seq_rows = by_seq[seq]
        cps = sorted(checkpoints_seen(seq_rows))
        last = seq_rows[-1] if seq_rows else {}
        p = _pred(last)
        auth = row_auth(last)
        restore = row_restore(last)
        timeline.append(
            {
                "script_run_seq": seq,
                "checkpoints": cps,
                "start_in_flight": p.get("start_in_flight"),
                "restore_blocked_reason": restore.get("restore_blocked_reason"),
                "authenticated": auth.get("authenticated"),
                "lifecycle": p.get("lifecycle"),
                "full_body_predicate": p.get("full_body_predicate"),
                "pause_control_predicate": p.get("pause_control_predicate"),
                "countdown_declaration_predicate": p.get("countdown_declaration_predicate"),
            }
        )

    handler_finish_rows = [
        r
        for r in audit_rows(ledger_rows)
        if str(r.get("checkpoint") or "").startswith("start_handler")
        or str(r.get("widget_key") or "").startswith("start_handler")
    ]
    post_latch = [t for t in timeline if "active_lifecycle_branch_entered" in t["checkpoints"]]

    if not audit_rows(ledger_rows):
        return {
            "classification": None,
            "reason": "insufficient_predicate_audit_events_for_root_classification",
            "timeline": timeline,
            "proven": False,
        }

    # Post-start passes with start_in_flight stuck true
    stuck = [t for t in post_latch if t.get("start_in_flight") is True]
    after_finish = any(
        "start_handler_after_finish_start" in checkpoints_seen([r]) for r in handler_finish_rows
    )
    if len(stuck) >= 2 and after_finish:
        for t in stuck:
            if t.get("checkpoints") and "timer_render_controls_entered" not in t["checkpoints"]:
                return {
                    "classification": QUEUEUIROOT1,
                    "reason": "start_in_flight_true_on_post_start_passes_without_control_center_checkpoint",
                    "timeline": timeline,
                    "proven": True,
                }

    unauth = [t for t in post_latch if t.get("authenticated") is False]
    if unauth:
        return {
            "classification": QUEUEUIROOT2,
            "reason": "authenticated_false_on_post_start_script_pass",
            "timeline": timeline,
            "proven": True,
        }

    stale_auth_rows = [
        r
        for r in audit_rows(ledger_rows)
        if str(row_restore(r).get("restore_blocked_reason") or "") == "auth_required"
        and row_auth(r).get("authenticated") is True
    ]
    if len(stale_auth_rows) >= 2:
        return {
            "classification": QUEUEUIROOT3,
            "reason": "auth_required_restore_block_while_authenticated",
            "timeline": timeline,
            "proven": True,
        }

    membership = any("membership_gate_block" in t["checkpoints"] for t in timeline)
    if membership:
        return {
            "classification": QUEUEUIROOT4,
            "reason": "membership_gate_early_return",
            "timeline": timeline,
            "proven": True,
        }

    any_room_body = any("room_body_entered" in t["checkpoints"] for t in post_latch)
    active_no_body = [
        t
        for t in post_latch
        if "active_lifecycle_branch_entered" in t["checkpoints"] and not any_room_body
    ]
    if active_no_body:
        return {
            "classification": QUEUEUIROOT5,
            "reason": "active_lifecycle_without_room_body_checkpoint",
            "timeline": timeline,
            "proven": True,
        }

    body_no_controls = [
        t
        for t in post_latch
        if "room_body_entered" in t["checkpoints"] and "timer_render_controls_entered" not in t["checkpoints"]
    ]
    if body_no_controls:
        return {
            "classification": QUEUEUIROOT6,
            "reason": "room_body_without_timer_render_controls",
            "timeline": timeline,
            "proven": True,
        }

    controls_pred_true = [
        t
        for t in post_latch
        if "timer_render_controls_entered" in t["checkpoints"] and t.get("pause_control_predicate") is True
    ]
    pause_dom = int(dom.get("pause_draft_count") or 0) >= 1
    if controls_pred_true and not pause_dom:
        return {
            "classification": QUEUEUIROOT7,
            "reason": "control_center_checkpoint_with_pause_predicate_true_but_dom_absent",
            "timeline": timeline,
            "proven": True,
        }

    defer_only = [
        t
        for t in post_latch
        if "heavy_paint_before_defer" in t["checkpoints"]
        and t.get("full_body_predicate")
        and not t.get("recommendation_predicate")
    ]
    if defer_only and not pause_dom:
        return {
            "classification": QUEUEUIROOT6,
            "reason": "heavy_paint_deferred_while_full_body_predicates_partial",
            "timeline": timeline,
            "proven": True,
        }

    return {
        "classification": QUEUEUIROOT8,
        "reason": "root_predicate_not_isolated_from_audit_rows",
        "timeline": timeline,
        "proven": False,
    }
