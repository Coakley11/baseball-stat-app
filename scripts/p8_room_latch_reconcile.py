"""Room latch reconciliation (harness) — LATCHREC1–8, timeline replay."""

from __future__ import annotations

from typing import Any

LATCHREC1 = "LATCHREC1 — ROOM LATCH ACTUALLY PASSED; CLASSIFIER USED LATER BUTTON FALSE"
LATCHREC2 = "LATCHREC2 — APPLICATION RUN-ID FILTER DROPPED LATCH ROWS"
LATCHREC3 = "LATCHREC3 — LATCH EXPORT OMITTED HANDLER/READ/DECLARATION ROWS"
LATCHREC4 = "LATCHREC4 — ROOM CREATED BUT LATER SERVER READ WAS NOT CAPTURED"
LATCHREC5 = "LATCHREC5 — ROOM CREATED THEN AUTH/RESTORE/CLEANUP CLEARED IT"
LATCHREC6 = "LATCHREC6 — ROOM AND SERVER STATE PERSISTED BUT UI/COUNTDOWN CORROBORATION WAS MISSED"
LATCHREC7 = "LATCHREC7 — ROOM CREATED BUT STATUS/PICK/DEADLINE BECAME INVALID"
LATCHREC8 = "LATCHREC8 — OTHER"

ACCEPTED_ROOM_CREATED = "ROOM_CREATED — ROOM_LATCH_RECONCILIATION_REQUIRED"

EVENT_ORDER = (
    "production_stage1_start_button_value",
    "production_stage1_start_handler_entered",
    "production_stage1_room_creation_entered",
    "production_stage1_room_creation_exited",
    "production_stage1_start_handler_exited",
    "production_stage1_handler_exit_session_state_proof",
    "production_stage1_room_state_write",
    "production_stage1_rerun_transition",
    "production_stage1_room_state_read",
    "production_live_draft_branch_canary",
    "production_global_script_run_canary",
    "production_stage1_room_state_restore",
    "production_stage1_room_state_clear",
    "production_countdown_declaration_pre",
    "production_countdown_declaration_post",
)


def _norm_room(v: Any) -> str:
    return str(v or "").strip().upper()


def _row_room(row: dict[str, Any]) -> str:
    for k in ("created_room_id", "room_id", "session_room_id", "local_created_room_id"):
        rid = _norm_room(row.get(k))
        if rid:
            return rid
    auth = row.get("authoritative_session_state") or {}
    if isinstance(auth, dict):
        return _norm_room(auth.get("session_room_id"))
    return ""


def merge_latch_rows_from_full_ledger(
    filtered: list[dict[str, Any]],
    full_rows: list[dict[str, Any]],
    *,
    application_diagnostic_run_id: str,
    created_room_id: str,
    click_ts: float = 0.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recover latch rows dropped by strict filter (run id / event name)."""
    app_run = str(application_diagnostic_run_id or "").strip()
    created = _norm_room(created_room_id)
    existing = {str(r.get("event_id") or f"{r.get('event')}:{r.get('ts')}") for r in filtered if isinstance(r, dict)}
    added: list[dict[str, Any]] = []
    for r in full_rows:
        if not isinstance(r, dict):
            continue
        ev = str(r.get("event") or "")
        if not ev.startswith("production_stage1_") and not ev.startswith("production_countdown_declaration"):
            continue
        if click_ts and float(r.get("ts") or 0) < click_ts - 0.25:
            continue
        row_run = str(r.get("run_id") or r.get("diagnostic_run_id") or "")
        if app_run and row_run and row_run != app_run:
            if created not in _row_room(r):
                continue
        if created and _row_room(r) not in ("", created) and _row_room(r) != created:
            if ev not in ("production_global_script_run_canary", "production_live_draft_branch_canary"):
                continue
        key = str(r.get("event_id") or f"{ev}:{r.get('ts')}")
        if key in existing:
            continue
        added.append(dict(r))
        existing.add(key)
    merged = sorted(filtered + added, key=lambda x: (float(x.get("ts") or 0), int(x.get("script_run_seq") or 0)))
    meta = {
        "filtered_before": len(filtered),
        "recovered_count": len(added),
        "merged_count": len(merged),
        "application_diagnostic_run_id": app_run,
    }
    return merged, meta


def server_latch_bundle_proven(
    *,
    filtered_ledger: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    created_room_id: str,
) -> dict[str, Any]:
    """Server-authoritative latch (button state ignored after handler success)."""
    created = _norm_room(created_room_id)
    out: dict[str, Any] = {"created_room_id": created, "checks": {}}
    if not created:
        out["ok"] = False
        return out

    handler_exits = [
        r
        for r in filtered_ledger
        if r.get("event") == "production_stage1_start_handler_exited"
        and _norm_room(r.get("created_room_id") or r.get("room_id")) == created
    ]
    proofs = [
        r
        for r in filtered_ledger
        if r.get("event") == "production_stage1_handler_exit_session_state_proof"
        and _norm_room(r.get("local_created_room_id") or r.get("room_id")) == created
    ]
    decl_post = [
        r
        for r in filtered_ledger
        if r.get("event") == "production_countdown_declaration_post"
        and _norm_room(r.get("room_id")) == created
    ]
    reads = [
        t
        for t in timeline
        if t.get("operation") == "read"
        and _norm_room(t.get("room_id_after")) == created
        and str(t.get("draft_status") or "").lower() == "in_progress"
    ]
    clears = [
        t
        for t in timeline
        if t.get("operation") == "clear"
        and _norm_room(t.get("room_id_before")) == created
    ]

    out["checks"] = {
        "handler_exited_with_room": bool(handler_exits),
        "handler_session_proof": bool(proofs),
        "countdown_declaration_post": bool(decl_post),
        "later_in_progress_read": bool(reads),
        "later_clear": bool(clears),
    }
    pick_ok = all(
        int(r.get("pick_index") or 0) == 0
        for r in handler_exits + proofs
        if r.get("pick_index") is not None
    ) or bool(reads and (reads[-1].get("pick_index") in (0, None)))
    deadline_ok = bool(
        handler_exits
        and (
            handler_exits[-1].get("deadline")
            or handler_exits[-1].get("deadline_token")
            or (proofs and (proofs[-1].get("deadline_token") or proofs[-1].get("session_deadline_token")))
        )
    ) or bool(reads and reads[-1].get("deadline_token"))

    out["checks"]["pick_index_zero"] = pick_ok
    out["checks"]["deadline_or_token"] = deadline_ok
    out["ok"] = (
        out["checks"]["handler_exited_with_room"]
        and (out["checks"]["handler_session_proof"] or out["checks"]["later_in_progress_read"])
        and not out["checks"]["later_clear"]
        and pick_ok
        and deadline_ok
        and (out["checks"]["countdown_declaration_post"] or out["checks"]["later_in_progress_read"])
    )
    return out


def classify_latch_reconciliation(
    *,
    verify_classification: dict[str, Any],
    server_bundle: dict[str, Any],
    filtered_meta: dict[str, Any] | None = None,
    final_scrape: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verify_code = str((verify_classification or {}).get("classification") or "")
    if verify_code.startswith("VERIFY1"):
        return {"classification": LATCHREC1, "room_latch_pass": True, "reason": "verify1_already"}

    if server_bundle.get("ok"):
        scrape = final_scrape or {}
        ui_room = _norm_room(scrape.get("room_id"))
        created = _norm_room(server_bundle.get("created_room_id"))
        if ui_room != created and not scrape.get("in_progress"):
            return {
                "classification": LATCHREC1,
                "room_latch_pass": True,
                "reason": "server_bundle_complete_ui_scrape_stale",
            }
        return {
            "classification": LATCHREC6,
            "room_latch_pass": True,
            "reason": "server_bundle_with_partial_ui",
        }

    rec = int((filtered_meta or {}).get("recovered_count") or 0)
    if rec > 0:
        return {"classification": LATCHREC2, "room_latch_pass": False, "reason": "rows_recovered_but_bundle_incomplete"}

    if server_bundle.get("checks", {}).get("later_clear"):
        return {"classification": LATCHREC5, "room_latch_pass": False, "reason": "later_clear"}

    if server_bundle.get("checks", {}).get("handler_exited_with_room") and not server_bundle.get("checks", {}).get(
        "later_in_progress_read"
    ):
        return {"classification": LATCHREC4, "room_latch_pass": False, "reason": "missing_post_read"}

    if server_bundle.get("checks", {}).get("handler_exited_with_room"):
        return {"classification": LATCHREC7, "room_latch_pass": False, "reason": "invalid_status_pick_deadline"}

    return {"classification": LATCHREC8, "room_latch_pass": False, "reason": verify_code or "unresolved"}


def build_room_timeline_rows(
    *,
    full_rows: list[dict[str, Any]],
    filtered_rows: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    harness_run_id: str = "",
    application_diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
    created_room_id: str = "",
) -> list[dict[str, Any]]:
    """Ordered export rows for artifact replay."""
    created = _norm_room(created_room_id)
    by_event: dict[str, list[dict[str, Any]]] = {}
    for src, label in ((filtered_rows, "latch_export"), (full_rows, "full_scrape")):
        for r in src:
            if not isinstance(r, dict):
                continue
            ev = str(r.get("event") or "")
            if not ev:
                continue
            if created and _row_room(r) not in ("", created) and _row_room(r) != created:
                if ev not in ("production_global_script_run_canary", "production_live_draft_branch_canary"):
                    continue
            row = {
                "event": ev,
                "ts": r.get("ts"),
                "script_run_seq": r.get("script_run_seq"),
                "harness_run_id": harness_run_id,
                "application_diagnostic_run_id": r.get("run_id") or r.get("diagnostic_run_id") or application_diagnostic_run_id,
                "streamlit_session_id": r.get("streamlit_session_id") or streamlit_session_id,
                "room_id": _row_room(r) or created,
                "room_status": r.get("room_status") or r.get("draft_status"),
                "pick_index": r.get("pick_index"),
                "deadline": r.get("deadline") or r.get("deadline_token"),
                "expected_token": r.get("expected_token"),
                "button_value": r.get("button_return_value"),
                "on_change_callback_armed": r.get("on_click_callback_armed"),
                "source": label,
            }
            by_event.setdefault(ev, []).append(row)

    for t in timeline:
        if not isinstance(t, dict):
            continue
        ev = str(t.get("event") or t.get("operation") or "")
        if not ev:
            continue
        by_event.setdefault(ev, []).append(
            {
                "event": ev,
                "ts": t.get("ts"),
                "script_run_seq": t.get("script_run_seq"),
                "harness_run_id": harness_run_id,
                "application_diagnostic_run_id": application_diagnostic_run_id,
                "streamlit_session_id": streamlit_session_id,
                "room_id": _norm_room(t.get("room_id_after") or t.get("room_id_before")) or created,
                "room_status": t.get("draft_status"),
                "pick_index": t.get("pick_index"),
                "deadline": t.get("deadline_token"),
                "expected_token": t.get("expected_token"),
                "button_value": None,
                "source": "room_state_timeline",
            }
        )

    ordered: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for ev in EVENT_ORDER:
        for row in sorted(by_event.get(ev, []), key=lambda x: float(x.get("ts") or 0)):
            key = f"{ev}:{row.get('ts')}:{row.get('script_run_seq')}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            ordered.append(row)
    for ev, rows in by_event.items():
        if ev in EVENT_ORDER:
            continue
        for row in sorted(rows, key=lambda x: float(x.get("ts") or 0)):
            ordered.append(row)
    return ordered


def replay_artifact_latch(artifact: dict[str, Any]) -> dict[str, Any]:
    """Replay D0FF6120-style artifact without rerunning Cloud."""
    setup = artifact.get("production_setup") or artifact.get("draft_start_validation") or {}
    harness_run_id = str(artifact.get("diagnostic_run_id") or "")
    app_run = str(setup.get("diagnostic_run_id") or setup.get("application_diagnostic_run_id") or "")
    if not app_run:
        for r in (setup.get("latch_ledger_export") or {}).get("rows") or []:
            app_run = str(r.get("run_id") or r.get("diagnostic_run_id") or "")
            if app_run:
                break
    created = _norm_room(setup.get("room_id") or setup.get("inferred_created_room_id"))
    full_count = int((setup.get("latch_ledger_export") or {}).get("row_count_full_scrape") or 0)
    filtered = list((setup.get("latch_ledger_export") or {}).get("rows") or [])
    timeline = list(setup.get("room_state_timeline") or [])
    server = server_latch_bundle_proven(filtered_ledger=filtered, timeline=timeline, created_room_id=created)
    latchrec = classify_latch_reconciliation(
        verify_classification=setup.get("verify_classification") or {},
        server_bundle=server,
        final_scrape=setup.get("authoritative_state") or {},
    )
    if server.get("ok") and not latchrec.get("room_latch_pass"):
        latchrec["room_latch_pass"] = True
        latchrec["classification"] = LATCHREC1
    return {
        "harness_run_id": harness_run_id,
        "application_diagnostic_run_id": app_run,
        "room_id": created,
        "streamlit_session_id": setup.get("streamlit_session_id") or "",
        "server_latch_bundle": server,
        "latch_reconciliation": latchrec,
        "room_latch_pass_reconciled": bool(latchrec.get("room_latch_pass")),
        "timeline_rows": build_room_timeline_rows(
            full_rows=[],
            filtered_rows=filtered,
            timeline=timeline,
            harness_run_id=harness_run_id,
            application_diagnostic_run_id=app_run,
            streamlit_session_id=str(setup.get("streamlit_session_id") or ""),
            created_room_id=created,
        ),
        "full_scrape_row_count": full_count,
        "filtered_row_count": len(filtered),
    }
