"""Open active Shared room and wait longer for Add-to-Queue; dump LDR diagnostics."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local_tb_server_manager import http_status  # noqa: E402

OUT = ROOT / "data" / "tb_probe"
REPORT = OUT / "pool_handoff_probe.json"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"


def body(page) -> str:
    try:
        return page.inner_text("body", timeout=25000)
    except Exception:
        return ""


def main() -> int:
    from playwright.sync_api import sync_playwright

    report: dict = {"http": http_status(8511), "samples": []}
    if not report["http"].get("ok"):
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto(HOST_URL, wait_until="domcontentloaded", timeout=120000)
        # dismiss chrome
        try:
            page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=2000)
        except Exception:
            pass
        deadline = time.time() + 180
        t0 = time.time()
        while time.time() < deadline:
            text = body(page)
            has_add = False
            try:
                has_add = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count() > 0
            except Exception:
                pass
            sample = {
                "t": round(time.time() - t0, 1),
                "has_add": has_add,
                "building": bool(re.search(r"still building the player pool", text, re.I)),
                "no_players": "No players left in the pool" in text,
                "on_clock": bool(re.search(r"On (the )?clock", text, re.I)),
                "ldr_steps": re.findall(r"⏱ LDR step[^\n]+", text)[:8],
                "rerun": re.findall(r"last_rerun=[^\s)]+", text)[:4],
            }
            report["samples"].append(sample)
            if has_add:
                report["verdict"] = "POOL_HANDOFF_VISIBLE"
                page.screenshot(path=str(OUT / "PH_ok.png"), full_page=True)
                (OUT / "PH_ok.txt").write_text(text[:12000], encoding="utf-8")
                break
            page.wait_for_timeout(5000)
        else:
            report["verdict"] = "POOL_HANDOFF_STILL_MISSING"
            text = body(page)
            page.screenshot(path=str(OUT / "PH_fail.png"), full_page=True)
            (OUT / "PH_fail.txt").write_text(text[:12000], encoding="utf-8")
            report["final_snip"] = text[:1500]
        browser.close()

    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("verdict", "samples") if k in report}, indent=2))
    return 0 if report.get("verdict") == "POOL_HANDOFF_VISIBLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
