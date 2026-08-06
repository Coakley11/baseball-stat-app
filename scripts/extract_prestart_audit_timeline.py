"""Extract ordered pre-Start auth timeline from queueui_root_predicate_audit.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "data" / "queueui_root_predicate_audit.json"
ORDER = [
    "suite_sid_detection",
    "load_browser_auth_tokens",
    "restore_auth_session_entry",
    "restore_auth_session_exit",
    "apply_authenticated_user_entry",
    "apply_authenticated_user_exit",
    "prepare_workspace_warm_skip",
    "before_apply_baseball_disk_state",
    "after_apply_baseball_disk_state",
    "before_start_control_render",
    "production_stage1_auth_state_before_start_control",
    "start_callback_before_snapshot",
    "production_stage1_start_callback_entered",
    "production_stage1_auth_snapshot_capture",
    "production_stage1_auth_snapshot_before_rerun",
    "production_stage1_auth_snapshot_restore_attempt",
    "production_stage1_auth_snapshot_post_restore",
]


def main() -> int:
    d = json.loads(AUDIT.read_text(encoding="utf-8"))
    run_id = d.get("application_diagnostic_run_id", "")
    sid = d.get("streamlit_session_id", "")
    pre_payloads = d.get("pre_click_auth_payloads") or {}
    payload_rows: list[dict] = []
    if isinstance(pre_payloads, dict):
        by_ev = pre_payloads.get("payloads_by_event") or {}
        if isinstance(by_ev, dict):
            for _ev, rows in by_ev.items():
                if isinstance(rows, list):
                    payload_rows.extend(r for r in rows if isinstance(r, dict))

    rows: list[dict] = list(payload_rows)
    timeline = d.get("auth_snapshot_timeline") or []
    for t in timeline:
        if isinstance(t, dict):
            rows.append(t)
    # Also need prestart hydration from ledger - scan JSON for event_id pattern
    import re

    text = AUDIT.read_text(encoding="utf-8")
    # Naive: find blocks is hard; use ledger_summary post_start
    post = (d.get("post_start_ledger_summary") or d.get("ledger_summary") or {})
    print(json.dumps({"run_id": run_id, "session_id": sid, "prestart_class": d.get("auth_prestart_classification"), "snapshot_class": d.get("auth_snapshot_classification"), "room": d.get("room_id"), "queue_campaign": d.get("queue_campaign_ran"), "expiration": d.get("expiration_wait"), "stage1a_queue": d.get("stage1a_queue"), "pre_click_payload_rows": len(payload_rows)}, indent=2))
    # Parse merged from click proof - grep event rows in file with json.loads line by line won't work
    # Load full and find all dicts with event key in nested structures
    all_rows: list[dict] = list(rows)

    def walk(o: object) -> None:
        if isinstance(o, dict):
            if o.get("event") and str(o.get("event_id", "")).startswith(run_id):
                all_rows.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(d)
    all_rows.sort(key=lambda r: (float(r.get("ts") or 0), str(r.get("event_id") or "")))

    def pick_checkpoint(cp: str) -> dict | None:
        for r in all_rows:
            ev = str(r.get("event") or "")
            if ev == "production_stage1_auth_prestart_hydration" and str(r.get("checkpoint") or "") == cp:
                return r
        return None

    def pick_event(ev: str, *, seq: int | None = None) -> dict | None:
        matches = [r for r in all_rows if str(r.get("event") or "") == ev]
        if seq is not None:
            matches = [r for r in matches if int(r.get("script_run_seq") or 0) == seq]
        return matches[-1] if matches else None

    out = []
    for label in ORDER:
        if label == "production_stage1_auth_state_before_start_control":
            r = pick_event(label)
        elif label.startswith("production_stage1"):
            r = pick_event(label)
        elif label == "production_stage1_start_callback_entered":
            r = pick_event(label)
        else:
            r = pick_checkpoint(label)
        if r:
            out.append(_summarize(label, r))
    # pre-click before_start on seq 2 or 3
    before_starts = [r for r in all_rows if r.get("event") == "production_stage1_auth_state_before_start_control"]
    if before_starts:
        for r in before_starts[:3]:
            out.insert(0, _summarize("before_start_control(all_preclick)", r))
    print(json.dumps({"ordered_timeline": out, "total_auth_rows": len(all_rows)}, indent=2, default=str))
    return 0


def _summarize(label: str, r: dict) -> dict:
    prot = r.get("protected_keys") if isinstance(r.get("protected_keys"), dict) else {}
    return {
        "step": label,
        "event_id": r.get("event_id"),
        "script_run_seq": r.get("script_run_seq"),
        "streamlit_session_id": r.get("streamlit_session_id"),
        "session_object_id": r.get("session_object_id"),
        "suite_sid_present": r.get("suite_sid_present"),
        "session_flag_present": r.get("session_flag_present") or prot.get("session_flag_present"),
        "auth_user_id_present": r.get("auth_user_id_present") or prot.get("auth_user_id_present"),
        "auth_email_present": r.get("auth_email_present") or prot.get("auth_email_present"),
        "access_token_present": r.get("access_token_present") or prot.get("access_token_present"),
        "refresh_token_present": r.get("refresh_token_present") or prot.get("refresh_token_present"),
        "is_authenticated": r.get("is_authenticated"),
        "auth_session_complete": r.get("auth_session_complete"),
        "auth_hydration_source": r.get("auth_hydration_source"),
        "hydration_attempted": r.get("hydration_attempted"),
        "hydration_skipped": r.get("hydration_skipped"),
        "skip_or_failure_reason": r.get("skip_or_failure_reason") or r.get("rejection_reason"),
        "restore_blocked_reason": r.get("restore_blocked_reason"),
        "capture_accepted": r.get("capture_accepted"),
        "start_button_enabled": r.get("start_button_enabled"),
        "authenticated_before": r.get("authenticated_before"),
        "authenticated_after": r.get("authenticated_after"),
        "browser_tokens_loaded": r.get("browser_tokens_loaded"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
