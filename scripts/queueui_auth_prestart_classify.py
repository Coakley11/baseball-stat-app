"""Classify pre-Start auth hydration failure (AUTH_PRESTART1–8)."""

from __future__ import annotations

from typing import Any

AUTH_PRESTART1 = "AUTH_PRESTART1 — Streamlit authentication was never hydrated before control render"
AUTH_PRESTART2 = "AUTH_PRESTART2 — browser restoration succeeded but _apply_authenticated_user() was not called"
AUTH_PRESTART3 = "AUTH_PRESTART3 — warm-workspace skip bypassed required hydration"
AUTH_PRESTART4 = "AUTH_PRESTART4 — disk-state application removed or replaced authentication"
AUTH_PRESTART5 = "AUTH_PRESTART5 — control rendered authenticated, but callback entered unauthenticated"
AUTH_PRESTART6 = "AUTH_PRESTART6 — authentication was cleared by a named mutation before snapshot capture"
AUTH_PRESTART7 = "AUTH_PRESTART7 — different Streamlit session or session object used at callback"
AUTH_PRESTART8 = "AUTH_PRESTART8 — other"


def _by_checkpoint(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if str(r.get("event") or "") != "production_stage1_auth_prestart_hydration":
            continue
        cp = str(r.get("checkpoint") or "")
        out.setdefault(cp, []).append(r)
    return out


def classify_auth_prestart_root(*, ledger_rows: list[dict[str, Any]]) -> dict[str, Any]:
    hydration = [r for r in ledger_rows if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"]
    before_ctrl = [
        r for r in ledger_rows if str(r.get("event") or "") == "production_stage1_auth_state_before_start_control"
    ]
    before_ctrl_last = before_ctrl[-1] if before_ctrl else {}
    callback = _by_checkpoint(hydration).get("start_callback_before_snapshot", [])
    callback_row = callback[-1] if callback else {}
    capture_rows = [r for r in ledger_rows if str(r.get("event") or "") == "production_stage1_auth_snapshot_capture"]
    capture = capture_rows[-1] if capture_rows else {}
    mutations = [r for r in ledger_rows if str(r.get("event") or "") == "production_stage1_auth_prestart_mutation"]
    warm = _by_checkpoint(hydration).get("prepare_workspace_warm_skip", [])
    warm_last = warm[-1] if warm else {}
    after_disk = _by_checkpoint(hydration).get("after_apply_baseball_disk_state", [])
    after_disk_last = after_disk[-1] if after_disk else {}
    apply_exit = _by_checkpoint(hydration).get("apply_authenticated_user_exit", [])

    classification = AUTH_PRESTART8
    detail = ""

    ctrl_auth = bool(before_ctrl_last.get("is_authenticated"))
    cb_auth = bool(callback_row.get("is_authenticated"))
    if before_ctrl_last and ctrl_auth and callback_row and not cb_auth:
        classification = AUTH_PRESTART5
        detail = "control_vs_callback_session_mismatch"
    elif before_ctrl_last and ctrl_auth and callback_row and cb_auth:
        detail = "control_and_callback_authenticated_capture_still_failed"
    elif before_ctrl_last and not ctrl_auth:
        if warm_last.get("hydration_skipped") and not apply_exit:
            classification = AUTH_PRESTART3
            detail = "warm_skip_no_apply_authenticated_user"
        elif after_disk_last.get("authenticated_before") and not after_disk_last.get("authenticated_after"):
            classification = AUTH_PRESTART4
            detail = "disk_apply_cleared_auth"
        else:
            classification = AUTH_PRESTART1
            detail = "never_hydrated_before_control"
    elif mutations and capture and not capture.get("capture_accepted"):
        classification = AUTH_PRESTART6
        detail = str(mutations[0].get("source_function") or mutations[0].get("key") or "mutation")
    elif callback_row and before_ctrl_last:
        if callback_row.get("session_object_id") != before_ctrl_last.get("session_object_id"):
            classification = AUTH_PRESTART7
            detail = "session_object_id_changed"
    elif capture and not capture.get("is_authenticated"):
        classification = AUTH_PRESTART1
        detail = str(capture.get("rejection_reason") or "unauthenticated_at_capture")

    return {
        "classification": classification,
        "detail": detail,
        "before_control": before_ctrl_last,
        "callback_before_snapshot": callback_row,
        "capture": capture,
        "mutation_count": len(mutations),
    }
