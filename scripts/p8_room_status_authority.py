"""Server-authoritative room status for harness latch replay (no app changes)."""

from __future__ import annotations

from typing import Any

LATCHSTATUS1 = "LATCHSTATUS1 — SERVER STATUS IN_PROGRESS; UI STATUS MISSING OR STALE"
LATCHSTATUS2 = "LATCHSTATUS2 — SERVER STATUS IN_PROGRESS; CLASSIFIER SELECTED WRONG ROW"
LATCHSTATUS3 = "LATCHSTATUS3 — STATUS NORMALIZATION REJECTED AN EQUIVALENT IN_PROGRESS VALUE"
LATCHSTATUS4 = "LATCHSTATUS4 — ROOM CREATED WITH NON-IN_PROGRESS STATUS"
LATCHSTATUS5 = "LATCHSTATUS5 — ROOM STARTED IN_PROGRESS THEN LATER STATUS CHANGED"
LATCHSTATUS6 = "LATCHSTATUS6 — AUTH/RESTORE OVERWROTE OR CLEARED ACTIVE STATUS"
LATCHSTATUS7 = "LATCHSTATUS7 — ROOM ID CAME FROM STALE OR FOREIGN ROOM EVIDENCE"
LATCHSTATUS8 = "LATCHSTATUS8 — APPLICATION/HARNESS RUN OR SESSION FILTER MISMATCH"
LATCHSTATUS9 = "LATCHSTATUS9 — ROOM ADVANCED OR TERMINATED BEFORE HARNESS ARMED"
LATCHSTATUS10 = "LATCHSTATUS10 — STATUS EVIDENCE MISSING FROM ALL AUTHORITATIVE SOURCES"
LATCHSTATUS11 = "LATCHSTATUS11 — OTHER"

_IN_PROGRESS = frozenset({"in_progress", "in-progress", "active", "live"})


def normalize_room_status(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return "missing"
    if s in _IN_PROGRESS:
        return "in_progress"
    return s


def _norm_room(v: Any) -> str:
    return str(v or "").strip().upper()


def _row_run(row: dict[str, Any]) -> str:
    return str(row.get("run_id") or row.get("diagnostic_run_id") or "").strip()


def _status_from_row(row: dict[str, Any]) -> str:
    auth = row.get("authoritative_session_state") or {}
    if isinstance(auth, dict):
        for k in ("session_draft_status", "draft_status", "room_status"):
            if auth.get(k) not in (None, ""):
                return normalize_room_status(auth.get(k))
    for k in ("session_draft_status", "draft_status", "room_status", "room_status_raw"):
        if row.get(k) not in (None, ""):
            return normalize_room_status(row.get(k))
    if row.get("draft_in_progress") is True:
        return "in_progress"
    if row.get("draft_in_progress") is False and row.get("event") == "production_stage1_surface_decision":
        return "setup"
    return "missing"


def _row_room(row: dict[str, Any]) -> str:
    for k in ("created_room_id", "room_id", "session_room_id", "local_created_room_id"):
        rid = _norm_room(row.get(k))
        if rid:
            return rid
    auth = row.get("authoritative_session_state") or {}
    if isinstance(auth, dict):
        return _norm_room(auth.get("session_room_id"))
    return ""


def _scoped_rows(
    rows: list[dict[str, Any]],
    *,
    room_id: str,
    application_diagnostic_run_id: str,
) -> list[dict[str, Any]]:
    rid = _norm_room(room_id)
    app = str(application_diagnostic_run_id or "").strip()
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rr = _row_room(r)
        if rid and rr and rr != rid:
            continue
        row_run = _row_run(r)
        if app and row_run and row_run != app:
            continue
        out.append(r)
    return out


def resolve_authoritative_room_status(
    *,
    ledger_rows: list[dict[str, Any]],
    timeline: list[dict[str, Any]] | None = None,
    room_id: str,
    application_diagnostic_run_id: str = "",
    ui_scrape: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Precedence: server read > handler proof > write > creation exit > canary > declaration > UI."""
    rid = _norm_room(room_id)
    scoped = _scoped_rows(ledger_rows, room_id=rid, application_diagnostic_run_id=application_diagnostic_run_id)
    ui = ui_scrape or {}
    candidates: list[dict[str, Any]] = []

    def add(source: str, raw: Any, row: dict[str, Any] | None = None) -> None:
        norm = normalize_room_status(raw)
        if norm == "missing":
            return
        candidates.append(
            {
                "source": source,
                "raw_status": str(raw or ""),
                "normalized_status": norm,
                "ts": float((row or {}).get("ts") or 0),
                "script_run_seq": (row or {}).get("script_run_seq"),
                "event": (row or {}).get("event"),
            }
        )

    for r in sorted(scoped, key=lambda x: float(x.get("ts") or 0)):
        ev = str(r.get("event") or "")
        if ev == "production_stage1_room_state_read":
            add("room_state_read", r.get("session_draft_status") or r.get("room_status"), r)
        elif ev == "production_stage1_handler_exit_session_state_proof":
            auth = r.get("authoritative_session_state") or {}
            add("handler_exit_session_state_proof", auth.get("session_draft_status") or r.get("room_status"), r)
        elif ev == "production_stage1_room_state_write":
            add("room_state_write", r.get("new_status") or r.get("room_status") or r.get("draft_status"), r)
        elif ev == "production_stage1_room_creation_exited":
            add("room_creation_exited", r.get("room_status") or r.get("draft_status"), r)
        elif ev == "production_live_draft_branch_canary":
            add("ldr_branch_canary", "in_progress" if r.get("draft_in_progress") else r.get("room_status"), r)
        elif ev.startswith("production_countdown_declaration"):
            add(str(r.get("event") or "declaration"), r.get("room_status") or r.get("draft_status") or "in_progress", r)

    for t in timeline or []:
        if not isinstance(t, dict):
            continue
        tr = _norm_room(t.get("room_id_after") or t.get("room_id_before"))
        if rid and tr and tr != rid:
            continue
        st = t.get("draft_status")
        if st:
            add("room_state_timeline", st, {"ts": t.get("ts"), "script_run_seq": t.get("script_run_seq"), "event": t.get("event")})

    if ui.get("in_progress"):
        add("ui_scrape", "in_progress", None)
    elif ui.get("room_id"):
        add("ui_scrape", "setup" if ui.get("setup_start_visible") else "missing", None)

    priority = [
        "room_state_read",
        "handler_exit_session_state_proof",
        "room_state_write",
        "room_creation_exited",
        "ldr_branch_canary",
        "production_countdown_declaration_post",
        "production_countdown_declaration_pre",
        "room_state_timeline",
        "ui_scrape",
    ]
    selected: dict[str, Any] | None = None
    for src in priority:
        for c in reversed(candidates):
            if c["source"] == src or src in c["source"]:
                selected = c
                break
        if selected:
            break
    if not selected and candidates:
        selected = candidates[-1]

    server_in_progress = any(
        c["normalized_status"] == "in_progress"
        for c in candidates
        if c["source"] != "ui_scrape"
    )
    ui_norm = normalize_room_status("in_progress" if ui.get("in_progress") else "")
    if ui.get("room_id") and not ui.get("in_progress"):
        ui_norm = "setup" if ui.get("setup_start_visible") else "missing"

    return {
        "room_id": rid,
        "application_diagnostic_run_id": application_diagnostic_run_id,
        "raw_status": selected.get("raw_status") if selected else "",
        "normalized_status": selected.get("normalized_status") if selected else "missing",
        "status_source": selected.get("source") if selected else "",
        "status_in_progress_server": server_in_progress,
        "ui_status_normalized": ui_norm,
        "candidates": candidates,
        "selected": selected,
    }


def classify_latch_status_boundary(
    *,
    status_resolution: dict[str, Any],
    room_latch_pass: bool,
    ledger_rows: list[dict[str, Any]],
    timeline: list[dict[str, Any]] | None,
    room_id: str,
    application_diagnostic_run_id: str,
    harness_run_id: str = "",
    ui_scrape: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ui = ui_scrape or {}
    rid = _norm_room(room_id)
    srv = bool(status_resolution.get("status_in_progress_server"))
    sel_norm = str(status_resolution.get("normalized_status") or "missing")
    ui_norm = str(status_resolution.get("ui_status_normalized") or "missing")

    scoped = _scoped_rows(ledger_rows, room_id=rid, application_diagnostic_run_id=application_diagnostic_run_id)
    app_rows = [r for r in ledger_rows if _row_run(r) == application_diagnostic_run_id]
    harness_only_dropped = bool(
        application_diagnostic_run_id
        and harness_run_id
        and application_diagnostic_run_id != harness_run_id
        and len(scoped) < len([r for r in ledger_rows if _row_room(r) == rid])
    )

    creation = [r for r in scoped if r.get("event") == "production_stage1_room_creation_exited"]
    first_create_status = normalize_room_status(
        (creation[0].get("room_status") or creation[0].get("draft_status")) if creation else ""
    )

    later_non_ip = [
        c
        for c in status_resolution.get("candidates") or []
        if c.get("source") != "ui_scrape"
        and c.get("normalized_status") not in ("in_progress", "missing")
        and float(c.get("ts") or 0) > float((status_resolution.get("selected") or {}).get("ts") or 0)
    ]

    audit = {
        "room_latch_pass": room_latch_pass,
        "status_in_progress_server": srv,
        "selected_normalized_status": sel_norm,
        "ui_status_normalized": ui_norm,
        "harness_run_id": harness_run_id,
        "application_diagnostic_run_id": application_diagnostic_run_id,
        "harness_only_filter_mismatch_suspected": harness_only_dropped,
    }

    if harness_only_dropped and not scoped:
        return _out(LATCHSTATUS8, audit, "application_rows_dropped_by_harness_run_filter")

    if not srv and sel_norm == "missing" and not creation:
        return _out(LATCHSTATUS10, audit, "no_status_evidence")

    if first_create_status not in ("missing", "in_progress", "") and creation:
        return _out(LATCHSTATUS4, audit, f"creation_status_{first_create_status}")

    if srv and later_non_ip:
        return _out(LATCHSTATUS5, audit, f"later_status_{later_non_ip[-1].get('normalized_status')}")

    first_ip_ts = 0.0
    for c in status_resolution.get("candidates") or []:
        if c.get("normalized_status") == "in_progress" and c.get("source") != "ui_scrape":
            first_ip_ts = max(first_ip_ts, float(c.get("ts") or 0))

    for t in timeline or []:
        if float(t.get("ts") or 0) <= first_ip_ts:
            continue
        if t.get("operation") == "clear" and _norm_room(t.get("room_id_before")) == rid:
            return _out(LATCHSTATUS6, audit, "room_state_clear_after_in_progress")
        inf = t.get("preserve_inference") or {}
        if t.get("operation") == "restore" and inf.get("inferred_clear_foreign_likely"):
            after = _norm_room(t.get("room_id_after"))
            if after != rid:
                return _out(LATCHSTATUS6, audit, "auth_restore_clear_after_in_progress")

    if srv and ui_norm != "in_progress":
        if room_latch_pass:
            return _out(LATCHSTATUS1, audit, "server_in_progress_ui_stale")
        return _out(LATCHSTATUS1, audit, "server_in_progress_ui_not_corroborated")

    if srv and sel_norm != "in_progress":
        return _out(LATCHSTATUS2, audit, "wrong_row_selected")

    if room_latch_pass and not srv:
        return _out(LATCHSTATUS10, audit, "latch_pass_contradicts_server_status")

    return _out(LATCHSTATUS11, audit, "unmapped")


def merge_ui_with_server_status(
    ui_scrape: dict[str, Any],
    status_resolution: dict[str, Any],
) -> dict[str, Any]:
    """Overlay server in_progress onto scrape for start boundary (does not mutate app)."""
    merged = dict(ui_scrape)
    if status_resolution.get("status_in_progress_server"):
        merged["in_progress"] = True
        merged["room_status_authoritative"] = status_resolution.get("normalized_status")
        merged["room_status_source"] = status_resolution.get("status_source")
        merged["room_status_raw"] = status_resolution.get("raw_status")
    else:
        merged["room_status_authoritative"] = status_resolution.get("normalized_status") or "missing"
        merged["room_status_source"] = status_resolution.get("status_source") or ""
        merged["room_status_raw"] = status_resolution.get("raw_status") or ""
    return merged


def _out(code: str, audit: dict[str, Any], detail: str) -> dict[str, Any]:
    return {"classification": code, "detail": detail, "audit": audit, "supersedes_start9d": code == LATCHSTATUS1}
