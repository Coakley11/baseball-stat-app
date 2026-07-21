"""Run Cloud Live Draft canary + production Solo acceptance via Playwright."""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
CANARY_URL = (
    f"{BASE}/~/+/?ld_accept=1&ld_canary=1&active_page=Live%20Draft%20Room"
)
PROD_URL = f"{BASE}/~/+/?ld_accept=1&active_page=Live%20Draft%20Room"
REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "cloud_live_draft_acceptance.json"


@dataclass
class AcceptanceReport:
    started_at: float = field(default_factory=time.time)
    deploy_build: str = ""
    canary: dict[str, Any] = field(default_factory=dict)
    production: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _body_text(page) -> str:
    try:
        return page.inner_text("body", timeout=15000)
    except Exception:
        return ""


def _wait_for(page, pattern: str, *, timeout_ms: int = 120000) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    rx = re.compile(pattern, re.I)
    while time.time() < deadline:
        if rx.search(_body_text(page)):
            return True
        page.wait_for_timeout(1500)
    return False


def _click_button(page, label: str) -> bool:
    try:
        page.get_by_role("button", name=re.compile(re.escape(label), re.I)).first.click(timeout=8000)
        page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


def _extract_build(text: str) -> str:
    m = re.search(r"baseball-dev-[a-f0-9]+", text, re.I)
    return m.group(0) if m else ""


def _countdown_values(text: str) -> list[int]:
    vals: list[int] = []
    for m in re.finditer(r"(\d{1,2}):(\d{2})", text):
        vals.append(int(m.group(1)) * 60 + int(m.group(2)))
    for m in re.finditer(r"Time remaining:\s*\*\*(\d+)s\*\*", text):
        vals.append(int(m.group(1)))
    for m in re.finditer(r"(\d+)s remaining", text, re.I):
        vals.append(int(m.group(1)))
    return vals


def run_canary(page, report: AcceptanceReport) -> bool:
    page.goto(CANARY_URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(12000)
    text = _body_text(page)
    report.deploy_build = _extract_build(text) or report.deploy_build
    if "Cloud canary requires" in text:
        report.errors.append("canary_gate_blocked")
        report.canary["gate_blocked"] = True
        return False
    if not _wait_for(page, r"Pause"):
        report.errors.append("canary_controls_missing")
        return False

    report.canary["started"] = time.time()
    picks_before = len(re.findall(r"Pick \d+:", text))
    expirations = 0
    t_end = time.time() + 620  # ~10+ minutes budget inside canary phase
    last_rem: int | None = None
    zero_hits = 0
    manual_done = auto_done = pause_done = resume_done = reset_done = False

    while time.time() < t_end and expirations < 4:
        text = _body_text(page)
        picks_now = len(re.findall(r"Pick \d+:", text))
        if picks_now > picks_before:
            expirations += picks_now - picks_before
            picks_before = picks_now
            report.canary.setdefault("expiration_events", []).append(
                {"ts": time.time(), "picks": picks_now, "expirations": expirations}
            )
        vals = _countdown_values(text)
        if vals:
            rem = min(vals)
            if rem == 0:
                zero_hits += 1
            if last_rem is not None and rem > last_rem + 5 and rem > 10:
                report.canary.setdefault("timer_jumps", []).append({"from": last_rem, "to": rem})
            last_rem = rem
        if expirations == 1 and not manual_done:
            if _click_button(page, "Draft Player"):
                manual_done = True
                report.canary["manual_pick"] = time.time()
        if expirations == 2 and not auto_done:
            if _click_button(page, "Auto Pick"):
                auto_done = True
                report.canary["auto_pick"] = time.time()
        if expirations == 2 and not pause_done:
            if _click_button(page, "Pause"):
                pause_done = True
                report.canary["pause"] = time.time()
                page.wait_for_timeout(4000)
        if pause_done and not resume_done:
            if _click_button(page, "Resume"):
                resume_done = True
                report.canary["resume"] = time.time()
        if expirations >= 3 and not reset_done:
            if _click_button(page, "Reset Timer"):
                reset_done = True
                report.canary["reset_timer"] = time.time()
        page.wait_for_timeout(3000)

    text = _body_text(page)
    vals = _countdown_values(text)
    report.canary.update(
        {
            "expirations": expirations,
            "manual_done": manual_done,
            "auto_done": auto_done,
            "pause_done": pause_done,
            "resume_done": resume_done,
            "reset_done": reset_done,
            "zero_hits": zero_hits,
            "countdown_samples": vals[:6],
            "duplicate_countdowns": len(vals) > 1 and max(vals) - min(vals) > 8,
            "board_picks": len(re.findall(r"Pick \d+:", text)),
        }
    )
    ok = (
        expirations >= 4
        and manual_done
        and auto_done
        and pause_done
        and resume_done
        and reset_done
        and not report.canary.get("duplicate_countdowns")
    )
    report.canary["passed"] = ok
    return ok


def run_production(page, report: AcceptanceReport) -> bool:
    page.goto(PROD_URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(12000)
    text = _body_text(page)
    report.deploy_build = _extract_build(text) or report.deploy_build

    # Solo setup: 2 teams, short timer, start draft
    for label in ("Start New Live Draft", "Start new live draft"):
        if _click_button(page, label):
            break
    page.wait_for_timeout(2000)
    for pat in (r"2 teams", r"Two teams", r"Num teams"):
        if re.search(pat, text, re.I):
            break
    # Try common setup controls
    try:
        page.get_by_text(re.compile("teams", re.I)).first.click(timeout=3000)
    except Exception:
        pass
    if _click_button(page, "Start Draft") or _click_button(page, "Start New Live Draft"):
        report.production["start_clicked"] = time.time()
    page.wait_for_timeout(15000)
    text = _body_text(page)
    report.production["start_stage_snippet"] = text[-2500:]
    if "Start Draft stages" in text or "canonical_snapshot_installed" in text:
        report.production["start_diagnostics_visible"] = True

    t_end = time.time() + 620
    expirations = 0
    picks_before = len(re.findall(r"Pick \d+:|drafted", text, re.I))
    while time.time() < t_end and expirations < 4:
        text = _body_text(page)
        picks_now = len(re.findall(r"Pick \d+:|drafted", text, re.I))
        if picks_now > picks_before:
            expirations += picks_now - picks_before
            picks_before = picks_now
        vals = _countdown_values(text)
        if len(vals) > 1 and max(vals) - min(vals) > 8:
            report.production.setdefault("timer_mismatch_events", []).append(vals)
        page.wait_for_timeout(4000)

    report.production.update(
        {
            "expirations": expirations,
            "passed": expirations >= 4,
        }
    )
    return bool(report.production.get("passed"))


def main() -> int:
    from playwright.sync_api import sync_playwright

    report = AcceptanceReport()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        try:
            canary_ok = run_canary(page, report)
            prod_ok = run_production(page, report) if canary_ok else False
        finally:
            browser.close()
    report.canary.setdefault("passed", False)
    report.production.setdefault("passed", False)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report.__dict__, indent=2, default=list), encoding="utf-8")
    print(json.dumps(report.__dict__, indent=2, default=list))
    return 0 if canary_ok and prod_ok else 1


if __name__ == "__main__":
    sys.exit(main())
