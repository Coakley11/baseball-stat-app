"""5× Ready wait≥10s → Start → Pick1 @60 (+ optional queue)."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "tb_probe" / "human_start_5x.json"
URL = "http://127.0.0.1:8511/?suite_workspace=daniel&active_page=Live%20Draft%20Room&ux_latency=1"


def _rt():
    spec = importlib.util.spec_from_file_location(
        "rt_accept", ROOT / "scripts" / "local_tb_realtime_analytics_accept.py"
    )
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _scrub() -> None:
    for name in ("daniel", "guest"):
        p = ROOT / "data" / "workspaces" / name / "baseball_user_state.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        st = d.get("state") if isinstance(d.get("state"), dict) else {}
        pfs = st.get("page_filter_state")
        if isinstance(pfs, dict):
            for k in list(pfs.keys()):
                if "Draft" in k or "Live" in k:
                    pfs.pop(k, None)
        bws = st.get("baseball_workspace_state")
        if isinstance(bws, dict):
            for k in list(bws.keys()):
                if any(x in k.lower() for x in ("draft", "live", "queue", "simulat")):
                    bws.pop(k, None)
        for k in list(st.keys()):
            if any(x in k.lower() for x in ("live_draft", "draft_room", "draft_queue", "draft_state")):
                st.pop(k, None)
        p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    rooms = ROOT / "data" / "draft_rooms"
    if rooms.is_dir():
        for p in list(rooms.glob("*.json")):
            if p.name.startswith("_"):
                continue
            try:
                p.replace(rooms / f"_archive_{p.stem}_{int(time.time())}.json")
            except Exception:
                pass


def _timer(page) -> int | None:
    for frame in page.frames:
        try:
            el = frame.locator(".live-draft-timer")
            if el.count():
                m = re.search(r"(\d+)", el.first.inner_text() or "")
                if m:
                    return int(m.group(1))
        except Exception:
            pass
    m = re.search(r"TIME REMAINING\s*(\d+)", page.locator("body").inner_text(), re.I)
    return int(m.group(1)) if m else None


def one(page, rt, i: int) -> dict:
    print(f"RUN {i} scrub", flush=True)
    _scrub()
    page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(3000)
    flow: dict = {}
    ok = rt._create_ready_solo(page, flow, num_teams=2, picks_per_team=3, timer_seconds=60)
    out = {"run": i, "create_ok": ok, "flow": flow}
    if not ok:
        out["ok"] = False
        return out
    # ensure enabled
    for _ in range(120):
        btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
        if btn.count():
            try:
                if btn.first.is_enabled():
                    break
            except Exception:
                pass
        page.wait_for_timeout(1000)
    print(f"RUN {i} wait10", flush=True)
    page.wait_for_timeout(11000)
    body = page.locator("body").inner_text()
    out["after_wait"] = {
        "consumer": "Your draft is ready" in body
        or "rankings and player projections are ready" in body,
        "tech": any(
            x in body
            for x in ("Lifecycle:", "Canonical projections", "Projections: ready", "Scheduled picks:")
        ),
        "has_start": page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I)).count() > 0,
        "timer": _timer(page),
    }
    page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I)).first.click(
        timeout=12000, force=True
    )
    first = None
    pick1 = False
    for _ in range(90):
        body = page.locator("body").inner_text()
        if re.search(r"\bPick\s*1\b", body, re.I):
            pick1 = True
        first = _timer(page)
        if pick1 and first is not None and first >= 55:
            break
        page.wait_for_timeout(400)
    out["pick1"] = pick1
    out["first_timer"] = first
    out["exact_60"] = first == 60
    out["ok"] = bool(
        pick1
        and first is not None
        and 55 <= first <= 60
        and out["after_wait"]["has_start"]
        and not out["after_wait"]["tech"]
        and out["after_wait"]["consumer"]
    )
    print(f"RUN {i} ok={out['ok']} timer={first}", flush=True)
    return out


def main() -> int:
    from playwright.sync_api import sync_playwright

    rt = _rt()
    report = {"runs": [], "queue": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i in range(1, 6):
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            try:
                report["runs"].append(one(page, rt, i))
            except Exception as exc:
                report["runs"].append({"run": i, "ok": False, "error": str(exc)[:200]})
            try:
                page.close()
            except Exception:
                pass
        # queue on last successful start session
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        last = one(page, rt, 99)
        report["queue_start"] = {k: last.get(k) for k in ("ok", "first_timer")}
        if last.get("ok"):
            # wait for cards
            for _ in range(90):
                if page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count() >= 3:
                    break
                page.wait_for_timeout(1000)
            lats = []
            for i in range(5):
                btns = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I))
                if btns.count() == 0:
                    break
                t0 = time.perf_counter()
                btns.first.click(timeout=8000)
                page.wait_for_timeout(500)
                lats.append(round(time.perf_counter() - t0, 3))
            body = page.locator("body").inner_text()
            report["queue"] = {
                "latencies_s": lats,
                "count": len(lats),
                "ok": len(lats) >= 5 and all(x < 2 for x in lats),
                "no_scarcity_dup": "Draft Decision · Roster & Scarcity" not in body,
                "team_needs": "Team Needs" in body,
                "add_btns": page.get_by_role(
                    "button", name=re.compile(r"Add to Queue", re.I)
                ).count(),
            }
        browser.close()
    report["starts_ok"] = sum(1 for r in report["runs"] if r.get("ok"))
    report["first_timers"] = [r.get("first_timer") for r in report["runs"]]
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("starts_ok", "first_timers", "queue")}, indent=2), flush=True)
    return 0 if report["starts_ok"] == 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
