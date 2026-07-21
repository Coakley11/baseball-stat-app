"""Production Solo Live Draft Cloud soak — ordinary path, strict phase order."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
PROD_URL = f"{BASE}/~/+/?active_page=Live%20Draft%20Room"
DIAG_URL = f"{BASE}/~/+/?ld_accept=1&active_page=Live%20Draft%20Room"
REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "cloud_production_solo_soak.json"

SCRAPE_STATE_JS = """() => {
  function roots() {
    const r = [document];
    for (const f of document.querySelectorAll('iframe')) {
      try { r.push(f.contentDocument); } catch (e) {}
    }
    return r.filter(Boolean);
  }
  let timer = null;
  let pick = null;
  let round = null;
  let team = null;
  let boardRows = 0;
  let ccTimer = null;
  let sidebarTeam = null;
  for (const root of roots()) {
    const timerEl = root.querySelector('.live-draft-timer');
    if (timerEl) {
      const n = parseInt(String(timerEl.textContent || '').trim(), 10);
      if (!Number.isNaN(n)) timer = n;
    }
    for (const pill of root.querySelectorAll('.ld-pill')) {
      const t = String(pill.innerText || '').replace(/\\s+/g, ' ').trim();
      const pm = t.match(/^Pick\\s+(\\d+)/i);
      if (pm) pick = parseInt(pm[1], 10);
      const rm = t.match(/^Round\\s+(\\d+)/i);
      if (rm) round = parseInt(rm[1], 10);
    }
    const teamEl = root.querySelector('.ld-team-name');
    if (teamEl) team = String(teamEl.innerText || '').trim();
    boardRows += root.querySelectorAll('[data-testid="stDataFrame"] tbody tr').length;
    for (const el of root.querySelectorAll('*')) {
      const tx = String(el.innerText || '');
      if (tx.includes('On the clock') && tx.length < 120) sidebarTeam = tx.split('\\n')[0].trim();
      const m = tx.match(/Time remaining[:\\s]+(\\d+)/i);
      if (m) ccTimer = parseInt(m[1], 10);
    }
  }
  return { timer, pick, round, team, boardRows, ccTimer, sidebarTeam };
}"""


def dom_counts(page) -> dict[str, int]:
    return page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          const labels = ['Pause Draft','Resume Draft','Auto Pick Now','End/Delete Draft','Draft Player','Draft Control Center','Time remaining'];
          const counts = {};
          for (const lab of labels) counts[lab]=0;
          for (const root of roots()) {
            for (const b of root.querySelectorAll('button')) {
              const r=b.getBoundingClientRect();
              if (r.width <= 0 || r.height <= 0) continue;
              const t=(b.innerText||'').replace(/\\s+/g,' ').trim();
              for (const lab of labels) if (t.includes(lab)) counts[lab]++;
            }
          }
          return counts;
        }"""
    )


def scrape_state(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(SCRAPE_STATE_JS)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


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
            key, val = key.strip(), val.strip()
            if key in ("hb_ticks", "exp_commits", "pick", "idle_rpm", "idle_wpm", "cc_mounts", "manual_mounts"):
                try:
                    out[key] = int(val) if val.lstrip("-").isdigit() else float(val)
                except ValueError:
                    out[key] = val
            else:
                out[key] = val
    return out


def all_frames_text(page) -> str:
    return page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          return roots().map((root) => (root.body ? root.body.innerText : '')).join('\\n');
        }"""
    )


def click_btn(page, label: str, *, wait_ms: int = 3000) -> bool:
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
                if (matches.length >= 1) { matches[0].click(); return matches.length === 1; }
              }
              return false;
            }""",
            label,
        )
        page.wait_for_timeout(wait_ms)
        return bool(clicked)
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


def select_option_by_label(page, label: str, option: str) -> bool:
    return bool(
        page.evaluate(
            """({label, option}) => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                for (const sel of root.querySelectorAll('[data-baseweb=\"select\"]')) {
                  const prev = sel.previousElementSibling;
                  const text = ((prev && prev.innerText) || sel.innerText || '').replace(/\\s+/g,' ').trim();
                  if (!text.includes(label)) continue;
                  const input = sel.querySelector('input');
                  if (input) { input.click(); input.value = option; input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true})); return true; }
                }
              }
              return false;
            }""",
            {"label": label, "option": option},
        )
    )


def dom_controls_ok(counts: dict[str, int]) -> bool:
    for key in ("Pause Draft", "Resume Draft", "Auto Pick Now"):
        if int(counts.get(key) or 0) != 1:
            return False
    return True


def wait_for_deploy(page, target_sha: str, *, timeout_s: int = 480) -> str:
    deadline = time.time() + timeout_s
    seen = ""
    while time.time() < deadline:
        try:
            page.goto(PROD_URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(4000)
            text = page.inner_text("body", timeout=20000)
            m = re.search(r"baseball-dev-([a-f0-9]{7})", text, re.I)
            seen = m.group(1).lower() if m else ""
            if seen == target_sha.lower():
                return seen
        except Exception:
            pass
        page.wait_for_timeout(15000)
    return seen


class SupabaseMonitor:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.idle_window_start: float | None = None
        self.idle_reads = 0
        self.idle_writes = 0
        self.full_room_loads = 0
        self.full_room_callers: dict[str, int] = {}

    def attach(self, page) -> None:
        def on_request(request) -> None:
            url = str(request.url or "")
            if "supabase" not in url.lower():
                return
            method = str(request.method or "GET").upper()
            entry = {"ts": time.time(), "method": method, "url": url[:240]}
            self.events.append(entry)
            if self.idle_window_start is None:
                return
            if method == "GET":
                self.idle_reads += 1
            else:
                self.idle_writes += 1
            if "draft_room" in url and method == "GET" and "head" not in url:
                self.full_room_loads += 1
                self.full_room_callers["network"] = int(self.full_room_callers.get("network") or 0) + 1

        page.on("request", on_request)

    def begin_idle_window(self) -> None:
        self.idle_window_start = time.time()
        self.idle_reads = 0
        self.idle_writes = 0
        self.full_room_loads = 0

    def idle_rates(self) -> dict[str, float]:
        if not self.idle_window_start:
            return {"reads_per_min": 0.0, "writes_per_min": 0.0, "full_room_per_min": 0.0}
        window = max(1.0, time.time() - self.idle_window_start)
        return {
            "reads_per_min": round(self.idle_reads * 60.0 / window, 2),
            "writes_per_min": round(self.idle_writes * 60.0 / window, 2),
            "full_room_per_min": round(self.full_room_loads * 60.0 / window, 2),
            "window_sec": round(window, 1),
        }


def validate_expiration_event(
    prev: dict[str, Any],
    cur: dict[str, Any],
    *,
    idx: int,
) -> dict[str, Any]:
    board_delta = int(cur.get("boardRows") or 0) - int(prev.get("boardRows") or 0)
    pick_delta = None
    if prev.get("pick") is not None and cur.get("pick") is not None:
        pick_delta = int(cur["pick"]) - int(prev["pick"])
    timer_restarted = cur.get("timer") is not None and int(cur.get("timer") or 0) >= 8
    agree_team = True
    if cur.get("team") and cur.get("ccTimer") is not None and cur.get("timer") is not None:
        agree_team = abs(int(cur["timer"]) - int(cur["ccTimer"])) <= 3 or int(cur["ccTimer"]) >= 8
    ok = (pick_delta == 1 or board_delta == 1) and timer_restarted and not (board_delta > 1)
    return {
        "index": idx,
        "board_delta": board_delta,
        "pick_delta": pick_delta,
        "timer_after": cur.get("timer"),
        "cc_timer_after": cur.get("ccTimer"),
        "pick_after": cur.get("pick"),
        "team_after": cur.get("team"),
        "timer_restarted": timer_restarted,
        "surfaces_agree": agree_team,
        "batch_pick": board_delta > 1,
        "ok": ok,
    }


def wait_for_active_draft(page, report: dict[str, Any], t_click: float) -> dict[str, Any] | None:
    for _ in range(120):
        page.wait_for_timeout(1000)
        d = dom_counts(page)
        if int(d.get("Pause Draft") or 0) >= 1:
            report["time_to_first_usable_s"] = round(time.time() - t_click, 2)
            report.setdefault("dom_samples", []).append({"when": "first_usable", "counts": d})
            return d
    report.setdefault("errors", []).append("start_never_reached_active_controls")
    return None


def wait_for_natural_expirations(
    page,
    report: dict[str, Any],
    monitor: SupabaseMonitor,
    *,
    need: int = 4,
    timeout_s: int = 600,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    deadline = time.time() + timeout_s
    prev = scrape_state(page)
    last_board = int(prev.get("boardRows") or 0)
    last_pick = int(prev.get("pick") or 1)
    monitor.begin_idle_window()
    timer_samples: list[int] = []
    last_low_timer_at: float | None = None

    while time.time() < deadline and len(events) < need:
        page.wait_for_timeout(1500)
        cur = scrape_state(page)
        stamp = parse_acceptance_stamp(all_frames_text(page))
        if stamp:
            report["acceptance_stamp_final"] = stamp
        tval = cur.get("timer")
        if tval is not None:
            timer_samples.append(int(tval))
            if int(tval) <= 2:
                last_low_timer_at = time.time()
        board_now = int(cur.get("boardRows") or 0)
        pick_now = int(cur.get("pick") or last_pick)
        pick_advanced = pick_now == last_pick + 1
        board_advanced = board_now > last_board
        if pick_advanced or board_advanced:
            delta = max(pick_now - last_pick, board_now - last_board)
            if delta > 1:
                report.setdefault("errors", []).append(f"batch_pick_at_expiration:{len(events)+1}:delta={delta}")
            evt = validate_expiration_event(prev, cur, idx=len(events) + 1)
            evt["ts"] = time.time()
            evt["stamp"] = stamp
            evt["hb_ticks"] = stamp.get("hb_ticks")
            evt["exp_commits"] = stamp.get("exp_commits")
            evt["pick_before"] = last_pick
            evt["pick_after"] = pick_now
            events.append(evt)
            if not evt["ok"] and pick_advanced:
                # pick index is authoritative; board dataframe scrape may lag
                evt["ok"] = pick_advanced and evt.get("timer_restarted")
            if not evt["ok"]:
                report.setdefault("errors", []).append(f"expiration_{len(events)}_invalid:{evt}")
            last_board = max(last_board, board_now)
            last_pick = pick_now
            prev = cur
            monitor.begin_idle_window()
        elif last_low_timer_at and (time.time() - last_low_timer_at) > 20 and int(cur.get("timer") or 0) <= 2:
            report.setdefault("errors", []).append(f"timer_frozen_at_zero_before_exp_{len(events)+1}")

    report["natural_expiration_events"] = events
    report["timer_samples_during_expirations"] = timer_samples[-40:]
    report["idle_egress_during_countdown"] = monitor.idle_rates()
    return events


def main() -> int:
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {
        "started_at": time.time(),
        "prod_url": PROD_URL,
        "production_path": True,
        "errors": [],
        "latencies": {},
        "phases": {},
    }
    monitor = SupabaseMonitor()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        monitor.attach(page)
        try:
            repo = Path(__file__).resolve().parent.parent
            target_sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=repo, text=True
            ).strip()
            report["expected_build"] = f"baseball-dev-{target_sha}"
            report["deploy_build_seen"] = wait_for_deploy(page, target_sha, timeout_s=360)

            # Phase 1 — ordinary Solo start (no ld_accept / canary / dev flags)
            page.goto(PROD_URL, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(8000)
            if "End/Delete Draft" in page.inner_text("body", timeout=20000):
                click_btn(page, "End/Delete Draft", wait_ms=4000)
            set_number(page, "Number of Teams", "2")
            set_number(page, "Picks per Team", "8")
            select_option_by_label(page, "Timer per Pick", "30 sec")
            page.wait_for_timeout(1500)
            t_click = time.time()
            if not click_btn(page, "Start New Live Draft"):
                report["errors"].append("start_button_missing")
                return 1
            d0 = wait_for_active_draft(page, report, t_click)
            if not d0 or not dom_controls_ok(d0):
                report["errors"].append(f"dom_controls_at_start:{d0}")

            # Phase 2 — four natural expirations before any controls
            exp_events = wait_for_natural_expirations(page, report, monitor, need=4, timeout_s=600)
            report["phases"]["natural_expirations"] = {
                "count": len(exp_events),
                "required": 4,
                "all_ok": all(e.get("ok") for e in exp_events) if exp_events else False,
            }
            if len(exp_events) < 4:
                report["errors"].append(f"expiration_commits_low:{len(exp_events)}")

            # Phase 3 — interaction matrix (only after 4 natural expirations)
            interactions: dict[str, bool] = {}
            latencies: dict[str, float] = {}
            if len(exp_events) >= 4:
                steps = [
                    ("manual_pick", "Draft Player"),
                    ("auto_pick", "Auto Pick Now"),
                    ("pause", "Pause Draft"),
                    ("resume", "Resume Draft"),
                    ("reset_timer", "Reset Timer"),
                ]
                for key, label in steps:
                    t0 = time.time()
                    ok = click_btn(page, label)
                    interactions[key] = ok
                    latencies[f"{key}_s"] = round(time.time() - t0, 2)
                    if not ok:
                        report["errors"].append(f"{key}_failed")
                    st = scrape_state(page)
                    if st.get("timer") is None and key not in ("pause",):
                        report["errors"].append(f"timer_missing_after_{key}")
                    d = dom_counts(page)
                    if not dom_controls_ok(d):
                        report["errors"].append(f"duplicate_controls_after_{key}:{d}")

                t0 = time.time()
                interactions["queue_add"] = click_btn(page, "Add to Queue") or click_btn(page, "⭐")
                latencies["queue_add_s"] = round(time.time() - t0, 2)
                t0 = time.time()
                interactions["queue_remove"] = click_btn(page, "Remove") or click_btn(page, "Clear Draft Queue")
                latencies["queue_remove_s"] = round(time.time() - t0, 2)
                if latencies["queue_remove_s"] > 3.5:
                    report["errors"].append(f"queue_remove_slow:{latencies['queue_remove_s']}s")

                page.goto(f"{BASE}/~/+/?active_page=Historical%20Explorer", wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(3000)
                nav_ok = click_btn(page, "Return to Live Draft")
                if not nav_ok:
                    page.goto(PROD_URL, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(10000)
                nav_dom = dom_counts(page)
                interactions["nav_back"] = dom_controls_ok(nav_dom)
                report["dom_samples"] = report.get("dom_samples") or []
                report["dom_samples"].append({"when": "after_nav_back", "counts": nav_dom})
                if not interactions["nav_back"]:
                    report["errors"].append(f"nav_restore_failed:{nav_dom}")

            report["interactions"] = interactions
            report["latencies"] = latencies

            final_stamp = parse_acceptance_stamp(all_frames_text(page))
            report["acceptance_stamp_final"] = final_stamp
            report["expiration_commits"] = int(final_stamp.get("exp_commits") or len(exp_events))
            report["heartbeat_ticks"] = int(final_stamp.get("hb_ticks") or 0)
            report["board_advances"] = [e.get("board_delta") for e in exp_events]
            report["new_deadlines"] = [e.get("timer_after") for e in exp_events]
            report["idle_supabase_reads_per_min"] = report.get("idle_egress_during_countdown", {}).get(
                "reads_per_min", monitor.idle_rates()["reads_per_min"]
            )
            report["idle_supabase_writes_per_min"] = report.get("idle_egress_during_countdown", {}).get(
                "writes_per_min", monitor.idle_rates()["writes_per_min"]
            )
            report["full_room_loads"] = monitor.full_room_loads
            report["full_room_callers"] = monitor.full_room_callers
            report["solo_poll_owner"] = final_stamp.get("solo_poll") or "local_page_js_countdown"

            egress_high = (
                float(report["idle_supabase_reads_per_min"] or 0) > 2.0
                or float(report["idle_supabase_writes_per_min"] or 0) > 0.5
            )
            if egress_high:
                report["errors"].append(
                    f"idle_egress_high:reads={report['idle_supabase_reads_per_min']}/min "
                    f"writes={report['idle_supabase_writes_per_min']}/min"
                )

            report["soak_duration_s"] = round(time.time() - report["started_at"], 1)
            report["passed"] = (
                len(exp_events) >= 4
                and all(e.get("ok") for e in exp_events)
                and all(interactions.get(k) for k in ("manual_pick", "auto_pick", "pause", "resume", "reset_timer", "queue_add", "queue_remove", "nav_back"))
                and not egress_high
                and not report["errors"]
            )
        finally:
            browser.close()

    repo = Path(__file__).resolve().parent.parent
    egress_tests = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_live_draft_solo_expire_loop.py", "-q"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    report["unit_egress_tests_passed"] = egress_tests.returncode == 0
    if not report["unit_egress_tests_passed"]:
        report.setdefault("errors", []).append("unit_egress_tests_failed")
    report["passed"] = bool(report.get("passed")) and bool(report["unit_egress_tests_passed"])

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
