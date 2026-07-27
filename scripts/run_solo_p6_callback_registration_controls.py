"""Run P6 callback-registration controls R0–R3 on Cloud (stop at first changed outcome)."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "solo_p6_callback_registration_controls.json"

from run_solo_persistent_parity_ladder_auth import BASE, official_required_sha, verify_official_deploy  # noqa: E402
from run_solo_persistent_parity_p6_only_auth import (  # noqa: E402
    _has_stage,
    _post_expiration_rows_present,
    _pre_expiration_mount_stages_ok,
    _score_p6_entrypoint_gate,
    run_p6_writer_session,
    scrape_p6_writer_probe,
)
from playwright_daniel_auth_session import harness_ready  # noqa: E402
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402


def p6_control_url(*, run_id: str, control: str, ls_key: str) -> str:
    from playwright_daniel_auth_session import append_suite_sid_to_url

    q = {
        "active_page": "Live Draft Room",
        "solo_delivery_diag": "1",
        "solo_persistent_parity": "P6",
        "solo_transport_probe": "1",
        "solo_p6_run_id": run_id,
        "solo_parity_ls_key": ls_key,
        "solo_p6_callback_control": control,
    }
    return append_suite_sid_to_url(f"{BASE}/?{urlencode(q)}")


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
    browser: dict[str, Any],
    r0_class: str | None,
) -> str:
    gate = _score_p6_entrypoint_gate(rows)
    if gate:
        return "INVALID"
    if not _pre_expiration_mount_stages_ok(rows):
        return "INVALID"
    send = int(browser.get("unique_setComponentValue") or browser.get("unique_transport_postMessage") or 0)
    parent = int(browser.get("deduped_parent_receipt") or browser.get("unique_transport_postMessage") or 0)
    if send < 1 or parent < 1:
        return "INVALID"
    cb = _callback_entries(rows)
    sentinel = _has_stage(rows, "sentinel_callback_entry")
    if cb == 1:
        if control == "R1" and r0_class in (
            "VALID_FAIL_CALLBACK_NOT_TRIGGERED",
            "VALID_FAIL_CALLBACK_REGISTRATION",
            "VALID_FAIL_ORIGINAL_CALLBACK_BINDING",
        ):
            return "VALID_FAIL_SUPPRESS_FLAG"
        return "PASS_CALLBACK_REGISTERED"
    if sentinel and cb == 0:
        return "VALID_FAIL_ORIGINAL_CALLBACK_BINDING"
    if control == "R1" and r0_class and r0_class != "PASS_CALLBACK_REGISTERED" and cb >= 1:
        return "VALID_FAIL_SUPPRESS_FLAG"
    return "VALID_FAIL_CALLBACK_NOT_TRIGGERED"


def main() -> int:
    if not harness_ready():
        print(json.dumps({"error": "playwright harness storage not ready"}))
        return 2
    pre = run_preflight()
    if not pre.get("ok"):
        print(json.dumps({"error": "auth preflight failed", "preflight": pre}))
        return 2
    deploy = verify_official_deploy()
    if not deploy.get("deploy_ok"):
        print(json.dumps({"error": "deploy not ready", "deploy": deploy}))
        return 2
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH
    from solo_wiring_matrix_harness_core import install_p6_harness_init

    results: list[dict[str, Any]] = []
    r0_class: str | None = None
    stopped_at: str | None = None
    declaration_diff: dict[str, Any] | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for control in ("R0", "R1", "R2", "R3"):
            run_id = str(uuid.uuid4())
            ls_key = f"solo_parity_ls_p6_ctrl_{control}_{int(time.time())}"
            row: dict[str, Any] = {"control": control, "run_id": run_id}
            ctx = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
            install_p6_harness_init(ctx)
            page = ctx.new_page()
            try:
                from cloud_streamlit_wake import goto_and_wake

                url = p6_control_url(run_id=run_id, control=control, ls_key=ls_key)
                goto_and_wake(page, url, timeout_s=240)
                t0 = time.time()
                last_payload: dict[str, Any] = {}
                browser_peak: dict[str, Any] = {}
                while time.time() - t0 < 48.0:
                    probe = scrape_p6_writer_probe(page)
                    payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
                    if payload:
                        last_payload = payload
                    from solo_wiring_matrix_harness_core import collect_p6_browser_peak

                    browser_peak = collect_p6_browser_peak(page)
                    if _has_stage(payload.get("ledger_rows") or [], "component_declared"):
                        if time.time() - t0 > 12.0:
                            break
                    time.sleep(0.45)
                rows = last_payload.get("ledger_rows") if isinstance(last_payload.get("ledger_rows"), list) else []
                outcome = classify_control_run(
                    control=control, rows=rows, browser=browser_peak, r0_class=r0_class
                )
                row.update(
                    {
                        "outcome": outcome,
                        "callback_entries": _callback_entries(rows),
                        "sentinel": _has_stage(rows, "sentinel_callback_entry"),
                        "browser": browser_peak,
                        "post_expiration": _post_expiration_rows_present(rows),
                        "declaration_diff": last_payload.get("declaration_diff"),
                        "declaration_audit": {
                            s: True
                            for s in ("declaration_attempt", "declaration_returned")
                            if _has_stage(rows, s)
                        },
                    }
                )
                if control == "R0":
                    r0_class = outcome
                    declaration_diff = last_payload.get("declaration_diff") if isinstance(
                        last_payload.get("declaration_diff"), dict
                    ) else None
                results.append(row)
                if control != "R0" and r0_class and outcome != r0_class:
                    stopped_at = control
                    break
                if outcome == "PASS_CALLBACK_REGISTERED" and control == "R1":
                    stopped_at = control
                    break
            finally:
                ctx.close()
        browser.close()

    report = {
        "required_sha": official_required_sha(deploy),
        "deploy": deploy,
        "r0_baseline": r0_class,
        "stopped_at": stopped_at,
        "results": results,
        "declaration_diff": declaration_diff,
        "smallest_fix_hypothesis": None,
    }
    if stopped_at == "R1" and r0_class != "PASS_CALLBACK_REGISTERED":
        report["smallest_fix_hypothesis"] = (
            "suppress_immediate_session_on_change=True defers Streamlit on_change until browser postMessage; "
            "setting False allows immediate _prod_on_change after mount (diagnostic R1 only)."
        )
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
