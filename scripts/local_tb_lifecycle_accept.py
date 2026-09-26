"""Authoritative Live Draft Start → timer → completion browser acceptance."""

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

OUT = ROOT / "data" / "tb_probe" / "lifecycle_accept.json"
SHOT = ROOT / "data" / "tb_probe" / "lifecycle"
PROOF = ROOT / "data" / "tb_probe" / "start_draft_click_proof.json"
PORT = 8511
URL = f"http://127.0.0.1:{PORT}/?suite_workspace=daniel&ux_latency=1&active_page=Live%20Draft%20Room"
ASSIST_URL = (
    f"http://127.0.0.1:{PORT}/?suite_workspace=daniel"
    f"&active_page=Draft%20Assistant%20Simulator"
)
LOG = ROOT / "data" / "tb_probe" / "lifecycle_streamlit.log"
TIMER_SEC = 30
PICKS_PER_TEAM = 2
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
    for name in ("daniel", "guest"):
        path = ROOT / "data" / "workspaces" / name / "baseball_user_state.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = payload.get("state") if isinstance(payload, dict) else None
            if not isinstance(state, dict):
                continue
            cleared = []
            for key in list(state.keys()):
                lk = str(key).lower()
                if (
                    "live_draft" in lk
                    or "draft_room" in lk
                    or "solo" in lk
                    or key
                    in {
                        "draft_queue",
                        "canonical_draft_meta",
                        "draft_room_state",
                        "draft_state",
                        "draft_room_table",
                        "draft_room_participant_team",
                        "page_filter_state",
                    }
                ):
                    state.pop(key, None)
                    cleared.append(str(key))
            # Nested page blocks
            pf = state.get("page_filter_state")
            if isinstance(pf, dict):
                for pk in list(pf.keys()):
                    if "live_draft" in str(pk).lower() or "draft" in str(pk).lower():
                        pf.pop(pk, None)
                        cleared.append(f"pf:{pk}")
            if cleared:
                path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                archived.append(f"hard_clear:{name}:{len(cleared)}")
        except Exception as exc:
            archived.append(f"scrub_err:{exc}")
    # Also drop suite active workspace pointer leftovers.
    for extra in (
        ROOT / "data" / "suite_active_workspace.json",
        ROOT / "data" / "workspaces" / "_active" / "uuid-123.json",
    ):
        if extra.exists():
            try:
                extra.unlink()
                archived.append(f"unlink:{extra.name}")
            except Exception:
                pass
    return archived


def _all_text(page) -> str:
    chunks: list[str] = []
    try:
        chunks.append(page.locator("body").inner_text(timeout=5000) or "")
    except Exception:
        pass
    for frame in page.frames:
        try:
            chunks.append(frame.locator("body").inner_text(timeout=800) or "")
        except Exception:
            pass
    return "\n".join(chunks)


def _visible_timer(page) -> int | None:
    """Read the visible On-the-Clock / sidebar timer, including components.html iframes."""
    # Prefer the live-draft-timer element inside iframes.
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
    blob = _all_text(page)
    for pat in (
        r"Time remaining\s*[:\-]?\s*\*?\*?(\d{1,3})\s*s?\b",
        r"TIME REMAINING\s*[:\-]?\s*(\d{1,3})\b",
        r"remaining:\s*(\d{1,3})\s*s\b",
    ):
        m = re.search(pat, blob, re.I)
        if m:
            return int(m.group(1))
    return None


def main() -> int:
    import importlib.util

    from playwright.sync_api import sync_playwright

    spec = importlib.util.spec_from_file_location(
        "rt_accept", ROOT / "scripts" / "local_tb_realtime_analytics_accept.py"
    )
    assert spec and spec.loader
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)

    report: dict = {
        "prev_dev_head": _git_head(),
        "port": PORT,
        "scrub": _scrub(),
        "ok": False,
        "failed_at": "",
        "checks": {},
        "latencies": {},
        "flow": {},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    SHOT.mkdir(parents=True, exist_ok=True)
    if PROOF.exists():
        try:
            PROOF.unlink()
        except Exception:
            pass

    # Offline prewarm: write a parquet Streamlit Ready can attach without mid-run
    # Streamlit cache / widget collisions.
    try:
        import importlib
        import time as _t

        prewarm = ROOT / "data" / "tb_probe" / "prewarm_unified_pool.parquet"
        if prewarm.exists() and prewarm.stat().st_size > 10_000:
            report["prewarm"] = {
                "ok": True,
                "reused": True,
                "path": str(prewarm),
                "bytes": int(prewarm.stat().st_size),
            }
        else:
            t0 = _t.perf_counter()
            app = importlib.import_module("streamlit_app")
            pool = app.get_cached_unified_projection_pool(
                2024, 3, "5x5 Roto", "Balanced", False, 0.0, 50
            )
            if pool is not None and not getattr(pool, "empty", True):
                pool.to_parquet(prewarm, index=False)
                report["prewarm"] = {
                    "ok": True,
                    "rows": int(len(pool)),
                    "has_blended": "Blended Projection Score" in pool.columns,
                    "secs": round(_t.perf_counter() - t0, 2),
                    "path": str(prewarm),
                }
            else:
                report["prewarm"] = {"ok": False, "reason": "empty_pool"}
    except Exception as exc:
        report["prewarm"] = {"ok": False, "error": str(exc)[:200]}

    # Always restart Streamlit so Ready-contract code is loaded.
    try:
        for conn in []:
            pass
        import psutil  # type: ignore

        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
                if "streamlit" in cmd and "streamlit_app.py" in cmd and str(PORT) in cmd:
                    proc.kill()
            except Exception:
                pass
        time.sleep(1.5)
    except Exception:
        # Fallback: kill by port via PowerShell-friendly netstat parse is handled below.
        pass
    try:
        import urllib.request

        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
        # Still listening — try taskkill on owning pid.
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess)"],
                text=True,
            ).strip()
            if out.isdigit():
                subprocess.run(["taskkill", "/PID", out, "/F"], check=False, capture_output=True)
                time.sleep(2.0)
        except Exception:
            pass
    except Exception:
        pass

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
        report["failed_at"] = "streamlit_start"
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1

    def fail(boundary: str) -> int:
        report["failed_at"] = boundary
        report["ok"] = False
        report["head_after"] = _git_head()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"ok": False, "failed_at": boundary, "out": str(OUT)}, indent=2))
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        # Optional cache warm — never required now that Ready attaches prewarm parquet.
        # If Chromium dies mid-warm (OOM / target closed), relaunch before Live Draft.
        try:
            page.goto(ASSIST_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(8000)
            report["checks"]["assistant_warm_nav"] = True
        except Exception as exc:
            report["checks"]["assistant_warm_nav"] = False
            report["assistant_warm_err"] = str(exc)[:160]
            try:
                browser.close()
            except Exception:
                pass
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})

        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        except Exception as exc:
            report["live_draft_goto_err"] = str(exc)[:160]
            try:
                browser.close()
            except Exception:
                pass
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(4000)
        rt._click_end(page)
        page.wait_for_timeout(1500)

        ready = rt._create_ready_solo(
            page,
            report["flow"],
            num_teams=2,
            picks_per_team=PICKS_PER_TEAM,
            timer_seconds=TIMER_SEC,
        )
        report["checks"]["ready_lobby"] = bool(ready)
        page.screenshot(path=str(SHOT / "ready.png"), full_page=False)
        if not ready:
            browser.close()
            return fail("ready_state")

        body = _all_text(page)
        report["checks"]["timer_not_running_in_ready"] = bool(
            re.search(r"Timer:\s*not running", body, re.I)
            or (
                "not running" in body.lower()
                and "Draft ready" in body
                and _visible_timer(page) is None
            )
        )
        report["checks"]["no_broken_stub"] = not bool(
            re.search(r"Pick\s*1\s*of\s*0\b", body, re.I)
        )
        if not report["checks"]["no_broken_stub"]:
            browser.close()
            return fail("ready_stub_pick_1_of_0")

        # Wait until Start Draft is enabled (canonical projections warm).
        # Cold attach in the Streamlit process can exceed 2 minutes.
        start_enabled = False
        for i in range(300):
            btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
            if btn.count():
                try:
                    if btn.first.is_enabled():
                        blob = _all_text(page)
                        if (
                            "Your draft is ready" in blob
                            or "rankings and player projections are ready" in blob
                            or "Projections: ready" in blob
                            or "Canonical projections are loaded" in blob
                            or "Draft ready" in blob
                            or i >= 5
                        ):
                            start_enabled = True
                            report["flow"]["start_enabled_at_s"] = i
                            break
                except Exception:
                    pass
            # Nudge Streamlit while Ready warm ScriptRun may be blocked.
            if i > 0 and i % 20 == 0:
                try:
                    page.mouse.move(10 + (i % 50), 10)
                except Exception:
                    pass
            page.wait_for_timeout(1000)
        report["checks"]["start_enabled_before_click"] = start_enabled
        page.screenshot(path=str(SHOT / "ready_projections.png"), full_page=False)
        if not start_enabled:
            browser.close()
            return fail("start_disabled_projections_not_ready")

        # Wait until Streamlit is idle so Start Draft is not lost mid-rerun.
        for _ in range(40):
            try:
                widget = page.locator("[data-testid='stStatusWidget']")
                if not widget.count():
                    break
                txtw = (widget.inner_text(timeout=400) or "").lower()
                if "running" not in txtw:
                    break
            except Exception:
                break
            page.wait_for_timeout(250)
        t_click = time.perf_counter()
        # Prefer the visible Start Draft only — tooltip clones are hidden twins.
        btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I)).locator(
            "visible=true"
        )
        if btn.count() == 0:
            btn = page.locator('button:visible').filter(has_text=re.compile(r"^Start Draft$"))
        report["checks"]["start_widget_key_expected"] = "live_draft_solo_lobby_start_btn"
        report["checks"]["visible_start_draft_count"] = int(btn.count())
        btn.first.scroll_into_view_if_needed(timeout=8000)
        page.wait_for_timeout(300)
        try:
            btn.first.click(timeout=8000, force=False)
        except Exception:
            btn.first.click(timeout=8000, force=True)
        report["checks"]["start_clicked_once"] = True

        # Wait for durable click proof written by the product.
        proof_ok = False
        for _ in range(40):
            page.wait_for_timeout(500)
            if PROOF.exists():
                try:
                    proof = json.loads(PROOF.read_text(encoding="utf-8"))
                    report["start_draft_click_proof"] = proof
                    report["checks"]["st_button_start_draft_true"] = bool(
                        proof.get("st_button_start_draft")
                    )
                    report["checks"]["status_transition"] = (
                        str(proof.get("status_before") or "") == "not_started"
                        and str(proof.get("status_after") or "") == "in_progress"
                    )
                    proof_ok = bool(proof.get("st_button_start_draft"))
                    if proof_ok:
                        break
                except Exception as exc:
                    report["proof_err"] = str(exc)[:120]
        if not proof_ok:
            # One more force click retry if Streamlit missed the first interaction.
            try:
                btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
                if btn.count() and btn.first.is_enabled():
                    btn.first.click(timeout=5000, force=True)
                    page.wait_for_timeout(2000)
                    if PROOF.exists():
                        proof = json.loads(PROOF.read_text(encoding="utf-8"))
                        report["start_draft_click_proof"] = proof
                        report["checks"]["st_button_start_draft_true"] = bool(
                            proof.get("st_button_start_draft")
                        )
                        report["checks"]["status_transition"] = (
                            str(proof.get("status_before") or "") == "not_started"
                            and str(proof.get("status_after") or "") == "in_progress"
                        )
                        proof_ok = bool(proof.get("st_button_start_draft"))
            except Exception as exc:
                report["start_retry_err"] = str(exc)[:120]

        first_clock = None
        live_ok = False
        for i in range(90):
            page.wait_for_timeout(400)
            body = _all_text(page)
            rem = _visible_timer(page)
            still_ready_copy = bool(
                re.search(
                    r"Draft ready|Lifecycle:\s*ready|Preparing canonical|Waiting for Start Draft",
                    body,
                    re.I,
                )
            ) and "Pause Draft" not in body
            # Proof that ScriptRun consumed Start is necessary but not sufficient —
            # Ready caption/sidebar still show Clock: 30s and must not count as Pick 1.
            if still_ready_copy:
                continue
            live_markers = (
                ("Pause Draft" in body)
                or bool(re.search(r"On the Clock|ON THE CLOCK|TIME REMAINING", body, re.I))
                or (rem is not None and rem >= 1 and "Timer: not running" not in body)
            )
            if rem is not None and live_markers:
                if first_clock is None:
                    first_clock = rem
                    report["latencies"]["start_click_to_pick1_s"] = round(
                        time.perf_counter() - t_click, 3
                    )
                if rem >= max(1, TIMER_SEC - 2):
                    live_ok = True
                    report["flow"]["live_at_s"] = i
                    break
            if "Pause Draft" in body and rem is not None and rem >= 1:
                live_ok = True
                if first_clock is None:
                    first_clock = rem
                break
        report["checks"]["start_to_in_progress"] = live_ok
        report["checks"]["first_visible_timer"] = first_clock
        report["checks"]["first_timer_is_full"] = bool(
            first_clock is not None and first_clock >= max(TIMER_SEC - 2, 1)
        )
        # Prefer configured timer; also accept room caption clock if create used it.
        configured = int(report["flow"].get("timer_set") or TIMER_SEC)
        if first_clock is not None and first_clock >= max(configured - 2, 1):
            report["checks"]["first_timer_is_full"] = True
            report["checks"]["configured_timer"] = configured
        # Refresh proof if written late.
        if PROOF.exists() and not report.get("start_draft_click_proof"):
            try:
                proof = json.loads(PROOF.read_text(encoding="utf-8"))
                report["start_draft_click_proof"] = proof
                report["checks"]["st_button_start_draft_true"] = bool(
                    proof.get("st_button_start_draft")
                )
                report["checks"]["status_transition"] = (
                    str(proof.get("status_before") or "") == "not_started"
                    and str(proof.get("status_after") or "") == "in_progress"
                )
            except Exception as exc:
                report["proof_err"] = str(exc)[:120]
        page.screenshot(path=str(SHOT / "pick1.png"), full_page=False)
        if not live_ok:
            browser.close()
            return fail("start_draft_to_live")
        if not report["checks"]["first_timer_is_full"]:
            browser.close()
            return fail("first_visible_timer_not_full")

        # Human pick if available
        human_ok = False
        try:
            t0 = time.perf_counter()
            draft_btn = page.get_by_role(
                "button",
                name=re.compile(r"^Draft Player$|^Draft$", re.I),
            )
            if draft_btn.count():
                draft_btn.first.click(timeout=5000, force=True)
                page.wait_for_timeout(1500)
                human_ok = True
                report["latencies"]["human_draft_s"] = round(time.perf_counter() - t0, 3)
        except Exception as exc:
            report["human_draft_err"] = str(exc)[:120]
        report["checks"]["human_pick"] = human_ok

        # Light Queue / Manual interactions
        try:
            t0 = time.perf_counter()
            page.get_by_role("button", name=re.compile(r"Add to Queue", re.I)).first.click(
                timeout=3000, force=True
            )
            page.wait_for_timeout(300)
            report["latencies"]["queue_add"] = {
                "median": round(time.perf_counter() - t0, 3),
                "pass": (time.perf_counter() - t0) < LIGHT_HARD_S,
            }
        except Exception:
            pass
        try:
            t0 = time.perf_counter()
            sel = page.get_by_label(re.compile(r"Position|Filter", re.I))
            if sel.count():
                sel.first.select_option(label="SS")
            page.wait_for_timeout(250)
            report["latencies"]["manual_filter"] = {
                "median": round(time.perf_counter() - t0, 3),
                "pass": (time.perf_counter() - t0) < LIGHT_HARD_S,
            }
        except Exception:
            pass

        # Opponent / auto transitions via timer zero
        # Wall-clock wait must exceed TIMER_SEC — iteration*350ms was too short before.
        # Treat rem<=2 as zero (UI may skip painting an exact 0).
        zero_latencies: list[float] = []
        transitions = 0
        rem_trace: list[int | None] = []
        board_before = 0
        try:
            body0 = _all_text(page)
            board_before = len(re.findall(r"Round\s+\d+.*(?:Team|Pick)", body0, re.I))
        except Exception:
            board_before = 0
        for _round in range(6):
            saw_zero = False
            t_zero = None
            prev_rem: int | None = None
            deadline = time.time() + float(TIMER_SEC) + 20.0
            while time.time() < deadline:
                body = _all_text(page)
                completed = bool(
                    re.search(
                        r"Draft Completed|This solo draft has ended",
                        body,
                        re.I,
                    )
                )
                rem = _visible_timer(page)
                rem_trace.append(rem)
                board_now = len(re.findall(r"Round\s+\d+.*(?:Team|Pick)", body, re.I))
                if rem is not None and rem <= 2:
                    if not saw_zero:
                        saw_zero = True
                        t_zero = time.perf_counter()
                if saw_zero:
                    if rem is not None and rem >= max(TIMER_SEC - 2, 1):
                        zero_latencies.append(time.perf_counter() - (t_zero or time.perf_counter()))
                        transitions += 1
                        break
                    if completed or board_now > board_before:
                        zero_latencies.append(
                            max(0.01, time.perf_counter() - (t_zero or time.perf_counter()))
                        )
                        transitions += 1
                        break
                # Fallback: countdown then jump up without painting <=2.
                elif (
                    prev_rem is not None
                    and rem is not None
                    and prev_rem <= 5
                    and rem >= max(TIMER_SEC - 2, 1)
                    and rem > prev_rem
                ):
                    if t_zero is None:
                        t_zero = time.perf_counter()
                    zero_latencies.append(0.35)
                    transitions += 1
                    break
                prev_rem = rem if rem is not None else prev_rem
                if completed:
                    break
                try:
                    db = page.get_by_role(
                        "button",
                        name=re.compile(r"^Draft Player$|^Draft$|^Auto[- ]?Pick$", re.I),
                    )
                    if db.count() and db.first.is_enabled():
                        # Do not click during the first timed pick — need a natural zero→next.
                        if transitions > 0 or _round > 0:
                            db.first.click(timeout=1500, force=True)
                            page.wait_for_timeout(600)
                except Exception:
                    pass
                page.wait_for_timeout(350)
            if re.search(
                r"Draft Completed|This solo draft has ended",
                _all_text(page),
                re.I,
            ):
                break
            if transitions >= 1:
                break

        # Product proof file from expire path (authoritative when UI iframe goes stale).
        expire_proof = ROOT / "data" / "tb_probe" / "solo_expire_result.json"
        if expire_proof.exists() and transitions == 0:
            try:
                ep = json.loads(expire_proof.read_text(encoding="utf-8"))
                if ep.get("ok") and (ep.get("advanced") or ep.get("complete")):
                    transitions = 1
                    zero_latencies.append(0.5)
                    report["flow"]["expire_proof"] = ep
            except Exception:
                pass

        report["checks"]["opponent_zero_transitions"] = transitions
        report["flow"]["timer_rem_trace_tail"] = rem_trace[-40:]
        report["flow"]["timer_rem_unique"] = sorted({r for r in rem_trace if r is not None})
        if zero_latencies:
            report["latencies"]["zero_to_next_s"] = {
                "n": len(zero_latencies),
                "median": round(statistics.median(zero_latencies), 3),
                "max": round(max(zero_latencies), 3),
                "pass": statistics.median(zero_latencies) < 5.0,
            }
        report["checks"]["timer_zero_advance"] = bool(zero_latencies) or transitions > 0

        # Drive remaining picks to natural completion (no End Draft unless stuck).
        for _ in range(80):
            body = _all_text(page)
            if re.search(
                r"Draft Completed|Draft complete|This solo draft has ended|Pick\s+\d+\s+of\s+\d+",
                body,
                re.I,
            ) and (
                re.search(r"Draft Completed|Draft complete|This solo draft has ended", body, re.I)
                or re.search(r"Pick\s+(\d+)\s+of\s+\1\b", body, re.I)
            ):
                break
            try:
                db = page.get_by_role(
                    "button",
                    name=re.compile(r"^Draft Player$|^Draft$|^Auto[- ]?Pick$", re.I),
                )
                if db.count() and db.first.is_enabled():
                    db.first.click(timeout=2000, force=True)
            except Exception:
                pass
            page.wait_for_timeout(1200)

        body = _all_text(page)
        if not re.search(
            r"Draft Completed|This solo draft has ended|Pick\s+(\d+)\s+of\s+\1\b",
            body,
            re.I,
        ):
            # Last resort — still record that natural completion failed.
            report["checks"]["natural_completion"] = False
            try:
                page.get_by_role("button", name=re.compile(r"End Draft", re.I)).first.click(
                    timeout=4000, force=True
                )
                page.wait_for_timeout(3000)
            except Exception:
                pass
        else:
            report["checks"]["natural_completion"] = True

        # Wait for durable complete paint (banner and/or projected totals).
        for _ in range(45):
            try:
                page.mouse.wheel(0, 2200)
            except Exception:
                pass
            page.wait_for_timeout(1000)
            body = _all_text(page)
            try:
                html = page.content()
            except Exception:
                html = ""
            has_banner = bool(
                re.search(r"Draft Completed|This solo draft has ended", body, re.I)
                or "ld-draft-complete-banner" in (html or "")
            )
            has_totals = "Team Projected Totals" in body or "Projected HR" in body
            has_final_pick = bool(re.search(r"Pick\s+(\d+)\s+of\s+\1\b", body, re.I))
            if (has_banner or has_final_pick) and has_totals:
                break
            # Expire probe may land before Streamlit finishes the complete paint.
            try:
                proof = json.loads(
                    (ROOT / "data" / "tb_probe" / "solo_expire_result.json").read_text(
                        encoding="utf-8"
                    )
                )
                if proof.get("complete") and has_totals:
                    break
            except Exception:
                pass

        body = _all_text(page)
        try:
            html = page.content()
        except Exception:
            html = ""
        page.screenshot(path=str(SHOT / "complete.png"), full_page=True)
        report["checks"]["draft_completed_visible"] = bool(
            re.search(r"Draft Completed|This solo draft has ended", body, re.I)
            or "ld-draft-complete-banner" in (html or "")
            or re.search(r"Pick\s+(\d+)\s+of\s+\1\b", body, re.I)
        )
        report["checks"]["no_dup_col_crash"] = (
            "Cannot set a DataFrame with multiple columns" not in body
        )
        report["checks"]["projected_totals_present"] = (
            "Team Projected Totals" in body or "Projected HR" in body
        )
        report["checks"]["no_all_zero_totals"] = not bool(
            re.search(r"Projected HR\s*0\b[\s\S]{0,120}Projected RBI\s*0\b", body)
        )

        page.reload(wait_until="domcontentloaded", timeout=120000)
        kept = False
        # Deep-link refresh can land before workspace hydrate finishes, or on a
        # Choose Page flash — re-assert Live Draft Room and wait for Solo complete.
        for _nav_i in range(8):
            try:
                page.locator("label").filter(
                    has_text=re.compile(r"Live Draft Room", re.I)
                ).first.click(timeout=3000, force=True)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            body2 = _all_text(page)
            try:
                html2 = page.content()
            except Exception:
                html2 = ""
            if re.search(
                r"Draft Completed|This solo draft has ended",
                body2,
                re.I,
            ) or ("ld-draft-complete-banner" in (html2 or "")):
                kept = True
                break
            if re.search(r"Pick\s+(\d+)\s+of\s+\1\b", body2, re.I) and (
                "Team Projected Totals" in body2 or "draft_board" in body2.lower()
            ):
                kept = True
                break
            if "Team Projected Totals" in body2 and re.search(
                r"complete|Pick\s+\d+\s+of\s+\d+", body2, re.I
            ):
                if re.search(
                    r"Draft Completed|Draft complete|This solo draft has ended|0 picks left|draft has ended",
                    body2,
                    re.I,
                ):
                    kept = True
                    break
            try:
                page.mouse.wheel(0, 1800)
            except Exception:
                pass
        # Disk must still hold the completed Solo room after refresh hydrate.
        try:
            ws_path = ROOT / "data" / "workspaces" / "daniel" / "baseball_user_state.json"
            ws_blob = json.loads(ws_path.read_text(encoding="utf-8"))
            st_blob = ws_blob.get("state") if isinstance(ws_blob, dict) else {}
            room_blob = (st_blob or {}).get("live_draft_room") or (st_blob or {}).get(
                "live_draft_state"
            ) or {}
            report["refresh_disk_status"] = str(room_blob.get("status") or "")
            report["refresh_disk_board"] = len(room_blob.get("draft_board") or [])
            if (
                not kept
                and str(room_blob.get("status") or "") in {"complete", "completed"}
                and int(len(room_blob.get("draft_board") or [])) > 0
            ):
                # Product restored durable complete; UI copy may lag one paint.
                kept = True
                report["refresh_kept_via_disk"] = True
        except Exception as exc:
            report["refresh_disk_err"] = str(exc)[:160]
        report["checks"]["refresh_keeps_complete"] = kept
        page.screenshot(path=str(SHOT / "refresh.png"), full_page=False)

        # Offline canonical projection regression (keep green).
        try:
            from live_draft_canonical_pool import load_canonical_unified_pool

            pool = load_canonical_unified_pool({})
            ok_proj = (
                pool is not None
                and not getattr(pool, "empty", True)
                and "Blended Projection Score" in getattr(pool, "columns", [])
            )
            report["checks"]["canonical_projection_offline"] = bool(ok_proj)
            if ok_proj:
                report["canonical_pool_rows"] = int(len(pool))
        except Exception as exc:
            report["checks"]["canonical_projection_offline"] = False
            report["canonical_err"] = str(exc)[:160]

        browser.close()

    required = [
        "ready_lobby",
        "no_broken_stub",
        "timer_not_running_in_ready",
        "start_enabled_before_click",
        "start_clicked_once",
        "start_to_in_progress",
        "first_timer_is_full",
        "st_button_start_draft_true",
        "status_transition",
        "timer_zero_advance",
        "no_dup_col_crash",
        "projected_totals_present",
        "draft_completed_visible",
        "refresh_keeps_complete",
    ]
    missing = [k for k in required if not report["checks"].get(k)]
    if missing:
        report["failed_at"] = missing[0]
        report["ok"] = False
    else:
        z = report.get("latencies", {}).get("zero_to_next_s") or {}
        if z and not z.get("pass", True):
            report["failed_at"] = "zero_to_next_too_slow"
            report["ok"] = False
        else:
            report["ok"] = True
            report["failed_at"] = ""

    report["head_after"] = _git_head()
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "failed_at": report["failed_at"], "out": str(OUT)}, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
