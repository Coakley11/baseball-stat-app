"""Offline re-label of a finished capture using observability rules (no browser)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from playwright_auth_observability import (  # noqa: E402
    AUTH_OBSERVABILITY1,
    CAPTURE_FAIL_OBSERVABILITY,
    classify_auth_observability,
    diagnostic_query_flags,
    session_binding_report,
)


def reclassify_result(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    sid = str(data.get("suite_sid") or "")
    strict = data.get("strict_capture") or {}
    start_enabled = bool(strict.get("start_enabled"))
    url = str(data.get("final_browser_url") or data.get("target_url") or "")
    flags = diagnostic_query_flags(url)
    cp = {
        "start_enabled": start_enabled,
        "streamlit_session_id": str(data.get("streamlit_session_id") or ""),
        "diagnostic_run_id": str(data.get("diagnostic_run_id") or ""),
        "diagnostic_query_flags": flags,
        "start_frame_index": 0,
    }
    timeline = data.get("login_timeline") or []
    lb = {
        "auth_row_count": sum(1 for _ in timeline),
        "row_count": len(timeline),
        "ledger_same_frame_as_start": True,
        "ledger_streamlit_session_id": cp["streamlit_session_id"],
        "ledger_diagnostic_run_id": cp["diagnostic_run_id"],
    }
    ss = {
        "enabled": start_enabled,
        "visible": strict.get("start_visible", start_enabled),
        "frame_index": 0,
        "page_url": url,
        "suite_sid": sid,
        "selected_page_reason": "capture_result_replay",
    }
    binding = session_binding_report(cp, lb, harness_sid=sid)
    code, detail, evidence = classify_auth_observability(
        start_surface=ss,
        checkpoint=cp,
        ledger_bind=lb,
        binding=binding,
        strict_failure=str(data.get("failure") or ""),
    )
    if start_enabled and str(data.get("auth_login_classification") or "") == "AUTH_LOGIN1":
        data["auth_login_classification"] = ""
        data["auth_observability_classification"] = code or AUTH_OBSERVABILITY1
        data["auth_observability_detail"] = detail
        data["failure"] = CAPTURE_FAIL_OBSERVABILITY
        data["accepted_observability_reclassification"] = True
        data["observability_evidence"] = evidence
    return data


def main() -> int:
    path = ROOT / "data" / "capture_playwright_daniel_auth_once.result.json"
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    updated = reclassify_result(path)
    path.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "suite_sid": updated.get("suite_sid"),
                "auth_observability_classification": updated.get("auth_observability_classification"),
                "auth_observability_detail": updated.get("auth_observability_detail"),
                "failure": updated.get("failure"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
