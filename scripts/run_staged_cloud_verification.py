"""Staged Cloud deploy verification and Solo timer gate (no 15m blind wait)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
LDR_URL = f"{BASE}/?active_page=Live%20Draft%20Room"
EXPECTED_SHA = "8fade52"
REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "cloud_staged_verification.json"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def read_local_deploy_sha() -> str:
    marker = Path(__file__).resolve().parent.parent / "deploy_commit.txt"
    line = marker.read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


def scrape_all_deploy_signals(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots() {
            const out = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) out.push(f.contentDocument); } catch (e) {}
            }
            return out.filter(Boolean);
          }
          const out = {
            solo_deploy_el: null,
            solo_deploy_comment: '',
            baseball_dev_labels: [],
            build_captions: [],
            body_snippet: '',
            page_title: document.title || '',
            iframe_count: document.querySelectorAll('iframe').length,
            waking: false,
          };
          let allText = '';
          let allHtml = '';
          for (const root of roots()) {
            const body = root.body;
            if (!body) continue;
            allText += (body.innerText || '') + '\\n';
            allHtml += (root.documentElement ? root.documentElement.innerHTML : '') + '\\n';
            const el = root.querySelector('#solo-deploy-build');
            if (el && !out.solo_deploy_el) {
              out.solo_deploy_el = {
                sha: el.getAttribute('data-sha') || '',
                build: el.getAttribute('data-build') || '',
              };
            }
          }
          out.body_snippet = allText.slice(0, 1200);
          const low = allText.toLowerCase();
          out.waking = low.includes('waking up') || low.includes('taking longer than normal');
          const cm = allHtml.match(/solo-deploy-build sha=([0-9a-f]{7})/ig) || [];
          out.solo_deploy_comment = cm.slice(0, 5).join(' | ');
          const labels = allText.match(/baseball-dev-[0-9a-f]{7}/ig) || [];
          out.baseball_dev_labels = [...new Set(labels.map((x) => x.toLowerCase()))];
          const caps = allText.match(/Build `baseball-dev-[0-9a-f]{7}`[^\\n]*/ig) || [];
          out.build_captions = caps.slice(0, 5);
          return out;
        }"""
    )


def scrape_from_page_content(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    m = re.search(r'solo-deploy-build sha=([0-9a-f]{7})', html, re.I)
    if m:
        out["comment_sha"] = m.group(1).lower()
    m2 = re.search(r'id="solo-deploy-build"[^>]*data-sha="([0-9a-f]{7})"', html, re.I)
    if m2:
        out["attr_sha"] = m2.group(1).lower()
    m3 = re.search(r'baseball-dev-([0-9a-f]{7})', html, re.I)
    if m3:
        out["label_sha"] = m3.group(1).lower()
    return out


def wait_app_ready(page, *, timeout_s: int = 180) -> dict[str, Any]:
    from cloud_streamlit_wake import all_frames_text, ensure_app_awake, is_app_asleep, is_app_waking

    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            text = all_frames_text(page)
            if is_app_asleep(text):
                ensure_app_awake(page, timeout_s=min(90, int(deadline - time.time())))
                continue
            probe = scrape_all_deploy_signals(page)
            last = probe
            body = str(probe.get("body_snippet") or "")
            if probe.get("waking") or is_app_waking(text):
                page.wait_for_timeout(3000)
                continue
            if len(body.strip()) > 80 or probe.get("solo_deploy_el") or probe.get("baseball_dev_labels"):
                return {"ready": True, **probe}
            if "Live Draft" in body or "Start New Live Draft" in body:
                return {"ready": True, **probe}
        except Exception as exc:
            last = {"ready": False, "error": f"{type(exc).__name__}:{exc}"}
        page.wait_for_timeout(2500)
    return {"ready": False, **last}


def resolve_observed_sha(signals: dict[str, Any], html_sha: dict[str, str]) -> str:
    el = signals.get("solo_deploy_el") or {}
    for candidate in (
        el.get("sha"),
        html_sha.get("attr_sha"),
        html_sha.get("comment_sha"),
        html_sha.get("label_sha"),
        (signals.get("baseball_dev_labels") or [None])[0],
    ):
        if candidate:
            text = str(candidate).lower()
            m = re.search(r'([0-9a-f]{7})$', text)
            return m.group(1) if m else text[:7]
    return ""


def scrape_state(page) -> dict[str, Any]:
    from run_production_solo_soak import scrape_state as _ss

    return _ss(page)


def dom_counts(page) -> dict[str, int]:
    from run_production_solo_soak import dom_counts as _dc

    return _dc(page)


def click_btn(page, label: str, *, wait_ms: int = 3000) -> bool:
    from run_production_solo_soak import click_btn as _cb

    return _cb(page, label, wait_ms=wait_ms)


def set_number(page, aria: str, val: str) -> bool:
    from run_production_solo_soak import set_number as _sn

    return _sn(page, aria, val)


def select_option_by_label(page, label: str, option: str) -> bool:
    from run_production_solo_soak import select_option_by_label as _so

    return _so(page, label, option)


def main() -> int:
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake

    expected = read_local_deploy_sha() or EXPECTED_SHA
    report: dict[str, Any] = {
        "started_at": time.time(),
        "target_url": LDR_URL,
        "expected_sha": expected,
        "expected_label": f"baseball-dev-{expected}",
        "deploy_commit_txt": expected,
        "local_suite_marker": f"baseball-dev-{expected}",
        "stages": {},
        "errors": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        try:
            wake_info = goto_and_wake(page, LDR_URL, timeout_s=240)
            report["wake"] = wake_info
            ready_probe = wait_app_ready(page, timeout_s=180)
            html = page.content()
            html_sha = scrape_from_page_content(html)
            observed = resolve_observed_sha(ready_probe, html_sha)
            report["stages"]["app_load"] = {
                "ready": bool(ready_probe.get("ready")),
                "page_title": ready_probe.get("page_title"),
                "waking": ready_probe.get("waking"),
                "body_snippet": str(ready_probe.get("body_snippet") or "")[:400],
                "iframe_count": ready_probe.get("iframe_count"),
            }
            report["stages"]["deploy_detection"] = {
                "solo_deploy_el": ready_probe.get("solo_deploy_el"),
                "solo_deploy_comment": ready_probe.get("solo_deploy_comment"),
                "baseball_dev_labels": ready_probe.get("baseball_dev_labels"),
                "build_captions": ready_probe.get("build_captions"),
                "page_content_sha": html_sha,
                "observed_sha": observed,
                "matches_expected": observed == expected,
            }
            report["deployed_sha_observed"] = observed
            if not ready_probe.get("ready"):
                report["errors"].append("app_not_ready")
            if not observed:
                report["errors"].append("deploy_sha_not_observed")
            elif observed != expected:
                report["errors"].append(f"deploy_sha_mismatch:expected={expected}:seen={observed}")
                report["verification_status"] = "not_yet_verified_wrong_build"
                browser.close()
                REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
                REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps(report, indent=2))
                return 2

            if observed != expected:
                pass  # handled above
            report["verification_status"] = "build_confirmed_not_yet_verified"

            # Stage: start solo draft with 30s timer
            if "End/Delete Draft" in page.inner_text("body"):
                click_btn(page, "End/Delete Draft", wait_ms=4000)
            set_number(page, "Number of Teams", "2")
            set_number(page, "Picks per Team", "8")
            select_option_by_label(page, "Timer per Pick", "30 sec")
            page.wait_for_timeout(1500)
            if not click_btn(page, "Start New Live Draft"):
                report["errors"].append("start_button_missing")
            else:
                t0 = time.time()
                active = False
                while time.time() - t0 < 120:
                    d = dom_counts(page)
                    if int(d.get("Pause Draft") or 0) >= 1:
                        active = True
                        break
                    page.wait_for_timeout(1000)
                report["stages"]["draft_start"] = {"active": active, "dom": d}

            # Stage: one natural expiration (~35s)
            prev = scrape_state(page)
            one_exp: dict[str, Any] = {"ok": False}
            t1 = time.time()
            while time.time() - t1 < 90:
                page.wait_for_timeout(2000)
                cur = scrape_state(page)
                board_delta = int(cur.get("boardRows") or 0) - int(prev.get("boardRows") or 0)
                pick_delta = None
                if prev.get("pick") and cur.get("pick"):
                    pick_delta = int(cur["pick"]) - int(prev["pick"])
                timer = cur.get("timer")
                if board_delta >= 1 or pick_delta == 1:
                    one_exp = {
                        "ok": True,
                        "board_delta": board_delta,
                        "pick_delta": pick_delta,
                        "timer_after": timer,
                        "pick_after": cur.get("pick"),
                        "team_after": cur.get("team"),
                        "frozen_at_zero": int(timer or 99) == 0,
                    }
                    break
                if timer == 0 and time.time() - t1 > 40:
                    one_exp = {"ok": False, "frozen_at_zero": True, "timer": 0}
                    break
            report["stages"]["one_natural_expiration"] = one_exp
            if not one_exp.get("ok"):
                report["errors"].append("one_natural_expiration_failed")

            # Stage: four natural expirations (continue from current state)
            exp_events: list[dict[str, Any]] = []
            if one_exp.get("ok"):
                exp_events.append({**one_exp, "index": 1})
                prev = scrape_state(page)
                while len(exp_events) < 4 and time.time() - t1 < 600:
                    page.wait_for_timeout(2000)
                    cur = scrape_state(page)
                    board_delta = int(cur.get("boardRows") or 0) - int(prev.get("boardRows") or 0)
                    pick_delta = None
                    if prev.get("pick") and cur.get("pick"):
                        pick_delta = int(cur["pick"]) - int(prev["pick"])
                    if board_delta >= 1 or pick_delta == 1:
                        exp_events.append(
                            {
                                "index": len(exp_events) + 1,
                                "ok": board_delta <= 1 and (pick_delta == 1 or board_delta == 1),
                                "board_delta": board_delta,
                                "pick_delta": pick_delta,
                                "timer_after": cur.get("timer"),
                                "pick_after": cur.get("pick"),
                                "frozen_at_zero": int(cur.get("timer") or 99) == 0,
                            }
                        )
                        prev = cur
                    elif int(cur.get("timer") or 99) == 0:
                        report.setdefault("timer_frozen_samples", []).append(time.time())
            report["stages"]["four_natural_expirations"] = {
                "count": len(exp_events),
                "required": 4,
                "events": exp_events,
            }
            if len(exp_events) < 4:
                report["errors"].append(f"natural_expirations_low:{len(exp_events)}")

            report["natural_expirations_completed"] = len(exp_events) >= 4
            report["picks_committed"] = len(exp_events)
            report["duplicate_picks"] = sum(1 for e in exp_events if int(e.get("board_delta") or 0) > 1)
            report["missing_picks"] = max(0, 4 - len(exp_events))
            report["timer_frozen_at_zero"] = any(e.get("frozen_at_zero") for e in exp_events)
            report["new_deadlines_after_pick"] = [e.get("timer_after") for e in exp_events]

        except Exception as exc:
            report["errors"].append(f"{type(exc).__name__}:{exc}")
        finally:
            browser.close()

    report["duration_s"] = round(time.time() - float(report["started_at"]), 1)
    if report.get("deployed_sha_observed") == expected and report.get("natural_expirations_completed"):
        report["verification_status"] = "soak_partial_pass"
    elif report.get("deployed_sha_observed") == expected:
        report["verification_status"] = "build_confirmed_soak_incomplete"
    elif not report.get("deployed_sha_observed"):
        report["verification_status"] = "not_yet_verified_deploy_unknown"

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("verification_status") == "soak_partial_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
