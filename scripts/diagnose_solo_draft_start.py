"""Fresh-context Playwright diagnostic: Solo Live Draft start workflow only."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
SETUP_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_component_diag=1&solo_diag_timer=10"
)
OUT_DIR = ROOT / "data" / "solo_draft_start_diag"
OUT_JSON = OUT_DIR / "solo_draft_start_diagnostic.json"
POST_CLICK_OBSERVE_S = 45


SCAN_BUTTONS_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const out = [];
  for (const root of roots()) {
    for (const b of root.querySelectorAll('button')) {
      const r = b.getBoundingClientRect();
      const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!t) continue;
      out.push({
        text: t,
        disabled: !!b.disabled,
        ariaDisabled: b.getAttribute('aria-disabled'),
        visible: r.width > 0 && r.height > 0,
        w: Math.round(r.width),
        h: Math.round(r.height),
        testid: b.getAttribute('data-testid') || '',
        kind: b.getAttribute('kind') || '',
      });
    }
  }
  return out;
}"""

SCAN_SETUP_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const numbers = [];
  const radios = [];
  let soloSelected = false;
  for (const root of roots()) {
    for (const inp of root.querySelectorAll('input[type=\"number\"]')) {
      numbers.push({
        aria: inp.getAttribute('aria-label') || '',
        value: inp.value,
        disabled: !!inp.disabled,
      });
    }
    for (const el of root.querySelectorAll('label')) {
      const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t.includes('Solo Draft') || t.includes('Shared Multiplayer')) {
        const input = el.querySelector('input') || (el.htmlFor ? root.getElementById(el.htmlFor) : null);
        radios.push({ label: t, checked: input ? !!input.checked : null });
        if (t.includes('Solo Draft') && input && input.checked) soloSelected = true;
      }
    }
  }
  return { numbers, radios, soloSelected };
}"""

MESSAGES_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const alerts = [];
  for (const root of roots()) {
    for (const el of root.querySelectorAll('[data-testid=\"stAlert\"], [data-baseweb=\"notification\"], .stException')) {
      const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t) alerts.push(t.slice(0, 500));
    }
  }
  const text = roots().map((x) => (x.body ? x.body.innerText : '')).join('\\n');
  const lines = [];
  for (const pat of ['Still working', 'Please wait', 'validation', 'must be', 'error', 'Error:', 'blocked']) {
    if (text.toLowerCase().includes(pat.toLowerCase())) lines.push(pat);
  }
  return { alerts: [...new Set(alerts)], hint_lines: lines };
}"""

STATE_PROBE_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  let mount = null;
  let deploySha = '';
  for (const root of roots()) {
    const m = root.querySelector('#solo-component-mount-diag');
    if (m) {
      mount = {
        diag_timer: m.getAttribute('data-diag-timer') || '',
        diag_remaining: m.getAttribute('data-diag-remaining') || '',
        mounted: m.getAttribute('data-mounted') || '',
        key: m.getAttribute('data-key') || '',
      };
    }
    const d = root.querySelector('#solo-deploy-build');
    if (d) deploySha = d.getAttribute('data-sha') || deploySha;
  }
  const text = roots().map((x) => (x.body ? x.body.innerText : '')).join('\\n');
  const roomMatch = text.match(/Room ID\\s+([A-F0-9]+)/i);
  return {
    deploy_sha: deploySha,
    mount_probe: mount,
    has_pause: /Pause Draft/i.test(text),
    has_start_setup: /Start New Live Draft/i.test(text),
    has_pick: /Pick\\s+\\d+/i.test(text),
    room_id: roomMatch ? roomMatch[1] : '',
    time_remaining_10: /Time remaining[:\\s]+10/i.test(text),
  };
}"""


def _dom_snapshot(page) -> str:
    try:
        return page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              return roots().map((root) => (root.body ? root.body.innerText : '')).join('\\n').slice(0, 12000);
            }"""
        )
    except Exception as exc:
        return f"<snapshot error: {exc}>"


def main() -> int:
    from cloud_streamlit_wake import all_frames_text, goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_solo_ad_isolation_gate import ensure_live_draft_room_for_deploy_probe
    from run_solo_clean_verification import clear_stale_solo_draft, scrape_live_sha
    from run_production_solo_soak import click_btn, dom_counts, set_number

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "setup_url": SETUP_URL,
        "started_at": time.time(),
        "checklist": {},
        "hypotheses": {},
        "console": [],
        "network_errors": [],
        "network_failed_requests": [],
    }

    console_logs: list[dict[str, Any]] = []
    net_errors: list[dict[str, Any]] = []
    failed_reqs: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()

        page.on(
            "console",
            lambda msg: console_logs.append(
                {"type": msg.type, "text": msg.text[:800], "ts": time.time()}
            ),
        )
        page.on(
            "pageerror",
            lambda err: console_logs.append(
                {"type": "pageerror", "text": str(err)[:800], "ts": time.time()}
            ),
        )

        def on_request_failed(req):
            failed_reqs.append(
                {
                    "url": req.url[:300],
                    "failure": req.failure,
                    "ts": time.time(),
                }
            )

        def on_response(resp):
            if resp.status >= 400 and "streamlit" in resp.url.lower():
                net_errors.append(
                    {"url": resp.url[:300], "status": resp.status, "ts": time.time()}
                )

        page.on("requestfailed", on_request_failed)
        page.on("response", on_response)

        wake = goto_and_wake(page, SETUP_URL, timeout_s=240)
        report["wake"] = wake
        page.wait_for_timeout(6000)

        sidebar_clicked = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                for (const el of root.querySelectorAll('label')) {
                  const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
                  if (t.includes('Live Draft Room')) { el.click(); return t; }
                }
              }
              return '';
            }"""
        )
        page.wait_for_timeout(8000)

        ldr_nav_ok = bool(scrape_live_sha(page)) or "Start New Live Draft" in all_frames_text(page)
        report["checklist"]["1_live_draft_room_navigation"] = {
            "ok": ldr_nav_ok,
            "sidebar_click_label": sidebar_clicked,
            "deploy_sha": scrape_live_sha(page),
            "page_url": page.url,
            "query_has_solo_component_diag": "solo_component_diag=1" in page.url,
            "query_has_solo_diag_timer": "solo_diag_timer=10" in page.url,
        }

        report["checklist"]["2_page_title_and_controls"] = {
            "document_title": page.title(),
            "visible_button_labels": [
                b["text"]
                for b in page.evaluate(SCAN_BUTTONS_JS)
                if b.get("visible") and b.get("text")
            ][:40],
            "dom_text_snippet": all_frames_text(page)[:2500],
        }

        setup_before = page.evaluate(SCAN_SETUP_JS)
        report["checklist"]["3_solo_mode_selected"] = {
            "solo_selected_from_dom": setup_before.get("soloSelected"),
            "radios": setup_before.get("radios"),
        }

        if not setup_before.get("soloSelected"):
            page.evaluate(
                """() => {
                  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
                  for (const root of roots()) {
                    for (const el of root.querySelectorAll('label')) {
                      const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
                      if (t.includes('Solo Draft')) { el.click(); return true; }
                    }
                  }
                  return false;
                }"""
            )
            page.wait_for_timeout(3000)
            setup_before = page.evaluate(SCAN_SETUP_JS)
            report["checklist"]["3_solo_mode_selected"]["after_explicit_click"] = setup_before

        clear_stale_solo_draft(page)
        teams_ok = set_number(page, "Number of Teams", "2")
        picks_ok = set_number(page, "Picks per Team", "8")
        page.wait_for_timeout(2500)
        setup_after_numbers = page.evaluate(SCAN_SETUP_JS)
        report["checklist"]["4_teams_and_timer_values"] = {
            "set_number_teams_dispatched": teams_ok,
            "set_number_picks_dispatched": picks_ok,
            "number_inputs_after": setup_after_numbers.get("numbers"),
            "url_timer_param": "solo_diag_timer=10" in page.url,
        }

        buttons = page.evaluate(SCAN_BUTTONS_JS)
        start_matches = [
            b
            for b in buttons
            if "Start New Live Draft" in str(b.get("text") or "")
            or b.get("text") == "Start New Live Draft"
        ]
        report["checklist"]["5_start_button_located"] = {
            "all_start_matches": start_matches,
            "duplicate_start_buttons": len(start_matches),
            "wrong_button_risk": len(start_matches) != 1,
        }

        target = start_matches[0] if len(start_matches) == 1 else (start_matches[0] if start_matches else None)
        report["checklist"]["6_button_enabled"] = {
            "target": target,
            "any_visible_start_disabled": any(
                m.get("visible") and m.get("disabled") for m in start_matches
            ),
        }

        page.screenshot(path=str(OUT_DIR / "before_start_click.png"), full_page=True)
        (OUT_DIR / "before_start_dom.txt").write_text(_dom_snapshot(page), encoding="utf-8")

        messages_before = page.evaluate(MESSAGES_JS)
        report["messages_before_click"] = messages_before

        url_before = page.url
        click_methods: dict[str, Any] = {}

        # Method A: harness evaluate click (current)
        click_methods["evaluate_click_first_match"] = click_btn(
            page, "Start New Live Draft", wait_ms=1500
        )

        # Method B: Playwright locator (preferred for Streamlit on_click)
        try:
            loc = page.get_by_role("button", name=re.compile(r"Start New Live Draft", re.I))
            count = loc.count()
            click_methods["playwright_locator_count"] = count
            if count >= 1:
                btn = loc.first
                click_methods["playwright_first_disabled"] = btn.is_disabled()
                if not btn.is_disabled():
                    btn.click(timeout=15000)
                    click_methods["playwright_click_dispatched"] = True
                else:
                    click_methods["playwright_click_dispatched"] = False
            else:
                click_methods["playwright_click_dispatched"] = False
        except Exception as exc:
            click_methods["playwright_error"] = str(exc)[:500]

        page.wait_for_timeout(2000)
        url_after_immediate = page.url
        report["checklist"]["7_click_dispatched"] = click_methods
        report["checklist"]["8_streamlit_rerun"] = {
            "url_before": url_before,
            "url_after_immediate": url_after_immediate,
            "url_changed": url_before != url_after_immediate,
        }

        page.screenshot(path=str(OUT_DIR / "after_start_click_2s.png"), full_page=True)
        (OUT_DIR / "after_start_click_2s_dom.txt").write_text(
            _dom_snapshot(page), encoding="utf-8"
        )

        timeline: list[dict[str, Any]] = []
        t0 = time.time()
        final_state: dict[str, Any] = {}
        while time.time() - t0 < POST_CLICK_OBSERVE_S:
            state = page.evaluate(STATE_PROBE_JS)
            msgs = page.evaluate(MESSAGES_JS)
            counts = dom_counts(page)
            row = {
                "elapsed_s": round(time.time() - t0, 1),
                "state": state,
                "dom_counts": counts,
                "messages": msgs,
            }
            timeline.append(row)
            final_state = row
            if int(counts.get("Pause Draft") or 0) >= 1 and state.get("room_id"):
                break
            page.wait_for_timeout(2000)

        page.screenshot(path=str(OUT_DIR / "after_observe_final.png"), full_page=True)
        (OUT_DIR / "after_observe_final_dom.txt").write_text(
            _dom_snapshot(page), encoding="utf-8"
        )

        st = final_state.get("state") or {}
        report["checklist"]["9_validation_warning_error"] = final_state.get("messages")
        report["checklist"]["10_draft_id_room_created"] = {
            "room_id": st.get("room_id"),
            "created": bool(st.get("room_id")),
        }
        report["checklist"]["11_room_in_progress"] = {
            "inferred_in_progress": bool(st.get("has_pause")) and bool(st.get("room_id")),
            "has_start_setup_still": st.get("has_start_setup"),
        }
        report["checklist"]["12_pause_and_pick_controls"] = {
            "dom_counts": final_state.get("dom_counts"),
            "has_pick": st.get("has_pick"),
        }
        mount = st.get("mount_probe") or {}
        report["checklist"]["13_ten_second_diag_mount"] = {
            "mount_probe": mount,
            "diag_timer_10": str(mount.get("diag_timer") or "") == "10",
            "time_remaining_10_ui": st.get("time_remaining_10"),
        }
        report["checklist"]["14_console_and_network"] = {
            "console_tail": console_logs[-30:],
            "network_http_errors": net_errors[-20:],
            "failed_requests": failed_reqs[-20:],
        }
        report["post_click_timeline"] = timeline
        report["draft_start_success"] = (
            bool(st.get("room_id"))
            and int((final_state.get("dom_counts") or {}).get("Pause Draft") or 0) >= 1
            and str(mount.get("diag_timer") or "") == "10"
        )

        report["hypotheses"] = {
            "wrong_or_duplicate_start_button": len(start_matches) != 1,
            "start_button_disabled": any(m.get("disabled") for m in start_matches if m.get("visible")),
            "setup_numbers_not_applied": not all(
                str(n.get("value") or "") in ("2", "8")
                for n in (setup_after_numbers.get("numbers") or [])
                if n.get("aria") in ("Number of Teams", "Picks per Team")
            ),
            "solo_mode_not_selected": not (setup_before.get("soloSelected") or setup_after_numbers.get("soloSelected")),
            "query_params_lost": "solo_component_diag=1" not in page.url,
            "evaluate_click_only_no_playwright": click_methods.get("evaluate_click_first_match")
            and not click_methods.get("playwright_click_dispatched"),
            "active_state_detection": report["draft_start_success"],
        }

        report["finished_at"] = time.time()
        context.close()
        browser.close()

    report["console"] = console_logs[-50:]
    report["network_errors"] = net_errors
    report["network_failed_requests"] = failed_reqs
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT_JSON), "draft_start_success": report["draft_start_success"]}, indent=2))
    print("screenshots", str(OUT_DIR))
    return 0 if report["draft_start_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
