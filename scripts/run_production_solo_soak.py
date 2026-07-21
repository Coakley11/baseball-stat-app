"""Production Solo Live Draft Cloud soak — full page, not canary."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
PROD_URL = f"{BASE}/~/+/?ld_accept=1&active_page=Live%20Draft%20Room"
REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "cloud_production_solo_soak.json"


def _roots(page):
    return page.evaluate(
        """() => {
          const r=[document];
          for (const f of document.querySelectorAll('iframe')) {
            try { r.push(f.contentDocument); } catch(e) {}
          }
          return r.filter(Boolean).length;
        }"""
    )


def dom_counts(page) -> dict[str, int]:
    return page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          const labels = ['Pause Draft','Resume Draft','Auto Pick Now','End/Delete Draft','Draft Player','Draft Control Center','Time remaining'];
          const counts = {};
          for (const lab of labels) counts[lab]=0;
          const dom = {};
          for (const cls of ['live-draft-controls','live-draft-action-row','live-draft-manual-panel','live-draft-board-panel']) {
            let n=0; for (const root of roots()) n += root.querySelectorAll('.'+cls).length; dom[cls]=n;
          }
          for (const root of roots()) {
            for (const b of root.querySelectorAll('button')) {
              const r=b.getBoundingClientRect();
              if (r.width <= 0 || r.height <= 0) continue;
              const t=(b.innerText||'').replace(/\\s+/g,' ').trim();
              for (const lab of labels) if (t.includes(lab)) counts[lab]++;
            }
            for (const el of root.querySelectorAll('*')) {
              const t=(el.innerText||'');
              if (t.includes('Time remaining')) counts['Time remaining']++;
              if (t.includes('Draft Control Center')) counts['Draft Control Center']++;
            }
          }
          return {counts, dom};
        }"""
    )


def parse_acceptance_stamp(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in text.splitlines():
        if "LDR accept ·" not in line:
            continue
        chunk = line.split("LDR accept ·", 1)[-1].strip()
        for part in chunk.split("·"):
            piece = part.strip()
            if "=" not in piece:
                continue
            key, val = piece.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key in ("cc_mounts", "manual_mounts", "hb_ticks", "exp_commits", "pick", "rev", "run_seq"):
                if val.isdigit() or (val.startswith("-") and val[1:].isdigit()):
                    out[key] = int(val)
                else:
                    out[key] = val
            else:
                out[key] = val
    return out


def extract_diag(page) -> list[str]:
    text = page.inner_text("body", timeout=20000)
    lines: list[str] = []
    for raw in text.splitlines():
        t = raw.strip()
        if re.search(
            r"Start Draft stages|Control center mounts|Manual panel mounts|Acceptance snapshot|"
            r"start_button_received|validation_completed|market_loaded|pool_build|"
            r"room_created|canonical_snapshot|recommendations_deferred|first_page_rendered|"
            r"heavy_content_rendered|deferred_full_pool|mounts=|LDR ·|LDR accept|cloud_accept|"
            r"Loading recommendations|Draft is live|baseball-dev-|Heartbeat ticks|expiration commits",
            t,
            re.I,
        ):
            lines.append(t[:320])
    return lines


def click_btn(page, label: str) -> bool:
    try:
        clicked = page.evaluate(
            """(label) => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const matches = [];
                for (const b of root.querySelectorAll('button')) {
                  const r=b.getBoundingClientRect();
                  if (r.width <= 0 || r.height <= 0) continue;
                  const t=(b.innerText||'').replace(/\\s+/g,' ').trim();
                  if (t.includes(label)) matches.push(b);
                }
                if (matches.length === 1) { matches[0].click(); return true; }
                if (matches.length > 1) { matches[0].click(); return 'dup'; }
              }
              return false;
            }""",
            label,
        )
        page.wait_for_timeout(3000)
        return clicked is True
    except Exception:
        return False


def set_number(page, aria: str, val: str) -> bool:
    return bool(
        page.evaluate(
            """({aria, val}) => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                for (const inp of root.querySelectorAll('input[type=\"number\"]')) {
                  if ((inp.getAttribute('aria-label')||'')===aria) {
                    inp.value=String(val);
                    inp.dispatchEvent(new Event('input',{bubbles:true}));
                    inp.dispatchEvent(new Event('change',{bubbles:true}));
                    return true;
                  }
                }
              }
              return false;
            }""",
            {"aria": aria, "val": val},
        )
    )


def countdown_values(text: str) -> list[int]:
    vals: list[int] = []
    for m in re.finditer(r"Time remaining:\s*\*\*(\d+)s\*\*", text):
        vals.append(int(m.group(1)))
    for m in re.finditer(r"remaining=(\d+)", text):
        vals.append(int(m.group(1)))
    for m in re.finditer(r"(\d+)s remaining", text, re.I):
        vals.append(int(m.group(1)))
    return vals


def stamp_ok(stamp: dict[str, Any]) -> bool:
    cc = int(stamp.get("cc_mounts") or 0)
    manual = int(stamp.get("manual_mounts") or 0)
    return cc == 1 and manual == 1


def dom_controls_ok(d: dict[str, Any]) -> bool:
    counts = d.get("counts") or {}
    for key in ("Pause Draft", "Resume Draft", "Auto Pick Now"):
        if int(counts.get(key) or 0) != 1:
            return False
    return True


def main() -> int:
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {
        "started_at": time.time(),
        "impl_commit": "",
        "deploy_marker": "",
        "expected_build": "",
        "stages": [],
        "dom_samples": [],
        "acceptance_stamps": [],
        "errors": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        try:
            page.goto(PROD_URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(15000)
            text = page.inner_text("body", timeout=20000)
            m = re.search(r"baseball-dev-[a-f0-9]+", text, re.I)
            report["deploy_build_seen"] = m.group(0) if m else ""

            if "End/Delete Draft" in text:
                click_btn(page, "End/Delete Draft")
                page.wait_for_timeout(5000)

            set_number(page, "Number of Teams", "2")
            set_number(page, "Picks per Team", "4")
            set_number(page, "P", "0")
            page.wait_for_timeout(2000)

            t_click = time.time()
            report["start_click_at"] = t_click
            start_click = click_btn(page, "Start New Live Draft")
            if start_click is False:
                report["errors"].append("start_button_missing")
                browser.close()
                REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
                return 1

            first_usable = None
            heavy_paint = None
            for _ in range(90):
                page.wait_for_timeout(1000)
                text = page.inner_text("body", timeout=20000)
                report["stages"] = extract_diag(page)
                stamp = parse_acceptance_stamp(text)
                if stamp:
                    report["acceptance_stamps"].append({"when": "poll", **stamp})
                d = dom_counts(page)
                if first_usable is None and d["counts"].get("Pause Draft", 0) >= 1:
                    first_usable = time.time() - t_click
                    report["time_to_first_usable_s"] = round(first_usable, 2)
                    report["dom_samples"].append({"when": "first_usable", **d, "stamp": stamp})
                if heavy_paint is None and re.search(
                    r"Recommendations|Top Picks|Draft Decision|heavy_content_rendered", text, re.I
                ):
                    heavy_paint = time.time() - t_click
                    report["time_to_heavy_paint_s"] = round(heavy_paint, 2)
                    report["dom_samples"].append({"when": "heavy_paint", **d, "stamp": stamp})
                if first_usable is not None and heavy_paint is not None:
                    break

            last_stamp = parse_acceptance_stamp(text)
            report["acceptance_stamp_final"] = last_stamp
            if not stamp_ok(last_stamp):
                report["errors"].append(f"mount_mismatch:{last_stamp}")
            d0 = dom_counts(page)
            if not dom_controls_ok(d0):
                report["errors"].append(f"dom_duplicate_at_start:{d0.get('counts')}")

            soak_end = time.time() + 420
            expirations_dom = 0
            picks_before = len(re.findall(r"Pick \d+:", text))
            manual_done = auto_done = pause_done = resume_done = reset_done = False
            queue_add_done = queue_remove_done = False
            timer_samples: list[int] = []
            latencies: dict[str, float] = {}
            heartbeat_samples: list[int] = []
            expiration_commits_samples: list[int] = []

            while time.time() < soak_end:
                text = page.inner_text("body", timeout=20000)
                stamp = parse_acceptance_stamp(text)
                if stamp:
                    heartbeat_samples.append(int(stamp.get("hb_ticks") or 0))
                    expiration_commits_samples.append(int(stamp.get("exp_commits") or 0))
                    report["acceptance_stamp_final"] = stamp

                picks_now = len(re.findall(r"Pick \d+:", text))
                if picks_now > picks_before:
                    expirations_dom += picks_now - picks_before
                    picks_before = picks_now
                    report.setdefault("expiration_events", []).append(
                        {"ts": time.time(), "dom_expirations": expirations_dom, "stamp": stamp}
                    )

                vals = countdown_values(text)
                if vals:
                    timer_samples.append(min(vals))

                exp_commits = int(stamp.get("exp_commits") or 0)
                hb_ticks = int(stamp.get("hb_ticks") or 0)

                if exp_commits >= 1 and not manual_done and "Draft Player" in text:
                    t0 = time.time()
                    if click_btn(page, "Draft Player"):
                        manual_done = True
                        latencies["manual_pick_s"] = round(time.time() - t0, 2)
                if exp_commits >= 2 and not auto_done:
                    t0 = time.time()
                    if click_btn(page, "Auto Pick Now"):
                        auto_done = True
                        latencies["auto_pick_s"] = round(time.time() - t0, 2)
                if exp_commits >= 2 and not pause_done:
                    t0 = time.time()
                    if click_btn(page, "Pause Draft"):
                        pause_done = True
                        latencies["pause_s"] = round(time.time() - t0, 2)
                        page.wait_for_timeout(4000)
                if pause_done and not resume_done:
                    t0 = time.time()
                    if click_btn(page, "Resume Draft"):
                        resume_done = True
                        latencies["resume_s"] = round(time.time() - t0, 2)
                if exp_commits >= 3 and not reset_done:
                    t0 = time.time()
                    if click_btn(page, "Reset Timer"):
                        reset_done = True
                        latencies["reset_timer_s"] = round(time.time() - t0, 2)

                d = dom_counts(page)
                if not dom_controls_ok(d):
                    report.setdefault("duplicate_events", []).append({"stamp": stamp, **d})

                if (
                    max(exp_commits, expirations_dom) >= 4
                    and hb_ticks >= 8
                    and manual_done
                    and auto_done
                    and pause_done
                    and resume_done
                    and reset_done
                ):
                    break
                page.wait_for_timeout(2000)

            if not queue_add_done:
                t0 = time.time()
                if click_btn(page, "Add to Queue") or click_btn(page, "⭐"):
                    queue_add_done = True
                    latencies["queue_add_s"] = round(time.time() - t0, 2)
            if not queue_remove_done:
                t0 = time.time()
                if click_btn(page, "Remove") or click_btn(page, "Clear Draft Queue"):
                    queue_remove_done = True
                    latencies["queue_remove_s"] = round(time.time() - t0, 2)

            page.goto(
                f"{BASE}/~/+/?ld_accept=1&active_page=Historical%20Explorer",
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(5000)
            page.goto(PROD_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(12000)
            nav_dom = dom_counts(page)
            nav_stamp = parse_acceptance_stamp(page.inner_text("body", timeout=20000))
            report["dom_samples"].append({"when": "after_nav_back", **nav_dom, "stamp": nav_stamp})
            report["stages"] = extract_diag(page)

            final_stamp = report.get("acceptance_stamp_final") or {}
            exp_commits = int(final_stamp.get("exp_commits") or 0)
            hb_ticks = int(final_stamp.get("hb_ticks") or 0)
            if hb_ticks < 8:
                report["errors"].append(f"heartbeat_ticks_low:{hb_ticks}")
            if exp_commits < 4:
                report["errors"].append(f"expiration_commits_low:{exp_commits}")
            if not dom_controls_ok(nav_dom):
                report["errors"].append(f"dom_duplicate_after_nav:{nav_dom.get('counts')}")
            if not stamp_ok(nav_stamp):
                report["errors"].append(f"mount_mismatch_after_nav:{nav_stamp}")

            report.update(
                {
                    "expiration_commits": exp_commits,
                    "dom_expirations": expirations_dom,
                    "heartbeat_ticks": hb_ticks,
                    "heartbeat_samples_tail": heartbeat_samples[-20:],
                    "expiration_commit_samples_tail": expiration_commits_samples[-20:],
                    "manual_done": manual_done,
                    "auto_done": auto_done,
                    "pause_done": pause_done,
                    "resume_done": resume_done,
                    "reset_done": reset_done,
                    "queue_add_done": queue_add_done,
                    "queue_remove_done": queue_remove_done,
                    "latencies": latencies,
                    "timer_samples_tail": timer_samples[-20:],
                    "soak_duration_s": round(time.time() - report["started_at"], 1),
                    "passed": (
                        max(exp_commits, expirations_dom) >= 4
                        and hb_ticks >= 8
                        and manual_done
                        and auto_done
                        and pause_done
                        and resume_done
                        and reset_done
                        and stamp_ok(final_stamp)
                        and stamp_ok(nav_stamp)
                        and dom_controls_ok(nav_dom)
                        and not report.get("duplicate_events")
                        and not report.get("errors")
                        and (report.get("time_to_first_usable_s") or 99) <= 8
                    ),
                }
            )
        finally:
            browser.close()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
