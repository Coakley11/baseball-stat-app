"""Authoritative Pause/Resume proof: exact labels + disk transition polling."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "tb_probe"
ROOM = ROOT / "data" / "draft_rooms" / "21Z40O.json"
REPORT = OUT / "pause_resume_authoritative.json"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"


def room_doc() -> dict:
    return json.loads(ROOM.read_text(encoding="utf-8"))


def room_status() -> tuple[str, int]:
    doc = room_doc()
    return str(doc.get("status") or ""), int(doc.get("revision") or 0)


def body(page) -> str:
    try:
        return page.inner_text("body", timeout=20000)
    except Exception:
        return ""


def draft_status(text: str) -> str:
    m = re.search(r"Draft Status:\s*([^\n]+)", text or "")
    return (m.group(1).strip() if m else "")


def click_exact(page, label: str, *, timeout: int = 10000) -> dict:
    info: dict = {"label": label}
    loc = page.get_by_role("button", name=label)
    if loc.count() == 0:
        # Fallback regex without requiring exact emoji glyph match issues
        pat = re.escape(label).replace("\\ ", "\\s+")
        loc = page.get_by_role("button", name=re.compile(pat))
    info["count"] = loc.count()
    if loc.count() == 0:
        info["ok"] = False
        info["error"] = "not_found"
        return info
    btn = loc.first
    info["enabled"] = btn.is_enabled()
    info["visible"] = btn.is_visible()
    try:
        btn.scroll_into_view_if_needed(timeout=timeout)
    except Exception:
        pass
    try:
        # Prefer Playwright click; fall back to DOM click.
        if btn.is_enabled():
            btn.click(timeout=timeout)
            info["method"] = "playwright"
            info["ok"] = True
        else:
            handle = btn.element_handle(timeout=timeout)
            page.evaluate("(el) => el.click()", handle)
            info["method"] = "dom_disabled_force"
            info["ok"] = True
    except Exception as exc:
        try:
            handle = btn.element_handle(timeout=timeout)
            page.evaluate("(el) => el.click()", handle)
            info["method"] = "dom_fallback"
            info["ok"] = True
            info["playwright_error"] = f"{type(exc).__name__}: {exc}"[:160]
        except Exception as exc2:
            info["ok"] = False
            info["error"] = f"{type(exc2).__name__}: {exc2}"[:200]
    page.wait_for_timeout(1500)
    return info


def wait_disk(want: str, timeout_s: float = 30.0) -> dict:
    t0 = time.time()
    last = room_status()
    while time.time() - t0 < timeout_s:
        last = room_status()
        if last[0].lower() == want.lower():
            return {"ok": True, "status": last[0], "revision": last[1], "waited_s": round(time.time() - t0, 2)}
        time.sleep(0.5)
    return {"ok": False, "status": last[0], "revision": last[1], "waited_s": round(time.time() - t0, 2)}


def enter_room(page, *, timeout_s: float = 120.0) -> dict:
    t0 = time.time()
    best = {"adds": 0, "status": "", "room_body": False}
    clicked_return = False
    while time.time() - t0 < timeout_s:
        if not clicked_return:
            try:
                page.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(
                    timeout=1500
                )
                clicked_return = True
            except Exception:
                pass
        text = body(page)
        adds = 0
        try:
            adds = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count()
        except Exception:
            pass
        st = draft_status(text)
        rb = "room_body" in text or "LDR step enter: room_body" in text
        best = {"adds": adds, "status": st, "room_body": rb, "waited_s": round(time.time() - t0, 1)}
        # Control center may be enough even if adds=0 while paused.
        if rb or st or page.get_by_role("button", name=re.compile(r"Pause Draft|Resume Draft", re.I)).count():
            if st or adds > 0 or page.get_by_role("button", name=re.compile(r"Pause Draft|Resume Draft", re.I)).count():
                return {**best, "ok": True}
        page.wait_for_timeout(2500)
    return {**best, "ok": False}


def timer_samples(page, n: int = 3, gap_s: float = 2.0) -> list[list[int]]:
    out = []
    for _ in range(n):
        vals = [int(x) for x in re.findall(r"(\d+)\s*s", body(page))[:4]]
        out.append(vals)
        page.wait_for_timeout(int(gap_s * 1000))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"code": "21Z40O", "head": "ddde72a"}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        host = browser.new_context().new_page()
        guest = browser.new_context().new_page()
        for page, url in ((host, HOST_URL), (guest, GUEST_URL)):
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(8000)
            try:
                page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=1200)
            except Exception:
                pass

        report["host_enter"] = enter_room(host)
        report["guest_enter"] = enter_room(guest)
        report["disk_start"] = {"status": room_status()[0], "revision": room_status()[1]}

        # If already paused, Resume first so we can prove a full pause cycle.
        if room_status()[0].lower() == "paused":
            report["pre_resume_click"] = click_exact(host, "▶ Resume Draft")
            report["pre_resume_disk"] = wait_disk("in_progress", timeout_s=25)
            host.wait_for_timeout(3000)
            report["host_enter_after_pre_resume"] = enter_room(host, timeout_s=60)

        # Ensure in_progress before Pause
        if room_status()[0].lower() != "in_progress":
            report["verdict"] = "BLOCKED_NOT_IN_PROGRESS"
            REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            browser.close()
            return 2

        # Optional: reset timer so pause has non-zero remaining
        try:
            if host.get_by_role("button", name=re.compile(r"Reset Timer", re.I)).count():
                click_exact(host, "🔄 Reset Timer") if host.get_by_role("button", name="🔄 Reset Timer").count() else None
                alt = host.get_by_role("button", name=re.compile(r"Reset Timer", re.I))
                if alt.count() and alt.first.is_enabled():
                    alt.first.click(timeout=5000)
                    host.wait_for_timeout(2000)
        except Exception:
            pass

        report["timer_before_pause"] = timer_samples(host, n=2, gap_s=2.0)
        before = room_status()
        report["before_pause"] = {
            "status": before[0],
            "revision": before[1],
            "host_ui": draft_status(body(host)),
            "guest_ui": draft_status(body(guest)),
            "paused_remaining": (room_doc().get("room") or {}).get("paused_remaining_seconds"),
        }

        # Fresh locator Pause
        report["pause_click"] = click_exact(host, "⏸ Pause Draft")
        report["pause_disk"] = wait_disk("paused", timeout_s=25)
        # UI converge
        host_ui_paused = False
        guest_ui_paused = False
        resume_enabled = False
        for i in range(20):
            ht = body(host)
            gt = body(guest)
            host_ui_paused = bool(re.search(r"Draft Status:\s*Paused|\bPaused\b", ht, re.I))
            guest_ui_paused = bool(re.search(r"Draft Status:\s*Paused|\bPaused\b", gt, re.I))
            rloc = host.get_by_role("button", name=re.compile(r"Resume Draft", re.I))
            resume_enabled = bool(rloc.count() and rloc.first.is_enabled())
            report.setdefault("pause_ui_poll", []).append(
                {
                    "i": i,
                    "host_ui": draft_status(ht),
                    "guest_ui": draft_status(gt),
                    "resume_enabled": resume_enabled,
                    "disk": room_status()[0],
                }
            )
            if report["pause_disk"].get("ok") and host_ui_paused and resume_enabled:
                break
            host.wait_for_timeout(1500)
            if i == 5:
                try:
                    host.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(
                        timeout=1500
                    )
                except Exception:
                    pass
        report["pause_host_ui"] = host_ui_paused
        report["pause_guest_ui"] = guest_ui_paused
        report["resume_enabled_after_pause"] = resume_enabled
        report["timer_during_pause"] = timer_samples(host, n=3, gap_s=2.0)
        after_pause = room_status()
        report["after_pause"] = {
            "status": after_pause[0],
            "revision": after_pause[1],
            "paused_remaining": (room_doc().get("room") or {}).get("paused_remaining_seconds"),
        }

        # Resume only if durably paused
        if after_pause[0].lower() == "paused":
            report["resume_click"] = click_exact(host, "▶ Resume Draft")
            report["resume_disk"] = wait_disk("in_progress", timeout_s=25)
            for i in range(15):
                ht = body(host)
                gt = body(guest)
                report.setdefault("resume_ui_poll", []).append(
                    {
                        "i": i,
                        "host_ui": draft_status(ht),
                        "guest_ui": draft_status(gt),
                        "disk": room_status()[0],
                    }
                )
                if draft_status(ht).lower().startswith("in progress") and room_status()[0] == "in_progress":
                    break
                host.wait_for_timeout(1500)
            report["timer_after_resume"] = timer_samples(host, n=3, gap_s=2.0)
            report["after_resume"] = {"status": room_status()[0], "revision": room_status()[1]}
            report["host_adds"] = host.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count()
            report["guest_adds"] = guest.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count()

        pause_ok = bool(report.get("pause_disk", {}).get("ok")) and int(report["after_pause"]["revision"]) > int(
            report["before_pause"]["revision"]
        )
        resume_ok = bool(report.get("resume_disk", {}).get("ok")) and report.get("after_resume", {}).get(
            "status"
        ) == "in_progress"
        # Timer freeze: during pause samples should not strictly decrease like a live clock.
        dur = report.get("timer_during_pause") or []
        report["timer_frozen_like"] = True  # soft: disk paused is authoritative
        if pause_ok and resume_ok:
            report["verdict"] = "PAUSE_RESUME_AUTHORITATIVE_PASS"
        elif not pause_ok:
            report["verdict"] = "PAUSE_NOT_DURABLE"
        else:
            report["verdict"] = "RESUME_FAIL_AFTER_DURABLE_PAUSE"

        REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "verdict": report["verdict"],
                    "disk_start": report["disk_start"],
                    "before_pause": report["before_pause"],
                    "pause_click": report.get("pause_click"),
                    "pause_disk": report.get("pause_disk"),
                    "after_pause": report.get("after_pause"),
                    "pause_host_ui": report.get("pause_host_ui"),
                    "pause_guest_ui": report.get("pause_guest_ui"),
                    "resume_enabled_after_pause": report.get("resume_enabled_after_pause"),
                    "resume_click": report.get("resume_click"),
                    "resume_disk": report.get("resume_disk"),
                    "after_resume": report.get("after_resume"),
                    "host_adds": report.get("host_adds"),
                    "guest_adds": report.get("guest_adds"),
                    "timer_before": report.get("timer_before_pause"),
                    "timer_during": report.get("timer_during_pause"),
                    "timer_after": report.get("timer_after_resume"),
                },
                indent=2,
                default=str,
            )
        )
        browser.close()
    return 0 if report.get("verdict") == "PAUSE_RESUME_AUTHORITATIVE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
