"""Human-test correction browser acceptance — Start 5× (wait≥10s), Queue, copy, scarcity."""

from __future__ import annotations

import importlib.util
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "tb_probe" / "human_test_correction_accept.json"
PORT = 8511
URL = f"http://127.0.0.1:{PORT}/?suite_workspace=daniel&ux_latency=1&active_page=Live%20Draft%20Room"
TIMER_SEC = 60
PICKS_PER_TEAM = 3


def _load_rt():
    spec = importlib.util.spec_from_file_location(
        "rt_accept", ROOT / "scripts" / "local_tb_realtime_analytics_accept.py"
    )
    assert spec and spec.loader
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    return rt


def _git_head() -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT)).decode().strip()
    except Exception:
        return ""


def _scrub() -> dict:
    archived = []
    rooms = ROOT / "data" / "draft_rooms"
    if rooms.is_dir():
        for p in rooms.glob("*.json"):
            if p.name.startswith("_"):
                continue
            try:
                dest = rooms / f"_archive_{p.stem}_{int(time.time())}.json"
                p.replace(dest)
                archived.append(dest.name)
            except Exception:
                pass
    for name in ("daniel", "guest"):
        path = ROOT / "data" / "workspaces" / name / "baseball_user_state.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = payload.get("state") if isinstance(payload, dict) else None
            if not isinstance(state, dict):
                continue
            for key in list(state.keys()):
                kl = key.lower()
                if "live_draft" in kl or key in {
                    "draft_queue",
                    "active_shared_draft_room_code",
                    "room_your_team",
                }:
                    state.pop(key, None)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass
    return {"archived": archived[:8]}


def _body(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=8000) or ""
    except Exception:
        return ""


def _visible_timer(page) -> int | None:
    for frame in page.frames:
        try:
            el = frame.locator(".live-draft-timer")
            if el.count():
                raw = (el.first.inner_text(timeout=500) or "").strip()
                m = re.search(r"(\d{1,3})", raw)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
    blob = _body(page)
    for pat in (
        r"TIME REMAINING\s*[:\-]?\s*(\d{1,3})\b",
        r"Time remaining\s*[:\-]?\s*\*?\*?(\d{1,3})\s*s?\b",
    ):
        m = re.search(pat, blob, re.I)
        if m:
            return int(m.group(1))
    return None


def _wait_start_enabled(page, timeout_s: float = 300.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        body = _body(page)
        btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
        if btn.count():
            try:
                if btn.first.is_enabled():
                    consumer = "Your draft is ready" in body or (
                        "rankings and player projections are ready" in body
                    )
                    tech = any(
                        x in body
                        for x in (
                            "Canonical projections",
                            "Lifecycle: ready",
                            "Projections: ready",
                            "Scheduled picks:",
                        )
                    )
                    return {
                        "ok": True,
                        "consumer_copy": consumer,
                        "tech_leak": tech,
                        "elapsed_s": round(time.time() - t0, 2),
                    }
            except Exception:
                pass
        page.wait_for_timeout(1000)
    return {"ok": False, "elapsed_s": round(time.time() - t0, 2), "snip": _body(page)[:400]}


def run_one_start(page, rt, run_i: int) -> dict:
    report: dict = {"run": run_i, "ok": False}
    _scrub()
    page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(2500)
    try:
        rt._click_end(page)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    flow: dict = {}
    ready = rt._create_ready_solo(
        page,
        flow,
        num_teams=2,
        picks_per_team=PICKS_PER_TEAM,
        timer_seconds=TIMER_SEC,
    )
    report["create_flow"] = flow
    report["ready_created"] = bool(ready)
    if not ready:
        report["error"] = "create_ready_failed"
        return report
    enabled = _wait_start_enabled(page)
    report["ready"] = enabled
    if not enabled.get("ok"):
        report["error"] = "start_not_enabled"
        return report

    # ≥10s Ready dwell — no timer / no board advance
    page.wait_for_timeout(11000)
    body_w = _body(page)
    report["after_wait_10s"] = {
        "has_start": page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I)).count() > 0,
        "timer": _visible_timer(page),
        "tech_leak": any(
            x in body_w
            for x in ("Lifecycle:", "Canonical projections", "Projections: ready", "Scheduled picks:")
        ),
        "consumer_ready": "Your draft is ready" in body_w
        or "rankings and player projections are ready" in body_w,
        "pick2_visible": bool(re.search(r"\bPick\s*2\b", body_w, re.I))
        and "Start Draft" not in body_w,
    }
    if not report["after_wait_10s"]["has_start"]:
        report["error"] = "lost_ready_during_wait"
        return report

    btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I)).locator(
        "visible=true"
    )
    if btn.count() == 0:
        btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
    btn.first.click(timeout=12000, force=True)

    t0 = time.time()
    first_timer = None
    pick1 = False
    feedback = False
    while time.time() - t0 < 60:
        body = _body(page)
        if re.search(r"Draft started|is on the clock", body, re.I):
            feedback = True
        if re.search(r"\bPick\s*1\b", body, re.I):
            pick1 = True
        sec = _visible_timer(page)
        if sec is not None:
            first_timer = sec
            if pick1 and sec >= 55:
                break
        page.wait_for_timeout(300)

    report["first_visible_timer"] = first_timer
    report["pick1_visible"] = pick1
    report["start_feedback_consumer"] = feedback
    report["tech_start_msg"] = (
        "Pick 1 clock begins when the live board is ready" in _body(page)
    )
    report["exact_60"] = first_timer == TIMER_SEC
    report["ok"] = bool(
        pick1
        and first_timer is not None
        and 55 <= int(first_timer) <= TIMER_SEC
        and report["after_wait_10s"]["has_start"]
        and not report["after_wait_10s"]["pick2_visible"]
    )
    return report


def run_queue_proof(page) -> dict:
    out: dict = {"ok": False, "latencies_s": [], "adds": []}
    t0 = time.time()
    while time.time() - t0 < 90:
        if page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count() >= 3:
            break
        page.wait_for_timeout(500)
    body_before = _body(page)
    x_before = body_before.count("✕")
    for i in range(5):
        btns = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I))
        if btns.count() == 0:
            out["adds"].append({"i": i, "error": "no_button"})
            break
        t1 = time.perf_counter()
        try:
            btns.first.click(timeout=8000)
        except Exception as exc:
            out["adds"].append({"i": i, "error": str(exc)[:120]})
            continue
        grew = False
        for _ in range(25):
            page.wait_for_timeout(80)
            body = _body(page)
            if body.count("✕") > x_before or "Queued" in body:
                grew = True
                x_before = body.count("✕")
                break
        lat = time.perf_counter() - t1
        out["latencies_s"].append(round(lat, 3))
        out["adds"].append({"i": i, "lat_s": round(lat, 3), "grew": grew})
        page.wait_for_timeout(200)
    if out["latencies_s"]:
        out["median_s"] = round(statistics.median(out["latencies_s"]), 3)
        xs = sorted(out["latencies_s"])
        out["p95_s"] = xs[max(0, int(len(xs) * 0.95) - 1)]
    out["ok"] = len(out["latencies_s"]) >= 5 and all(x < 2.0 for x in out["latencies_s"])
    body = _body(page)
    out["no_fit_calculating"] = "Roster Fit calculating" not in body
    out["no_scarcity_dup"] = "Draft Decision · Roster & Scarcity" not in body
    out["team_needs"] = "Team Needs" in body
    out["rec_rankings"] = "Recommendation Rankings" in body or "Recommendation rankings" in body
    return out


def run_timer_zero(page, max_n: int = 2) -> dict:
    out: dict = {"ok": False, "timings": []}
    for _ in range(max_n):
        # Wait until low
        for __ in range(200):
            sec = _visible_timer(page)
            if sec is not None and sec <= 3:
                break
            page.wait_for_timeout(400)
        pick_before = None
        m = re.search(r"\bPick\s*(\d+)\b", _body(page), re.I)
        if m:
            pick_before = int(m.group(1))
        saw_zero = False
        t_zero = None
        deadline = time.time() + 20
        while time.time() < deadline:
            sec = _visible_timer(page)
            if sec == 0 and not saw_zero:
                saw_zero = True
                t_zero = time.perf_counter()
            if saw_zero and t_zero is not None and sec is not None and sec >= 55:
                m2 = re.search(r"\bPick\s*(\d+)\b", _body(page), re.I)
                pick_after = int(m2.group(1)) if m2 else None
                if pick_after and pick_before and pick_after > pick_before:
                    out["timings"].append(
                        {
                            "from": pick_before,
                            "to": pick_after,
                            "zero_to_next_s": round(time.perf_counter() - t_zero, 3),
                            "next_timer": sec,
                        }
                    )
                    break
            page.wait_for_timeout(40)
        else:
            out["timings"].append(
                {"from": pick_before, "saw_zero": saw_zero, "error": "timeout"}
            )
    ok_times = [
        t["zero_to_next_s"]
        for t in out["timings"]
        if isinstance(t.get("zero_to_next_s"), (int, float))
    ]
    out["all_timings_s"] = ok_times
    out["ok"] = bool(ok_times) and all(x < 2.0 for x in ok_times)
    return out


def main() -> int:
    from playwright.sync_api import sync_playwright

    rt = _load_rt()
    report: dict = {
        "prev_dev_head": "df8574ff099f780b3ef224ecde12952d5c0db54c",
        "head": _git_head(),
        "port": PORT,
        "starts": [],
        "queue": {},
        "timer_zero": {},
        "checks": {},
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i in range(1, 6):
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            try:
                one = run_one_start(page, rt, i)
            except Exception as exc:
                one = {"run": i, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:240]}
            report["starts"].append(one)
            try:
                page.close()
            except Exception:
                pass

        report["starts_ok"] = sum(1 for s in report["starts"] if s.get("ok"))
        report["checks"]["starts_5_of_5"] = report["starts_ok"] == 5
        report["checks"]["first_timers"] = [s.get("first_visible_timer") for s in report["starts"]]
        report["checks"]["consumer_ready"] = all(
            (s.get("ready") or {}).get("consumer_copy") for s in report["starts"] if s.get("ok")
        )
        report["checks"]["no_tech_leak"] = all(
            not (s.get("ready") or {}).get("tech_leak")
            and not (s.get("after_wait_10s") or {}).get("tech_leak")
            for s in report["starts"]
            if s.get("ok")
        )

        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        live = run_one_start(page, rt, 99)
        report["live_start"] = {k: live.get(k) for k in ("ok", "first_visible_timer", "error")}
        if live.get("ok"):
            report["queue"] = run_queue_proof(page)
            report["timer_zero"] = run_timer_zero(page, max_n=2)
            body = _body(page)
            report["checks"]["no_scarcity_dup"] = "Draft Decision · Roster & Scarcity" not in body
            report["checks"]["team_needs"] = "Team Needs" in body
        browser.close()

    report["verdict_partial"] = {
        "starts": report["checks"].get("starts_5_of_5"),
        "queue": (report.get("queue") or {}).get("ok"),
        "timer_zero": (report.get("timer_zero") or {}).get("ok"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "starts_ok": report["starts_ok"],
        "first_timers": report["checks"].get("first_timers"),
        "queue": report.get("queue"),
        "timer_zero": report.get("timer_zero"),
        "checks": report["checks"],
        "out": str(OUT),
    }, indent=2, default=str))
    return 0 if report["checks"].get("starts_5_of_5") else 1


if __name__ == "__main__":
    raise SystemExit(main())
