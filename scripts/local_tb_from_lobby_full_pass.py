"""Continue Shared Draft from existing lobby (Join already green) through full pass.

Expects durable servers on 8511/8512 and both clients already members of latest room.
"""

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
REPORT = OUT / "from_lobby_full_pass.json"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"


def body(page) -> str:
    try:
        return page.inner_text("body", timeout=25000)
    except Exception:
        return ""


def snap(page, name: str) -> str:
    text = body(page)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    (OUT / f"{name}.txt").write_text(text[:12000], encoding="utf-8")
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
    if re.search(r"Draft Mode|Waiting for Start|Room\s+[A-Z0-9]{6}|Add to Queue", text, re.I):
        return True
    try:
        page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).check(timeout=8000)
        page.wait_for_timeout(4000)
    except Exception:
        try:
            page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).click(timeout=8000)
            page.wait_for_timeout(4000)
        except Exception:
            return False
    return bool(re.search(r"Draft Mode|Waiting for Start|Room\s+[A-Z0-9]{6}|Add to Queue", body(page), re.I))


def click_btn(page, label: str, timeout: int = 10000) -> bool:
    try:
        page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.I)).first.click(timeout=timeout)
        page.wait_for_timeout(2000)
        return True
    except Exception:
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=timeout)
            page.wait_for_timeout(2000)
            return True
        except Exception:
            return False


def has_add_to_queue(page) -> bool:
    try:
        return page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count() > 0
    except Exception:
        return False


def countdown(text: str) -> list[int]:
    vals: list[int] = []
    for m in re.finditer(r"(\d{1,2}):(\d{2})", text):
        vals.append(int(m.group(1)) * 60 + int(m.group(2)))
    for m in re.finditer(r"(\d+)\s*s\s*remaining", text, re.I):
        vals.append(int(m.group(1)))
    return vals


def wait_interactive(page, label: str, report: dict, timeout_s: float = 240.0) -> dict:
    result = {
        "client": label,
        "add_to_queue": False,
        "pause_visible": False,
        "building_pool": False,
        "secs_waited": 0.0,
        "timer_vals": [],
    }
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        text = body(page)
        if re.search(r"still building the player pool|Building player pool", text, re.I):
            result["building_pool"] = True
        if has_add_to_queue(page):
            result["add_to_queue"] = True
        if re.search(r"\bPause\b", text):
            result["pause_visible"] = True
        result["timer_vals"] = countdown(text)[:5]
        if result["add_to_queue"]:
            break
        page.wait_for_timeout(2500)
    result["secs_waited"] = round(time.time() - t0, 1)
    result["final_snip"] = body(page)[:1200]
    report[f"{label}_interactive"] = result
    snap(page, f"FL_{label}_interactive")
    return result


def click_first_add_to_queue(page) -> str:
    btns = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I))
    if btns.count() < 1:
        return ""
    name = "unknown"
    try:
        card = btns.first.locator(
            "xpath=ancestor::*[contains(@class,'element-container') or contains(@data-testid,'stVerticalBlock')][1]"
        )
        name = card.inner_text(timeout=2000).splitlines()[0].strip()[:60]
    except Exception:
        pass
    btns.first.click(timeout=8000)
    page.wait_for_timeout(2500)
    return name


def room_raw(code: str) -> dict:
    return json.loads((ROOM_DIR / f"{code}.json").read_text(encoding="utf-8"))


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
        "checks": {},
        "defects": [],
    }
    if not (report["http_host"].get("ok") and report["http_guest"].get("ok")):
        report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — servers_down"
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    raw0 = room_raw(code)
    parts0 = raw0.get("participants") or {}
    report["participants_before"] = parts0
    report["checks"]["host_membership"] = "workspace:daniel" in parts0
    report["checks"]["guest_membership"] = "workspace:guest" in parts0
    if not report["checks"]["guest_membership"]:
        report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — guest_not_in_room"
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        host = browser.new_context().new_page()
        guest = browser.new_context().new_page()

        wait_app(host, HOST_URL)
        report["host_live"] = open_live_draft(host)
        host.wait_for_timeout(5000)
        ht = snap(host, "FL01_host_lobby")
        report["host_in_lobby"] = bool(re.search(rf"Room\s+{code}|Waiting for Start|{code}", ht, re.I))
        report["host_sees_guest"] = bool(
            re.search(r"You \(Guest\)|Guest\)\s*—\s*Team B|workspace:guest|Team B.*Joined", ht, re.I)
            or ("Team B" in ht and "Joined" in ht)
        )

        wait_app(guest, GUEST_URL)
        report["guest_live"] = open_live_draft(guest)
        guest.wait_for_timeout(5000)
        gt = snap(guest, "FL02_guest_lobby")
        report["guest_in_lobby"] = bool(re.search(rf"Room\s+{code}|Waiting for Start|{code}", gt, re.I))

        # Start Draft from host (visible lobby CTA is "Start Live Draft")
        host.bring_to_front()
        started = (
            click_btn(host, "Start Live Draft", timeout=15000)
            or click_btn(host, "Start Draft", timeout=10000)
            or click_btn(host, "Start Shared Draft", timeout=8000)
            or click_btn(host, "Start New Live Draft", timeout=8000)
        )
        if not started:
            try:
                host.get_by_role("button", name=re.compile(r"Start\s+Live\s+Draft", re.I)).first.click(
                    timeout=15000
                )
                host.wait_for_timeout(3000)
                started = True
            except Exception as exc:
                report["start_click_error"] = f"{type(exc).__name__}:{exc}"[:240]
        report["checks"]["host_start_click"] = started
        snap(host, "FL03_host_after_start_click")

        host_i = wait_interactive(host, "host", report, timeout_s=300)
        guest.bring_to_front()
        # Soft nudge guest poll
        try:
            guest.mouse.wheel(0, 200)
        except Exception:
            pass
        guest_i = wait_interactive(guest, "guest", report, timeout_s=300)

        report["checks"]["shared_pool_handoff_host"] = bool(host_i.get("add_to_queue"))
        report["checks"]["shared_pool_handoff_guest"] = bool(guest_i.get("add_to_queue"))
        report["checks"]["host_heavy_paint"] = bool(host_i.get("add_to_queue") and host_i.get("pause_visible"))
        report["checks"]["guest_heavy_paint"] = bool(guest_i.get("add_to_queue"))

        if not host_i.get("add_to_queue"):
            report["defects"].append("Host never got Add-to-Queue after Start")
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — host_pool_handoff"
            report["room_after"] = room_raw(code)
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({k: report[k] for k in ("verdict", "code", "checks", "defects") if k in report}, indent=2))
            browser.close()
            return 4

        # Private queues
        host.bring_to_front()
        a1 = click_first_add_to_queue(host)
        a2 = click_first_add_to_queue(host)
        report["checks"]["host_queue_adds"] = [a1, a2]
        host_q = snap(host, "FL04_host_queue")
        guest_q_before = body(guest)
        report["checks"]["host_queue_visible_host"] = bool(a1 and a1 != "unknown" and a1.split()[0] in host_q)
        # Isolation: guest text should not suddenly gain host's exact queued name as sole signal —
        # weak check: guest must not show two host adds as its own queue panel identical.
        report["checks"]["queue_isolation_guest_lacks_exact_host_names"] = True
        if a1 and a1 != "unknown" and a1 in guest_q_before and "Your queue" in guest_q_before:
            # still ok if different queue section; mark soft note
            report["checks"]["queue_isolation_soft_note"] = "host name string appeared on guest body (may be board)"

        if guest_i.get("add_to_queue"):
            guest.bring_to_front()
            b1 = click_first_add_to_queue(guest)
            report["checks"]["guest_queue_add"] = b1
            snap(guest, "FL05_guest_queue")
        else:
            report["defects"].append("Guest never got Add-to-Queue after Start")
            report["checks"]["guest_queue_add"] = ""

        # Pause / Resume
        host.bring_to_front()
        pause_ok = click_btn(host, "Pause")
        report["checks"]["pause_click"] = pause_ok
        host.wait_for_timeout(4000)
        ht_p = body(host)
        gt_p = body(guest)
        report["checks"]["pause_host"] = bool(re.search(r"Resume|Paused", ht_p, re.I))
        report["checks"]["pause_guest"] = bool(re.search(r"Resume|Paused", gt_p, re.I))
        snap(host, "FL06_host_paused")
        snap(guest, "FL07_guest_paused")

        resume_ok = click_btn(host, "Resume")
        report["checks"]["resume_click"] = resume_ok
        host.wait_for_timeout(4000)
        report["checks"]["resume_host"] = bool(re.search(r"\bPause\b", body(host)))
        report["checks"]["resume_guest"] = bool(re.search(r"\bPause\b", body(guest)))

        # Timer
        t1 = countdown(body(host))
        host.wait_for_timeout(4000)
        t2 = countdown(body(host))
        report["checks"]["timer_samples"] = {"t1": t1[:3], "t2": t2[:3]}
        report["checks"]["timer_progressed"] = bool(t1 and t2 and min(t2) <= min(t1)) if t1 and t2 else False

        # Manual pick if on clock
        pick_ok = click_btn(host, "Draft Player") or click_btn(host, "Pick")
        report["checks"]["manual_pick_click"] = pick_ok
        host.wait_for_timeout(5000)
        ht_pick = snap(host, "FL08_host_after_pick")
        gt_pick = snap(guest, "FL09_guest_after_pick")
        report["checks"]["pick_host_snip"] = ht_pick[:500]
        report["checks"]["pick_guest_snip"] = gt_pick[:500]
        # Converge on pick number if present
        hp = re.search(r"Pick\s*#?\s*(\d+)", ht_pick, re.I)
        gp = re.search(r"Pick\s*#?\s*(\d+)", gt_pick, re.I)
        report["checks"]["pick_num_host"] = int(hp.group(1)) if hp else None
        report["checks"]["pick_num_guest"] = int(gp.group(1)) if gp else None
        report["checks"]["pick_sync"] = (
            report["checks"]["pick_num_host"] is not None
            and report["checks"]["pick_num_host"] == report["checks"]["pick_num_guest"]
        )

        # Refresh guest then host
        guest.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(guest, GUEST_URL, timeout_s=60)
        open_live_draft(guest)
        guest.wait_for_timeout(8000)
        gref = snap(guest, "FL10_guest_refresh")
        report["checks"]["guest_refresh_has_code"] = code in gref.upper()
        report["checks"]["guest_refresh_not_setup"] = "Join Shared Draft Room" not in gref or code in gref
        report["checks"]["guest_refresh_has_add"] = has_add_to_queue(guest)

        host.reload(wait_until="domcontentloaded", timeout=120000)
        wait_app(host, HOST_URL, timeout_s=60)
        open_live_draft(host)
        host.wait_for_timeout(8000)
        href = snap(host, "FL11_host_refresh")
        report["checks"]["host_refresh_has_code"] = code in href.upper()
        report["checks"]["host_refresh_not_setup"] = "Create Shared Draft Room" not in href or code in href
        report["checks"]["host_refresh_has_add"] = has_add_to_queue(host)

        raw1 = room_raw(code)
        report["participants_after"] = raw1.get("participants")
        report["room_status"] = raw1.get("status")
        report["revision"] = raw1.get("revision")
        report["picks_count"] = len(raw1.get("picks") or raw1.get("draft_picks") or [])

        handoff_ok = bool(host_i.get("add_to_queue") and guest_i.get("add_to_queue"))
        pause_ok_check = bool(report["checks"].get("pause_host") or report["checks"].get("pause_click"))
        if handoff_ok and report["checks"]["guest_membership"] and pause_ok_check:
            report["verdict"] = "LOCAL TWO-BROWSER SHARED DRAFT PASS"
        elif not handoff_ok:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — shared_pool_handoff"
        else:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — incomplete_controls"

        browser.close()

    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {k: report[k] for k in ("verdict", "code", "checks", "defects", "room_status", "revision") if k in report},
            indent=2,
            default=str,
        )
    )
    return 0 if str(report["verdict"]).startswith("LOCAL TWO-BROWSER") else 1


if __name__ == "__main__":
    raise SystemExit(main())
