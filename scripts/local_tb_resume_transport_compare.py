"""Compare acceptance-style vs probe-style Resume click transport on a paused room."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CODE = "UP9NR7"
ROOM = ROOT / "data" / "draft_rooms" / f"{CODE}.json"
OUT = ROOT / "data" / "tb_probe" / "resume_transport_compare.json"
HOST = "http://127.0.0.1:8511/?active_page=Live%20Draft%20Room&suite_workspace=daniel"


def room_snap() -> dict:
    for _ in range(20):
        try:
            text = ROOM.read_text(encoding="utf-8")
            if not text.strip():
                time.sleep(0.2)
                continue
            doc = json.loads(text)
            room = doc.get("room") if isinstance(doc.get("room"), dict) else {}
            return {
                "doc_status": doc.get("status"),
                "room_status": room.get("status"),
                "revision": doc.get("revision"),
                "paused_remaining": room.get("paused_remaining_seconds"),
            }
        except Exception:
            time.sleep(0.2)
    return {}


def install_ws_hook(page) -> None:
    page.add_init_script(
        """
        (() => {
          window.__resume_ws = { out: [], in: [], clicks: [] };
          const OrigWS = window.WebSocket;
          function Wrapped(url, protocols) {
            const ws = protocols !== undefined ? new OrigWS(url, protocols) : new OrigWS(url);
            const push = (dir, data) => {
              let text = '';
              try {
                if (typeof data === 'string') text = data.slice(0, 800);
                else if (data && data.byteLength !== undefined) text = 'bin:' + data.byteLength;
                else text = String(data).slice(0, 200);
              } catch (e) { text = 'err'; }
              window.__resume_ws[dir].push({ t: Date.now(), text });
              if (window.__resume_ws[dir].length > 80) window.__resume_ws[dir].shift();
            };
            const origSend = ws.send.bind(ws);
            ws.send = (data) => { push('out', data); return origSend(data); };
            ws.addEventListener('message', (ev) => push('in', ev.data));
            return ws;
          }
          Wrapped.prototype = OrigWS.prototype;
          Wrapped.OPEN = OrigWS.OPEN; Wrapped.CLOSED = OrigWS.CLOSED;
          Wrapped.CONNECTING = OrigWS.CONNECTING; Wrapped.CLOSING = OrigWS.CLOSING;
          window.WebSocket = Wrapped;
          document.addEventListener('click', (ev) => {
            const t = ev.target && (ev.target.closest ? ev.target.closest('button') : null);
            const label = t ? String(t.innerText || t.textContent || '').trim().slice(0, 80) : '';
            if (/Resume/i.test(label)) {
              window.__resume_ws.clicks.push({
                t: Date.now(), trusted: !!ev.isTrusted, label,
                disabled: !!(t && t.disabled),
                testid: t ? (t.getAttribute('data-testid') || '') : '',
                key: t ? (t.getAttribute('kind') || t.getAttribute('data-baseweb') || '') : '',
              });
            }
          }, true);
        })();
        """
    )


def probe_resume_dom(page) -> dict:
    return page.evaluate(
        """() => {
          const out = [];
          for (const b of document.querySelectorAll('button')) {
            const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!/Resume Draft/i.test(t)) continue;
            const r = b.getBoundingClientRect();
            out.push({
              text: t.slice(0, 80),
              disabled: !!b.disabled,
              visible: r.width > 0 && r.height > 0,
              testid: b.getAttribute('data-testid') || '',
              aria: b.getAttribute('aria-label') || '',
              className: String(b.className || '').slice(0, 120),
              form: !!b.closest('form'),
              inIframe: false,
            });
          }
          return { count: out.length, buttons: out };
        }"""
    )


def wait_ready(page) -> dict:
    page.wait_for_timeout(8000)
    info = {"ready": False, "loops": 0}
    for i in range(40):
        info["loops"] = i + 1
        try:
            page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=800)
        except Exception:
            pass
        try:
            page.get_by_role("button", name=re.compile(r"Return to Live Draft$", re.I)).first.click(
                timeout=1500
            )
        except Exception:
            pass
        text = page.inner_text("body")
        dom = probe_resume_dom(page)
        loc = page.get_by_role("button", name=re.compile(r"Resume Draft", re.I))
        enabled = bool(loc.count() and not loc.first.is_disabled())
        if CODE in text.upper() and re.search(r"Draft Status:", text, re.I) and enabled:
            info["ready"] = True
            info["dom"] = dom
            info["status_line"] = (
                m.group(0) if (m := re.search(r"Draft Status:[^\n]+", text)) else None
            )
            return info
        page.wait_for_timeout(2000)
    info["dom"] = probe_resume_dom(page)
    return info


def ws_snapshot(page) -> dict:
    try:
        return page.evaluate("() => window.__resume_ws || {}") or {}
    except Exception as exc:
        return {"error": str(exc)[:160]}


def click_acceptance_style(page) -> dict:
    out = {"method": "stBaseButton-primary+Resume Draft"}
    before_ws = len((ws_snapshot(page).get("out") or []))
    try:
        primary = page.locator('[data-testid="stBaseButton-primary"]').filter(
            has_text=re.compile(r"Resume Draft", re.I)
        )
        out["primary_count"] = primary.count()
        role = page.get_by_role("button", name=re.compile(r"Resume Draft", re.I))
        out["role_count"] = role.count()
        out["role_enabled"] = bool(role.count() and not role.first.is_disabled())
        out["dom_before"] = probe_resume_dom(page)
        if primary.count():
            primary.first.scroll_into_view_if_needed(timeout=8000)
            # Re-resolve immediately before click (acceptance pattern)
            primary = page.locator('[data-testid="stBaseButton-primary"]').filter(
                has_text=re.compile(r"Resume Draft", re.I)
            )
            out["click_at"] = time.time()
            primary.first.click(timeout=12000)
            out["ok"] = True
        else:
            out["ok"] = False
            out["error"] = "no_primary"
    except Exception as exc:
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}:{exc}"[:200]
    page.wait_for_timeout(2500)
    snap = ws_snapshot(page)
    outs = snap.get("out") or []
    out["ws_out_after"] = len(outs)
    out["ws_out_delta"] = max(0, len(outs) - before_ws)
    out["ws_out_sample"] = outs[-5:]
    out["ws_clicks"] = snap.get("clicks") or []
    # Heuristic: Streamlit backmsg often binary; count new outs
    out["has_new_ws_out"] = out["ws_out_delta"] > 0
    return out


def click_probe_style(page) -> dict:
    out = {"method": "get_by_role Resume Draft"}
    before_ws = len((ws_snapshot(page).get("out") or []))
    try:
        loc = page.get_by_role("button", name=re.compile(r"Resume Draft", re.I)).first
        out["dom_before"] = probe_resume_dom(page)
        out["enabled"] = not loc.is_disabled()
        loc.scroll_into_view_if_needed(timeout=8000)
        # Fresh resolve
        loc = page.get_by_role("button", name=re.compile(r"Resume Draft", re.I)).first
        out["click_at"] = time.time()
        loc.click(timeout=8000)
        out["ok"] = True
    except Exception as exc:
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}:{exc}"[:200]
    page.wait_for_timeout(2500)
    snap = ws_snapshot(page)
    outs = snap.get("out") or []
    out["ws_out_delta"] = max(0, len(outs) - before_ws)
    out["ws_out_sample"] = outs[-5:]
    out["ws_clicks"] = snap.get("clicks") or []
    out["has_new_ws_out"] = out["ws_out_delta"] > 0
    return out


def wait_disk(status: str, timeout_s: float = 20.0) -> dict:
    t0 = time.time()
    last = room_snap()
    while time.time() - t0 < timeout_s:
        last = room_snap()
        if str(last.get("doc_status") or "").lower() == status:
            last["elapsed_s"] = round(time.time() - t0, 3)
            return last
        time.sleep(0.5)
    last["elapsed_s"] = round(time.time() - t0, 3)
    last["timed_out"] = True
    return last


def main() -> int:
    report: dict = {"code": CODE, "before": room_snap(), "timeline": []}
    if str(report["before"].get("doc_status") or "").lower() != "paused":
        report["error"] = "room_not_paused"
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # --- A: acceptance-style primary click on fresh context ---
        ctx_a = browser.new_context()
        page_a = ctx_a.new_page()
        install_ws_hook(page_a)
        page_a.goto(HOST, wait_until="domcontentloaded", timeout=120000)
        ready_a = wait_ready(page_a)
        report["A_ready"] = ready_a
        # Mimic acceptance delay: snap-like wait + timer sample
        page_a.wait_for_timeout(3000)
        before_a = room_snap()
        click_a = click_acceptance_style(page_a)
        after_a = wait_disk("in_progress", timeout_s=18.0)
        report["A_click"] = click_a
        report["A_before_click"] = before_a
        report["A_after"] = after_a
        report["A_disk_ok"] = str(after_a.get("doc_status") or "").lower() == "in_progress"
        ctx_a.close()

        # If A succeeded, re-pause via probe for B would need pause click; skip if room resumed.
        # Re-open and try B only if still paused; if A failed room still paused.
        still = room_snap()
        report["between"] = still
        if str(still.get("doc_status") or "").lower() != "paused":
            report["B_skipped"] = "room_already_in_progress_after_A"
            # Pause again with product UI to allow B? Prefer keep comparison when A failed.
        else:
            ctx_b = browser.new_context()
            page_b = ctx_b.new_page()
            install_ws_hook(page_b)
            page_b.goto(HOST, wait_until="domcontentloaded", timeout=120000)
            ready_b = wait_ready(page_b)
            report["B_ready"] = ready_b
            # Probe: click immediately after ready (no 3s delay)
            before_b = room_snap()
            click_b = click_probe_style(page_b)
            after_b = wait_disk("in_progress", timeout_s=18.0)
            report["B_click"] = click_b
            report["B_before_click"] = before_b
            report["B_after"] = after_b
            report["B_disk_ok"] = str(after_b.get("doc_status") or "").lower() == "in_progress"
            ctx_b.close()

        browser.close()

    if report.get("A_disk_ok"):
        report["classification"] = "ACCEPTANCE_STYLE_OK"
    elif report.get("B_disk_ok"):
        report["classification"] = "ACCEPTANCE_STYLE_FAIL_PROBE_STYLE_OK"
        if not report.get("A_click", {}).get("has_new_ws_out") and report.get("B_click", {}).get(
            "has_new_ws_out"
        ):
            report["earliest"] = "RESUME_CLICK_EVENT_NO_STREAMLIT_BACKMSG"
        elif report.get("A_click", {}).get("primary_count", 0) != 1:
            report["earliest"] = "RESUME_WRONG_MATCH"
        else:
            report["earliest"] = "RESUME_ACCEPTANCE_CLICK_NO_MUTATION"
    else:
        report["classification"] = "BOTH_FAIL"
        report["earliest"] = "RESUME_BOTH_STYLES_FAIL"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("A_disk_ok") or report.get("B_disk_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
