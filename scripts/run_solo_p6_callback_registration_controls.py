"""Run P6 callback-registration controls R0–R3 on Cloud (stop at first changed outcome)."""

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

OUT = ROOT / "data" / "solo_p6_callback_registration_controls.json"

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


def _callback_entries(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for r in rows
        if isinstance(r, dict) and r.get("stage") in ("callback_entry", "on_change_callback_entry")
    )


def classify_control_run(
    *,
    control: str,
    rows: list[dict[str, Any]],
    peak: dict[str, Any],
    p6_overall: str,
    r0_class: str | None,
) -> str:
    gate = _score_p6_entrypoint_gate(rows)
    if gate:
        return "INVALID"
    if not _pre_expiration_mount_stages_ok(rows):
        return "INVALID"
    send = int(
        peak.get("setComponentValue_invocation")
        or peak.get("browser_set_component_value")
        or peak.get("setComponentValue")
        or 0
    )
    parent = int(peak.get("parent_message") or peak.get("deduped_parent_receipt") or 0)
    if send < 1 or parent < 1:
        return "INVALID"
    cb = _callback_entries(rows)
    sentinel = _has_stage(rows, "sentinel_callback_entry")
    if cb == 1:
        if control == "R1" and r0_class in (
            "VALID_FAIL_CALLBACK_NOT_TRIGGERED",
            "VALID_FAIL_CALLBACK_REGISTRATION",
        ):
            return "VALID_FAIL_SUPPRESS_FLAG"
        return "PASS_CALLBACK_REGISTERED"
    if sentinel and cb == 0:
        return "VALID_FAIL_ORIGINAL_CALLBACK_BINDING"
    if control == "R0" and p6_overall == "VALID_FAIL_CALLBACK_REGISTRATION":
        return "VALID_FAIL_CALLBACK_NOT_TRIGGERED"
    return "VALID_FAIL_CALLBACK_NOT_TRIGGERED"


def main() -> int:
    if not harness_ready():
        print(json.dumps({"error": "playwright harness storage not ready"}))
        return 2
    if not run_preflight().get("authenticated_restored"):
        print(json.dumps({"error": "auth preflight failed"}))
        return 2

    required = official_required_sha()
    from playwright.sync_api import sync_playwright

    results: list[dict[str, Any]] = []
    r0_class: str | None = None
    stopped_at: str | None = None
    declaration_diff: dict[str, Any] | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        deploy_page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        deploy = verify_official_deploy(deploy_page, required=required)
        deploy_page.context.close()
        if not deploy.get("deploy_ok"):
            print(json.dumps({"error": "deploy not ready", "deploy": deploy}))
            browser.close()
            return 2

        for control in ("R0", "R1", "R2", "R3"):
            run_id = str(uuid.uuid4())
            ls_key = f"solo_parity_ls_p6_{control}_{int(time.time())}"
            url = p6_writer_url(run_id=run_id, ls_key=ls_key, callback_control=control)
            run = run_p6_writer_session(browser, deploy=deploy, run_id=run_id, writer_url=url)
            rows = run.get("ordered_ledger") if isinstance(run.get("ordered_ledger"), list) else []
            peak = run.get("peak") if isinstance(run.get("peak"), dict) else {}
            p6_overall = str((run.get("scored") or {}).get("overall") or "")
            last_payload = run.get("last_payload") if isinstance(run.get("last_payload"), dict) else {}
            outcome = classify_control_run(
                control=control,
                rows=rows,
                peak=peak,
                p6_overall=p6_overall,
                r0_class=r0_class,
            )
            row = {
                "control": control,
                "run_id": run_id,
                "p6_overall": p6_overall,
                "outcome": outcome,
                "callback_entries": _callback_entries(rows),
                "sentinel": _has_stage(rows, "sentinel_callback_entry"),
                "peak": peak,
                "declaration_diff": last_payload.get("declaration_diff"),
                "declaration_audit": {
                    s: _has_stage(rows, s) for s in ("declaration_attempt", "declaration_returned", "declaration_diff_recorded")
                },
                "ordered_stages": [r.get("stage") for r in rows if isinstance(r, dict)],
            }
            if control == "R0":
                r0_class = outcome
                if isinstance(last_payload.get("declaration_diff"), dict):
                    declaration_diff = last_payload["declaration_diff"]
            results.append(row)
            if control != "R0" and r0_class and outcome != r0_class:
                stopped_at = control
                break
            if outcome == "PASS_CALLBACK_REGISTERED" and control == "R1":
                stopped_at = control
                break
        browser.close()

    report = {
        "required_sha": required,
        "deploy": deploy,
        "r0_baseline": r0_class,
        "stopped_at": stopped_at,
        "results": results,
        "declaration_diff": declaration_diff,
        "smallest_fix_hypothesis": None,
    }
    if stopped_at == "R1" and r0_class != "PASS_CALLBACK_REGISTERED":
        report["smallest_fix_hypothesis"] = (
            "suppress_immediate_session_on_change=True skips the post-mount _prod_on_change() poll; "
            "R1 (suppress=False) is the first control that registers/triggers Python callback."
        )
    elif r0_class == "VALID_FAIL_CALLBACK_NOT_TRIGGERED":
        for r in results:
            if r.get("outcome") == "VALID_FAIL_ORIGINAL_CALLBACK_BINDING":
                report["smallest_fix_hypothesis"] = (
                    "Streamlit invokes on_change on the sentinel wrapper but not on the production deliver binding "
                    "passed into _prod_on_change — inspect closure/deliver_callback identity at declaration time."
                )
                break
            if r.get("outcome") == "PASS_CALLBACK_REGISTERED" and r.get("control") == "R3":
                report["smallest_fix_hypothesis"] = (
                    "B2 helper declaration at same key/token succeeds; production _mount_persistent_wake_micro_controlled "
                    "kwargs (session_prefix/persistent/placement) affect Streamlit callback registration."
                )
                break

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
