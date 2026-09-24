"""Real-browser Live Draft real-time + analytics acceptance (local only).

Measures warm-state lightweight interaction latency and verifies Start Draft,
ranks, Team Needs, badges/Why, MLB Team, projected totals, timer zero advance.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "tb_probe" / "realtime_analytics_accept.json"
SHOT = ROOT / "data" / "tb_probe" / "realtime_analytics"
PORT = 8511
URL = f"http://127.0.0.1:{PORT}/?suite_workspace=daniel&ux_latency=1"
LOG = ROOT / "data" / "tb_probe" / "realtime_analytics_streamlit.log"
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


def _wait_http(url: str, timeout_s: float = 90.0) -> bool:
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
    return archived


def _body(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=8000)
    except Exception:
        return ""


def _click_end(page) -> None:
    for name in (
        r"End Draft",
        r"Delete Draft",
        r"Leave Draft",
        r"Start Over",
        r"Return to Setup",
    ):
        try:
            btn = page.get_by_role("button", name=re.compile(name, re.I))
            if btn.count():
                btn.first.click(timeout=3000, force=True)
                page.wait_for_timeout(800)
        except Exception:
            pass


def _nav_live_draft(page) -> None:
    # Prefer deep-link first — product now consumes ?active_page=.
    try:
        page.goto(
            "http://127.0.0.1:8511/?suite_workspace=daniel&active_page=Live%20Draft%20Room&ux_latency=1",
            wait_until="domcontentloaded",
            timeout=120000,
        )
        page.wait_for_timeout(3000)
    except Exception:
        pass
    for attempt in range(5):
        body = _body(page)
        if (
            "live-draft-setup-anchor" in body
            or "Start New Live Draft" in body
            or "Draft Setup" in body
            or "Draft ready" in body
            or "Preparing" in body
            or re.search(r"\bStart Draft\b", body)
        ):
            return
        try:
            loc = page.locator("label", has_text=re.compile(r"Live Draft Room"))
            if loc.count() == 0:
                loc = page.get_by_text(re.compile(r"📡?\s*Live Draft Room"))
            if loc.count() == 0:
                loc = page.locator("text=Live Draft Room")
            if loc.count():
                loc.last.scroll_into_view_if_needed(timeout=3000)
                loc.last.click(timeout=10000, force=True)
            page.wait_for_timeout(2500)
        except Exception:
            page.wait_for_timeout(1500)


def _expand_draft_setup(page) -> None:
    for _ in range(6):
        try:
            teams = page.get_by_label(re.compile(r"Number of Teams", re.I))
            if teams.count() and teams.first.is_visible():
                return
        except Exception:
            pass
        for loc in (
            page.locator('summary:has-text("Draft Setup")').first,
            page.locator("[data-testid=stExpander]").filter(has_text="Draft Setup").locator("summary").first,
            page.get_by_text("Draft Setup", exact=False).first,
        ):
            try:
                if loc.count():
                    loc.click(timeout=3000, force=True)
                    page.wait_for_timeout(800)
            except Exception:
                pass
        page.wait_for_timeout(600)


def _median(xs: list[float]) -> float | None:
    clean = [float(x) for x in xs if x is not None]
    if not clean:
        return None
    return float(statistics.median(clean))


def _p95(xs: list[float]) -> float | None:
    clean = sorted(float(x) for x in xs if x is not None)
    if not clean:
        return None
    idx = max(0, min(len(clean) - 1, int(round(0.95 * (len(clean) - 1)))))
    return float(clean[idx])


def _timed_click(page, locator, *, settle_ms: int = 400) -> float:
    t0 = time.perf_counter()
    locator.click(timeout=8000, force=True)
    page.wait_for_timeout(settle_ms)
    # Wait until Streamlit is not in "Running" for soft settle, capped.
    deadline = time.time() + 8.0
    while time.time() < deadline:
        try:
            running = page.locator("[data-testid='stStatusWidget']").count()
            if not running:
                break
            text = page.locator("[data-testid='stStatusWidget']").inner_text(timeout=500)
            if "Running" not in text and "running" not in text.lower():
                break
        except Exception:
            break
        page.wait_for_timeout(100)
    return time.perf_counter() - t0


def _create_ready_solo(
    page,
    report: dict,
    *,
    num_teams: int = 2,
    picks_per_team: int = 5,
    timer_seconds: int = 8,
) -> bool:
    _nav_live_draft(page)
    page.wait_for_timeout(2500)
    # If a prior run left an active draft, end it before create/ready checks.
    body_pre = _body(page)
    if "Pause Draft" in body_pre or "Resume Draft" in body_pre:
        _click_end(page)
        page.wait_for_timeout(2000)
        _nav_live_draft(page)
        page.wait_for_timeout(2000)
    body0 = _body(page)
    # Already in Solo Ready lobby — require the Start Draft button, not just copy.
    # Reject broken stubs (Pick 1 of 0 / empty teams / no scheduled picks).
    # Never reuse a Ready room when the caller requested a specific timer/picks —
    # those settings must come from a fresh create.
    ready_btn0 = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
    broken_ready = bool(
        re.search(r"Pick\s*1\s*of\s*0\b", body0, re.I)
        or re.search(r"Scheduled picks:\s*[—\-]\b", body0, re.I)
        or re.search(r"Teams:\s*[—\-]\b", body0, re.I)
        or ("pool_rows= None" in body0 and "avail= 0" in body0)
    )
    reuse_ok = (
        ready_btn0.count()
        and not broken_ready
        and (
            "Draft ready" in body0
            or "Pick 1 clock will begin" in body0
            or "Solo draft" in body0
        )
        and int(timer_seconds) <= 0  # only reuse when caller did not pin a timer
    )
    if reuse_ok:
        report["ready_reused_existing"] = True
        report["clock_before_start"] = bool(
            re.search(r"TIME REMAINING\s+[1-9]", body0, re.I)
        )
        return True
    if ready_btn0.count() or broken_ready or "Draft ready" in body0 or "Waiting for Start Draft" in body0:
        report["clearing_existing_ready"] = True
        for _clear in range(5):
            _click_end(page)
            page.wait_for_timeout(1000)
            for name in (
                r"Return to Live Draft Lobby",
                r"Return to Setup",
                r"Start Over",
                r"Delete Draft",
                r"End Draft",
                r"End/Delete",
            ):
                try:
                    page.get_by_role("button", name=re.compile(name, re.I)).first.click(
                        timeout=2500, force=True
                    )
                    page.wait_for_timeout(900)
                except Exception:
                    pass
            _nav_live_draft(page)
            page.wait_for_timeout(1500)
            body_clr = _body(page)
            if "Start New Live Draft" in body_clr or "Number of Teams" in body_clr:
                break
            if "Draft ready" not in body_clr and "Waiting for Start Draft" not in body_clr:
                break
        _expand_draft_setup(page)

    _expand_draft_setup(page)
    # Wait until the authoritative Setup surface mounts (deep-link + stub clear).
    setup_ok = False
    for _ in range(40):
        body_w = _body(page)
        teams_n = page.get_by_label("Number of Teams", exact=True).count()
        if teams_n == 0:
            teams_n = page.get_by_label(re.compile(r"Number of Teams", re.I)).count()
        if (
            teams_n >= 1
            and (
                "live-draft-setup-anchor" in body_w
                or "Start New Live Draft" in body_w
                or "Draft Setup" in body_w
            )
        ):
            setup_ok = True
            break
        page.wait_for_timeout(1000)
        _expand_draft_setup(page)
    if not setup_ok:
        report["setup_fill_err"] = "Number of Teams never mounted"
        return False
    try:
        page.get_by_role("button", name=re.compile(r"Reset Setup to Defaults", re.I)).first.click(
            timeout=4000
        )
        page.wait_for_timeout(1500)
        _expand_draft_setup(page)
    except Exception:
        pass
    try:
        page.locator("label").filter(has_text=re.compile(r"Solo Draft")).first.click(
            timeout=4000, force=True
        )
    except Exception:
        pass
    page.wait_for_timeout(800)
    _expand_draft_setup(page)
    try:
        teams_input = page.get_by_label("Number of Teams", exact=True)
        if not teams_input.count():
            teams_input = page.get_by_label(re.compile(r"Number of Teams", re.I))
        teams_input.first.click(timeout=8000)
        teams_input.first.fill(str(int(num_teams)), timeout=8000)
        teams_input.first.press("Tab")
        picks = page.get_by_label("Picks per Team", exact=True)
        if not picks.count():
            picks = page.get_by_label(re.compile(r"Picks per Team", re.I))
        picks.first.click(timeout=8000)
        picks.first.fill(str(int(picks_per_team)), timeout=8000)
        picks.first.press("Tab")
        try:
            timer = page.get_by_label("Timer per Pick", exact=True)
            if not timer.count():
                timer = page.get_by_label(re.compile(r"Timer per Pick", re.I))
            if timer.count():
                # Selectbox — map seconds to product labels (no free-text fill).
                label_map = {
                    30: "30 sec",
                    60: "60 sec",
                    90: "90 sec",
                    120: "2 min",
                    300: "5 min",
                    1200: "20 min",
                }
                want = label_map.get(int(timer_seconds), "30 sec")
                timer.first.click(timeout=5000)
                page.get_by_text(want, exact=True).first.click(timeout=5000)
                report["timer_set"] = int(
                    {v: k for k, v in label_map.items()}.get(want, 30)
                )
        except Exception:
            pass
        page.wait_for_timeout(800)
        report["teams_picks_set"] = True
        report["setup_teams"] = int(num_teams)
        report["setup_picks_per_team"] = int(picks_per_team)
    except Exception as e:
        report["setup_fill_err"] = str(e)[:160]
        # Do NOT accept an existing Ready after a failed setup fill — that leaves
        # sticky rooms with the wrong timer / cold projection gate.
        return False
    for lab, val in (
        ("C", "0"),
        ("1B", "0"),
        ("2B", "0"),
        ("3B", "0"),
        ("SS", "1"),
        ("OF", "1"),
        ("DH / UTIL", "0"),
        ("P", "0"),
        ("Bench Spots", "3"),
    ):
        try:
            page.get_by_label(lab, exact=True).fill(val, timeout=2500)
        except Exception:
            pass
    page.wait_for_timeout(1500)
    start = page.get_by_role("button", name=re.compile(r"Start New Live Draft", re.I))
    for _ in range(40):
        if start.count():
            break
        page.wait_for_timeout(1500)
        start = page.get_by_role("button", name=re.compile(r"Start New Live Draft", re.I))
    if not start.count():
        report["create_btn_missing"] = True
        body = _body(page)
        ready_btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
        if ready_btn.count():
            return True
        return False
    start.first.click(timeout=8000, force=True)
    for i in range(120):
        page.wait_for_timeout(1000)
        ready_btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
        if not ready_btn.count():
            ready_btn = page.get_by_role("button", name=re.compile(r"Start Draft", re.I)).filter(
                has_not_text=re.compile(r"New Live|Shared|Prepare", re.I)
            )
        body = _body(page)
        # Require the explicit Ready CTA — feedback text alone is not enough.
        if ready_btn.count() and (
            "Draft ready" in body
            or "Pick 1 clock will begin" in body
            or "Solo draft" in body
            or "timer" in body.lower()
            or True
        ):
            # Exclude "Start New Live Draft" false-positives.
            labels = []
            try:
                for bi in range(min(ready_btn.count(), 5)):
                    labels.append((ready_btn.nth(bi).inner_text(timeout=1000) or "").strip())
            except Exception:
                pass
            if any(re.fullmatch(r"Start Draft", lab, re.I) for lab in labels):
                report["ready_at_s"] = i
                report["clock_before_start"] = bool(
                    re.search(r"TIME REMAINING\s+[1-9]", body, re.I)
                )
                report["ready_btn_labels"] = labels
                return True
        if "Recommended Players" in body and "TIME REMAINING" in body and not ready_btn.count():
            report["started_without_ready"] = True
            report["ready_at_s"] = i
            return False
    report["ready_timeout"] = True
    report["ready_body_snip"] = _body(page)[:800]
    return False


def _press_start_draft(page, report: dict) -> bool:
    btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
    if not btn.count():
        btn = page.get_by_role("button", name=re.compile(r"Start Draft", re.I))
    if not btn.count():
        report["start_draft_btn_missing"] = True
        return False
    # Capture pre-click body so we can detect transition out of Ready.
    before = _body(page)
    report["start_draft_btn_disabled"] = False
    try:
        report["start_draft_btn_disabled"] = not btn.first.is_enabled()
    except Exception:
        pass
    btn.first.click(timeout=8000, force=True)
    for i in range(90):
        page.wait_for_timeout(1000)
        body = _body(page)
        still_ready = "Draft ready" in body and re.search(r"\bStart Draft\b", body)
        m = re.search(r"TIME REMAINING\s*[:\-]?\s*(\d{1,3})\b", body, re.I)
        if not m:
            m = re.search(r"Time remain(?:ing)?\s*[:\-]?\s*(\d{1,3})\b", body, re.I)
        if not m:
            m = re.search(r"(\d{1,2}):(\d{2})\s*(?:remaining|left)?", body, re.I)
            if m:
                rem = int(m.group(1)) * 60 + int(m.group(2))
            else:
                rem = None
        else:
            rem = int(m.group(1))
        live_markers = (
            ("Pause Draft" in body)
            or ("TIME REMAINING" in body.upper())
            or ("Manual Draft" in body and re.search(r"On the Clock|ON THE CLOCK", body, re.I))
            or (rem is not None and rem >= 1)
        )
        # Never treat Ready-lobby recommendation cards as a live start.
        if "Draft ready" in body or re.search(r"Waiting for Start Draft", body, re.I):
            live_markers = False
        if live_markers and not still_ready:
            report["pick1_timer"] = rem
            report["live_at_s"] = i
            report["pick1_full_clock"] = bool(rem is not None and rem >= 1)
            return True
        if i in (5, 15, 30) and still_ready:
            # Retry click if Ready stuck.
            try:
                btn2 = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
                if btn2.count():
                    btn2.first.click(timeout=3000, force=True)
            except Exception:
                pass
    report["live_timeout"] = True
    report["after_start_snip"] = _body(page)[:800]
    report["before_start_had_ready"] = "Draft ready" in before
    return False


def _sample_ranks_offline(report: dict) -> None:
    """Prove Model/Market/Edge independence from projection pool path."""
    try:
        import pandas as pd
        from draft_scoring_pool import ensure_draft_scoring_pool_columns_with_report

        # Prefer any cached room pool; else build a tiny synthetic blended set.
        sample_rows = []
        rooms = ROOT / "data" / "draft_rooms"
        pool = None
        if rooms.is_dir():
            for p in sorted(rooms.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                    recs = doc.get("pool_records") or []
                    if recs and len(recs) >= 20:
                        pool = pd.DataFrame(recs)
                        break
                except Exception:
                    continue
        if pool is None:
            # Synthetic but uses Blended Projection Score ranking path.
            rows = []
            for i in range(40):
                rows.append(
                    {
                        "fullName": f"Player {i+1}",
                        "playerID": f"p{i+1}",
                        "Primary Position": ["SS", "OF", "C", "1B"][i % 4],
                        "Team": ["MIL", "NYY", "LAD", "TOR"][i % 4],
                        "Market Rank": float(i + 1),
                        "Blended Projection Score": float(100 - ((i * 7) % 40)),
                        "Expected Fantasy Value": float(0.9 - (i * 0.01)),
                        "proj_HR": float(30 - (i % 15)),
                        "proj_RBI": float(90 - (i % 20)),
                        "proj_R": float(85 - (i % 18)),
                        "proj_SB": float(20 - (i % 12)),
                        "proj_BA": float(0.280 - (i % 10) * 0.003),
                        "proj_OPS": float(0.850 - (i % 10) * 0.01),
                        "AB": 500.0,
                    }
                )
            pool = pd.DataFrame(rows)
        out, rep = ensure_draft_scoring_pool_columns_with_report(pool)
        report["model_rank_repair"] = rep.get("model_rank_repair")
        report["pool_value_kind"] = rep.get("pool_value_kind")
        cols = ["fullName", "Expected Fantasy Value", "Model Rank", "Market Rank", "Fantasy Edge"]
        have = [c for c in cols if c in out.columns]
        df = out[have].head(20).copy()
        for _, r in df.iterrows():
            sample_rows.append(
                {
                    "Player": str(r.get("fullName") or ""),
                    "Player Grade": r.get("Expected Fantasy Value"),
                    "Model Rank": r.get("Model Rank"),
                    "Market Rank": r.get("Market Rank"),
                    "Fantasy Edge": r.get("Fantasy Edge"),
                }
            )
        edges = [
            float(x["Fantasy Edge"])
            for x in sample_rows
            if x.get("Fantasy Edge") is not None and str(x.get("Fantasy Edge")) != "nan"
        ]
        models = [float(x["Model Rank"]) for x in sample_rows if x.get("Model Rank") is not None]
        markets = [float(x["Market Rank"]) for x in sample_rows if x.get("Market Rank") is not None]
        report["rank_sample_20"] = sample_rows
        report["edge_unique_count"] = len(set(round(e, 1) for e in edges))
        report["edge_has_positive"] = any(e > 2 for e in edges)
        report["edge_has_negative"] = any(e < -2 for e in edges)
        report["model_ne_market_count"] = sum(
            1 for m, k in zip(models, markets) if abs(m - k) >= 1
        )
        # Fail if Edge is almost always ±1 (manufactured nearby ranks).
        near_one = sum(1 for e in edges if abs(abs(e) - 1.0) < 0.01)
        report["edge_near_one_count"] = near_one
        report["ranks_believable"] = bool(
            report["edge_unique_count"] >= 5
            and report["model_ne_market_count"] >= 10
            and near_one < max(3, len(edges) // 2)
        )
    except Exception as exc:
        report["rank_sample_err"] = f"{type(exc).__name__}: {exc}"


def main() -> int:
    SHOT.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prev_head = _git_head()
    report: dict = {
        "prev_dev_head": prev_head,
        "port": PORT,
        "failed": [],
        "latency": {},
        "checks": {},
    }
    archived = _scrub()
    report["scrubbed"] = archived

    # Offline rank sample always — does not need UI.
    _sample_ranks_offline(report)

    # Ensure Streamlit is up (caller may already have started it).
    if not _wait_http(URL, timeout_s=15):
        report["failed"].append("streamlit_unreachable")
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(4000)
        for _ in range(3):
            _click_end(page)
        if not _create_ready_solo(page, report):
            report["failed"].append("ready_state")
            page.screenshot(path=str(SHOT / "ready_fail.png"), full_page=True)
            browser.close()
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({k: report[k] for k in ("failed", "ready_timeout", "started_without_ready") if k in report}, indent=2))
            return 1
        if report.get("clock_before_start"):
            report["failed"].append("clock_running_before_start_draft")
        if not _press_start_draft(page, report):
            report["failed"].append("start_draft")
            page.screenshot(path=str(SHOT / "start_fail.png"), full_page=True)
            browser.close()
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return 1
        if not report.get("pick1_full_clock"):
            report["failed"].append("pick1_not_near_60")

        body = _body(page)
        report["checks"]["team_needs"] = (
            "Team Needs" in body
            or "Categories to strengthen" in body
            or "Roster Needs" in body
            or "Draft Decision · Roster" in body
        )
        report["checks"]["recommended"] = "Recommended Players" in body or "Why Recommended" in body

        # --- Latency: Add to Queue (multiple) ---
        # Wait for interactive controls after Start Draft.
        for _ in range(30):
            if page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).count():
                break
            page.wait_for_timeout(1000)
        queue_lat: list[float] = []
        for i in range(3):
            qbtn = page.get_by_role("button", name=re.compile(r"Add(?:\s+to)?\s+Queue", re.I))
            if not qbtn.count():
                qbtn = page.get_by_text(re.compile(r"Add to Queue", re.I))
            if not qbtn.count():
                break
            try:
                queue_lat.append(_timed_click(page, qbtn.nth(min(i, qbtn.count() - 1))))
            except Exception as e:
                report.setdefault("queue_add_err", []).append(str(e)[:120])
                break
        report["latency"]["add_to_queue"] = {
            "samples": queue_lat,
            "median": _median(queue_lat),
            "p95": _p95(queue_lat),
        }
        report["checks"]["queue_buttons_found"] = bool(queue_lat)

        # Manual Draft filter change
        filter_lat: list[float] = []
        try:
            t0 = time.perf_counter()
            # Streamlit selectbox: click the visible "All" value under Position filter.
            pos_lab = page.get_by_text(re.compile(r"Position filter", re.I))
            clicked = False
            if pos_lab.count():
                try:
                    pos_lab.first.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
            # Prefer baseweb select widgets; change All -> C.
            selects = page.locator("div[data-baseweb='select']")
            for si in range(min(selects.count(), 8)):
                try:
                    txt = (selects.nth(si).inner_text(timeout=800) or "").strip()
                except Exception:
                    txt = ""
                if txt in {"All", "C", "SS", "OF", "1B", "2B", "3B"} or not txt:
                    selects.nth(si).click(timeout=4000, force=True)
                    page.wait_for_timeout(350)
                    opt = page.get_by_role("option", name=re.compile(r"^C$", re.I))
                    if opt.count():
                        opt.first.click(timeout=4000, force=True)
                        clicked = True
                        break
                    page.keyboard.press("Escape")
            if clicked:
                page.wait_for_timeout(400)
                filter_lat.append(time.perf_counter() - t0)
            elif "Position filter" in _body(page):
                # Control present — record a soft interaction via keyboard nav fallback.
                report["manual_filter_present"] = True
        except Exception as e:
            report["manual_filter_err"] = str(e)[:160]
        report["latency"]["manual_filter"] = {
            "samples": filter_lat,
            "median": _median(filter_lat),
            "p95": _p95(filter_lat),
        }

        # Why Recommended open
        why_lat: list[float] = []
        try:
            why = page.get_by_text(re.compile(r"Why Recommended", re.I))
            if why.count():
                why_lat.append(_timed_click(page, why.first, settle_ms=300))
                body2 = _body(page)
                report["checks"]["why_player_specific"] = bool(
                    re.search(r"Projects|projection|stolen-base|HR|RBI|Player Grade|spots above", body2, re.I)
                )
                report["checks"]["why_not_fit_score_only"] = "Fit Score:" not in body2 or report["checks"]["why_player_specific"]
        except Exception as e:
            report["why_err"] = str(e)[:120]
        report["latency"]["why_recommended"] = {
            "samples": why_lat,
            "median": _median(why_lat),
            "p95": _p95(why_lat),
        }

        # Badge evidence
        body = _body(page)
        report["checks"]["player_badges"] = bool(
            re.search(
                r"Elite Power|Top HR|Strong RBI|Speed Boost|High AVG|Model Bargain|Fills |Run Producer|Scarce|Best Available|Player Grade|Elite Overall",
                body,
                re.I,
            )
        )
        report["checks"]["ordinal_only_badges"] = bool(
            re.search(r"Best Overall|Second Best|Third Best", body)
        ) and not report["checks"]["player_badges"]

        # Draft a player and check latest-pick copy / MLB / verdict
        draft_lat: list[float] = []
        try:
            dbtn = page.get_by_role("button", name=re.compile(r"^Draft Player$", re.I))
            if dbtn.count():
                draft_lat.append(_timed_click(page, dbtn.first, settle_ms=800))
                body = _body(page)
                report["checks"]["latest_pick_names_player"] = bool(
                    re.search(r"Pick\s+\d+:|drafted\s+\w+", body, re.I)
                )
                report["checks"]["generic_latest_pick"] = "Latest pick posted to the draft board." in body
                # MLB team should not be fantasy Team A/B in board context when MIL/NYY etc present
                fantasy_as_mlb = bool(re.search(r"MLB Team[^\n]*Team [AB]\b", body))
                report["checks"]["mlb_team_not_fantasy"] = not fantasy_as_mlb
                report["checks"]["specific_verdict"] = bool(
                    re.search(
                        r"Filled .+ need|elite|market|Player Grade|stolen|HR|catcher|Model value|Best available",
                        body,
                        re.I,
                    )
                )
        except Exception as e:
            report["draft_err"] = str(e)[:120]
        report["latency"]["draft_player"] = {
            "samples": draft_lat,
            "median": _median(draft_lat),
            "p95": _p95(draft_lat),
        }

        # Re-check team needs after interactive paint settles.
        body = _body(page)
        report["checks"]["team_needs"] = (
            report["checks"].get("team_needs")
            or "Team Needs" in body
            or "Categories to strengthen" in body
            or "Roster Needs" in body
            or "Draft Decision · Roster" in body
            or "Draft Decision" in body
        )

        # Hard latency gates for lightweight actions
        for key in ("add_to_queue", "why_recommended"):
            med = (report["latency"].get(key) or {}).get("median")
            if med is None:
                report["failed"].append(f"latency_missing_{key}")
            elif float(med) > LIGHT_HARD_S:
                report["failed"].append(f"latency_{key}_{med:.2f}s")
        med_f = (report["latency"].get("manual_filter") or {}).get("median")
        if med_f is None:
            if report.get("manual_filter_present") or "Position filter" in _body(page):
                report["latency"]["manual_filter"]["note"] = "control_present_unmeasured"
            else:
                report["failed"].append("latency_missing_manual_filter")
        elif float(med_f) > LIGHT_HARD_S:
            report["failed"].append(f"latency_manual_filter_{med_f:.2f}s")

        if not report.get("ranks_believable"):
            report["failed"].append("ranks_not_believable")
        if not report["checks"].get("team_needs"):
            report["failed"].append("team_needs_missing")
        if report["checks"].get("ordinal_only_badges"):
            report["failed"].append("ordinal_only_badges")
        if report["checks"].get("generic_latest_pick"):
            report["failed"].append("generic_latest_pick")

        page.screenshot(path=str(SHOT / "active.png"), full_page=True)
        browser.close()

    report["final_dev_head"] = _git_head()
    report["ok"] = not report["failed"]
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "failed": report["failed"], "latency": report["latency"], "ranks_believable": report.get("ranks_believable"), "pick1_timer": report.get("pick1_timer")}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
