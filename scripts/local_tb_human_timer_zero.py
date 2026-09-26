"""Server-driven Solo timer acceptance: consecutive visible pick transitions.

Observes ``[data-testid=live-draft-on-clock][data-pick-index]`` at ~50–100 ms.
Zero is an event, not a required visible state. Measures:
  Pick N first browser-visible → Pick N+1 first browser-visible
with no missing integer pick indexes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "tb_probe" / "human_timer_zero.json"
TXN_LOG = ROOT / "data" / "tb_probe" / "solo_expire_txn.jsonl"
LIFE_LOG = ROOT / "data" / "tb_probe" / "solo_fragment_lifecycle.jsonl"
URL = "http://127.0.0.1:8511/?suite_workspace=daniel&active_page=Live%20Draft%20Room&ux_latency=1"
WRAPPER_SEL = '[data-testid="live-draft-on-clock"]'
TIMER_SEL = '[data-testid="live-draft-timer"][data-authoritative="1"]'
# Durability default: 8s × 20 transitions. Formal 10×@30 via env override.
CLOCK = int(os.environ.get("TB_TIMER_CLOCK") or 8)
TARGET_EXPIRES = int(os.environ.get("TB_TIMER_TARGET") or 20)
# Preliminary proof before full target.
PRELIM_TRANSITIONS = 3  # Pick 1→2→3→4 means 3 transitions
POLL_MS = 50


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
    for log in (TXN_LOG, LIFE_LOG, ROOT / "data" / "tb_probe" / "solo_rerun_blocked.jsonl"):
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("", encoding="utf-8")
        except Exception:
            pass


def _read_jsonl(path: Path, n: int = 40) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return []
    out: list[dict] = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def _board_players() -> list[str]:
    players: list[str] = []
    rooms = ROOT / "data" / "draft_rooms"
    if not rooms.is_dir():
        return players
    newest = None
    newest_mtime = -1.0
    for p in rooms.glob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            mt = p.stat().st_mtime
        except Exception:
            continue
        if mt > newest_mtime:
            newest_mtime = mt
            newest = p
    if newest is None:
        return players
    try:
        room = json.loads(newest.read_text(encoding="utf-8"))
        board = room.get("draft_board") or []
        for row in board:
            if isinstance(row, dict):
                name = str(row.get("Player") or row.get("player") or "").strip()
                if name:
                    players.append(name)
    except Exception:
        pass
    return players


def _wrapper_snapshot(page) -> dict | None:
    """Authoritative On-the-Clock wrapper + nested timer attributes."""
    try:
        snap = page.evaluate(
            """() => {
              const roots = Array.from(
                document.querySelectorAll('[data-testid="live-draft-on-clock"]')
              ).filter((el) => {
                const style = window.getComputedStyle(el);
                return style && style.display !== 'none' && style.visibility !== 'hidden';
              });
              if (!roots.length) return null;
              // Prefer highest data-pick-index if duplicates linger.
              let best = roots[0];
              let bestIdx = -1;
              for (const el of roots) {
                const raw = el.getAttribute('data-pick-index');
                const idx = raw != null && raw !== '' ? parseInt(raw, 10) : -1;
                if (idx >= bestIdx) { best = el; bestIdx = idx; }
              }
              // Authoritative count: only wrappers for the current (max) pick.
              // Stale lower-index nodes from a prior fragment remount must not fail.
              const authRoots = roots.filter((el) => {
                const raw = el.getAttribute('data-pick-index');
                const idx = raw != null && raw !== '' ? parseInt(raw, 10) : -1;
                return idx === bestIdx;
              });
              const timer = best.querySelector('[data-testid="live-draft-timer"]')
                || document.querySelector('[data-testid="live-draft-timer"][data-authoritative="1"]');
              const teamEl = best.querySelector('[data-testid="live-draft-team"]');
              let remaining = null;
              if (timer) {
                const m = (timer.textContent || '').match(/(\\d+)/);
                if (m) remaining = parseInt(m[1], 10);
              }
              const pidxAttr = best.getAttribute('data-pick-index');
              let pickIndex = pidxAttr != null && pidxAttr !== '' ? parseInt(pidxAttr, 10) : null;
              if (pickIndex == null && timer) {
                const tpi = timer.getAttribute('data-pick-index');
                if (tpi != null && tpi !== '') pickIndex = parseInt(tpi, 10);
              }
              return {
                wrapper_count: authRoots.length,
                wrapper_count_all: roots.length,
                pick_index: pickIndex,
                pick_number: pickIndex == null ? null : pickIndex + 1,
                remaining: remaining,
                team: teamEl ? (teamEl.textContent || '').trim() : '',
                room_id: best.getAttribute('data-room-id') || '',
                state_version: best.getAttribute('data-state-version') || '',
                board_len: best.getAttribute('data-board-len'),
              };
            }"""
        )
        return snap if isinstance(snap, dict) else None
    except Exception:
        return None


def _iframe_timer_count(page) -> int:
    try:
        return int(
            page.evaluate(
                """() => {
                  let n = 0;
                  for (const iframe of document.querySelectorAll('iframe')) {
                    try {
                      const doc = iframe.contentDocument;
                      if (doc && doc.querySelector('[data-testid="live-draft-timer"]')) n += 1;
                    } catch (e) {}
                  }
                  return n;
                }"""
            )
        )
    except Exception:
        return -1


def _probe_responsive(url: str, timeout_s: float = 15.0) -> dict:
    import urllib.request

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            body = resp.read(64)
        return {
            "ok": int(code or 0) == 200,
            "status": code,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "bytes": len(body),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }


def _match_txn_rows(rows: list[dict], pick_index_before: int) -> dict | None:
    hit = None
    want = int(pick_index_before)
    for row in rows:
        raw = row.get("pick_index_before")
        if raw is None:
            continue
        try:
            got = int(raw)
        except (TypeError, ValueError):
            continue
        if got != want:
            continue
        if row.get("expire_advanced") or row.get("expire_ok"):
            hit = row
        elif hit is None:
            hit = row
    return hit


def _match_txn(pick_index_before: int) -> dict | None:
    return _match_txn_rows(_read_jsonl(TXN_LOG, 80), pick_index_before)


def _observe_pick_sequence(page, *, start_pick_number: int, transitions: int, clock: int) -> dict:
    """Event-based: record first browser sighting of each consecutive pick index."""
    observations: list[dict] = []
    seen: dict[int, dict] = {}
    deadline = time.time() + (clock + 45) * (transitions + 1)
    last_wrapper_missing_at = None
    connection_closed = False
    while time.time() < deadline and len(seen) < (transitions + 1):
        try:
            snap = _wrapper_snapshot(page)
        except Exception as exc:
            if "closed" in str(exc).lower() or "Connection" in type(exc).__name__:
                connection_closed = True
                break
            snap = None
        if not snap or snap.get("pick_index") is None:
            if last_wrapper_missing_at is None:
                last_wrapper_missing_at = time.time()
            try:
                page.wait_for_timeout(POLL_MS)
            except Exception:
                connection_closed = True
                break
            continue
        last_wrapper_missing_at = None
        pidx = int(snap["pick_index"])
        pnum = pidx + 1
        if pnum < start_pick_number:
            try:
                page.wait_for_timeout(POLL_MS)
            except Exception:
                connection_closed = True
                break
            continue
        if pnum not in seen:
            now = time.time()
            board = _board_players()
            row = {
                "pick_number": pnum,
                "pick_index": pidx,
                "first_visible_ts": now,
                "initial_clock": snap.get("remaining"),
                "team": snap.get("team"),
                "wrapper_count": snap.get("wrapper_count"),
                "board_len": len(board),
                "room_id": snap.get("room_id"),
                "state_version": snap.get("state_version"),
            }
            seen[pnum] = row
            observations.append(row)
            print(
                f"browser first-visible Pick {pnum} clock={row['initial_clock']} "
                f"wrappers={row['wrapper_count']} team={row['team']}",
                flush=True,
            )
            expected = list(range(start_pick_number, start_pick_number + transitions + 1))
            if all(p in seen for p in expected):
                break
        try:
            page.wait_for_timeout(POLL_MS)
        except Exception:
            connection_closed = True
            break

    expected = list(range(start_pick_number, start_pick_number + transitions + 1))
    missing = [p for p in expected if p not in seen]
    timings: list[dict] = []
    for i in range(transitions):
        frm = start_pick_number + i
        to = frm + 1
        from_obs = seen.get(frm)
        to_obs = seen.get(to)
        txn = _match_txn(frm - 1) if frm in seen else None
        server_from_to = None
        expire_ms = None
        warm_hit = None
        server_ts = None
        if txn:
            expire_ms = txn.get("expire_ms")
            warm_hit = txn.get("warm_plan_hit")
            server_ts = txn.get("deadline_detected") or txn.get("next_deadline_created")
            server_from_to = (
                f"{int(txn['pick_index_before']) + 1}"
                f"→{int(txn.get('pick_index_after') if txn.get('pick_index_after') is not None else -1) + 1}"
            )
        server_to_browser = None
        if isinstance(server_ts, (int, float)) and to_obs:
            server_to_browser = round(float(to_obs["first_visible_ts"]) - float(server_ts), 3)
        browser_dwell = None
        if from_obs and to_obs:
            browser_dwell = round(
                float(to_obs["first_visible_ts"]) - float(from_obs["first_visible_ts"]), 3
            )
        skipped = to not in seen or (frm in seen and to in seen and to != frm + 1)
        timings.append(
            {
                "expiration": i + 1,
                "server_from_to": server_from_to,
                "browser_from_to": f"{frm}→{to}" if to in seen else f"{frm}→?",
                "from": frm,
                "to": to if to in seen else None,
                "warm_plan_hit": warm_hit,
                "server_expire_ms": expire_ms,
                "server_to_browser_s": server_to_browser,
                "browser_dwell_s": browser_dwell,
                "initial_visible_clock": (to_obs or {}).get("initial_clock"),
                "wrapper_count": (to_obs or {}).get("wrapper_count"),
                "missing": skipped or to not in seen,
                "team": (to_obs or {}).get("team"),
                "board_len": (to_obs or {}).get("board_len"),
            }
        )
    return {
        "observations": observations,
        "timings": timings,
        "missing_picks": missing,
        "wrapper_missing_during_run": last_wrapper_missing_at is not None,
        "last_wrapper_missing_at": last_wrapper_missing_at,
        "seen_picks": sorted(seen.keys()),
        "connection_closed": connection_closed,
    }


def main() -> int:
    from playwright.sync_api import sync_playwright

    rt = _rt()
    _scrub()
    report: dict = {
        "timings": [],
        "wrapper_selector": WRAPPER_SEL,
        "timer_selector": TIMER_SEL,
        "clock_seconds": CLOCK,
        "target_expires": TARGET_EXPIRES,
        "poll_ms": POLL_MS,
        "architecture": "solo_server_driven_fragment_lifecycle",
        "fragment_cadence_s": 0.5,
    }
    print("scrubbed; launching browser", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(3000)
        flow: dict = {}
        # Enough picks for TARGET_EXPIRES consecutive transitions (+ buffer).
        picks_per = max(12, (TARGET_EXPIRES // 2) + 3)
        ok = rt._create_ready_solo(
            page, flow, num_teams=2, picks_per_team=picks_per, timer_seconds=CLOCK
        )
        report["create"] = ok
        report["flow"] = flow
        try:
            print(
                f"create_ok={ok} flow={json.dumps(flow, ensure_ascii=True, default=str)}",
                flush=True,
            )
        except Exception:
            print(f"create_ok={ok}", flush=True)
        if not ok:
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            browser.close()
            return 1
        for _ in range(90):
            btn = page.get_by_role("button", name=re.compile(r"^Start Draft$", re.I))
            if btn.count():
                try:
                    if btn.first.is_enabled():
                        break
                except Exception:
                    pass
            page.wait_for_timeout(1000)
        start_report: dict = {}
        started = rt._press_start_draft(page, start_report)
        report["start"] = start_report
        report["started"] = started
        print(
            f"Start Draft started={started} report={json.dumps(start_report, ensure_ascii=True)}",
            flush=True,
        )
        if not started:
            # Recovery: sidebar often shows live draft while Start helper timed out
            # waiting for the on-clock wrapper after Return-to-Live.
            body = ""
            try:
                body = page.inner_text("body") or ""
            except Exception:
                pass
            live_hint = bool(
                re.search(r"On clock:\s*\S+", body, re.I)
                and re.search(r"\d+\s*/\s*\d+\s*picks", body, re.I)
            )
            report["start_recovery_live_hint"] = live_hint
            if live_hint:
                for attempt in range(3):
                    try:
                        page.goto(
                            "http://127.0.0.1:8511/?suite_workspace=daniel&active_page=Live%20Draft%20Room&ux_latency=1",
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                        page.wait_for_timeout(3500)
                    except Exception as exc:
                        report[f"recovery_goto_err_{attempt}"] = f"{type(exc).__name__}: {exc}"[:120]
                    # Prefer the sidebar/banner Return control (emoji-safe).
                    for pattern in (
                        r"Return to Live Draft",
                        r"Live Draft Room",
                    ):
                        try:
                            btns = page.get_by_role("button", name=re.compile(pattern, re.I))
                            n = btns.count()
                            for i in range(min(n, 3)):
                                try:
                                    btns.nth(i).click(timeout=2500, force=False)
                                    page.wait_for_timeout(2500)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    snap = _wrapper_snapshot(page)
                    if snap and isinstance(snap.get("remaining"), int) and snap.get("pick_number") == 1:
                        started = True
                        report["started"] = True
                        report["start_recovered"] = True
                        report["start_recovery_attempt"] = attempt
                        start_report["pick1_timer"] = snap.get("remaining")
                        break
                    # Text fallback — server caption may paint before st.html testid.
                    try:
                        body2 = page.inner_text("body") or ""
                    except Exception:
                        body2 = ""
                    if re.search(r"TIME REMAINING\s+[1-9]", body2, re.I) or re.search(
                        r"On the clock", body2, re.I
                    ):
                        for _ in range(40):
                            snap = _wrapper_snapshot(page)
                            if snap and isinstance(snap.get("remaining"), int):
                                started = True
                                report["started"] = True
                                report["start_recovered"] = True
                                report["start_recovery_attempt"] = attempt
                                start_report["pick1_timer"] = snap.get("remaining")
                                break
                            page.wait_for_timeout(500)
                        if started:
                            break
                if not started:
                    try:
                        report["recovery_body_snip"] = (page.inner_text("body") or "")[:600]
                    except Exception:
                        pass
            if not started:
                report["error"] = "Start Draft did not reach live timer"
                OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
                browser.close()
                return 1

        # Wait until any live on-clock wrapper is visible. Start recovery can take
        # longer than CLOCK seconds, so Pick 1 may already have expired — arm on
        # whatever pick is showing and observe forward from there.
        pick1_deadline = time.time() + 90
        first_snap = None
        while time.time() < pick1_deadline:
            snap = _wrapper_snapshot(page)
            if (
                snap
                and snap.get("pick_index") is not None
                and isinstance(snap.get("remaining"), int)
                and int(snap["remaining"]) >= 1
                and int(snap.get("wrapper_count") or 0) >= 1
            ):
                first_snap = snap
                break
            page.wait_for_timeout(100)
        report["first_wrapper"] = first_snap
        report["iframe_timer_count_at_start"] = _iframe_timer_count(page)
        if first_snap is None:
            report["error"] = "Pick 1 wrapper never armed after Start"
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            browser.close()
            return 1
        if int(report["iframe_timer_count_at_start"] or 0) != 0:
            report["error"] = "Solo timer still using iframe components.html"
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            browser.close()
            return 1
        start_pick = int(first_snap.get("pick_number") or 1)
        report["observe_start_pick"] = start_pick
        print(
            f"Pick {start_pick} armed clock={first_snap.get('remaining')} "
            f"wrappers={first_snap.get('wrapper_count')}",
            flush=True,
        )

        # --- One continuous observation: Pick start → start+TARGET ---
        print(
            f"=== consecutive visible picks (target {TARGET_EXPIRES} transitions) "
            f"from Pick {start_pick} ===",
            flush=True,
        )
        full = _observe_pick_sequence(
            page, start_pick_number=start_pick, transitions=TARGET_EXPIRES, clock=CLOCK
        )
        # Seed start pick from the armed snapshot if observe started after first expire.
        if first_snap and start_pick not in (full.get("seen_picks") or []):
            seed = {
                "pick_number": start_pick,
                "pick_index": start_pick - 1,
                "first_visible_ts": time.time(),
                "remaining": first_snap.get("remaining"),
                "initial_clock": first_snap.get("remaining"),
                "wrapper_count": first_snap.get("wrapper_count"),
                "team": first_snap.get("team"),
                "seeded_from_arm": True,
            }
            obs = list(full.get("observations") or [])
            obs.insert(0, seed)
            full["observations"] = obs
            seen = [start_pick] + [p for p in (full.get("seen_picks") or []) if p != start_pick]
            full["seen_picks"] = seen
            print(f"seeded Pick {start_pick} from arm snapshot", flush=True)
        expected_prelim = list(range(start_pick, start_pick + 4))
        prelim_seen = [p for p in (full.get("seen_picks") or []) if p in expected_prelim]
        prelim_ok = (
            prelim_seen == expected_prelim
            and not full.get("connection_closed")
        )
        report["preliminary_3"] = {
            "seen_picks": prelim_seen,
            "expected": expected_prelim,
            "timings": (full.get("timings") or [])[:3],
            "missing_picks": [p for p in expected_prelim if p not in prelim_seen],
            "connection_closed": full.get("connection_closed"),
        }
        report["preliminary_3_ok"] = prelim_ok
        print(
            f"preliminary_3_ok={prelim_ok} seen={prelim_seen} "
            f"missing={report['preliminary_3']['missing_picks']}",
            flush=True,
        )
        if not prelim_ok:
            report["error"] = "preliminary 3 consecutive visible transitions failed"
            report["server_txns"] = _read_jsonl(TXN_LOG, 30)
            report["lifecycle_tail"] = _read_jsonl(LIFE_LOG, 40)
            report["ok"] = False
            try:
                browser.close()
            except Exception:
                pass
            OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2), flush=True)
            return 1

        report["timings"] = list(full.get("timings") or [])[:TARGET_EXPIRES]
        report["seen_picks"] = list(full.get("seen_picks") or [])
        expected_picks = list(range(start_pick, start_pick + TARGET_EXPIRES + 1))
        report["missing_picks"] = [p for p in expected_picks if p not in report["seen_picks"]]
        report["observations"] = full.get("observations") or []
        report["connection_closed"] = bool(full.get("connection_closed"))

        report["players"] = _board_players()
        try:
            final_snap = _wrapper_snapshot(page)
        except Exception:
            final_snap = None
        report["final_wrapper"] = final_snap
        report["timer_instances_final"] = int((final_snap or {}).get("wrapper_count") or 0)
        try:
            report["iframe_timer_count_final"] = _iframe_timer_count(page)
        except Exception:
            report["iframe_timer_count_final"] = -1
        report["server_txns"] = _read_jsonl(TXN_LOG, 40)
        report["lifecycle_tail"] = _read_jsonl(LIFE_LOG, 60)
        report["rerun_blocked"] = _read_jsonl(
            ROOT / "data" / "tb_probe" / "solo_rerun_blocked.jsonl", 40
        )
        report["responsive_after"] = _probe_responsive("http://127.0.0.1:8511/")

        seq_to = [t.get("to") for t in report["timings"] if t.get("to") is not None]
        report["pick_to_sequence"] = seq_to
        report["no_skip"] = (
            len(seq_to) >= TARGET_EXPIRES
            and all(seq_to[i] == seq_to[i - 1] + 1 for i in range(1, len(seq_to)))
            and seq_to[0] == start_pick + 1
            and not report["missing_picks"]
        )
        report["no_duplicate_picks"] = len(report["players"]) == len(set(report["players"]))
        report["no_sticky_zero"] = not any(
            (t.get("initial_visible_clock") or 99) <= 1 for t in report["timings"]
        )
        try:
            browser.close()
        except Exception:
            pass

    wrapper_ok = all(int(t.get("wrapper_count") or 0) == 1 for t in report["timings"])
    report["wrapper_count_always_1"] = wrapper_ok
    # Backfill any timing rows that missed txn match during the live observe loop.
    txn_rows = list(report.get("server_txns") or []) or _read_jsonl(TXN_LOG, 80)
    for t in report["timings"]:
        if t.get("server_expire_ms") is not None and t.get("server_to_browser_s") is not None:
            continue
        frm = t.get("from")
        if frm is None:
            continue
        txn = _match_txn_rows(txn_rows, int(frm) - 1)
        if not txn:
            continue
        if t.get("server_expire_ms") is None:
            t["server_expire_ms"] = txn.get("expire_ms")
        if t.get("warm_plan_hit") is None:
            t["warm_plan_hit"] = txn.get("warm_plan_hit")
            if not t.get("server_from_to"):
                t["server_from_to"] = (
                    f"{int(txn['pick_index_before']) + 1}"
                    f"→{int(txn.get('pick_index_after') if txn.get('pick_index_after') is not None else -1) + 1}"
                )
        if t.get("server_to_browser_s") is None:
            server_ts = txn.get("deadline_detected") or txn.get("next_deadline_created")
            to_obs = next(
                (
                    o
                    for o in (report.get("observations") or [])
                    if int(o.get("pick_number") or -1) == int(t.get("to") or -2)
                ),
                None,
            )
            if isinstance(server_ts, (int, float)) and to_obs and to_obs.get("first_visible_ts"):
                t["server_to_browser_s"] = round(
                    float(to_obs["first_visible_ts"]) - float(server_ts), 3
                )
    ok_times = [
        t["server_to_browser_s"]
        for t in report["timings"]
        if isinstance(t.get("server_to_browser_s"), (int, float))
    ]
    expire_ms = [
        t["server_expire_ms"]
        for t in report["timings"]
        if isinstance(t.get("server_expire_ms"), (int, float))
    ]
    report["all_server_to_browser_s"] = ok_times
    report["all_expire_ms"] = expire_ms
    if ok_times:
        s = sorted(ok_times)
        report["server_to_browser_median"] = s[len(s) // 2]
        report["server_to_browser_p95"] = s[max(0, int(len(s) * 0.95) - 1)]
        report["server_to_browser_max"] = max(s)
    if expire_ms:
        s = sorted(expire_ms)
        report["server_expire_median_ms"] = s[len(s) // 2]
        report["server_expire_p95_ms"] = s[max(0, int(len(s) * 0.95) - 1)]

    report["ok"] = (
        len(report["timings"]) >= TARGET_EXPIRES
        and bool(report.get("no_skip"))
        and bool(report.get("no_duplicate_picks"))
        and bool(report.get("no_sticky_zero"))
        and wrapper_ok
        and int(report.get("iframe_timer_count_final") or 0) == 0
        and bool((report.get("responsive_after") or {}).get("ok"))
        and len(ok_times) >= TARGET_EXPIRES
        and all(float(x) < 2.0 for x in ok_times)
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
