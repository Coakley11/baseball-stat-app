"""Run RV0–RV3 return-value binding ladder on Cloud (authenticated). Stops at first valid failure."""

from __future__ import annotations

import base64
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
OUT = ROOT / "data" / "solo_rv_binding_ladder.json"


def required_implementation_sha() -> str:
    marker = ROOT / "deploy_commit.txt"
    if marker.is_file():
        for line in marker.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "branch:" not in line.lower():
                return line.split()[0].lower()[:7]
    return "a2aaa8e"


REQUIRED_SHA = required_implementation_sha()

from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url, harness_ready  # noqa: E402
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from run_production_stage1_authenticated import (  # noqa: E402
    production_url,
    wait_one_expiration,
    validate_production_draft_start,
)
from solo_draft_start_harness import execute_solo_draft_start_workflow  # noqa: E402
from stage1_preflight_cleanup import run_stage1_preflight_cleanup  # noqa: E402


def rv_url(step: str, run_id: str, *, ldr: bool = False) -> str:
    q = {
        "solo_rv_ladder": step,
        "solo_rv_run_id": run_id,
        "solo_delivery_diag": "1",
        "solo_component_diag": "1",
        "solo_diag_timer": "10",
    }
    if ldr:
        q["active_page"] = "Live Draft Room"
    base = f"{BASE}/?{urlencode(q)}"
    return append_suite_sid_to_url(base)


def scrape_b64_probe(page, element_id: str) -> dict[str, Any]:
    try:
        b64 = page.evaluate(
            f"""() => {{
              function roots(){{ const r=[document]; for (const f of document.querySelectorAll('iframe')) {{ try {{ r.push(f.contentDocument);}} catch(e){{}} }} return r.filter(Boolean); }}
              for (const root of roots()) {{
                const el = root.querySelector(#{element_id});
                if (el) return el.getAttribute('data-b64') || '';
              }}
              return '';
            }}"""
        )
        if not b64:
            return {}
        pad = b64 + "==="[: (4 - len(b64) % 4) % 4]
        return json.loads(base64.b64decode(pad).decode("utf-8"))
    except Exception:
        return {}


def scrape_registry_localstorage(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
              try {
                const s = localStorage.getItem('__solo_rv_instance_registry_v1');
                return s ? JSON.parse(s) : {};
              } catch (e) { return {}; }
            }"""
        )
        if isinstance(raw, dict) and raw.get("last"):
            return raw
        probe = scrape_b64_probe(page, "solo-rv-instance-registry")
        if probe:
            return {"python_side_probe": probe, "last": [], "logical": []}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def verify_cloud_sha(page) -> tuple[str, str]:
    from cloud_streamlit_wake import scrape_deploy_sha_from_page
    from run_production_solo_soak import all_frames_text, scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from verify_cloud_deploy_playwright import scrape_deploy

    probe = scrape_deploy(page) or {}
    sha = (
        scrape_live_sha(page)
        or scrape_deploy_sha_from_page(page)
        or scrape_deploy_build(page)
        or str(probe.get("sha") or "")
    ).strip().lower()[:7]
    build = str(probe.get("build") or "").strip()
    if not build:
        m = __import__("re").search(r"baseball-dev-([0-9a-f]{7})", all_frames_text(page), __import__("re").I)
        if m:
            build = f"baseball-dev-{m.group(1).lower()}"
    return sha, build


def assert_cloud_implementation_ready(page, required: str) -> tuple[bool, str, str]:
    sha, build = verify_cloud_sha(page)
    ok_sha = sha == required[:7]
    ok_build = build.lower() == f"baseball-dev-{required[:7].lower()}"
    if ok_sha and ok_build:
        return True, sha, build
    if ok_sha and not ok_build:
        return False, sha, build
    return False, sha, build


def poll_control_probe_best(page, best: dict[str, Any]) -> dict[str, Any]:
    probe = scrape_b64_probe(page, "solo-rv-control-probe")
    if probe and len(probe.get("rows") or []) >= len(best.get("rows") or []):
        return probe
    return best


def wait_rv0_with_probe_polling(page, *, timeout_s: float = 95.0) -> tuple[dict[str, Any], dict[str, Any]]:
    best_probe: dict[str, Any] = {}
    exp = wait_one_expiration(page, timeout_s=timeout_s)
    poll_until = time.time() + 60.0
    while time.time() < poll_until:
        best_probe = poll_control_probe_best(page, best_probe)
        page.wait_for_timeout(2000)
    best_probe = poll_control_probe_best(page, best_probe)
    return exp, best_probe


def evaluate_step(step: str, *, run_id: str, expiration: dict[str, Any], control_probe: dict[str, Any], reg: dict[str, Any], room_id: str = "") -> dict[str, Any]:
    from live_draft_solo_rv_binding_ladder import (
        build_declaration_timeline,
        build_instance_identity_report,
        classify_root_cause,
        grade_rv_control_validity,
        summarize_browser_events,
    )
    from live_draft_solo_rv_control_probe import ledger_to_declaration_rows

    ledger_rows = list(control_probe.get("rows") or [])
    rows = ledger_to_declaration_rows(ledger_rows)
    browser = summarize_browser_events(expiration, reg)
    validity_ok, validity_reason = __import__(
        "live_draft_solo_rv_binding_ladder", fromlist=["validate_rv_control_prerequisites"]
    ).validate_rv_control_prerequisites(
        declaration_rows=rows,
        browser=browser,
        expiration=expiration,
        control_probe_rows=ledger_rows,
    )
    verdict, reason = grade_rv_control_validity(
        step=step,
        ledger=ledger_rows,
        declaration_rows=rows,
        browser=browser,
        expiration=expiration,
    )
    root = classify_root_cause(
        validity_ok=validity_ok,
        verdict=verdict,
        browser=browser,
        declaration_rows=rows,
    )
    return {
        "step": step,
        "run_id": run_id,
        "room_id": room_id,
        "verdict": verdict,
        "reason": reason,
        "validity_ok": validity_ok,
        "validity_reason": validity_reason,
        "root_cause": root,
        "browser_summary": browser,
        "control_probe_ledger": ledger_rows,
        "instance_identity_report": build_instance_identity_report(expiration, reg),
        "declaration_timeline": build_declaration_timeline({"rows": rows}),
        "expiration_summary": {
            "token_sent": expiration.get("token_sent"),
            "observation_duration_s": expiration.get("observation_duration_s"),
            "post_send_observation_s": expiration.get("post_send_observation_s"),
            "client_stages_tail": list(expiration.get("client_stages") or [])[-20:],
        },
    }


def run_rv0(context, run_id: str, *, cloud_sha: str, cloud_build: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    page = context.new_page()
    goto_and_wake(page, rv_url("RV0", run_id), timeout_s=240)
    page.wait_for_timeout(12000)
    exp, probe = wait_rv0_with_probe_polling(page, timeout_s=95.0)
    reg = scrape_registry_localstorage(page)
    result = evaluate_step("RV0", run_id=run_id, expiration=exp, control_probe=probe, reg=reg)
    result["cloud_sha"] = cloud_sha
    result["cloud_build"] = cloud_build
    page.close()
    return result


def run_rv_real_step(context, step: str, run_id: str, *, cloud_sha: str, cloud_build: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    page = context.new_page()
    cleanup = run_stage1_preflight_cleanup(page)
    if not cleanup.get("ok"):
        page.close()
        return {"step": step, "verdict": "INVALID", "reason": "setup_lobby_blocked", "run_id": run_id, "cleanup": cleanup}
    url = production_url()
    draft = execute_solo_draft_start_workflow(page, url, navigate=False)
    start_val = validate_production_draft_start(page, draft, prior_room_id=str(cleanup.get("detected_room_id") or ""))
    if not start_val.get("valid"):
        page.close()
        return {"step": step, "verdict": "INVALID", "reason": "draft_start_invalid", "run_id": run_id, "start": start_val}
    goto_and_wake(page, rv_url(step, run_id, ldr=(step in ("RV2", "RV3"))), timeout_s=240)
    page.wait_for_timeout(12000)
    exp, probe = wait_rv0_with_probe_polling(page, timeout_s=95.0)
    reg = scrape_registry_localstorage(page)
    result = evaluate_step(
        step,
        run_id=run_id,
        expiration=exp,
        control_probe=probe,
        reg=reg,
        room_id=str(start_val.get("latched_room_id") or ""),
    )
    result["cloud_sha"] = cloud_sha
    result["cloud_build"] = cloud_build
    page.close()
    return result


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1
    summary: dict[str, Any] = {
        "started_at": time.time(),
        "required_implementation_sha": REQUIRED_SHA,
        "artifact": str(OUT),
        "steps": [],
        "stopped_at": None,
        "first_valid_failure": None,
    }
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        pre_ctx = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        pre_page = pre_ctx.new_page()
        goto_and_wake(
            pre_page,
            append_suite_sid_to_url(f"{BASE}/?solo_delivery_diag=1"),
            timeout_s=240,
        )
        pre_page.wait_for_timeout(10000)
        ok, verified_sha, verified_build = assert_cloud_implementation_ready(pre_page, REQUIRED_SHA)
        pre_page.close()
        pre_ctx.close()
        summary["cloud_sha_verified_at_start"] = verified_sha
        summary["cloud_build_verified_at_start"] = verified_build
        if not ok:
            summary["aborted"] = True
            summary["abort_reason"] = f"cloud_sha_mismatch_{verified_sha}_need_{REQUIRED_SHA[:7]}"
            browser.close()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            print(json.dumps(summary, indent=2, default=str))
            return 1
        for step in ("RV0",):
            run_id = str(uuid.uuid4())
            context = browser.new_context(
                storage_state=str(STORAGE_PATH),
                viewport={"width": 1440, "height": 1400},
            )
            if step == "RV0":
                result = run_rv0(context, run_id, cloud_sha=verified_sha, cloud_build=verified_build)
            else:
                result = run_rv_real_step(
                    context, step, run_id, cloud_sha=verified_sha, cloud_build=verified_build
                )
            context.close()
            summary["steps"].append(result)
            v = str(result.get("verdict") or "")
            if step == "RV0":
                if v != "PASS_RETURN_VALUE_DELIVERY":
                    summary["stopped_at"] = step
                    if v == "INVALID":
                        summary["first_invalid_control"] = result
                    else:
                        summary["first_valid_failure"] = result
                    break
                continue
            if v not in ("PASS",):
                summary["stopped_at"] = step
                summary["first_valid_failure"] = result
                break
        browser.close()
    summary["finished_at"] = time.time()
    summary["implementation_sha_observed"] = summary.get("cloud_sha_verified_at_start")
    summary["cloud_build_observed"] = summary.get("cloud_build_verified_at_start")
    if summary["steps"] and summary["steps"][-1].get("cloud_sha"):
        summary["implementation_sha_observed"] = summary["steps"][-1].get("cloud_sha")
        summary["cloud_build_observed"] = summary["steps"][-1].get("cloud_build")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not summary.get("stopped_at") else 1


if __name__ == "__main__":
    raise SystemExit(main())
