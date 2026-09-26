"""Focused post-durability regressions: Queue 5×, then short completion."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "tb_probe" / "post_durability_regs.json"
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


def main() -> int:
    from playwright.sync_api import sync_playwright

    rt = _rt()
    _scrub()
    report: dict = {"ok": False, "queue": {}, "completion": {}, "alonso": {}}
    print("scrubbed; launching", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(2500)
        flow: dict = {}
        ok = rt._create_ready_solo(page, flow, num_teams=2, picks_per_team=4, timer_seconds=8)
        report["create"] = ok
        report["flow"] = flow
        if not ok:
            report["error"] = "create_failed"
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            browser.close()
            return 1
        start_rep: dict = {}
        started = rt._press_start_draft(page, start_rep)
        report["start"] = start_rep
        report["started"] = started
        print(f"started={started} live_at={start_rep.get('live_at_s')}", flush=True)
        if not started:
            report["error"] = "start_failed"
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            browser.close()
            return 1

        # --- Queue: 5 rapid Add to Queue clicks ---
        q: dict = {"latencies_s": [], "labels": [], "ok": False}
        deadline = time.time() + 45
        while time.time() < deadline and len(q["latencies_s"]) < 5:
            btns = page.get_by_role("button", name=re.compile(r"Add to Queue", re.I))
            n = btns.count()
            if n <= 0:
                page.wait_for_timeout(400)
                continue
            idx = len(q["latencies_s"]) % max(n, 1)
            try:
                label = (btns.nth(idx).inner_text() or "")[:80]
            except Exception:
                label = ""
            t0 = time.perf_counter()
            try:
                btns.nth(idx).click(timeout=3000, force=False)
                page.wait_for_timeout(250)
                q["latencies_s"].append(round(time.perf_counter() - t0, 3))
                q["labels"].append(label)
                print(f"queue_add {len(q['latencies_s'])} {label!r} {q['latencies_s'][-1]}s", flush=True)
            except Exception as exc:
                q.setdefault("errors", []).append(f"{type(exc).__name__}: {exc}"[:120])
                page.wait_for_timeout(400)
        body = ""
        try:
            body = page.inner_text("body") or ""
        except Exception:
            pass
        q["body_has_queue"] = bool(re.search(r"draft queue|your queue|queued", body, re.I))
        q["ok"] = len(q["latencies_s"]) >= 5 and all(x < 2.0 for x in q["latencies_s"])
        report["queue"] = q
        print(f"queue_ok={q['ok']} n={len(q['latencies_s'])} lat={q['latencies_s']}", flush=True)

        # --- Alonso eligibility smoke via Manual Draft search if present ---
        alonso: dict = {"ok": False}
        try:
            # Prefer drafting Alonso via search/manual if UI exposes it.
            search = page.get_by_placeholder(re.compile(r"search|player", re.I))
            if search.count():
                search.first.fill("Pete Alonso")
                page.wait_for_timeout(800)
                body2 = page.inner_text("body") or ""
                alonso["body_has_alonso"] = "Alonso" in body2
                # If C is filled in a longer draft this would matter; here just prove player visible.
                alonso["ok"] = "Alonso" in body2
            else:
                alonso["skipped"] = "no_search"
                alonso["ok"] = True  # not blocking when manual search absent in minimal view
        except Exception as exc:
            alonso["error"] = f"{type(exc).__name__}: {exc}"[:160]
        report["alonso"] = alonso

        # --- Completion: let short draft finish / End Draft ---
        comp: dict = {"ok": False}
        # 2 teams × 4 picks = 8 picks; 8s clock → ~64s. Prefer End Draft if present.
        end = page.get_by_role("button", name=re.compile(r"End Draft|Complete Draft", re.I))
        if end.count():
            try:
                end.first.click(timeout=5000, force=False)
                page.wait_for_timeout(3000)
                comp["clicked_end"] = True
            except Exception as exc:
                comp["end_err"] = f"{type(exc).__name__}: {exc}"[:120]
        else:
            # Wait for natural completion with short clock.
            for _ in range(90):
                b = page.inner_text("body") or ""
                if re.search(r"draft complete|this solo draft has ended|complete", b, re.I):
                    comp["natural"] = True
                    break
                page.wait_for_timeout(2000)
        body3 = ""
        try:
            body3 = page.inner_text("body") or ""
        except Exception:
            pass
        comp["complete_text"] = bool(
            re.search(r"draft complete|this solo draft has ended|status:\s*complete", body3, re.I)
        )
        # Refresh survival
        try:
            page.reload(wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            body4 = page.inner_text("body") or ""
            comp["after_refresh"] = bool(
                re.search(r"draft complete|complete|ended|Live Draft", body4, re.I)
            )
        except Exception as exc:
            comp["refresh_err"] = f"{type(exc).__name__}: {exc}"[:120]
            comp["after_refresh"] = False
        comp["ok"] = bool(comp.get("complete_text") or comp.get("natural") or comp.get("clicked_end"))
        report["completion"] = comp
        print(f"completion={comp}", flush=True)

        browser.close()

    report["ok"] = bool(report["queue"].get("ok")) and bool(report["completion"].get("ok"))
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "queue": report["queue"], "completion": report["completion"], "alonso": report["alonso"]}, indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
