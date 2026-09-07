"""Diagnose Shared Draft Pause click → durable disk mutation (read-only repro)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "tb_probe"
ROOM = ROOT / "data" / "draft_rooms" / "21Z40O.json"
HOST_LOG = ROOT / "data" / "tb_probe" / "server_manager" / "host_8511.log"
HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"
REPORT = OUT / "pause_durable_diag.json"


def room_snap() -> dict:
    raw = ROOM.read_text(encoding="utf-8")
    doc = json.loads(raw)
    room = doc.get("room") if isinstance(doc.get("room"), dict) else {}
    return {
        "status": doc.get("status"),
        "revision": doc.get("revision"),
        "room_status": room.get("status"),
        "pick": room.get("current_pick_index") or doc.get("current_pick_index"),
        "paused_remaining": room.get("paused_remaining_seconds") or doc.get("paused_remaining_seconds"),
        "updated_at": doc.get("updated_at"),
        "bytes": len(raw),
    }


def body(page) -> str:
    try:
        return page.inner_text("body", timeout=20000)
    except Exception:
        return ""


def log_tail_match(path: Path, start_size: int, needle: str) -> list[str]:
    if not path.is_file():
        return []
    data = path.read_bytes()[start_size:]
    text = data.decode("utf-8", errors="replace")
    return [ln for ln in text.splitlines() if needle.lower() in ln.lower()][-40:]


def wait_interactive(page, timeout_s: float = 90.0) -> int:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            n = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count()
        except Exception:
            n = 0
        if n > 0:
            return n
        try:
            page.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(
                timeout=1500
            )
        except Exception:
            pass
        page.wait_for_timeout(2500)
    return 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"code": "21Z40O", "git_head": "ddde72a", "timeline": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        host = browser.new_context().new_page()
        guest = browser.new_context().new_page()

        for page, url, name in ((host, HOST_URL, "host"), (guest, GUEST_URL, "guest")):
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(8000)
            try:
                page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=1200)
            except Exception:
                pass
            adds = wait_interactive(page)
            report[f"{name}_adds"] = adds

        before = room_snap()
        report["before"] = before
        ht = body(host)
        report["before_host_status"] = (
            m.group(0) if (m := re.search(r"Draft Status:[^\n]+", ht)) else None
        )
        report["before_timer"] = re.findall(r"(\d+)\s*s", ht)[:4]

        pause_btns = []
        for i in range(min(host.get_by_role("button").count(), 150)):
            try:
                t = (host.get_by_role("button").nth(i).inner_text(timeout=400) or "").strip()
            except Exception:
                continue
            if re.search(r"Pause", t, re.I):
                loc = host.get_by_role("button").nth(i)
                pause_btns.append(
                    {
                        "label": t,
                        "enabled": loc.is_enabled(),
                        "visible": loc.is_visible(),
                    }
                )
        report["pause_buttons"] = pause_btns

        # Fresh locator on exact authoritative control
        loc = host.get_by_role("button", name="⏸ Pause Draft")
        if loc.count() == 0:
            loc = host.get_by_role("button", name=re.compile(r"Pause Draft", re.I))
        report["pause_locator_count"] = loc.count()
        report["pause_enabled"] = loc.first.is_enabled() if loc.count() else False
        report["pause_visible"] = loc.first.is_visible() if loc.count() else False

        log_size = HOST_LOG.stat().st_size if HOST_LOG.is_file() else 0
        t_click = time.time()

        # Method A: Playwright locator click
        click_a = {"method": "playwright_locator"}
        try:
            loc.first.click(timeout=8000, no_wait_after=False)
            click_a["ok"] = True
        except Exception as exc:
            click_a["ok"] = False
            click_a["error"] = f"{type(exc).__name__}: {exc}"[:200]
        host.wait_for_timeout(1500)
        mid_a = room_snap()
        click_a["disk_after_1_5s"] = mid_a
        report["click_a"] = click_a
        report["timeline"].append({"t": time.time() - t_click, "event": "after_playwright_click", **mid_a})

        # If still in_progress, Method B: DOM el.click()
        click_b = {"method": "dom_evaluate_click"}
        if str(mid_a.get("status") or "").lower() != "paused":
            try:
                loc2 = host.get_by_role("button", name=re.compile(r"Pause Draft", re.I)).first
                loc2.wait_for(state="visible", timeout=5000)
                handle = loc2.element_handle(timeout=5000)
                host.evaluate("(el) => el.click()", handle)
                click_b["ok"] = True
            except Exception as exc:
                click_b["ok"] = False
                click_b["error"] = f"{type(exc).__name__}: {exc}"[:200]
            for i in range(20):
                snap = room_snap()
                report["timeline"].append({"t": time.time() - t_click, "i": i, **snap})
                if str(snap.get("status") or "").lower() == "paused":
                    break
                # also catch empty/partial write
                host.wait_for_timeout(500)
            click_b["disk_final"] = room_snap()
        else:
            click_b["skipped"] = "already_paused_after_playwright"
            click_b["disk_final"] = mid_a
        report["click_b"] = click_b

        after = room_snap()
        report["after"] = after
        host.wait_for_timeout(3000)
        guest.wait_for_timeout(2000)
        ht2 = body(host)
        gt2 = body(guest)
        report["after_host_status"] = (
            m.group(0) if (m := re.search(r"Draft Status:[^\n]+", ht2)) else None
        )
        report["after_guest_status"] = (
            m.group(0) if (m := re.search(r"Draft Status:[^\n]+", gt2)) else None
        )
        report["after_timer_host"] = re.findall(r"(\d+)\s*s", ht2)[:4]
        report["after_timer_guest"] = re.findall(r"(\d+)\s*s", gt2)[:4]
        report["resume_host"] = bool(re.search(r"Resume Draft", ht2, re.I))
        report["resume_guest"] = bool(re.search(r"Resume Draft", gt2, re.I))
        report["resume_enabled_host"] = False
        try:
            rloc = host.get_by_role("button", name=re.compile(r"Resume Draft", re.I)).first
            report["resume_enabled_host"] = rloc.is_enabled()
            report["resume_label"] = (rloc.inner_text(timeout=1000) or "").strip()
        except Exception:
            pass

        report["host_log_pause_hits"] = log_tail_match(HOST_LOG, log_size, "pause")
        report["host_log_branch"] = log_tail_match(HOST_LOG, log_size, "PAUSE_BRANCH")
        report["host_log_button_returned"] = log_tail_match(HOST_LOG, log_size, "PAUSE_BUTTON")

        paused = str(after.get("status") or "").lower() == "paused"
        rev_advanced = int(after.get("revision") or 0) > int(before.get("revision") or 0)
        if paused and rev_advanced:
            report["classification"] = "PAUSE_OK_DURABLE"
        elif paused and not rev_advanced:
            report["classification"] = "PAUSE_DISK_STATUS_WITHOUT_REVISION"
        elif click_a.get("ok") and not paused:
            # check if handler logs present
            if report["host_log_branch"]:
                report["classification"] = "PAUSE_ROOM_MUTATION_REJECTED_OR_WRITE_NOT_PERSISTED"
            elif report["host_log_button_returned"]:
                returned_true = any("true" in ln.lower() for ln in report["host_log_button_returned"])
                report["classification"] = (
                    "PAUSE_HANDLER_NOT_ENTERED"
                    if not returned_true
                    else "PAUSE_ROOM_WRITE_NOT_PERSISTED"
                )
            else:
                report["classification"] = "PAUSE_WIDGET_TRANSPORT_NOT_DELIVERED"
        else:
            report["classification"] = "PAUSE_CLICK_HARNESS_MISS_OR_TRANSPORT"

        (OUT / "PAD01_host_after_pause.txt").write_text(ht2[:16000], encoding="utf-8")
        (OUT / "PAD02_guest_after_pause.txt").write_text(gt2[:16000], encoding="utf-8")
        REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "classification": report["classification"],
                    "before": before,
                    "after": after,
                    "click_a": click_a,
                    "click_b": {k: click_b.get(k) for k in ("method", "ok", "skipped", "error", "disk_final")},
                    "pause_buttons": pause_btns,
                    "resume_enabled_host": report["resume_enabled_host"],
                    "log_branch_n": len(report["host_log_branch"]),
                    "log_button_n": len(report["host_log_button_returned"]),
                },
                indent=2,
                default=str,
            )
        )
        browser.close()
    return 0 if report.get("classification") == "PAUSE_OK_DURABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
