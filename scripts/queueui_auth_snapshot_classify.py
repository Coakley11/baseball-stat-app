"""Classify Start-arm auth snapshot failure (AUTH_SNAPSHOT1–8) from stage-1 ledger."""

from __future__ import annotations

from typing import Any

AUTH_EVENTS = (
    "production_stage1_auth_state_before_start_control",
    "production_stage1_auth_snapshot_capture",
    "production_stage1_auth_snapshot_before_rerun",
    "production_stage1_auth_snapshot_restore_attempt",
    "production_stage1_auth_snapshot_post_restore",
    "production_stage1_auth_state_mutation",
    "production_stage1_queueui_predicate_audit",
    "production_stage1_start_handler_exited",
)

AUTH_SNAPSHOT1 = "AUTH_SNAPSHOT1 — source Streamlit session was not authenticated before Start"
AUTH_SNAPSHOT2 = "AUTH_SNAPSHOT2 — valid auth existed but snapshot capture was rejected"
AUTH_SNAPSHOT3 = "AUTH_SNAPSHOT3 — snapshot was captured but lost before rerun"
AUTH_SNAPSHOT4 = "AUTH_SNAPSHOT4 — snapshot existed but was not restored"
AUTH_SNAPSHOT5 = "AUTH_SNAPSHOT5 — snapshot restore was rejected"
AUTH_SNAPSHOT6 = "AUTH_SNAPSHOT6 — auth restored successfully but was overwritten afterward"
AUTH_SNAPSHOT7 = "AUTH_SNAPSHOT7 — restored into a different Streamlit session or session object"
AUTH_SNAPSHOT8 = "AUTH_SNAPSHOT8 — other"


def _rows_by_event(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ev = str(r.get("event") or "")
        if ev:
            out.setdefault(ev, []).append(r)
    return out


def auth_snapshot_timeline_from_ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordered auth diagnostic timeline for reporting."""
    timeline: list[dict[str, Any]] = []
    for ev in AUTH_EVENTS:
        for r in _rows_by_event(rows).get(ev, []):
            timeline.append(
                {
                    "event": ev,
                    "script_run_seq": r.get("script_run_seq"),
                    "ts": r.get("ts"),
                    "streamlit_session_id": r.get("streamlit_session_id"),
                    "session_object_id": r.get("session_object_id"),
                    "capture_accepted": r.get("capture_accepted"),
                    "rejection_reason": r.get("rejection_reason"),
                    "restore_accepted": r.get("restore_accepted"),
                    "is_authenticated": r.get("is_authenticated"),
                    "authenticated_after_restore": r.get("authenticated_after_restore"),
                    "context": r.get("context"),
                    "checkpoint": r.get("checkpoint"),
                }
            )
    timeline.sort(key=lambda x: (float(x.get("ts") or 0), str(x.get("event") or "")))
    return timeline


def classify_auth_snapshot_root(
    *,
    ledger_rows: list[dict[str, Any]],
    auth_preflight_authenticated: bool | None = None,
    browser_suite_sid_present: bool | None = None,
) -> dict[str, Any]:
    by_ev = _rows_by_event(ledger_rows)
    before = (by_ev.get("production_stage1_auth_state_before_start_control") or [])[-1:]
    before = before[0] if before else {}
    capture_rows = by_ev.get("production_stage1_auth_snapshot_capture") or []
    capture = capture_rows[-1] if capture_rows else {}
    before_rerun = (by_ev.get("production_stage1_auth_snapshot_before_rerun") or [])[-1:]
    before_rerun = before_rerun[0] if before_rerun else {}
    restore_rows = by_ev.get("production_stage1_auth_snapshot_restore_attempt") or []
    restore = restore_rows[0] if restore_rows else {}
    post_restore_rows = [
        r
        for r in by_ev.get("production_stage1_auth_snapshot_post_restore") or []
        if "before_reconcile" in str(r.get("context") or "")
        or str(r.get("context") or "").startswith("live_draft_restore_allowed")
    ]
    post_restore = post_restore_rows[-1] if post_restore_rows else {}
    mutations = by_ev.get("production_stage1_auth_state_mutation") or []
    predicate_rows = [
        r
        for r in by_ev.get("production_stage1_queueui_predicate_audit") or []
        if str(r.get("checkpoint") or "") == "ldr_post_start_script_entry"
    ]
    earliest_pred = min(predicate_rows, key=lambda r: int(r.get("script_run_seq") or 999)) if predicate_rows else {}

    browser_auth = {
        "playwright_storage_loaded": auth_preflight_authenticated is not None,
        "provider_preflight_authenticated": bool(auth_preflight_authenticated),
        "suite_sid_present_reported": browser_suite_sid_present,
    }
    streamlit_auth = {
        "before_start_is_authenticated": before.get("is_authenticated"),
        "capture_accepted": capture.get("capture_accepted"),
        "before_rerun_is_authenticated": before_rerun.get("current_is_authenticated"),
        "restore_accepted": restore.get("restore_accepted"),
        "post_restore_is_authenticated": post_restore.get("is_authenticated"),
        "earliest_predicate_authenticated": (earliest_pred.get("auth") or {}).get("authenticated")
        if isinstance(earliest_pred.get("auth"), dict)
        else earliest_pred.get("is_authenticated"),
    }

    classification = AUTH_SNAPSHOT8
    detail = ""

    if before and not bool(before.get("is_authenticated")):
        classification = AUTH_SNAPSHOT1
        detail = "pre_start_control_not_authenticated"
    elif capture and capture.get("capture_attempted") and not capture.get("capture_accepted"):
        classification = AUTH_SNAPSHOT2
        detail = str(capture.get("rejection_reason") or "capture_rejected")
    elif capture.get("capture_accepted") and before_rerun and not before_rerun.get("snapshot_key_present"):
        classification = AUTH_SNAPSHOT3
        detail = "snapshot_missing_at_callback_exit"
    elif before_rerun.get("snapshot_key_present") and restore and not restore.get("restore_attempted"):
        classification = AUTH_SNAPSHOT4
        detail = "restore_not_attempted_despite_snapshot"
    elif restore.get("restore_attempted") and not restore.get("restore_accepted"):
        classification = AUTH_SNAPSHOT5
        detail = str(restore.get("rejection_reason") or "restore_rejected")
    elif restore.get("restore_accepted") and restore.get("same_streamlit_session_id") is False:
        classification = AUTH_SNAPSHOT7
        detail = "streamlit_session_id_mismatch"
    elif restore.get("restore_accepted") and bool(restore.get("authenticated_after_restore")):
        auth_pops = [
            m
            for m in mutations
            if m.get("operation") == "pop"
            and str(m.get("key") or "") in ("_suite_auth_session", "_suite_auth_tokens")
            and int(m.get("script_run_seq") or 0) >= int(restore.get("script_run_seq") or 0)
        ]
        if auth_pops and not bool(post_restore.get("is_authenticated")):
            classification = AUTH_SNAPSHOT6
            detail = f"auth_cleared_after_restore:{auth_pops[0].get('source_function')}"
        elif not bool(streamlit_auth.get("earliest_predicate_authenticated")):
            classification = AUTH_SNAPSHOT6
            detail = "authenticated_after_restore_but_predicate_false"
    elif earliest_pred and not (
        (earliest_pred.get("auth") or {}).get("authenticated")
        if isinstance(earliest_pred.get("auth"), dict)
        else earliest_pred.get("is_authenticated")
    ):
        classification = AUTH_SNAPSHOT8
        detail = "earliest_predicate_unauthenticated_no_prior_signal"

    return {
        "classification": classification,
        "detail": detail,
        "browser_provider_authentication": browser_auth,
        "streamlit_application_authentication": streamlit_auth,
        "timeline_event_count": len(auth_snapshot_timeline_from_ledger(ledger_rows)),
    }
