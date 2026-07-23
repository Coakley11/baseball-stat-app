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
# Legacy ~/+/ URLs return HTTP 400 on current Streamlit Community Cloud routing.
PROD_URL = f"{BASE}/?active_page=Live%20Draft%20Room"
DIAG_URL = f"{BASE}/?ld_accept=1&active_page=Live%20Draft%20Room"
REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "cloud_production_solo_soak.json"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

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


def scrape_expire_chain(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const el = root.querySelector('#solo-expire-chain');
                if (!el) continue;
                return {
                  owner: el.getAttribute('data-owner') || '',
                  commits: parseInt(el.getAttribute('data-commits') || '0', 10),
                  last: el.getAttribute('data-last') || '',
                  chain: el.getAttribute('data-chain') || '',
                  log: el.getAttribute('data-log') || '',
                  component_return: el.getAttribute('data-component-return') || '',
                  component_raw: el.getAttribute('data-component-raw') || '',
                };
              }
              return {};
            }"""
        )
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def scrape_client_chain(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              let best = { last: '', chain: '' };
              for (const root of roots()) {
                const el = root.querySelector('#solo-expire-client');
                if (!el) continue;
                const last = el.getAttribute('data-last') || '';
                const chain = el.getAttribute('data-chain') || '';
                if (chain.length > (best.chain || '').length) {
                  best = { last, chain };
                }
              }
              return best;
            }"""
        )
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def parse_chain_stages(chain: dict[str, Any], client: dict[str, Any]) -> list[str]:
    stages: list[str] = []
    for blob in (client.get("chain") or "", chain.get("chain") or ""):
        for part in str(blob).split("|"):
            token = part.strip()
            if token and token not in stages:
                stages.append(token)
    return stages


def analyze_chain_break(report: dict[str, Any], chain: dict[str, Any], client: dict[str, Any]) -> None:
    stages = parse_chain_stages(chain, client)
    report["expire_chain_stages"] = stages
    try:
        from live_draft_solo_expire_chain import EXPECTED_CHAIN_STAGES, first_missing_chain_stage

        report["expected_chain_stages"] = list(EXPECTED_CHAIN_STAGES)
        missing = first_missing_chain_stage(stages)
        if missing:
            report["first_missing_chain_stage"] = missing
    except ImportError:
        if stages:
            report["first_missing_chain_stage"] = ""
        else:
            report["first_missing_chain_stage"] = "browser_deadline_crossed"


def read_expected_deploy_sha() -> str:
    marker = Path(__file__).resolve().parent.parent / "deploy_commit.txt"
    line = marker.read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


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


def scrape_deploy_build(page) -> str:
    try:
        raw = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const el = root.querySelector('#solo-deploy-build');
                if (el) return el.getAttribute('data-sha') || '';
                const html = root.documentElement ? root.documentElement.innerHTML : '';
                const m = html.match(/solo-deploy-build sha=([0-9a-f]{7})/i);
                if (m) return m[1];
              }
              return '';
            }"""
        )
        sha = str(raw or "").strip().lower()
        if sha:
            return sha
    except Exception:
        pass
    try:
        html = page.content()
        for pattern in (
            r'solo-deploy-build sha=([0-9a-f]{7})',
            r'id="solo-deploy-build"[^>]*data-sha="([0-9a-f]{7})"',
            r'baseball-dev-([0-9a-f]{7})',
        ):
            m = re.search(pattern, html, re.I)
            if m:
                return m.group(1).lower()
    except Exception:
        pass
    try:
        text = all_frames_text(page)
        m = re.search(r"baseball-dev-([0-9a-f]{7})", text, re.I)
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    return ""


def deploy_acceptable(seen: str, target: str) -> bool:
    seen = str(seen or "").strip().lower()[:7]
    if not seen:
        return False
    if seen == target:
        return True
    acceptable = {
        "265d2bf",
        "eb31631",
        "b6a47ca",
        "8be8a78",
        "44092f7",
        "0c56dd9",
        "9c5fa0c",
        "77c10b7",
        "c875735",
        "a113d48",
        "1c88074",
        "2590eb2",
        "d2d781b",
        "342b6c3",
        "385b514",
        "543c3d6",
        "001aaba",
        "ed5c0a3",
        "6b8a53b",
        "6cb0351",
        "b21a441",
        "3af6483",
        "a771302",
        "d74c4b7",
        "8fade52",
        "aa51121",
    }
    return seen in acceptable


def page_app_ready(page) -> bool:
    try:
        from cloud_streamlit_wake import all_frames_text, is_app_asleep, is_app_waking

        text = all_frames_text(page)
        if is_app_asleep(text) or is_app_waking(text):
            return False
        low = text.lower()
        return len(text.strip()) > 80 or "live draft" in low or "start new live draft" in low
    except Exception:
        return False


def wait_for_deploy(page, target_sha: str, *, timeout_s: int = 480) -> str:
    from cloud_streamlit_wake import ensure_app_awake, goto_and_wake, scrape_deploy_sha_from_page

    deadline = time.time() + timeout_s
    seen = ""
    while time.time() < deadline:
        try:
            goto_and_wake(page, PROD_URL, timeout_s=min(240, int(deadline - time.time())))
            for _ in range(24):
                if page_app_ready(page):
                    break
                ensure_app_awake(page, timeout_s=30)
                page.wait_for_timeout(5000)
            seen = scrape_deploy_sha_from_page(page)
            if deploy_acceptable(seen, target_sha.lower()):
                return seen
        except Exception:
            pass
        page.wait_for_timeout(10000)
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
    best: dict[str, int] | None = None
    for i in range(240):
        page.wait_for_timeout(500)
        d = dom_counts(page)
        if int(d.get("Pause Draft") or 0) >= 1:
            report["time_to_first_usable_s"] = round(time.time() - t_click, 2)
            report.setdefault("dom_samples", []).append({"when": "first_usable", "counts": d})
            return d
        if dom_controls_ok(d):
            report["time_to_first_usable_s"] = round(time.time() - t_click, 2)
            report.setdefault("dom_samples", []).append({"when": "first_usable_controls", "counts": d})
            return d
        if int(d.get("Pause Draft") or 0) > 0:
            best = d
        if i in (20, 40, 80) and any(int(d.get(k) or 0) for k in d):
            report.setdefault("dom_samples", []).append({"when": f"start_wait_{i//2}s", "counts": d})
    if best:
        report["time_to_first_usable_s"] = round(time.time() - t_click, 2)
        report.setdefault("dom_samples", []).append({"when": "first_usable_best_effort", "counts": best})
        return best
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
    chain_samples: list[dict[str, Any]] = []
    client_samples: list[dict[str, Any]] = []
    wake_url_hits = 0
    component_sent_hits = 0
    last_url = ""

    while time.time() < deadline and len(events) < need:
        page.wait_for_timeout(1500)
        cur = scrape_state(page)
        stamp = parse_acceptance_stamp(all_frames_text(page))
        chain = scrape_expire_chain(page)
        client = scrape_client_chain(page)
        url_now = str(page.url or "")
        if "solo_wake=" in url_now and url_now != last_url:
            wake_url_hits += 1
            last_url = url_now
        if chain or client:
            sample = {"ts": time.time(), **chain, "client_last": client.get("last"), "client_chain": client.get("chain")}
            report["expire_chain_final"] = {**chain, "client": client}
            if not chain_samples or chain_samples[-1].get("commits") != chain.get("commits"):
                chain_samples.append(sample)
            if client and (not client_samples or client_samples[-1].get("chain") != client.get("chain")):
                client_samples.append({**client, "ts": time.time()})
            if "component_value_sent" in str(client.get("chain") or ""):
                component_sent_hits += 1
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
            evt["chain_commits"] = chain.get("commits")
            evt["chain_last"] = chain.get("last")
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
    report["expire_chain_samples"] = chain_samples[-24:]
    report["expire_client_samples"] = client_samples[-24:]
    report["solo_wake_url_hits"] = wake_url_hits
    report["component_value_sent_hits"] = component_sent_hits
    if wake_url_hits > 0:
        report.setdefault("errors", []).append(f"legacy_url_wake_detected:{wake_url_hits}")
    analyze_chain_break(report, report.get("expire_chain_final") or {}, scrape_client_chain(page))
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
            target_sha = read_expected_deploy_sha()
            report["expected_build"] = f"baseball-dev-{target_sha}"
            report["commits_expected"] = ["77c10b7", "9c5fa0c", target_sha]
            report["deploy_build_seen"] = wait_for_deploy(page, target_sha, timeout_s=900)
            if not report["deploy_build_seen"]:
                report.setdefault("errors", []).append(f"deploy_not_seen:expected={target_sha}")
                report["passed"] = False
                report["verification_status"] = "not_yet_verified_deploy_unknown"
                report["soak_duration_s"] = round(time.time() - report["started_at"], 1)
                REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
                REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
                return 1

            # Phase 1 — ordinary Solo start (no ld_accept / canary / dev flags)
            from cloud_streamlit_wake import goto_and_wake

            goto_and_wake(page, PROD_URL, timeout_s=180)
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
                analyze_chain_break(
                    report,
                    report.get("expire_chain_final") or scrape_expire_chain(page),
                    scrape_client_chain(page),
                )
                missing = report.get("first_missing_chain_stage")
                if missing:
                    report["errors"].append(f"chain_break_at:{missing}")
                elif not (report.get("expire_chain_final") or {}).get("chain"):
                    report["errors"].append("expire_chain_empty_no_server_ticks")

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

                page.goto(f"{BASE}/?active_page=Historical%20Explorer", wait_until="domcontentloaded", timeout=90000)
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
            final_chain = scrape_expire_chain(page)
            report["acceptance_stamp_final"] = final_stamp
            report["expire_chain_final"] = final_chain or report.get("expire_chain_final") or {}
            report["expiration_commits"] = max(
                int(final_stamp.get("exp_commits") or 0),
                int((report.get("expire_chain_final") or {}).get("commits") or 0),
                len(exp_events),
            )
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
            report["solo_poll_owner"] = (
                (report.get("expire_chain_final") or {}).get("owner")
                or final_stamp.get("solo_poll")
                or "wake_cloud"
            )
            if len(exp_events) < 4:
                chain = report.get("expire_chain_final") or {}
                report["expire_chain_diagnosis"] = {
                    "owner": chain.get("owner"),
                    "commits": chain.get("commits"),
                    "last_stage": chain.get("last"),
                    "chain": chain.get("chain"),
                }
                if not chain:
                    report["errors"].append("expire_chain_probe_missing")
                elif int(chain.get("commits") or 0) == 0:
                    last = str(chain.get("last") or "")
                    if last == "wake_received" and "deadline_crossed" not in str(chain.get("chain") or ""):
                        report["errors"].append("wake_received_but_no_deadline_crossed")
                    elif "deadline_crossed" in str(chain.get("chain") or "") and "commit_confirmed" not in str(
                        chain.get("chain") or ""
                    ):
                        report["errors"].append("deadline_crossed_but_no_commit")
                    elif not last:
                        report["errors"].append("expire_chain_empty_no_server_ticks")

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
