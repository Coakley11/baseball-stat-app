"""Proven Cloud Solo draft start steps for Playwright harnesses (not product code)."""

from __future__ import annotations

import re
import time
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
DEFAULT_SETUP_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_component_diag=1&solo_diag_timer=10"
)


def click_sidebar_live_draft_room(page) -> str:
    return str(
        page.evaluate(
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
        or ""
    )


def ensure_live_draft_setup_visible(page, *, settle_ms: int = 8000) -> dict[str, Any]:
    """Navigate sidebar until Live Draft setup (Start New Live Draft) is visible."""
    from cloud_streamlit_wake import all_frames_text
    from run_solo_clean_verification import scrape_live_sha

    info: dict[str, Any] = {"deploy_sha": scrape_live_sha(page)}
    info["sidebar_click_label"] = click_sidebar_live_draft_room(page)
    page.wait_for_timeout(settle_ms)
    info["deploy_sha_after"] = scrape_live_sha(page)
    info["setup_visible"] = "Start New Live Draft" in all_frames_text(page)
    return info


def click_streamlit_button(page, label: str, *, wait_ms: int = 2500) -> dict[str, Any]:
    """Prefer DOM evaluate click (works with Streamlit on_click in component iframe)."""
    from run_production_solo_soak import click_btn

    result: dict[str, Any] = {"label": label, "evaluate_click": False, "playwright_click": False}
    matches = page.evaluate(
        """(label) => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          const out = [];
          for (const root of roots()) {
            for (const b of root.querySelectorAll('button')) {
              const r = b.getBoundingClientRect();
              if (r.width <= 0 || r.height <= 0) continue;
              const t = String(b.innerText || '').replace(/\\s+/g, ' ').trim();
              if (t.includes(label)) out.push({ text: t, disabled: !!b.disabled });
            }
          }
          return out;
        }""",
        label,
    )
    result["matches"] = matches
    result["evaluate_click"] = click_btn(page, label, wait_ms=wait_ms)
    if "/" not in label:
        try:
            loc = page.get_by_role("button", name=re.compile(re.escape(label), re.I))
            if loc.count() >= 1 and not loc.first.is_disabled():
                loc.first.click(timeout=15000)
                result["playwright_click"] = True
                page.wait_for_timeout(wait_ms)
        except Exception as exc:
            result["playwright_error"] = str(exc)[:300]
    result["ok"] = bool(result["evaluate_click"] or result["playwright_click"])
    return result


def clear_stale_solo_draft_on_setup(page) -> dict[str, Any]:
    from cloud_streamlit_wake import all_frames_text

    body = all_frames_text(page)
    if "End/Delete Draft" not in body:
        return {"cleared": False, "reason": "no_end_delete_control"}
    return {"cleared": True, **click_streamlit_button(page, "End/Delete Draft", wait_ms=6000)}


def wait_for_active_solo_diag_draft(
    page,
    *,
    max_wait_s: int = 120,
    require_diag_timer_10: bool = True,
) -> dict[str, Any]:
    from run_production_solo_soak import dom_counts

    meta: dict[str, Any] = {
        "draft_active": False,
        "room_id": "",
        "diag_timer_ok": False,
        "elapsed_s": 0.0,
    }
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        body = page.inner_text("body", timeout=15000)
        if "Room ID" in body:
            m = re.search(r"Room ID\s+([A-F0-9]+)", body, re.I)
            if m:
                meta["room_id"] = m.group(1)
        counts = dom_counts(page)
        mount = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const m = root.querySelector('#solo-component-mount-diag');
                if (m) return {
                  diag_timer: m.getAttribute('data-diag-timer')||'',
                  diag_remaining: m.getAttribute('data-diag-remaining')||'',
                };
              }
              return {};
            }"""
        )
        meta["mount_probe"] = mount
        diag_ok = str(mount.get("diag_timer") or "") == "10" if require_diag_timer_10 else True
        if int(counts.get("Pause Draft") or 0) >= 1 and meta.get("room_id"):
            meta["draft_active"] = True
            meta["diag_timer_ok"] = diag_ok
            if diag_ok:
                meta["elapsed_s"] = round(time.time() - t0, 1)
                return meta
        page.wait_for_timeout(1000)
    meta["elapsed_s"] = round(time.time() - t0, 1)
    return meta


def start_fresh_solo_draft_automation(page, *, setup_url: str = DEFAULT_SETUP_URL) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_production_solo_soak import click_btn, set_number
    from run_solo_clean_verification import clear_stale_solo_draft

    report: dict[str, Any] = {"setup_url": setup_url}
    goto_and_wake(page, setup_url, timeout_s=240)
    page.wait_for_timeout(6000)
    report["navigation"] = ensure_live_draft_setup_visible(page)
    clear_stale_solo_draft(page)
    report["set_teams"] = set_number(page, "Number of Teams", "2")
    report["set_picks"] = set_number(page, "Picks per Team", "8")
    page.wait_for_timeout(2500)
    report["start_click"] = {
        "evaluate_click": click_btn(page, "Start New Live Draft", wait_ms=3500),
    }
    report["start_click"]["ok"] = bool(report["start_click"]["evaluate_click"])
    report.update(wait_for_active_solo_diag_draft(page))
    return report
