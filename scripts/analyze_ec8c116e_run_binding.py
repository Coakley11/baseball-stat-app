"""Explain EC8C116E lifecycle 15 vs transport ledger 12 (retrospective)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_run_binding import lifecycle_seq_from_render_trace


def main() -> int:
    gate_path = ROOT / "data" / "production_bridge_queue_seed_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    proof = gate.get("francisco_widget_liveness_proof") or {}
    trace = proof.get("app_render_trace") or {}
    transport = proof.get("post_click_transport") or {}
    lifecycle = lifecycle_seq_from_render_trace(trace)

    report = {
        "bridge": gate.get("bridge_suite_sid_prefix"),
        "room": (trace.get("room_id") or ""),
        "runtime": trace.get("app_sha"),
        "lifecycle_current_script_run_seq": lifecycle.get("lifecycle_current_script_run_seq"),
        "legacy_transport_script_run_seq_before": transport.get("script_run_seq_before"),
        "legacy_transport_script_run_seq_after": transport.get("ledger_script_run_seq_after"),
        "root_cause": (
            "Transport used scrape_stage1_ledger_rows[-1].script_run_seq (last appended ledger row, often an "
            "older event at seq 12) while lifecycle DOM used session _solo_stage1_script_run_seq embedded in "
            "rec-card render trace (current generation 15). These are different observers; Francisco was not "
            "necessarily clicked during ledger row 12 — the harness graded rerun against stale last-row seq."
        ),
        "fix": (
            "Use #solo-production-ledger-diag data-script-run-seq / max ledger row seq as transport grade seq; "
            "compare to lifecycle seq via run_binding_consistent before A2/A3/A4."
        ),
        "dom_capture_empty_cause": (
            "Listener was installed via page.evaluate on top document with generic first stBaseButton-secondary, "
            "while Playwright clicked Francisco inside the Streamlit app iframe — events logged in wrong window."
        ),
    }
    out = ROOT / "data" / "ec8c116e_run_binding_reconciliation.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
