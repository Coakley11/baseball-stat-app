"""Replay and regrade Stage 1A-CORE artifacts (harness only)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reconcile_saved_core_run(summary: dict[str, Any]) -> dict[str, Any]:
    from stage1_harness_observability import classify_core_reconciliation

    sa = summary.get("stage1a") or {}
    exp = sa.get("expiration") or {}
    draft_valid = sa.get("draft_start_validation") or summary.get("draft_start_validation") or {}
    grade = sa.get("grade") or {}
    merged = list(exp.get("merged_server_ledger") or grade.get("ledger_meta", {}).get("merged_server_ledger") or [])
    if not merged:
        merged = list((grade.get("ledger_meta") or {}).get("merged_server_ledger") or [])

    harness_id = str(summary.get("core_harness_run_id") or "")
    app_run = str(summary.get("application_diagnostic_run_id") or exp.get("application_diagnostic_run_id") or "")
    room = str(
        summary.get("fresh_room_id")
        or draft_valid.get("latched_room_id")
        or summary.get("room_id")
        or ""
    ).upper()
    frozen = str(
        draft_valid.get("expected_token")
        or (summary.get("setup_authority") or {}).get("expected_token")
        or exp.get("token_sent")
        or ""
    )
    exp_for_recon = {
        **exp,
        "application_diagnostic_run_id": app_run,
        "fresh_room_id": room,
        "token_sent": frozen or exp.get("token_sent"),
    }
    report = classify_core_reconciliation(
        exp=exp_for_recon,
        draft_valid=draft_valid,
        merged_ledger=merged,
        frozen_token=frozen,
        run_id=app_run,
        room_id=room,
        legacy_grade=grade,
    )
    return {
        "harness_run_id": harness_id,
        "application_diagnostic_run_id": app_run,
        "streamlit_session_id": str(
            (summary.get("production_setup") or {}).get("identity_timeline", [{}])[0].get("streamlit_session_id")
            or ""
        ),
        "room_id": room,
        "frozen_pick_0_token": frozen,
        "cloud_sha": summary.get("cloud_sha"),
        "legacy_overall_classification": grade.get("overall_classification"),
        "legacy_functional_verdict": grade.get("functional_verdict"),
        "queue_independence": sa.get("queue_independence") or grade.get("queue_independence"),
        **report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Stage 1A-CORE artifact reconciliation")
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "data" / "production_stage1_authenticated_summary.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "p8_core_reconcile_ce62d9b7.json",
    )
    args = parser.parse_args()
    summary = load_summary(args.summary)
    report = reconcile_saved_core_run(summary)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "binding_timeline"}, indent=2, default=str))
    print(f"timeline_rows={len(report.get('binding_timeline') or [])}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
