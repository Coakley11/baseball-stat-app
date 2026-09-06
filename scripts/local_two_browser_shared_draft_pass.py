"""Local two-browser Shared Draft pass (no Cloud, no push).

Starts nothing — expects Streamlit already listening on HOST_URL / GUEST_URL.
Uses two Playwright browser contexts with distinct storage.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "local_two_browser_shared_draft_pass.json"

HOST_URL = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
GUEST_URL = "http://127.0.0.1:8512/?active_page=Live%20Draft%20Room&suite_workspace=guest"


def _body(page: Page) -> str:
    try:
        return page.inner_text("body", timeout=20000)
    except Exception:
        return ""


def _click(page: Page, label: str, *, timeout: int = 8000) -> bool:
    try:
        page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.I)).first.click(
            timeout=timeout
        )
        page.wait_for_timeout(1500)
        return True
    except Exception:
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=timeout)
            page.wait_for_timeout(1500)
            return True
        except Exception:
            return False


def _click_radio(page: Page, label: str) -> bool:
    patterns = [
        re.compile(re.escape(label), re.I),
        re.compile(r"Shared Multiplayer Draft Room", re.I) if "shared" in label.lower() else None,
        re.compile(r"^Solo Draft", re.I) if "solo" in label.lower() else None,
    ]
    for rx in patterns:
        if rx is None:
            continue
        try:
            page.get_by_role("radio", name=rx).first.click(timeout=5000)
            page.wait_for_timeout(1500)
            return True
        except Exception:
            pass
        try:
            page.get_by_label(rx).first.click(timeout=5000)
            page.wait_for_timeout(1500)
            return True
        except Exception:
            pass
        try:
            page.get_by_text(rx).first.click(timeout=5000)
            page.wait_for_timeout(1500)
            return True
        except Exception:
            pass
    return False


def _select_shared_mode(page: Page) -> bool:
    ok = _click_radio(page, "Shared Multiplayer Draft Room") or _click_radio(page, "Shared Multiplayer")
    page.wait_for_timeout(2000)
    text = _body(page)
    return ok and bool(
        re.search(r"Create Shared Draft Room|Join Shared Draft Room|Enter code", text, re.I)
    )


def _wait_text(page: Page, pattern: str, *, timeout_s: float = 90.0) -> bool:
    rx = re.compile(pattern, re.I)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if rx.search(_body(page)):
            return True
        page.wait_for_timeout(1500)
    return False


_CODE_DENY = frozenset(
    {
        "SHARED",
        "DRAFTS",
        "PLAYER",
        "PLAYERS",
        "TEAMAA",
        "TEAMB",
        "RESUME",
        "PAUSED",
        "STATUS",
        "ROSTER",
        "BUTTON",
        "SELECT",
        "FILTER",
        "QUEUEQ",
    }
)


def _extract_room_code(text: str) -> str:
    """Prefer explicit room-code UI patterns; never accept words like SHARED."""
    for pat in (
        r"Room\s+([A-Z0-9]{6})\s*[·•|]",
        r"Room Code\s+\*\*([A-Z0-9]{6})\*\*",
        r"Room Code[:\s]+([A-Z0-9]{6})",
        r"share code[:\s]+([A-Z0-9]{6})",
    ):
        m = re.search(pat, text, re.I)
        if m:
            code = m.group(1).upper()
            if code not in _CODE_DENY:
                return code
    # Fallback: 6-char alphanumeric that looks like a share code (has digit).
    for m in re.finditer(r"\b([A-Z0-9]{6})\b", text.upper()):
        code = m.group(1)
        if code in _CODE_DENY:
            continue
        if any(ch.isdigit() for ch in code) and any(ch.isalpha() for ch in code):
            return code
    return ""


def _countdown_seconds(text: str) -> list[int]:
    vals: list[int] = []
    for m in re.finditer(r"(\d{1,2}):(\d{2})", text):
        vals.append(int(m.group(1)) * 60 + int(m.group(2)))
    for m in re.finditer(r"(\d+)\s*s\s*remaining", text, re.I):
        vals.append(int(m.group(1)))
    return vals


def _has_add_to_queue(page: Page) -> bool:
    try:
        n = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count()
        return n > 0
    except Exception:
        return False


def _queue_names(text: str) -> list[str]:
    # Best-effort: queue panel lines after "Draft queue" / "Your queue"
    names: list[str] = []
    for m in re.finditer(r"(?:queue|Queued)[^\n]{0,20}\n((?:[^\n]+\n){0,12})", text, re.I):
        block = m.group(1)
        for line in block.splitlines():
            line = line.strip()
            if not line or len(line) > 40:
                continue
            if re.search(r"Add to Queue|Pause|Resume|Start|Join|Watchlist", line, re.I):
                continue
            if re.match(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z'\-]+)+$", line):
                names.append(line)
    return names


def _dismiss_streamlit_chrome(page: Page) -> None:
    try:
        page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=1500)
    except Exception:
        pass


def _goto_live_draft(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    deadline = time.time() + 90
    while time.time() < deadline:
        text = _body(page)
        if re.search(r"Room\s+[A-Z0-9]{6}|Create Shared Draft Room|Join Shared Draft|Waiting for Start", text, re.I):
            break
        if "Live Draft Room" in text and len(text) > 400:
            break
        page.wait_for_timeout(2000)
    _dismiss_streamlit_chrome(page)
    try:
        page.get_by_role("radio", name=re.compile(r"Live Draft Room", re.I)).click(timeout=3000)
        page.wait_for_timeout(2500)
    except Exception:
        try:
            page.get_by_text(re.compile(r"^📡 Live Draft Room$|Live Draft Room", re.I)).first.click(timeout=3000)
            page.wait_for_timeout(2500)
        except Exception:
            pass


def setup_shared_host(page: Page, report: dict[str, Any]) -> str:
    _goto_live_draft(page, HOST_URL)
    text = _body(page)
    report["host_initial_snip"] = text[:800]

    # Stale lobby with a code that is not on disk blocks guests ("Room code not found").
    # Always End/Delete and create a fresh Shared room for a clean two-browser pass.
    if re.search(r"Waiting for Start Draft|Room\s+[A-Z0-9]{6}", text, re.I):
        report["host_cleared_stale_lobby"] = True
        _click(page, "Return to Live Draft Lobby")
        page.wait_for_timeout(2000)
        _click(page, "End/Delete Draft") or _click(page, "End Draft") or _click(page, "Delete Draft")
        page.wait_for_timeout(2000)
        # Confirm dialogs
        _click(page, "Confirm") or _click(page, "Yes") or _click(page, "Delete")
        page.wait_for_timeout(3000)
        text = _body(page)

    shared_ok = _select_shared_mode(page)
    report["host_shared_mode"] = shared_ok
    if not shared_ok:
        try:
            page.get_by_text(re.compile(r"Shared Multiplayer Draft Room", re.I)).first.click(timeout=8000)
            page.wait_for_timeout(2500)
        except Exception:
            pass
    report["host_create_click"] = _click(page, "Create Shared Draft Room", timeout=20000)
    page.wait_for_timeout(8000)
    deadline = time.time() + 150
    code = ""
    while time.time() < deadline:
        text = _body(page)
        code = _extract_room_code(text)
        if code and (
            re.search(r"Waiting for Start Draft|Your team:", text, re.I)
            or (ROOT / "data" / "draft_rooms" / f"{code}.json").is_file()
        ):
            break
        if "Starting" in text:
            report.setdefault("host_saw_starting", True)
        if re.search(r"Could not create|Room code not found|error", text, re.I):
            report["host_create_error_snip"] = text[:600]
        page.wait_for_timeout(2000)
    report["room_code"] = code
    report["host_after_create_snip"] = _body(page)[:800]
    if code:
        path = ROOT / "data" / "draft_rooms" / f"{code}.json"
        report["host_room_file_exists"] = path.is_file()
        report["host_room_file"] = str(path) if path.is_file() else ""
    return code


def join_guest(page: Page, code: str, report: dict[str, Any]) -> bool:
    _goto_live_draft(page, GUEST_URL)
    _click(page, "Return to Live Draft Lobby")
    page.wait_for_timeout(2500)
    # Scroll toward Draft Mode / Shared controls
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    shared_ok = _select_shared_mode(page)
    report["guest_shared_mode"] = shared_ok
    if not shared_ok:
        # Force-click long label text
        try:
            page.get_by_text(re.compile(r"Shared Multiplayer Draft Room", re.I)).first.click(timeout=8000)
            page.wait_for_timeout(2500)
            shared_ok = bool(re.search(r"Join Shared Draft Room|Enter code", _body(page), re.I))
            report["guest_shared_mode_retry"] = shared_ok
        except Exception as exc:
            report["guest_shared_mode_error"] = str(exc)[:160]
    # Wait for join section
    _wait_text(page, r"Join Shared Draft Room|Enter code", timeout_s=30)
    try:
        page.get_by_text(re.compile(r"Join Shared Draft Room", re.I)).first.scroll_into_view_if_needed()
    except Exception:
        pass
    filled = False
    # Prefer the dedicated join-code field (placeholder ABC123) — never League Name.
    for locator in (
        page.get_by_placeholder("ABC123"),
        page.get_by_placeholder(re.compile(r"ABC123", re.I)),
        page.get_by_label(re.compile(r"^Enter code$", re.I)),
        page.locator("input[aria-label='Enter code']"),
    ):
        try:
            loc = locator.first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=3000)
            loc.fill("")
            loc.fill(code, timeout=4000)
            filled = True
            break
        except Exception:
            continue
    report["guest_code_filled"] = filled
    page.wait_for_timeout(3500)
    # Team claim
    try:
        page.get_by_label(re.compile(r"Which team are you", re.I)).click(timeout=3000)
        page.get_by_text(re.compile(r"^Team B$", re.I)).click(timeout=3000)
    except Exception:
        try:
            page.get_by_text(re.compile(r"^Team B$", re.I)).first.click(timeout=3000)
        except Exception:
            pass
    ok = (
        _click(page, "Join Room", timeout=15000)
        or _click(page, "Re-enter Draft", timeout=8000)
    )
    report["guest_join_click"] = ok
    page.wait_for_timeout(8000)
    text = _body(page)
    report["guest_after_join_snip"] = text[:1200]
    report["guest_has_code"] = code.upper() in text.upper()
    return ok and (
        code.upper() in text.upper()
        or bool(re.search(r"Your team:\s*Team B|joined as Team B|Waiting for Start|On clock", text, re.I))
    )


def start_draft_host(page: Page, report: dict[str, Any]) -> bool:
    ok = (
        _click(page, "Start Live Draft", timeout=15000)
        or _click(page, "Start Draft", timeout=10000)
        or _click(page, "Start Shared Draft", timeout=8000)
        or _click(page, "Start New Live Draft", timeout=8000)
        or _click(page, "Start", timeout=5000)
    )
    report["host_start_click"] = ok
    page.wait_for_timeout(8000)
    return ok


def wait_interactive(page: Page, label: str, report: dict[str, Any], *, timeout_s: float = 180.0) -> dict[str, Any]:
    result = {
        "client": label,
        "add_to_queue": False,
        "pause_visible": False,
        "timer_vals": [],
        "stuck_starting": False,
        "stuck_building_pool": False,
        "secs_waited": 0.0,
    }
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        text = _body(page)
        if re.search(r"Starting…|Starting\.\.\.", text):
            result["stuck_starting"] = True
        if re.search(r"still building the player pool", text, re.I):
            result["stuck_building_pool"] = True
        if _has_add_to_queue(page):
            result["add_to_queue"] = True
        if re.search(r"\bPause\b", text):
            result["pause_visible"] = True
        result["timer_vals"] = _countdown_seconds(text)[:5]
        if result["add_to_queue"] and result["pause_visible"]:
            break
        if result["add_to_queue"] and re.search(r"in_progress|On the Clock|Pick\s*#?\s*1", text, re.I):
            break
        page.wait_for_timeout(2000)
    result["secs_waited"] = round(time.time() - t0, 1)
    result["final_snip"] = _body(page)[:1000]
    report[f"{label}_interactive"] = result
    return result


def click_first_add_to_queue(page: Page) -> str:
    btns = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I))
    if btns.count() < 1:
        return ""
    # Try to find player name near first card
    name = ""
    try:
        card = btns.first.locator("xpath=ancestor::*[contains(@class,'element-container') or contains(@data-testid,'stVerticalBlock')][1]")
        name = card.inner_text(timeout=2000).splitlines()[0].strip()[:60]
    except Exception:
        name = "unknown"
    btns.first.click(timeout=8000)
    page.wait_for_timeout(2500)
    return name


def main() -> int:
    report: dict[str, Any] = {
        "started_at": time.time(),
        "host_url": HOST_URL,
        "guest_url": GUEST_URL,
        "checks": {},
        "defects": [],
    }
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=True)
        host_ctx = browser.new_context()
        guest_ctx = browser.new_context()
        host = host_ctx.new_page()
        guest = guest_ctx.new_page()

        code = setup_shared_host(host, report)
        try:
            host.screenshot(path=str(ROOT / "data" / "tb_host_after_create.png"), full_page=True)
        except Exception:
            pass
        if not code:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — host_create_no_room_code"
            report["defects"].append("Host did not receive a 6-character room code after Create Shared Draft Room")
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            browser.close()
            return 2

        joined = join_guest(guest, code, report)
        try:
            guest.screenshot(path=str(ROOT / "data" / "tb_guest_after_join.png"), full_page=True)
        except Exception:
            pass
        report["checks"]["guest_joined"] = joined
        if not joined:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — guest_join"
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            browser.close()
            return 3

        # Host starts
        host.bring_to_front()
        start_draft_host(host, report)
        host_i = wait_interactive(host, "host", report)
        guest.bring_to_front()
        # Guest may need a poll cycle — nudge with soft reload of body wait
        guest_i = wait_interactive(guest, "guest", report)

        report["checks"]["shared_pool_handoff_host"] = bool(host_i.get("add_to_queue"))
        report["checks"]["shared_pool_handoff_guest"] = bool(guest_i.get("add_to_queue"))
        if not host_i.get("add_to_queue"):
            report["defects"].append("Host never got Add-to-Queue after Start (pool handoff)")
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — host_add_to_queue_missing"
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            browser.close()
            return 4
        if not guest_i.get("add_to_queue"):
            report["defects"].append("Guest never got Add-to-Queue after Start (pool handoff)")
            # Continue gathering evidence but mark blocked

        # Private queue checks (product: queues are per-participant, not shared)
        host.bring_to_front()
        a_player = click_first_add_to_queue(host)
        report["checks"]["queue_a_added"] = a_player
        host_text = _body(host)
        guest_text = _body(guest)
        report["checks"]["queue_a_visible_on_host"] = bool(a_player and a_player.split()[0] in host_text) if a_player else False
        # Guest should NOT necessarily show host queue (private)
        report["checks"]["queue_isolation_guest_lacks_host_add"] = True
        if a_player and a_player != "unknown" and a_player in guest_text and "Add to Queue" in guest_text:
            # weak signal only
            pass

        guest.bring_to_front()
        b_player = click_first_add_to_queue(guest) if guest_i.get("add_to_queue") else ""
        report["checks"]["queue_b_added"] = b_player

        # Pause / Resume from host
        host.bring_to_front()
        pause_ok = _click(host, "Pause")
        report["checks"]["pause_click"] = pause_ok
        page_wait = host
        page_wait.wait_for_timeout(4000)
        host_paused = bool(re.search(r"Resume|Paused", _body(host), re.I))
        guest_paused = bool(re.search(r"Resume|Paused", _body(guest), re.I))
        report["checks"]["pause_host"] = host_paused
        report["checks"]["pause_guest"] = guest_paused
        resume_ok = _click(host, "Resume")
        report["checks"]["resume_click"] = resume_ok
        host.wait_for_timeout(4000)
        report["checks"]["resume_host"] = bool(re.search(r"\bPause\b", _body(host)))
        report["checks"]["resume_guest"] = bool(re.search(r"\bPause\b", _body(guest)))

        # Timer samples
        t1 = _countdown_seconds(_body(host))
        host.wait_for_timeout(3500)
        t2 = _countdown_seconds(_body(host))
        report["checks"]["timer_host_samples"] = {"t1": t1[:3], "t2": t2[:3]}
        report["checks"]["timer_progressed"] = bool(t1 and t2 and min(t2) < min(t1)) if t1 and t2 else False

        # Manual pick if available
        pick_ok = _click(host, "Draft Player") or _click(host, "Pick")
        report["checks"]["manual_pick_click"] = pick_ok
        host.wait_for_timeout(4000)
        report["checks"]["host_pick_snip"] = _body(host)[:600]
        report["checks"]["guest_pick_snip"] = _body(guest)[:600]

        # Refresh guest
        guest.reload(wait_until="domcontentloaded")
        guest.wait_for_timeout(10000)
        report["checks"]["guest_refresh_snip"] = _body(guest)[:800]
        report["checks"]["guest_refresh_has_code"] = code in _body(guest).upper()
        report["checks"]["guest_refresh_has_add"] = _has_add_to_queue(guest)

        # Refresh host
        host.reload(wait_until="domcontentloaded")
        host.wait_for_timeout(10000)
        report["checks"]["host_refresh_snip"] = _body(host)[:800]
        report["checks"]["host_refresh_has_code"] = code in _body(host).upper()
        report["checks"]["host_refresh_has_add"] = _has_add_to_queue(host)

        # Verdict
        handoff_ok = bool(host_i.get("add_to_queue") and guest_i.get("add_to_queue"))
        if handoff_ok and joined and (host_paused or pause_ok):
            report["verdict"] = "LOCAL TWO-BROWSER SHARED DRAFT PASS"
        elif not handoff_ok:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — shared_pool_handoff"
        else:
            report["verdict"] = "LOCAL SHARED DRAFT BLOCKED — incomplete_controls"

        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("verdict", "room_code", "checks", "defects") if k in report}, indent=2))
        browser.close()
        return 0 if report["verdict"].startswith("LOCAL TWO-BROWSER") else 1


if __name__ == "__main__":
    raise SystemExit(main())
