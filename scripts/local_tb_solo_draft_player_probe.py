"""Focused Solo Start → Draft Player commit probe."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "tb_probe" / "solo_draft_player_probe.json"
PORT = 8532
URL = f"http://127.0.0.1:{PORT}/?active_page=Live%20Draft%20Room&suite_workspace=daniel"
LOG = ROOT / "data" / "tb_probe" / "solo_draft_player_probe_streamlit.log"


def _body(page) -> str:
    try:
        return page.inner_text("body")
    except Exception:
        return ""


def _picks(text: str) -> int | None:
    m = re.search(r"(\d+)\s*/\s*\d+\s*picks made", text, re.I)
    return int(m.group(1)) if m else None


def _wait_http(timeout_s: float = 120.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=3) as resp:
                if int(getattr(resp, "status", 200) or 200) < 500:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


def main() -> int:
    report: dict = {"t0": time.time()}
    # Scrub via existing helper
    scrub = ROOT / "scripts" / "local_tb_scrub_human_clean.py"
    subprocess.run([sys.executable, str(scrub)], cwd=str(ROOT), check=False)

    log_f = open(LOG, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "streamlit_app.py",
            "--server.port",
            str(PORT),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
            "--server.enableCORS",
            "false",
            "--server.enableXsrfProtection",
            "false",
        ],
        cwd=str(ROOT),
        stdout=log_f,
        stderr=subprocess.STDOUT,
    )
    report["pid"] = proc.pid
    try:
        if not _wait_http():
            report["fatal"] = "streamlit_not_ready"
            return 2

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.goto(URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(8000)
            try:
                page.get_by_text(re.compile(r"Always rerun", re.I)).first.click(timeout=2000)
            except Exception:
                pass
            for _ in range(30):
                body = _body(page)
                if "Start New Live Draft" in body or "Solo Draft" in body:
                    break
                page.wait_for_timeout(1000)
            try:
                page.locator("label").filter(has_text=re.compile(r"Live Draft Room")).first.click(
                    timeout=8000
                )
                page.wait_for_timeout(3000)
            except Exception:
                pass

            # End any leftover draft
            for pat in (r"End/Delete Draft", r"End Live Draft", r"Disregard Saved Draft"):
                try:
                    b = page.get_by_role("button", name=re.compile(pat, re.I))
                    if b.count():
                        b.first.click(timeout=3000)
                        page.wait_for_timeout(1500)
                except Exception:
                    pass
            page.wait_for_timeout(2000)
            try:
                page.get_by_text(re.compile(r"Solo Draft", re.I)).first.click(timeout=4000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            try:
                page.get_by_label(re.compile(r"Timer per Pick", re.I)).click(timeout=2500)
                page.wait_for_timeout(300)
                page.get_by_text(re.compile(r"^30 sec$"), exact=True).click(timeout=2500)
            except Exception:
                pass

            start = page.get_by_role("button", name=re.compile(r"Start New Live Draft", re.I))
            report["start_btn_n"] = start.count()
            if start.count() == 0:
                report["fatal"] = "no_start_button"
                report["boot"] = _body(page)[:900]
                browser.close()
                raise RuntimeError("no_start_button")
            start.first.click(timeout=15000)
            t0 = time.perf_counter()
            for _ in range(60):
                page.wait_for_timeout(1000)
                text = _body(page)
                if "Recommended Players" in text and page.get_by_role(
                    "button", name=re.compile(r"Draft Player", re.I)
                ).count():
                    break
            report["start_s"] = round(time.perf_counter() - t0, 2)
            text = _body(page)
            report["picks_before"] = _picks(text)
            report["lock_snip"] = ""
            if "Draft Player locked:" in text:
                idx = text.find("Draft Player locked:")
                report["lock_snip"] = text[idx : idx + 320]
            report["snip_before"] = text[:1200]

            dbtns = page.get_by_role("button", name=re.compile(r"Draft Player", re.I))
            report["draft_btn_n"] = dbtns.count()
            infos = []
            for i in range(min(dbtns.count(), 8)):
                b = dbtns.nth(i)
                infos.append(
                    {
                        "i": i,
                        "text": (b.inner_text(timeout=1000) or "")[:40],
                        "disabled": b.get_attribute("disabled"),
                        "aria": b.get_attribute("aria-disabled"),
                        "enabled_api": b.is_enabled(),
                    }
                )
            report["draft_btn_infos"] = infos

            # Inspect real DOM disabled state
            report["dom_disabled"] = page.evaluate(
                """() => {
                  const btns = [...document.querySelectorAll('button')].filter(b => /Draft Player/i.test(b.innerText||''));
                  return btns.slice(0,8).map(b => ({
                    text: (b.innerText||'').slice(0,40),
                    disabledProp: !!b.disabled,
                    hasDisabledAttr: b.hasAttribute('disabled'),
                    ariaDisabled: b.getAttribute('aria-disabled'),
                    className: (b.className||'').slice(0,80),
                  }));
                }"""
            )
            # Click first Draft Player (Streamlit often reports is_enabled=False incorrectly).
            clicked_i = 0
            dbtns.first.scroll_into_view_if_needed(timeout=2000)
            dbtns.first.click(timeout=8000, force=True)
            report["clicked_i"] = clicked_i

            samples = []
            for tick in range(20):
                page.wait_for_timeout(500)
                t = _body(page)
                samples.append(
                    {
                        "tick": tick,
                        "picks": _picks(t),
                        "has_pete": "Pete Alonso" in t,
                        "submitting": "Submitting" in t,
                        "pick2": bool(re.search(r"Pick\\s*2|Round\\s*2", t, re.I)),
                        "starting": bool(re.search(r"Starting", t)),
                        "lock": ("Draft Player locked:" in t),
                    }
                )
                if samples[-1]["picks"] and samples[-1]["picks"] > 0:
                    break
            report["samples"] = samples
            after = _body(page)
            report["snip_after"] = after[:1500]
            if "Draft Player locked:" in after:
                idx = after.find("Draft Player locked:")
                report["lock_snip_after"] = after[idx : idx + 320]
            page.screenshot(
                path=str(ROOT / "data" / "tb_probe" / "solo_draft_player_probe.png"),
                full_page=False,
            )
            browser.close()
    except Exception as e:
        report["fatal"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        try:
            log_f.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    report["elapsed_s"] = round(time.time() - report["t0"], 1)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if (report.get("samples") or [{}])[-1].get("picks") else 1


if __name__ == "__main__":
    raise SystemExit(main())
