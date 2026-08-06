"""Analyze capture ledger for auth event eviction vs emission (harness)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH_EVENT_MARKERS = (
    "production_stage1_auth_state_before_start_control",
    "production_stage1_auth_prestart_hydration",
    "production_stage1_auth_prestart_mutation",
    "save_browser_auth_tokens",
    "apply_authenticated_user",
)


def analyze_trace_bundle(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("ledger_summary") or {}
    event_ids = list(summary.get("event_ids") or [])
    seqs: list[int] = []
    for eid in event_ids:
        m = re.match(r"[^:]+:(\d+):", str(eid))
        if m:
            seqs.append(int(m.group(1)))
    auth_in_export = [e for e in event_ids if any(x in str(e) for x in AUTH_EVENT_MARKERS)]
    min_seq = min(seqs) if seqs else 0
    max_seq = max(seqs) if seqs else 0
    result = {
        "export_row_count": int(summary.get("row_count") or 0),
        "export_event_id_count": len(event_ids),
        "min_event_seq_in_export": min_seq,
        "max_event_seq_in_export": max_seq,
        "auth_markers_in_export": auth_in_export,
        "auth_markers_in_export_count": len(auth_in_export),
    }
    if max_seq > 400 and not auth_in_export:
        result["ledger_auth_diagnosis"] = (
            "AUTH_OBSERVABILITY7 — authentication evidence rolled out of bounded ledger "
            "(merged/export window retains high-sequence canary/UI rows only)"
        )
        result["exact_condition"] = 1
        result["exact_condition_detail"] = (
            "events likely existed earlier in run but evicted from merged MAX_ROWS=400 before DOM export; "
            "repeated registration/canary rows displaced auth from retained window"
        )
    elif not auth_in_export:
        result["ledger_auth_diagnosis"] = "AUTH_OBSERVABILITY5 — no auth transition rows in bound export"
        result["exact_condition"] = 4
        result["exact_condition_detail"] = "no auth markers in export sample; emission on path unproven from export"
    else:
        result["ledger_auth_diagnosis"] = "auth markers present in export"
        result["exact_condition"] = 0
    return result


def main() -> int:
    path = ROOT / "data" / "capture_playwright_daniel_auth_trace" / "f86e3566_1786050953" / "trace_bundle.json"
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    out = analyze_trace_bundle(path)
    out_path = ROOT / "data" / "f86e3566_ledger_auth_analysis.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
