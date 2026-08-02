"""Replay focused setup artifact 8b51ead — room status timeline and LATCHSTATUS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

HARNESS_RUN_ID = "8b51ead096e040dd"
APP_RUN_ID = "9a346d731566454a"
ROOM_ID = "75287EC1"


def load_8b51ead_artifact(path: Path | None = None) -> dict[str, Any]:
    p = path or (ROOT / "data" / "production_p8_binding_diagnostic.json")
    return json.loads(p.read_text(encoding="utf-8"))


def replay_8b51ead_setup(path: Path | None = None) -> dict[str, Any]:
    import sys

    sys.path.insert(0, str(SCRIPTS))
    from p8_pre_expiration_resolve import pre_expiration_evidence_freeze_ts, resolve_authoritative_pre_expiration_state
    from p8_room_latch_reconcile import build_room_timeline_rows, replay_artifact_latch, server_latch_bundle_proven
    from p8_room_latch_timeline import build_room_state_timeline
    from p8_room_status_authority import classify_latch_status_boundary, resolve_authoritative_room_status
    from p8_start_boundary_classify import classify_start_boundary

    artifact = load_8b51ead_artifact(path)
    setup = artifact.get("production_setup") or artifact.get("draft_start_validation") or {}
    harness_run_id = str(artifact.get("harness_run_id") or artifact.get("diagnostic_run_id") or HARNESS_RUN_ID)
    app_run = str(setup.get("application_diagnostic_run_id") or APP_RUN_ID)
    rid = str(setup.get("room_id") or ROOM_ID).upper()
    export = setup.get("latch_ledger_export") or {}
    filtered = list(export.get("rows") or [])
    timeline = list(setup.get("room_state_timeline") or artifact.get("room_latch_timeline") or [])
    if not timeline and filtered:
        timeline = build_room_state_timeline(filtered, created_room_id=rid)

    ui = setup.get("authoritative_state") or {}
    status_auth = resolve_authoritative_room_status(
        ledger_rows=filtered,
        timeline=timeline,
        room_id=rid,
        application_diagnostic_run_id=app_run,
        ui_scrape=ui,
    )
    latch_status = classify_latch_status_boundary(
        status_resolution=status_auth,
        room_latch_pass=bool(setup.get("room_latch_pass")),
        ledger_rows=filtered,
        timeline=timeline,
        room_id=rid,
        application_diagnostic_run_id=app_run,
        harness_run_id=harness_run_id,
        ui_scrape=ui,
    )
    freeze = pre_expiration_evidence_freeze_ts(filtered, room_id=rid, diagnostic_run_id=app_run)
    pre = resolve_authoritative_pre_expiration_state(
        ledger_rows=filtered,
        ui_scrape=ui,
        room_id=rid,
        diagnostic_run_id=app_run,
        room_latch_pass=bool(setup.get("room_latch_pass")),
        now_ts=freeze,
    )
    server_bundle = server_latch_bundle_proven(filtered_ledger=filtered, timeline=timeline, created_room_id=rid)
    latch_replay = replay_artifact_latch(artifact)

    ordered = build_room_timeline_rows(
        full_rows=filtered,
        filtered_rows=filtered,
        timeline=timeline,
        harness_run_id=harness_run_id,
        application_diagnostic_run_id=app_run,
        streamlit_session_id=str(setup.get("streamlit_session_id") or ""),
        created_room_id=rid,
    )

    return {
        "harness_run_id": harness_run_id,
        "application_diagnostic_run_id": app_run,
        "room_id": rid,
        "streamlit_session_id": setup.get("streamlit_session_id"),
        "recorded_focused_p8_outcome": artifact.get("focused_p8_outcome"),
        "recorded_start_boundary": setup.get("start_boundary"),
        "ui_scrape_status": {
            "in_progress": ui.get("in_progress"),
            "setup_start_visible": ui.get("setup_start_visible"),
            "room_id": ui.get("room_id"),
        },
        "room_status_authority": status_auth,
        "latch_status_classification": latch_status,
        "pre_expiration_resolution": {
            k: pre.get(k)
            for k in (
                "pre_expiration_ready",
                "status",
                "status_source",
                "expected_token",
                "countdown_mounted",
                "countdown_mount_source",
                "consistency",
            )
        },
        "server_latch_bundle": server_bundle,
        "room_latch_replay": latch_replay,
        "ordered_room_status_timeline": ordered,
        "application_ledger_row_count": len([r for r in filtered if str(r.get("run_id") or "") == app_run]),
        "harness_run_id_on_rows": sorted({str(r.get("run_id") or "") for r in filtered if r.get("run_id")})[:5],
    }


def main() -> int:
    out = replay_8b51ead_setup()
    dest = ROOT / "data" / "p8_replay_8b51ead_latch_status.json"
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(
        {
            "latch_status": out["latch_status_classification"].get("classification"),
            "pre_expiration_ready": out["pre_expiration_resolution"].get("pre_expiration_ready"),
            "status_source": out["room_status_authority"].get("status_source"),
            "artifact": str(dest),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
