"""Playwright preflight: confirm P2 diagnostic build before running the gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

TARGET_SHA = "1bda44f"
OUT = Path(__file__).resolve().parent.parent / "data" / "p2_deploy_preflight.json"


def _build_label_ok(page, sha: str) -> tuple[bool, str]:
    from cloud_streamlit_wake import all_frames_text
    import re

    label = f"baseball-dev-{sha}"
    text = all_frames_text(page)
    if re.search(rf"baseball-dev-{re.escape(sha)}", text, re.I):
        return True, label
    try:
        html = page.content()
    except Exception:
        html = ""
    if re.search(rf"baseball-dev-{re.escape(sha)}", html, re.I):
        return True, label
    if re.search(rf'data-sha="{re.escape(sha)}"', html, re.I) or re.search(
        rf"solo-deploy-build sha={re.escape(sha)}", html, re.I
    ):
        return True, label
    return False, ""


def main() -> int:
    from playwright.sync_api import sync_playwright
    from cloud_streamlit_wake import goto_and_wake
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_placement_p2_gate import (
        P2_SETUP_URL,
        scrape_p2_deploy_hooks,
        wait_p2_observation_ready,
    )
    from solo_draft_start_harness import click_sidebar_for_ldr

    report: dict[str, Any] = {"target_sha": TARGET_SHA, "checks": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1400})

        goto_and_wake(page, P2_SETUP_URL, timeout_s=240)
        page.wait_for_timeout(5000)
        click_sidebar_for_ldr(page, settle_ms=6000)
        page.wait_for_timeout(2000)

        sha = (scrape_live_sha(page) or "").lower()[:7]
        hooks_lobby = scrape_p2_deploy_hooks(page)
        label_ok, label = _build_label_ok(page, sha)
        report["runtime_sha"] = sha
        report["build_label"] = label if label_ok else (f"baseball-dev-{TARGET_SHA}" if sha == TARGET_SHA else "")
        report["hooks_setup_lobby"] = hooks_lobby
        report["checks"]["runtime_sha"] = sha == TARGET_SHA
        report["checks"]["build_label"] = bool(report["build_label"])
        report["checks"]["latch_probe"] = bool(hooks_lobby.get("latch_probe_present"))

        if not all(
            (
                report["checks"]["runtime_sha"],
                report["checks"]["build_label"],
                report["checks"]["latch_probe"],
            )
        ):
            report["preflight_pass"] = False
            browser.close()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"preflight_pass": False, "artifact": str(OUT)}, indent=2))
            return 1

        # In-draft hooks: start one Solo draft and require v2 + observation-ready before gate.
        from solo_draft_start_harness import (
            execute_solo_draft_start_workflow,
            maybe_clear_stale_draft,
        )

        maybe_clear_stale_draft(page, [])
        draft = execute_solo_draft_start_workflow(page, P2_SETUP_URL, navigate=False)
        report["draft_start_success"] = bool(draft.get("start_success"))
        report["room_id"] = draft.get("room_id") or ""
        hooks_in_room = scrape_p2_deploy_hooks(page)
        obs = wait_p2_observation_ready(page, max_wait_s=60)
        ladder = (obs.get("probe") or {}).get("ladder") or {}
        latch = (obs.get("probe") or {}).get("latch") or {}
        v2_dom = bool(
            page.evaluate(
                """() => {
                  function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean)}
                  for(const x of roots()){
                    const l=x&&x.querySelector('#solo-placement-ladder-diag');
                    if(l && l.getAttribute('data-p2-harness')==='v2') return true;
                  }
                  return false;
                }"""
            )
        )
        report["hooks_in_room"] = hooks_in_room
        report["observation_ready"] = obs
        report["checks"]["p2_harness_v2"] = v2_dom or bool(hooks_in_room.get("p2_harness_v2"))
        report["checks"]["observation_ready"] = bool(obs.get("ready"))
        report["checks"]["latched_p2"] = str(latch.get("requested") or "").upper() == "P2"
        report["checks"]["draft_start"] = report["draft_start_success"]
        report["preflight_pass"] = all(report["checks"].values())
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"preflight_pass": report["preflight_pass"], "artifact": str(OUT)}, indent=2))
    return 0 if report["preflight_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
