"""Continue Guest Join against an already-created UI room (68FJOT or latest)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from local_tb_server_manager import http_status  # noqa: E402

OUT = ROOT / "data" / "tb_probe"
ROOM_DIR = ROOT / "data" / "draft_rooms"
REPORT = OUT / "join_route_guest_continue.json"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"


def body(page) -> str:
    try:
        return page.inner_text("body", timeout=25000)
    except Exception:
        return ""


def snap(page, name: str) -> str:
    text = body(page)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    (OUT / f"{name}.txt").write_text(text[:9000], encoding="utf-8")
    return text


def wait_app(page, url: str, timeout_s: float = 90.0) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    deadline = time.time() + timeout_s
    text = ""
    while time.time() < deadline:
        text = body(page)
        if text.strip() in ("", "Stop\nDeploy", "Deploy") or len(text) < 80:
            page.wait_for_timeout(1500)
            continue
        if "not responding" in text.lower():
            page.wait_for_timeout(2000)
            continue
        break
    return text


def open_live_draft(page) -> bool:
    text = body(page)
    if "Draft Mode" in text or "Draft Setup" in text or "Waiting for Start" in text:
        return True
    # Prefer radio role used by Choose Page
    try:
        page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).check(timeout=8000)
        page.wait_for_timeout(5000)
    except Exception:
        try:
            page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).click(timeout=8000)
            page.wait_for_timeout(5000)
        except Exception:
            try:
                page.locator("label", has_text=re.compile(r"Live Draft Room", re.I)).first.click(timeout=8000)
                page.wait_for_timeout(5000)
            except Exception:
                return False
    text = body(page)
    return "Draft Mode" in text or "Draft Setup" in text or "Waiting for Start" in text or "Create Shared" in text


def select_shared(page) -> bool:
    for lab in (r"Shared Multiplayer Draft Room", r"Shared Multiplayer", r"^Shared$"):
        try:
            page.get_by_text(re.compile(lab, re.I)).first.click(timeout=5000)
            page.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    try:
        page.get_by_role("radio", name=re.compile(r"Shared", re.I)).click(timeout=5000)
        page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


def in_lobby(text: str, code: str) -> bool:
    if not code or code not in text:
        return False
    return bool(
        "Waiting for Start" in text
        or "Join code:" in text
        or f"Room {code}" in text
        or "Shared Draft Room Ready" in text
    )


def main() -> int:
    from playwright.sync_api import sync_playwright

    rooms = sorted(ROOM_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not rooms:
        print(json.dumps({"verdict": "NO_ROOM"}))
        return 2
    code = rooms[0].stem.upper()
    report: dict = {
        "code": code,
        "http_host": http_status(8511),
        "http_guest": http_status(8512),
    }
    if not report["http_guest"].get("ok"):
        report["verdict"] = "GUEST_SERVER_DOWN"
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        host = browser.new_context().new_page()
        guest = browser.new_context().new_page()

        wait_app(host, HOST_URL)
        report["host_live"] = open_live_draft(host)
        # Wait out Starting… if still creating
        for _ in range(40):
            ht = body(host)
            if in_lobby(ht, code) or ("Starting" not in ht and code in ht):
                break
            host.wait_for_timeout(3000)
        host_text = snap(host, "JC01_host")
        report["host_in_lobby"] = in_lobby(host_text, code)
        report["host_starting"] = "Starting" in host_text

        wait_app(guest, GUEST_URL)
        report["guest_live"] = open_live_draft(guest)
        g0 = snap(guest, "JC02_guest_live")
        report["guest_shared_ok"] = select_shared(guest)
        guest.wait_for_timeout(3000)
        g1 = snap(guest, "JC03_guest_shared")
        report["guest_join_ui"] = "Join Shared Draft Room" in g1
        if report["guest_join_ui"]:
            guest.get_by_placeholder("ABC123").fill(code, timeout=8000)
            guest.wait_for_timeout(3500)
            snap(guest, "JC04_guest_filled")
            btn = guest.get_by_role("button", name=re.compile(r"^Join( Room| as )", re.I)).first
            report["join_enabled"] = btn.is_enabled()
            btn.click(timeout=10000)
            report["join_click"] = True
            # Wait for route handoff
            for _ in range(20):
                guest.wait_for_timeout(2000)
                after = body(guest)
                if in_lobby(after, code):
                    break
            after = snap(guest, "JC05_guest_after_join")
            report["guest_in_lobby"] = in_lobby(after, code)
            report["guest_still_setup"] = "Join Shared Draft Room" in after and not report["guest_in_lobby"]
            report["guest_has_code"] = code in after
            # refresh
            guest.reload(wait_until="domcontentloaded", timeout=120000)
            wait_app(guest, GUEST_URL, timeout_s=60)
            open_live_draft(guest)
            guest.wait_for_timeout(8000)
            ref = snap(guest, "JC06_guest_refresh")
            report["guest_refresh_in_lobby"] = in_lobby(ref, code)

        raw = json.loads((ROOM_DIR / f"{code}.json").read_text(encoding="utf-8"))
        parts = raw.get("participants") or {}
        report["participants"] = parts
        report["guest_membership"] = "workspace:guest" in parts
        report["revision"] = raw.get("revision")

        try:
            gstate = json.loads(
                (ROOT / "data" / "workspaces" / "guest" / "baseball_user_state.json").read_text(encoding="utf-8")
            ).get("state") or {}
            from live_draft_completion import resolve_live_draft_lifecycle

            report["guest_disk_code"] = gstate.get("active_shared_draft_room_code")
            report["guest_disk_lifecycle"] = resolve_live_draft_lifecycle(gstate)
            report["guest_route_contract"] = gstate.get("_shared_room_join_route_contract")
        except Exception as exc:
            report["guest_disk_err"] = f"{type(exc).__name__}:{exc}"[:200]

        if report.get("join_click") and report.get("guest_membership") and report.get("guest_in_lobby"):
            report["verdict"] = "GUEST_JOIN_ROUTE_BROWSER_PASS"
        elif report.get("join_click") and report.get("guest_membership") and not report.get("guest_in_lobby"):
            report["verdict"] = "GUEST_MEMBERSHIP_CREATED_ROUTE_NOT_ENTERED"
        else:
            report["verdict"] = "LOCAL_SHARED_DRAFT_BLOCKED"

        browser.close()

    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "GUEST_JOIN_ROUTE_BROWSER_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
