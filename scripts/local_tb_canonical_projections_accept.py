"""Offline + browser canonical projections / Live Draft acceptance (local only)."""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "tb_probe" / "canonical_projections_accept.json"
SHOT = ROOT / "data" / "tb_probe" / "canonical_projections"
PORT = 8511
URL = f"http://127.0.0.1:{PORT}/?suite_workspace=daniel&ux_latency=1"
LOG = ROOT / "data" / "tb_probe" / "canonical_projections_streamlit.log"
LIGHT_HARD_S = 2.0


def _git_head() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT))
            .decode()
            .strip()
        )
    except Exception:
        return ""


def _wait_http(url: str, timeout_s: float = 120.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if int(getattr(resp, "status", 200) or 200) < 500:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


def _scrub() -> list[str]:
    archived: list[str] = []
    rooms = ROOT / "data" / "draft_rooms"
    if rooms.is_dir():
        for p in rooms.glob("*.json"):
            if p.name.startswith("_"):
                continue
            dest = rooms / f"_archive_{p.stem}_{int(time.time())}.json"
            try:
                p.replace(dest)
                archived.append(dest.name)
            except Exception:
                pass
    try:
        import importlib.util

        scrub_path = ROOT / "scripts" / "local_tb_scrub_human_clean.py"
        spec = importlib.util.spec_from_file_location("scrub", scrub_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in ("daniel", "guest"):
            archived.extend(
                mod.scrub(ROOT / "data" / "workspaces" / name / "baseball_user_state.json")
            )
    except Exception as exc:
        archived.append(f"scrub_err:{exc}")
    # Hard-clear sticky Ready stubs that leave Pick 1 of 0 / empty teams.
    for name in ("daniel", "guest"):
        path = ROOT / "data" / "workspaces" / name / "baseball_user_state.json"
        if not path.exists():
            continue
        try:
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
            state = payload.get("state") if isinstance(payload, dict) else None
            if not isinstance(state, dict):
                continue
            cleared = []
            for key in (
                "live_draft_room",
                "pfs.live_draft_room",
                "live_draft_state",
                "pfs.live_draft_state",
                "draft_queue",
                "canonical_draft_meta",
            ):
                if key in state:
                    state.pop(key, None)
                    cleared.append(key)
            if cleared:
                path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                archived.append(f"hard_clear:{name}:{','.join(cleared)}")
        except Exception as exc:
            archived.append(f"hard_clear_err:{exc}")
    return archived


def offline_canonical_proof() -> dict:
    import pandas as pd

    import streamlit_app as app
    from live_draft_canonical_pool import (
        attach_canonical_pool_to_room,
        collapse_identity_columns,
        enrich_roster_frame_from_canonical,
        load_canonical_unified_pool,
    )

    t0 = time.perf_counter()
    # Same loader Live Draft / Draft Assistant use (session-aware live settings).
    pool = load_canonical_unified_pool({})
    if pool is None or getattr(pool, "empty", True):
        pool = app.get_cached_unified_projection_pool(2024, 3, "5x5 Roto", "Balanced", False, 0.0, 50)
    load_s = time.perf_counter() - t0
    assert pool is not None and not pool.empty

    name_col = "fullName" if "fullName" in pool.columns else "Player"
    sample_names = [
        "Juan Soto",
        "Aaron Judge",
        "Shohei Ohtani",
        "Jose Ramirez",
        "Gunnar Henderson",
        "Corbin Carroll",
    ]
    cross_page = []
    for name in sample_names:
        hit = pool[pool[name_col].astype(str).str.lower() == name.lower()]
        if hit.empty:
            continue
        row = hit.iloc[0]
        cross_page.append(
            {
                "player": name,
                "proj_HR": float(pd.to_numeric(row.get("proj_HR"), errors="coerce") or 0),
                "proj_RBI": float(pd.to_numeric(row.get("proj_RBI"), errors="coerce") or 0),
                "proj_R": float(pd.to_numeric(row.get("proj_R"), errors="coerce") or 0),
                "proj_SB": float(pd.to_numeric(row.get("proj_SB"), errors="coerce") or 0),
                "proj_BA": float(pd.to_numeric(row.get("proj_BA"), errors="coerce") or 0),
                "model": float(pd.to_numeric(row.get("Model Rank"), errors="coerce") or 0),
                "market": float(pd.to_numeric(row.get("Market Rank"), errors="coerce") or 0),
                "edge": float(pd.to_numeric(row.get("Fantasy Edge"), errors="coerce") or 0),
            }
        )

    # 30-player rank compare: canonical page == Live Draft after attach
    top = pool.sort_values("Market Rank").head(30).copy()
    room = {
        "status": "not_started",
        "teams": ["Team A", "Team B"],
        "config": {
            "scoring_type": "5x5 Roto",
            "fantasy_format": "5x5 Roto",
            "projection_style": "Balanced",
            "projection_window": 3,
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1, "BN": 2},
            "picks_per_team": 5,
            "timer_seconds": 8,
            "teams": ["Team A", "Team B"],
            "your_team": "Team A",
        },
        "pool": None,
        "rosters": {"Team A": [], "Team B": []},
        "draft_board": [],
        "pick_order": [],
        "current_pick_index": 0,
    }
    session = {"live_draft_room": room}
    attached = attach_canonical_pool_to_room(session, room, force=True)
    live_pool = session["live_draft_room"]["pool"]
    rank_rows = []
    near_eq = 0
    for _, crow in top.iterrows():
        nm = str(crow.get(name_col) or "").strip()
        live = live_pool[live_pool[name_col].astype(str).str.lower() == nm.lower()]
        if live.empty:
            continue
        lrow = live.iloc[0]
        c_model = float(pd.to_numeric(crow.get("Model Rank"), errors="coerce") or 0)
        l_model = float(pd.to_numeric(lrow.get("Model Rank"), errors="coerce") or 0)
        c_mkt = float(pd.to_numeric(crow.get("Market Rank"), errors="coerce") or 0)
        l_mkt = float(pd.to_numeric(lrow.get("Market Rank"), errors="coerce") or 0)
        if abs(c_model - c_mkt) <= 1.5:
            near_eq += 1
        rank_rows.append(
            {
                "player": nm,
                "canon_model": c_model,
                "live_model": l_model,
                "canon_market": c_mkt,
                "live_market": l_mkt,
                "edge": c_mkt - c_model,
                "model_match": abs(c_model - l_model) < 0.5,
                "market_match": abs(c_mkt - l_mkt) < 0.5,
            }
        )

    # Team totals proof: draft 5 known players onto Team A
    five = []
    for name in ["Juan Soto", "Aaron Judge", "Jose Ramirez", "Gunnar Henderson", "Corbin Carroll"]:
        hit = pool[pool[name_col].astype(str).str.lower() == name.lower()]
        if hit.empty:
            continue
        r = hit.iloc[0].to_dict()
        five.append(
            {
                "playerID": r.get("playerID"),
                "fullName": r.get(name_col),
                "Player": r.get(name_col),
                "Primary Position": r.get("Primary Position") or "OF",
                "MLB Team": r.get("Team") or r.get("MLB Team"),
            }
        )
    room2 = dict(room)
    room2["status"] = "complete"
    room2["pool"] = live_pool
    room2["rosters"] = {"Team A": five, "Team B": five[:3]}
    session2 = {"live_draft_room": room2}
    totals = app.live_draft_team_totals(room2, session=session2)
    roster = app.live_draft_rosters_df(room2, session=session2)
    roster = enrich_roster_frame_from_canonical(roster, session=session2, room=room2)
    roster = collapse_identity_columns(roster)
    team_a = roster[roster["Fantasy Team"] == "Team A"]
    individual = []
    for _, r in team_a.iterrows():
        individual.append(
            {
                "player": str(r.get("Player") or r.get("fullName")),
                "proj_HR": float(pd.to_numeric(r.get("proj_HR"), errors="coerce") or 0),
                "proj_RBI": float(pd.to_numeric(r.get("proj_RBI"), errors="coerce") or 0),
                "proj_R": float(pd.to_numeric(r.get("proj_R"), errors="coerce") or 0),
                "proj_SB": float(pd.to_numeric(r.get("proj_SB"), errors="coerce") or 0),
                "proj_BA": float(pd.to_numeric(r.get("proj_BA"), errors="coerce") or 0),
            }
        )
    sum_hr = sum(x["proj_HR"] for x in individual)
    ta = totals[totals["Fantasy Team"] == "Team A"].iloc[0] if not totals.empty else None

    mkt = pd.to_numeric(pool["Market Rank"], errors="coerce")
    mdl = pd.to_numeric(pool["Model Rank"], errors="coerce")
    edge = mkt - mdl
    near_eq_all = int((mdl - mkt).abs().le(1.5).sum())

    return {
        "pool_load_s": round(load_s, 2),
        "pool_rows": int(len(pool)),
        "attach": attached,
        "cross_page_sample": cross_page,
        "rank_30": rank_rows,
        "rank_30_model_match": sum(1 for r in rank_rows if r["model_match"]) >= max(28, len(rank_rows) - 2),
        "rank_30_market_match": sum(1 for r in rank_rows if r["market_match"]) >= max(28, len(rank_rows) - 2),
        "rank_30_model_match_count": sum(1 for r in rank_rows if r["model_match"]),
        "rank_30_market_match_count": sum(1 for r in rank_rows if r["market_match"]),
        "near_eq_in_top30": near_eq,
        "near_eq_all_pool": near_eq_all,
        "edge_abs_gt5": int(edge.abs().gt(5).sum()),
        "team_a_individuals": individual,
        "team_a_sum_hr": sum_hr,
        "team_a_totals_hr": float(ta["Projected HR"]) if ta is not None else None,
        "team_a_totals_avg": float(ta["Projected AVG"]) if ta is not None else None,
        "team_a_totals_match_sum": (
            ta is not None and abs(float(ta["Projected HR"]) - sum_hr) < 0.6
        ),
        "roster_cols_unique": bool(roster.columns.is_unique),
        "canonical_loader": "get_cached_unified_projection_pool / live_draft_canonical_pool",
    }


def browser_pass(report: dict) -> dict:
    from playwright.sync_api import sync_playwright

    # Reuse the proven Solo Ready → Start Draft automation from the prior accept script.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "rt_accept", ROOT / "scripts" / "local_tb_realtime_analytics_accept.py"
    )
    assert spec and spec.loader
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)

    SHOT.mkdir(parents=True, exist_ok=True)
    result: dict = {"ok": False, "latencies": {}, "checks": {}, "flow": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        t_cold = time.perf_counter()
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(5000)
        result["app_cold_s"] = round(time.perf_counter() - t_cold, 2)

        # Draft Assistant cold/warm
        t0 = time.perf_counter()
        rt._nav_live_draft.__wrapped__ if False else None  # noqa: keep import side-effects quiet
        for label, key_cold, key_warm in (
            (r"Draft Assistant", "assistant_cold_s", "assistant_warm_s"),
            (r"Fantasy Sleepers", "sleepers_cold_s", "sleepers_warm_s"),
        ):
            t0 = time.perf_counter()
            try:
                loc = page.locator("label", has_text=re.compile(label)).first
                loc.click(timeout=10000, force=True)
                page.wait_for_timeout(2500)
            except Exception:
                pass
            result[key_cold] = round(time.perf_counter() - t0, 2)
            page.screenshot(path=str(SHOT / f"{key_cold}.png"), full_page=False)
            t1 = time.perf_counter()
            try:
                page.locator("label", has_text=re.compile(r"Live Draft Room")).first.click(
                    timeout=8000, force=True
                )
                page.wait_for_timeout(1200)
                page.locator("label", has_text=re.compile(label)).first.click(
                    timeout=8000, force=True
                )
                page.wait_for_timeout(1500)
            except Exception:
                pass
            result[key_warm] = round(time.perf_counter() - t1, 2)

        # Solo create → Ready → Start Draft (always clear any sticky session room first)
        try:
            page.locator("label", has_text=re.compile(r"Live Draft Room")).first.click(
                timeout=10000, force=True
            )
            page.wait_for_timeout(2500)
        except Exception:
            pass
        rt._click_end(page)
        page.wait_for_timeout(1500)
        try:
            page.get_by_role("button", name=re.compile(r"Return to Live Draft Lobby|Delete Draft|Start Over", re.I)).first.click(
                timeout=4000, force=True
            )
            page.wait_for_timeout(2000)
        except Exception:
            pass
        ready = rt._create_ready_solo(page, result["flow"])
        result["checks"]["ready_lobby"] = bool(ready)
        page.screenshot(path=str(SHOT / "ready.png"), full_page=False)
        if ready:
            # Wait for Streamlit idle before Start so the click is not lost mid-rerun.
            for _ in range(30):
                try:
                    widget = page.locator("[data-testid='stStatusWidget']")
                    if not widget.count():
                        break
                    txtw = (widget.inner_text(timeout=500) or "").lower()
                    if "running" not in txtw:
                        break
                except Exception:
                    break
                page.wait_for_timeout(500)
            started = rt._press_start_draft(page, result["flow"])
        else:
            started = False
        result["checks"]["start_draft_gate"] = bool(started)
        page.screenshot(path=str(SHOT / "live_started.png"), full_page=False)
        txt = rt._body(page)

        result["checks"]["team_needs_present"] = "Team Needs" in txt
        result["checks"]["no_bn_slot_labels"] = not bool(re.search(r"\bBN\s*[123]\b", txt))
        cat_block = (re.findall(r"Categories to strengthen([\s\S]{0,240})", txt) or [""])[0]
        result["checks"]["no_balanced_as_category"] = "Balanced" not in cat_block
        result["checks"]["bench_wording"] = bool(
            re.search(r"Bench|spots open|Complete", txt, re.I)
        )
        result["checks"]["why_or_badges"] = bool(
            re.search(
                r"Why Recommended|Elite Power|Speed Boost|Fills .* Need|Projects for|Strong RBI",
                txt,
                re.I,
            )
        )
        result["checks"]["real_model_edge"] = bool(
            re.search(r"Edge\s*[+\-]?\d{1,3}", txt, re.I)
        )

        lats: dict[str, list[float]] = {
            "manual_filter": [],
            "why_toggle": [],
            "queue_add": [],
        }
        for pos in ("SS", "OF", "C", "All"):
            try:
                t0 = time.perf_counter()
                sel = page.get_by_label(re.compile(r"Position|Filter", re.I))
                if sel.count():
                    sel.first.select_option(label=pos)
                else:
                    page.get_by_text(pos, exact=True).first.click(timeout=1500, force=True)
                page.wait_for_timeout(250)
                lats["manual_filter"].append(time.perf_counter() - t0)
            except Exception:
                pass
        try:
            t0 = time.perf_counter()
            page.get_by_text(re.compile(r"Why Recommended", re.I)).first.click(
                timeout=2500, force=True
            )
            page.wait_for_timeout(250)
            lats["why_toggle"].append(time.perf_counter() - t0)
        except Exception:
            pass
        try:
            t0 = time.perf_counter()
            page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).first.click(
                timeout=3000, force=True
            )
            page.wait_for_timeout(350)
            lats["queue_add"].append(time.perf_counter() - t0)
            qtxt = rt._body(page)
            result["checks"]["queue_has_proj"] = bool(
                re.search(r"\d+\s*HR|\.\d{3}\s*AVG|proj", qtxt, re.I)
            )
            result["checks"]["queue_not_stuck_calculating"] = "Roster Fit calculating" not in qtxt
        except Exception:
            result["checks"]["queue_has_proj"] = False

        for k, vals in lats.items():
            if vals:
                result["latencies"][k] = {
                    "n": len(vals),
                    "median": round(statistics.median(vals), 3),
                    "p95": round(sorted(vals)[max(0, int(len(vals) * 0.95) - 1)], 3),
                    "max": round(max(vals), 3),
                    "pass": statistics.median(vals) < LIGHT_HARD_S,
                }

        # Timer zero → next pick
        timer_ok = False
        zero_to_next = None
        for _ in range(90):
            txt = rt._body(page)
            m = re.search(r"TIME REMAINING\s*(\d+)", txt, re.I)
            if m and int(m.group(1)) == 0:
                t_zero = time.perf_counter()
                for _2 in range(60):
                    page.wait_for_timeout(200)
                    txt2 = rt._body(page)
                    m2 = re.search(r"TIME REMAINING\s*(\d+)", txt2, re.I)
                    if m2 and int(m2.group(1)) > 3:
                        zero_to_next = time.perf_counter() - t_zero
                        timer_ok = True
                        break
                    if re.search(r"Draft Completed|Team Projected Totals", txt2, re.I):
                        timer_ok = True
                        break
                break
            if re.search(r"Draft Completed|Team Projected Totals", txt, re.I):
                timer_ok = True
                break
            page.wait_for_timeout(1000)
        result["checks"]["timer_zero_advance"] = timer_ok
        result["latencies"]["zero_to_next_s"] = (
            round(zero_to_next, 3) if zero_to_next is not None else None
        )

        # Force end for completion checks if needed
        try:
            page.get_by_role("button", name=re.compile(r"End Draft", re.I)).first.click(
                timeout=3000, force=True
            )
            page.wait_for_timeout(3000)
        except Exception:
            pass
        # Wait for autopicks to finish short draft
        for _ in range(60):
            txt = rt._body(page)
            if "Team Projected Totals" in txt or "Draft Completed" in txt:
                break
            page.wait_for_timeout(2000)
        txt = rt._body(page)
        page.screenshot(path=str(SHOT / "completion.png"), full_page=True)
        result["checks"]["projected_totals_present"] = (
            "Team Projected Totals" in txt or "Projected HR" in txt
        )
        result["checks"]["no_all_zero_totals"] = not bool(
            re.search(r"Projected HR\s*0\b[\s\S]{0,120}Projected RBI\s*0\b", txt)
        )
        result["checks"]["no_duplicate_col_crash"] = (
            "Cannot set a DataFrame with multiple columns" not in txt
        )
        result["checks"]["latest_pick_named"] = bool(
            re.search(r"Pick\s+\d+:\s+.+\s+drafted\s+", txt, re.I)
        )

        light_ok = all(
            v.get("pass", True) for v in result["latencies"].values() if isinstance(v, dict)
        )
        result["ok"] = bool(
            result["checks"].get("start_draft_gate")
            and result["checks"].get("no_duplicate_col_crash")
            and result["checks"].get("team_needs_present")
            and result["checks"].get("no_balanced_as_category")
            and light_ok
        )
        browser.close()
    return result


def main() -> int:
    report: dict = {
        "head_before": _git_head(),
        "port": PORT,
        "scrub": _scrub(),
        "offline": {},
        "browser": {},
        "ok": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)

    print("OFFLINE canonical proof…")
    try:
        report["offline"] = offline_canonical_proof()
    except Exception as exc:
        report["offline"] = {"error": f"{type(exc).__name__}: {exc}"}
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print("OFFLINE FAILED", report["offline"])
        return 1

    # Launch streamlit if needed
    if not _wait_http(f"http://127.0.0.1:{PORT}/", timeout_s=3):
        LOG.parent.mkdir(parents=True, exist_ok=True)
        logf = open(LOG, "w", encoding="utf-8")
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
            ],
            cwd=str(ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
        report["pid"] = proc.pid
        if not _wait_http(f"http://127.0.0.1:{PORT}/", timeout_s=180):
            report["error"] = "streamlit_start_timeout"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return 1
    else:
        report["pid"] = "existing"

    print("BROWSER pass…")
    try:
        report["browser"] = browser_pass(report)
    except Exception as exc:
        report["browser"] = {"error": f"{type(exc).__name__}: {exc}"}

    off = report["offline"]
    br = report.get("browser") or {}
    report["ok"] = bool(
        off.get("team_a_totals_match_sum")
        and off.get("rank_30_model_match")
        and off.get("near_eq_in_top30", 99) < 10
        and off.get("roster_cols_unique")
        and br.get("ok")
    )
    report["head_after"] = _git_head()
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "out": str(OUT)}, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
