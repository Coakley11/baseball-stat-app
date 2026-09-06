"""Resume + refresh continuation for an already-paused Shared Draft room."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_tb_full_shared_draft_pass import (  # noqa: E402
    HOST_URL,
    GUEST_URL,
    OUT,
    ROOM_DIR,
    add_count,
    body,
    click_control,
    open_live_draft,
    room_raw,
    snap,
    wait_app,
)
from local_tb_server_manager import http_status  # noqa: E402

REPORT = OUT / "resume_refresh_continue.json"


def main() -> int:
    from playwright.sync_api import sync_playwright

    rooms = sorted(ROOM_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    code = rooms[0].stem.upper() if rooms else ""
    report: dict = {
        "code": code,
        "http_host": http_status(8511),
        "http_guest": http_status(8512),
        "before": room_raw(code) if code else {},
    }
    if not code:
        report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — NO_ROOM"
        REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, default=str))
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        host = browser.new_context().new_page()
        guest = browser.new_context().new_page()
        wait_app(host, HOST_URL)
        open_live_draft(host)
        try:
            host.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(timeout=2500)
        except Exception:
            pass
        host.wait_for_timeout(4000)
        snap(host, "RR01_host_before_resume")
        report["status_before"] = str(room_raw(code).get("status") or "")
        report["resume_click"] = click_control(host, r"Resume Draft", r"^Resume$", r"\bResume\b")
        resumed = False
        for i in range(25):
            stt = str(room_raw(code).get("status") or "").lower()
            report.setdefault("resume_poll", []).append({"i": i, "status": stt})
            if stt == "in_progress":
                resumed = True
                break
            host.wait_for_timeout(1500)
        report["resume_disk"] = resumed
        snap(host, "RR02_host_after_resume")
        wait_app(guest, GUEST_URL)
        open_live_draft(guest)
        try:
            guest.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(timeout=2500)
        except Exception:
            pass
        guest.wait_for_timeout(5000)
        gt = snap(guest, "RR03_guest_after_resume")
        report["guest_sees_in_progress"] = bool(re.search(r"In Progress", gt, re.I))
        report["host_add"] = add_count(host)
        report["guest_add"] = add_count(guest)

        guest.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(guest, GUEST_URL)
        open_live_draft(guest)
        try:
            guest.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(timeout=2500)
        except Exception:
            pass
        guest.wait_for_timeout(10000)
        gref = snap(guest, "RR04_guest_refresh")
        report["guest_refresh"] = {
            "same_code": code in gref.upper(),
            "in_progress": "In Progress" in gref,
            "add_count": add_count(guest),
            "not_setup": "Create Shared Draft Room" not in gref or code in gref.upper(),
        }

        host.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(host, HOST_URL)
        open_live_draft(host)
        try:
            host.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(timeout=2500)
        except Exception:
            pass
        host.wait_for_timeout(10000)
        href = snap(host, "RR05_host_refresh")
        report["host_refresh"] = {
            "same_code": code in href.upper(),
            "in_progress": "In Progress" in href,
            "add_count": add_count(host),
            "not_setup": "Create Shared Draft Room" not in href or code in href.upper(),
        }
        report["after"] = {
            "status": room_raw(code).get("status"),
            "revision": room_raw(code).get("revision"),
            "participants": list((room_raw(code).get("participants") or {}).keys()),
        }
        ok = bool(
            report["resume_click"]
            and report["resume_disk"]
            and report["guest_refresh"]["same_code"]
            and report["host_refresh"]["same_code"]
            and report["guest_refresh"]["not_setup"]
            and report["host_refresh"]["not_setup"]
        )
        report["verdict"] = (
            "LOCAL TWO-BROWSER SHARED DRAFT PASS — RESUME_REFRESH"
            if ok
            else "LOCAL SHARED DRAFT BLOCKED — RESUME"
        )
        browser.close()

    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("verdict", "code", "resume_click", "resume_disk", "guest_refresh", "host_refresh", "after") if k in report}, indent=2, default=str))
    return 0 if "PASS" in report["verdict"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
