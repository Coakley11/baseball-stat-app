"""Graded B2 synthetic matrix cell — official Cloud SHA gate + transport/lifecycle verdicts."""

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
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
OUT = ROOT / "data" / "solo_wiring_b2_baseline.json"
DEPLOY_PROBE_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room&solo_delivery_diag=1&solo_bridge_transition=A0"
)


def official_required_sha() -> str:
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from run_solo_wiring_b1_a2_sequence_auth import (  # noqa: E402
    observe_cell,
    scrape_probe,
)
from solo_wiring_matrix_harness_core import (  # noqa: E402
    attach_dual_verdicts,
    build_cell_record,
    dual_verdicts,
)
from verify_cloud_deploy_playwright import scrape_deploy  # noqa: E402


def matrix_url(widget_key: str, ls_key: str) -> str:
    q = urlencode(
        {
            "active_page": "Live Draft Room",
            "solo_wiring_synthetic": "1",
            "solo_wiring_matrix": "B2",
            "solo_wiring_key": widget_key,
            "solo_wiring_ls_key": ls_key,
            "solo_transport_probe": "1",
        }
    )
    return append_suite_sid_to_url(f"{BASE}/?{q}")


def verify_official_deploy(page, *, required: str, timeout_s: float = 900.0) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    expected_build = f"baseball-dev-{required}"
    t0 = time.time()
    last: dict[str, Any] = {}
    while time.time() - t0 < timeout_s:
        goto_and_wake(page, DEPLOY_PROBE_URL, timeout_s=240)
        page.wait_for_timeout(8000)
        probe = scrape_deploy(page)
        sha = str(probe.get("sha") or "").lower()[:7]
        build = str(probe.get("build") or "")
        last = {
            "cloud_sha": sha,
            "cloud_build": build,
            "probe": probe,
            "required_sha": required,
            "required_build": expected_build,
        }
        if sha == required and build == expected_build:
            last["deploy_ok"] = True
            return last
        page.wait_for_timeout(20000)
    last["deploy_ok"] = False
    return last


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    if not run_preflight().get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    required = official_required_sha()
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {
        "cell": "B2",
        "a1_not_rerun": True,
        "required_sha": required,
        "required_build": f"baseball-dev-{required}",
        "accepted_prior": {"A1": "PASS baseline", "A2": "PASS", "B1_transport": "PASS (dual verdict)"},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        deploy_page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        deploy = verify_official_deploy(deploy_page, required=required)
        report["deploy_probe"] = deploy
        deploy_page.context.close()

        if not deploy.get("deploy_ok"):
            report["outcome"] = "ABORTED"
            report["reason"] = "cloud_deploy_mismatch"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps(report, indent=2, default=str))
            browser.close()
            return 1

        widget_key = f"solo_wiring_b2_{uuid.uuid4().hex[:10]}"
        ls_key = f"solo_wiring_ls_b2_{uuid.uuid4().hex[:10]}"
        ctx = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        page = ctx.new_page()
        goto_and_wake(page, matrix_url(widget_key, ls_key), timeout_s=240)
        from solo_wiring_matrix_harness_core import install_parent_capture

        install_parent_capture(page)
        t_nav = time.time()
        probe: dict[str, Any] = {"missing": True}
        while time.time() - t_nav < 90.0:
            install_parent_capture(page)
            probe = scrape_probe(page)
            if not probe.get("missing"):
                break
            page.wait_for_timeout(500)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=2000)
            page.wait_for_timeout(1000)
        except Exception:
            pass
        if probe.get("missing"):
            for _ in range(8):
                page.wait_for_timeout(2000)
                probe = scrape_probe(page)
                if not probe.get("missing"):
                    break
        if probe.get("missing"):
            report["outcome"] = "INVALID"
            report["invalid_reasons"] = ["matrix_probe_missing"]
            ctx.close()
            browser.close()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 1

        expected = str(probe.get("expected") or "")
        deadline = float(expected.split("|")[2]) if expected.count("|") >= 2 else time.time() + 12
        scored = observe_cell(page, cell="B2", expected_token=expected, deadline=deadline)
        peak = scored.get("distinct") or {}
        attach_dual_verdicts(scored, peak, cell="B2", expected_token=expected)
        record = build_cell_record(
            cell="B2",
            scored=scored,
            peak=peak,
            expected_token=expected,
            widget_key=widget_key,
            ls_key=ls_key,
            cloud_sha=str(deploy.get("cloud_sha") or ""),
            cloud_build=str(deploy.get("cloud_build") or ""),
            required_sha=required,
        )
        record["observation_s"] = scored.get("observation_s")
        record["artifact_path"] = str(OUT)
        record["graded_outcome"] = scored.get("transport_verdict")
        record["interpretation"] = (
            "B2 transport PASS → frontend+wrapper functional together; investigate persistent key/wake/ownership."
            if scored.get("transport_verdict") == "PASS"
            else "B2 transport FAIL with B1+A2 transport PASS → frontend×micro-wrapper interaction."
            if scored.get("transport_verdict") in ("FAIL", "INVALID")
            else "Review B2 transport/lifecycle artifacts."
        )
        report.update(record)
        ctx.close()
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("transport_verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
