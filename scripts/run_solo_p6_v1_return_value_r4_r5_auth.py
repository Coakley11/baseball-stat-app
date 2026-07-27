"""Cloud R4/R5 — V1 component return-value controls on P6 dedicated route."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "solo_p6_v1_return_value_r4_r5.json"

from run_solo_persistent_parity_ladder_auth import official_required_sha, verify_official_deploy  # noqa: E402
from run_solo_persistent_parity_p6_only_auth import (  # noqa: E402
    _has_stage,
    _pre_expiration_mount_stages_ok,
    _score_p6_entrypoint_gate,
    p6_writer_url,
    run_p6_writer_session,
)
from playwright_daniel_auth_session import harness_ready  # noqa: E402
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402


def _return_rows(rows: list[dict[str, Any]], control: str) -> list[dict[str, Any]]:
    stage = "r5_component_return_value" if control == "R5" else "r4_component_return_value"
    return [r for r in rows if isinstance(r, dict) and r.get("stage") == stage]


def _max_script_run(rows: list[dict[str, Any]]) -> int:
    return max((int(r.get("script_run") or 0) for r in rows if isinstance(r, dict)), default=0)


def grade_v1_return_control(
    *,
    control: str,
    rows: list[dict[str, Any]],
    peak: dict[str, Any],
    expected_token: str,
    session_ids: set[str],
) -> str:
    ret_rows = _return_rows(rows, control)
    if any(isinstance(r, dict) and r.get("return_matches_expected") for r in ret_rows):
        if len(session_ids) > 1:
            return "INVALID"
        send = int(peak.get("setComponentValue_invocation") or 0)
        parent = int(peak.get("parent_message") or 0)
        if send < 1 or parent < 1:
            return "INVALID"
        return "PASS_RETURN_VALUE_DELIVERY"

    gate = _score_p6_entrypoint_gate(rows)
    if gate:
        return "INVALID"
    if not _pre_expiration_mount_stages_ok(rows):
        return "INVALID"
    if len(session_ids) > 1:
        return "INVALID"
    send = int(peak.get("setComponentValue_invocation") or 0)
    parent = int(peak.get("parent_message") or 0)
    if send < 1 or parent < 1:
        return "INVALID"
    if int(peak.get("setComponentValue_invocation") or 0) > 1:
        return "INVALID"
    if _max_script_run(ret_rows) < 2:
        return "INVALID"
    if ret_rows and all(not r.get("return_matches_expected") for r in ret_rows):
        return "VALID_FAIL_RETURN_VALUE_NOT_DELIVERED"
    return "INVALID"


def main() -> int:
    if not harness_ready() or not run_preflight().get("authenticated_restored"):
        print(json.dumps({"error": "harness or auth not ready"}))
        return 2

    required = official_required_sha()
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {"required_sha": required, "controls": []}
    r4_outcome: str | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        deploy_page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        deploy = verify_official_deploy(deploy_page, required=required)
        deploy_page.context.close()
        if not deploy.get("deploy_ok"):
            print(json.dumps({"error": "deploy mismatch", "deploy": deploy}))
            browser.close()
            return 2
        report["deploy"] = deploy

        for control in ("R4", "R5"):
            if control == "R5" and r4_outcome == "PASS_RETURN_VALUE_DELIVERY":
                report["controls"].append({"control": "R5", "skipped": True, "reason": "R4 passed"})
                break
            if control == "R5" and r4_outcome not in (
                "VALID_FAIL_RETURN_VALUE_NOT_DELIVERED",
                "VALID_FAIL_CALLBACK_NOT_TRIGGERED",
            ):
                report["controls"].append(
                    {
                        "control": "R5",
                        "skipped": True,
                        "reason": f"R4 outcome {r4_outcome} — R5 only when R4 fails canonical return path",
                    }
                )
                break

            run_id = str(uuid.uuid4())
            ls_key = f"solo_parity_ls_p6_{control}_{int(time.time())}"
            url = p6_writer_url(run_id=run_id, ls_key=ls_key, callback_control=control)
            run = run_p6_writer_session(browser, deploy=deploy, run_id=run_id, writer_url=url)
            payload = run.get("last_payload") if isinstance(run.get("last_payload"), dict) else {}
            rows = payload.get("ledger_rows") if isinstance(payload.get("ledger_rows"), list) else []
            if not rows:
                rows = run.get("ordered_ledger") if isinstance(run.get("ordered_ledger"), list) else []
            peak = run.get("peak") if isinstance(run.get("peak"), dict) else {}
            expected = str(run.get("expected_token") or "")
            sids = set(run.get("streamlit_session_ids") or [])
            outcome = grade_v1_return_control(
                control=control,
                rows=rows,
                peak=peak,
                expected_token=expected,
                session_ids=sids,
            )
            entry = {
                "control": control,
                "run_id": run_id,
                "outcome": outcome,
                "expected_token": expected,
                "return_rows": _return_rows(rows, control),
                "max_script_run": _max_script_run(_return_rows(rows, control)),
                "peak": peak,
                "p6_overall": (run.get("scored") or {}).get("overall"),
            }
            report["controls"].append(entry)
            if control == "R4":
                r4_outcome = outcome
            if outcome == "PASS_RETURN_VALUE_DELIVERY":
                break

        browser.close()

    report["r4_outcome"] = r4_outcome
    report["frontend_note"] = (
        "Production countdown uses manual window.parent.postMessage(streamlit:setComponentValue); "
        "see docs/STREAMLIT_V1_CUSTOM_COMPONENT_API_1.59.1.md and solo_countdown_component/frontend/index.html."
    )
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
