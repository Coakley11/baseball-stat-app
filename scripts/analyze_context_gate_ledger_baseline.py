"""Analyze context gate C2 ledger_len_before=1 without C3/C0 ledger match."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "data" / "production_bridge_fragment_context_isolation_gate.json"


def main() -> int:
    if not GATE.is_file():
        print(json.dumps({"ok": False, "error": "missing_gate_artifact", "path": str(GATE)}))
        return 1
    report = json.loads(GATE.read_text(encoding="utf-8"))
    controls = list(report.get("context_controls") or [])
    by = {str(c.get("control")): c for c in controls if isinstance(c, dict)}
    c3 = by.get("C3") or {}
    c0 = by.get("C0") or {}
    c2 = by.get("C2") or {}
    out = {
        "ok": True,
        "artifact": str(GATE),
        "c3_ledger_delta": (c3.get("callback_ledger_delta") or {}),
        "c0_ledger_delta": (c0.get("callback_ledger_delta") or {}),
        "c2_ledger_len_before": (c2.get("ledger_len_before")),
        "c2_callback_ledger_delta": (c2.get("callback_ledger_delta") or {}),
        "interpretation": (
            "C3 and C0 both reported recommendation-fragment ledger 0→0 with no matching source row. "
            "C2 baseline ledger_len_before=1 but callback_ledger_last for source fragment_context_c2 was empty — "
            "the single row is not attributable to C3/C0/C2/C1 in the saved artifact (full ledger JSON was not snapshotted at expander open). "
            "Likely contamination from shared #solo-stage1-rec-fragment-callback-ledger DOM after expander rerun "
            "(matrix/context/recommendation diag re-render) or stale duplicate ledger nodes in iframe. "
            "Do not relabel C3 from this row; use dedicated _stage1_button_dispatch_events for dispatch gate."
        ),
        "chronology_between_c0_and_c2": [
            e
            for e in (report.get("chronology") or [])
            if isinstance(e, dict) and str(e.get("step")) in ("C0", "context_expander", "C2")
        ],
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
