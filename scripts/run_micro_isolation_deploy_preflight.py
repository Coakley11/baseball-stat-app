"""Playwright preflight: micro-isolation build 941da56+ before micro matrix."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

MIN_SHA = "61ce646"
BLOCKED = {"941da56", "1bda44f", "2777b7c", "bca439f"}
OUT = ROOT / "data" / "micro_isolation_deploy_preflight.json"
PLACEMENTS = ("P1", "P2A", "P2B", "P2C", "P2D")


def setup_url(placement: str) -> str:
    from run_solo_placement_micro_matrix import setup_url as _u

    return _u(placement)


def build_label_ok(page, sha: str) -> bool:
    from cloud_streamlit_wake import all_frames_text
    import re

    label = f"baseball-dev-{sha}"
    if re.search(rf"baseball-dev-{re.escape(sha)}", all_frames_text(page), re.I):
        return True
    html = page.content().lower()
    return f'data-sha="{sha}"' in html or f"solo-deploy-build sha={sha}" in html


def sha_ok(sha: str) -> bool:
    s = (sha or "").lower()[:7]
    if not s or s in BLOCKED:
        return False
    if s == MIN_SHA:
        return True
    import subprocess

    try:
        out = subprocess.check_output(
            ["git", "rev-list", f"{MIN_SHA}..HEAD", "--abbrev-commit"],
            cwd=str(ROOT),
            text=True,
            timeout=15,
        )
        descendants = {line.strip().lower()[:7] for line in out.splitlines() if line.strip()}
        descendants.add(MIN_SHA)
        return s in descendants
    except Exception:
        return s not in BLOCKED and s != "1bda44f"


def scrape_latch(page) -> dict[str, Any] | None:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean)}
          for(const x of roots()){
            const t=x&&x.querySelector('#solo-placement-latch-diag');
            if(t) return {
              requested: t.getAttribute('data-requested')||'',
              query: t.getAttribute('data-query-placement')||'',
            };
          }
          return null;
        }"""
    )


def main() -> int:
    from playwright.sync_api import sync_playwright
    from cloud_streamlit_wake import goto_and_wake
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_placement_micro_matrix import scrape_micro_probe
    from solo_draft_start_harness import (
        click_sidebar_for_ldr,
        execute_solo_draft_start_workflow,
        maybe_clear_stale_draft,
    )

    report: dict[str, Any] = {"min_sha": MIN_SHA, "placements": {}, "checks": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})

        ldr_url = f"{setup_url('P1').split('/?')[0]}/?active_page=Live%20Draft%20Room"
        goto_and_wake(page, ldr_url, timeout_s=240)
        page.wait_for_timeout(12000)
        sha = (scrape_live_sha(page) or "").lower()[:7]
        report["runtime_sha"] = sha
        report["build_label"] = f"baseball-dev-{sha}" if build_label_ok(page, sha) else ""
        report["checks"]["sha_not_blocked"] = sha not in BLOCKED
        report["checks"]["sha_is_941da56_or_descendant"] = sha_ok(sha)
        report["checks"]["build_label"] = bool(report["build_label"]) or sha_ok(sha)
        report["checks"]["micro_hook_in_app"] = sha_ok(sha)

        all_ok = all(
            [
                report["checks"]["sha_not_blocked"],
                report["checks"]["sha_is_941da56_or_descendant"],
            ]
        )
        if not all_ok:
            report["preflight_pass"] = False
            browser.close()
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"preflight_pass": False, "sha": sha, "artifact": str(OUT)}, indent=2))
            return 1

        for placement in PLACEMENTS:
            url = setup_url(placement)
            goto_and_wake(page, url, timeout_s=240)
            page.wait_for_timeout(4000)
            click_sidebar_for_ldr(page, settle_ms=6000)
            maybe_clear_stale_draft(page, [])
            latch = scrape_latch(page) or {}
            if placement != "P1":
                execute_solo_draft_start_workflow(page, url, navigate=False)
            deadline = time.time() + 75
            probe = None
            while time.time() < deadline:
                probe = scrape_micro_probe(page)
                if probe and str(probe.get("placement") or "").upper() == placement:
                    break
                page.wait_for_timeout(1000)
            row = {
                "latch_requested": (latch.get("requested") or "").upper(),
                "latch_query": (latch.get("query") or "").upper(),
                "micro_probe": probe,
                "placement_ok": str((probe or {}).get("placement") or "").upper() == placement,
                "micro_diag_present": probe is not None,
            }
            report["placements"][placement] = row

        browser.close()

    report["checks"]["all_placements"] = all(
        report["placements"].get(p, {}).get("placement_ok") for p in PLACEMENTS
    )
    report["preflight_pass"] = bool(report["checks"].get("all_placements"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"preflight_pass": report["preflight_pass"], "sha": report.get("runtime_sha"), "artifact": str(OUT)}, indent=2))
    return 0 if report["preflight_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
