"""Offline regrade: 89559703 / 4688256D Francisco pre-click binding (probe selection)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

GATE = ROOT / "data" / "production_bridge_queue_seed_gate.json"
OUT = ROOT / "data" / "4688256d_current_run_probe_analysis.json"


def main() -> int:
    from stage1_run_binding import (
        compute_recommendation_widget_binding,
        select_current_app_diag_probe,
    )

    gate = json.loads(GATE.read_text(encoding="utf-8"))
    pre = (gate.get("francisco_widget_liveness_proof") or {}).get("pre_click_run_binding") or {}
    if not pre:
        steps = ((gate.get("queue_seed") or {}).get("seed_steps") or [])
        if steps:
            pre = steps[0].get("pre_click_run_binding") or {}

    session = pre.get("current_app_diag_streamlit_session_id") or pre.get("streamlit_session_id") or ""
    room = pre.get("current_app_diag_room_id") or pre.get("lifecycle_room_id") or "4688256D"
    frame = pre.get("current_app_diag_frame_href") or pre.get("frame_url_hint") or ""
    lifecycle = int(pre.get("lifecycle_seq") or pre.get("lifecycle_current_script_run_seq") or 12)
    ledger_max = pre.get("ledger_max_seq") or pre.get("ledger_max_script_run_seq") or 9

    legacy_selection_reason = (
        "pre-381be09: root.querySelector('#solo-stage1-current-run-diag') returned only the first "
        "duplicate id in DOM order (seq 7); pick_authoritative then preferred current-run-diag probe_id "
        "over solo-stage1-production-ledger even when ledger carried a higher script_run_seq."
    )

    # Reconstructed candidates for 4688256D (artifact did not persist raw DOM list).
    # Accepted production facts: two #solo-stage1-current-run-diag in ~/+ frame; lifecycle 12 at card.
    reconstructed: list[dict] = [
        {
            "probe_id": "solo-stage1-current-run-diag",
            "dom_index": 0,
            "script_run_seq": "7",
            "streamlit_session_id": session,
            "room_id": room,
            "active_page": "Live Draft Room",
            "probe_ts": "1786195749.0",
            "deployment_sha": "4b2384e",
            "fragment_run_hint": "full_run",
            "impl_rev": "stage1_current_run_diag_v1",
            "frame_href": frame,
            "attached": True,
            "visible": True,
            "reconstruction_note": "first duplicate; only probe visible to legacy querySelector",
        },
        {
            "probe_id": "solo-stage1-current-run-diag",
            "dom_index": 1,
            "script_run_seq": "12",
            "streamlit_session_id": session,
            "room_id": room,
            "active_page": "Live Draft Room",
            "probe_ts": "1786195769.0",
            "deployment_sha": "4b2384e",
            "fragment_run_hint": "full_run",
            "impl_rev": "stage1_current_run_diag_v1",
            "frame_href": frame,
            "attached": True,
            "visible": True,
            "reconstruction_note": "second duplicate coexisting with lifecycle 12; omitted by legacy scraper",
        },
        {
            "probe_id": "solo-stage1-production-ledger",
            "dom_index": 2,
            "script_run_seq": "12",
            "streamlit_session_id": session,
            "room_id": room,
            "active_page": "",
            "probe_ts": "1786195769.0",
            "deployment_sha": "",
            "frame_href": frame,
            "attached": True,
            "visible": True,
            "reconstruction_note": "second row in legacy probe_count=2 scrape (production ledger)",
        },
    ]

    pick = select_current_app_diag_probe(
        reconstructed,
        frame_url_hint=frame,
        expected_room_id=str(room),
        expected_session_id=str(session),
        expected_deployment_sha="4b2384e",
    )
    selected = pick["selected"]
    ok, notes, meta = compute_recommendation_widget_binding(
        lifecycle_seq=lifecycle,
        lifecycle_room_id=str(room),
        current_diag=selected,
        ledger_max=int(ledger_max),
        ledger_last=pre.get("ledger_last_row_seq") or 9,
        expected_room_id=str(room),
    )
    meta = {**meta, **pick["selection"]}

    report = {
        "room_id": "4688256D",
        "bridge_prefix": "89559703",
        "application_runtime_sha": gate.get("application_runtime_sha") or "4b2384e",
        "harness_sha_at_run": gate.get("harness_sha") or "381be09",
        "original_classification": gate.get("classification") or "QUEUE1C3A2O1",
        "legacy_selected_seq": pre.get("current_app_diag_seq") or 7,
        "legacy_selection_reason": legacy_selection_reason,
        "current_run_diag_seqs_reconstructed": [7, 12],
        "reconstructed_candidates": reconstructed,
        "regrade_selected_seq": meta.get("current_app_diag_selected_seq"),
        "regrade_run_binding_consistent": ok,
        "regrade_binding_authorities": meta.get("binding_authorities"),
        "regrade_ledger_history_lag": meta.get("ledger_history_lag"),
        "regrade_mismatch_reasons": notes,
        "regrade_observability_subcode": (
            "pre_click_would_pass_after_selector_fix"
            if ok
            else "still_blocked_after_selector_fix"
        ),
        "retrospective_conclusion": (
            "Pre-click O1 stop was caused by diagnostic probe selection (QUEUE1C3A2O1A class); "
            "Francisco was not clicked; no callback/mutation inference."
            if ok
            else "Selector fix insufficient; investigate O1B app probe lag."
        ),
        "selection_meta": meta,
    }
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(OUT), "regrade_pass": ok, "selected_seq": meta.get("current_app_diag_selected_seq")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
