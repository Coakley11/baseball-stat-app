"""Minimal two-client stability smoke before Shared Draft browser work."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_tb_server_manager import (  # noqa: E402
    http_status,
    process_alive,
    start_host_guest,
    status_snapshot,
    stop_all,
)

OUT = ROOT / "data" / "tb_probe"
REPORT = OUT / "two_client_stability_smoke.json"


def main() -> int:
    from playwright.sync_api import sync_playwright

    report: dict = {
        "verdict": "FAIL",
        "classification_target": "LOCAL TWO-CLIENT SERVER STABILITY PASS",
    }
    handles = start_host_guest(out_dir=OUT / "server_manager", wait_ready_s=90.0)
    report["start"] = {k: v.to_dict() for k, v in handles.items()}
    report["room_store"] = handles["host"].room_store
    report["topology"] = {
        "mode": "two_processes",
        "reason": (
            "Shared Draft uses per-process Streamlit session_state + separate "
            "SUITE_WORKSPACE_ID/BASEBALL_DEVICE_ID; both resolve the same absolute "
            f"data/draft_rooms store ({handles['host'].room_store}). "
            "One process + two browser contexts would share one Python process and "
            "can conflate workspace/device env; two processes match real multi-user "
            "local backend topology."
        ),
    }
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            host = browser.new_context().new_page()
            guest = browser.new_context().new_page()
            host.goto("http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel", timeout=120000)
            guest.goto("http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest", timeout=120000)
            host.wait_for_timeout(6000)
            guest.wait_for_timeout(6000)
            # Force Live Draft via sidebar text when restore lands elsewhere.
            for page, label in ((host, "host"), (guest, "guest")):
                try:
                    page.get_by_text("📡 Live Draft Room").click(timeout=5000)
                    page.wait_for_timeout(4000)
                except Exception:
                    try:
                        page.locator("text=Live Draft Room").nth(0).click(timeout=5000)
                        page.wait_for_timeout(4000)
                    except Exception as exc:
                        report[f"{label}_nav_err"] = f"{type(exc).__name__}:{exc}"[:200]
            # Several interactions / reruns
            for i in range(3):
                for page in (host, guest):
                    try:
                        page.mouse.wheel(0, 800)
                        page.wait_for_timeout(1500)
                        page.mouse.wheel(0, -400)
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass
                snap = status_snapshot(handles)
                report[f"mid_status_{i}"] = {
                    name: {"alive": v["alive"], "http_ok": v["http"].get("ok")}
                    for name, v in snap.items()
                }
                for name, v in snap.items():
                    if not v["alive"] or not v["http"].get("ok"):
                        report["verdict"] = "FAIL"
                        report["failed_at"] = f"mid_status_{i}"
                        report["status"] = snap
                        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
                        print(json.dumps(report, indent=2))
                        return 1
            # Survive after playwright closes (servers must remain).
            browser.close()
            time.sleep(2)
            final = status_snapshot(handles)
            report["final_status"] = {
                name: {"alive": v["alive"], "http_ok": v["http"].get("ok"), "pid": v.get("pid")}
                for name, v in final.items()
            }
            ok = all(v["alive"] and v["http"].get("ok") for v in final.values())
            report["verdict"] = "LOCAL TWO-CLIENT SERVER STABILITY PASS" if ok else "FAIL"
            REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 0 if ok else 1
    finally:
        # Leave servers running for subsequent Join proof if smoke passed.
        if report.get("verdict") != "LOCAL TWO-CLIENT SERVER STABILITY PASS":
            report["stop"] = stop_all(handles)
            REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
