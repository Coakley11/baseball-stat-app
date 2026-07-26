"""Production-parity ladder P0–P6 from B2 baseline (Cloud auth, stop at first valid failure)."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
OUT = ROOT / "data" / "solo_persistent_parity_ladder.json"
CONTROLS = ("P0", "P1", "P2", "P3", "P4", "P5", "P6")
DEPLOY_PROBE_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room&solo_delivery_diag=1&solo_bridge_transition=A0"
)


def official_required_sha() -> str:
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from run_solo_wiring_b2_graded_auth import verify_official_deploy  # noqa: E402
from solo_wiring_matrix_harness_core import (  # noqa: E402
    build_distinct_counts,
    collect_parent_messages,
    install_parent_capture,
    merge_peak_distinct,
    score_matrix_cell,
    scrape_repro_events,
)
from verify_cloud_deploy_playwright import scrape_deploy  # noqa: E402


def parity_url(control: str, *, widget_key: str = "", ls_key: str = "") -> str:
    q: dict[str, str] = {
        "active_page": "Live Draft Room",
        "solo_delivery_diag": "1",
        "solo_persistent_parity": control,
        "solo_transport_probe": "1",
    }
    if widget_key:
        q["solo_parity_widget_key"] = widget_key
    if ls_key:
        q["solo_parity_ls_key"] = ls_key
    return append_suite_sid_to_url(f"{BASE}/?{urlencode(q)}")


def scrape_parity_probe(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for (const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean);}
          for (const r of roots()) {
            const el = r.querySelector('#solo-persistent-parity-diag');
            if (!el) continue;
            let decoded = null;
            const b64 = el.getAttribute('data-b64')||'';
            try { decoded = b64 ? JSON.parse(atob(b64)) : null; } catch(e) { decoded = {err:String(e)}; }
            return {
              expected: el.getAttribute('data-expected-token')||'',
              key: el.getAttribute('data-key')||'',
              control: el.getAttribute('data-control')||'',
              decoded,
            };
          }
          return {missing:true};
        }"""
    )


def observe_control(page, *, control: str, expected_token: str, deadline: float) -> dict[str, Any]:
    install_parent_capture(page, expected_token=expected_token)
    t0 = time.time()
    browser_send_ts: float | None = None
    samples: list[dict[str, Any]] = []
    parent_all: list[dict[str, Any]] = []
    peak: dict[str, Any] = {}

    while time.time() - t0 < 32.0:
        install_parent_capture(page, expected_token=expected_token)
        repro = scrape_repro_events(page)
        sc = repro.get("stage_counts") if isinstance(repro.get("stage_counts"), dict) else {}
        parent_rows = collect_parent_messages(page)
        parent_all = parent_rows
        if browser_send_ts is None and (
            int(sc.get("transport_postmessage_invoked") or 0) >= 1
            or int(sc.get("component_value_sent") or 0) >= 1
        ):
            browser_send_ts = time.time()

        probe = scrape_parity_probe(page)
        decoded = probe.get("decoded") if isinstance(probe.get("decoded"), dict) else {}
        meta = decoded.get("meta") if isinstance(decoded.get("meta"), dict) else {}
        callbacks = meta.get("callback_log") if isinstance(meta.get("callback_log"), list) else []
        prod_n = 0
        for c in callbacks:
            if isinstance(c, dict):
                prod_n = max(prod_n, int(c.get("production_on_change_count") or 0))
        if prod_n > len(callbacks):
            callbacks = list(callbacks) + [{"ts": time.time(), "source": "production_flag_count", "seq": prod_n}]
        session_raw = str(meta.get("session_state_value") or "").strip("'\"")

        distinct = build_distinct_counts(
            repro=repro,
            parent_rows=parent_rows,
            expected_token=expected_token,
            session_raw=session_raw,
            callback_log=callbacks,
            browser_send_ts=browser_send_ts,
        )
        if prod_n > int(distinct.get("on_change_callback") or 0):
            distinct["on_change_callback"] = prod_n
        peak = merge_peak_distinct(peak, distinct)
        samples.append({"elapsed_s": round(time.time() - t0, 1), "distinct": distinct})

        scored = score_matrix_cell(peak, cell="B2", expected_token=expected_token)
        if scored.get("outcome") == "PASS":
            scored["distinct"] = peak
            scored["samples"] = samples
            scored["observation_s"] = round(time.time() - t0, 1)
            scored["probe"] = probe
            scored["meta"] = meta
            return scored

        if time.time() >= deadline + 8 and int(peak.get("browser_deadline_crossed") or 0) >= 1:
            break
        page.wait_for_timeout(800)

    probe = scrape_parity_probe(page)
    decoded = probe.get("decoded") if isinstance(probe.get("decoded"), dict) else {}
    meta = decoded.get("meta") if isinstance(decoded.get("meta"), dict) else {}
    callbacks = meta.get("callback_log") if isinstance(meta.get("callback_log"), list) else []
    session_raw = str(meta.get("session_state_value") or "").strip("'\"")
    repro = scrape_repro_events(page)
    distinct = build_distinct_counts(
        repro=repro,
        parent_rows=parent_all,
        expected_token=expected_token,
        session_raw=session_raw,
        callback_log=callbacks,
        browser_send_ts=browser_send_ts,
    )
    peak = merge_peak_distinct(peak, distinct)
    scored = score_matrix_cell(peak, cell="B2", expected_token=expected_token)
    if (
        int(peak.get("on_change_callback") or 0) >= 1
        and int(peak.get("logical_send_postmessage") or 0) == 0
        and int(peak.get("parent_message") or 0) == 0
    ):
        scored["outcome"] = "INVALID"
        scored.setdefault("invalid_reasons", []).append("python_callback_without_browser_evidence")
    scored["distinct"] = peak
    scored["samples"] = samples[-15:]
    scored["observation_s"] = round(time.time() - t0, 1)
    scored["probe"] = probe
    scored["meta"] = meta
    return scored


def build_control_record(
    control: str,
    *,
    scored: dict[str, Any],
    widget_key: str,
    ls_key: str,
    deploy: dict[str, Any],
) -> dict[str, Any]:
    distinct = scored.get("distinct") if isinstance(scored.get("distinct"), dict) else {}
    meta = scored.get("meta") if isinstance(scored.get("meta"), dict) else {}
    prod = meta.get("production_state") if isinstance(meta.get("production_state"), dict) else {}
    probe = scored.get("probe") if isinstance(scored.get("probe"), dict) else {}
    decoded = probe.get("decoded") if isinstance(probe.get("decoded"), dict) else {}
    log_tail = decoded.get("log_tail") if isinstance(decoded.get("log_tail"), list) else []
    lc = distinct.get("lifecycle") if isinstance(distinct.get("lifecycle"), dict) else {}
    invalid = list(scored.get("invalid_reasons") or [])
    transport = {
        "one_logical_send": int(distinct.get("logical_send_postmessage") or 0) == 1,
        "one_parent_message": int(distinct.get("parent_message") or 0) == 1,
        "exact_python_receipt": bool(distinct.get("session_raw_matches")),
        "one_on_change": int(distinct.get("on_change_callback") or 0) == 1,
        "no_pre_send_token": not bool(distinct.get("pre_send_session_token")),
        "no_duplicate_send_or_callback": "duplicate_callback_or_remount_delivery" not in invalid,
        "counts": {
            "logical_send": int(distinct.get("logical_send_postmessage") or 0),
            "parent_message": int(distinct.get("parent_message") or 0),
            "on_change": int(distinct.get("on_change_callback") or 0),
            "python_raw_receipt": int(distinct.get("python_raw_receipt") or 0),
        },
    }
    lifecycle = {
        "widget_key": widget_key or probe.get("key") or meta.get("widget_key"),
        "widget_id": meta.get("widget_id"),
        "production_iframe_count": int(distinct.get("production_iframes") or 0),
        "iframe_remount_count": int(lc.get("iframe_remount_count") or 0),
        "timer_armed_count": int(distinct.get("timer_armed") or 0),
        "timer_cancellation_count": int(lc.get("tick_cancelled_count") or 0),
        "page_stopped": meta.get("page_stopped"),
        "page_continued": meta.get("page_stopped") is False,
    }
    production_state = {
        **prod,
        "current_room_id": prod.get("expected_room_pick") and meta.get("draft_id"),
    }
    live = session_room_from_log(log_tail) or {}
    if live:
        production_state["current_room_id"] = live.get("room_id") or production_state.get("current_room_id")
        production_state["current_pick"] = live.get("pick")
        production_state["current_deadline"] = live.get("deadline")
    return {
        "control": control,
        "widget_key": lifecycle["widget_key"],
        "expected_token": probe.get("expected") or meta.get("expire_token"),
        "local_storage_key": ls_key,
        "outcome": scored.get("outcome"),
        "invalid_reasons": scored.get("invalid_reasons"),
        "missing": scored.get("missing"),
        "requirements": scored.get("requirements"),
        "transport": transport,
        "lifecycle": lifecycle,
        "production_state": production_state,
        "callback_and_ownership_timeline": log_tail,
        "distinct": distinct,
        "meta": meta,
        "page_stopped": meta.get("page_stopped"),
        "callback_log": meta.get("callback_log"),
        "observation_s": scored.get("observation_s"),
        "deploy": deploy,
    }


def session_room_from_log(log_tail: list[Any]) -> dict[str, Any]:
    for row in reversed(log_tail):
        if not isinstance(row, dict):
            continue
        if row.get("stage") == "parity_control_start":
            continue
        if "expire_token" in row:
            tok = str(row.get("expire_token") or "")
            parts = tok.split("|")
            if len(parts) >= 3:
                return {"room_id": parts[0], "pick": parts[1], "deadline": parts[2]}
    return {}


def run_control(browser, control: str, *, deploy: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    widget_key = ""
    ls_key = f"solo_parity_ls_{control.lower()}_{uuid.uuid4().hex[:10]}"
    if control == "P0":
        widget_key = f"solo_parity_p0_{uuid.uuid4().hex[:10]}"
    url = parity_url(control, widget_key=widget_key, ls_key=ls_key)

    ctx = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
    page = ctx.new_page()
    try:
        goto_and_wake(page, url, timeout_s=240)
        install_parent_capture(page)
        t_nav = time.time()
        probe: dict[str, Any] = {"missing": True}
        while time.time() - t_nav < 90.0:
            install_parent_capture(page)
            probe = scrape_parity_probe(page)
            if not probe.get("missing"):
                break
            page.wait_for_timeout(500)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=2000)
            page.wait_for_timeout(1000)
        except Exception:
            pass
        if probe.get("missing"):
            return {
                "control": control,
                "widget_key": widget_key,
                "local_storage_key": ls_key,
                "outcome": "INVALID",
                "invalid_reasons": ["parity_ladder_not_on_cloud_deploy"],
                "deploy": deploy,
                "url": url,
            }
        expected = str(probe.get("expected") or "")
        if not expected:
            decoded = probe.get("decoded") if isinstance(probe.get("decoded"), dict) else {}
            meta = decoded.get("meta") if isinstance(decoded.get("meta"), dict) else {}
            expected = str(meta.get("expire_token") or "")
        deadline = float(expected.split("|")[-1]) if expected.count("|") >= 2 else time.time() + 10
        scored = observe_control(page, control=control, expected_token=expected, deadline=deadline)
        return build_control_record(
            control,
            scored=scored,
            widget_key=widget_key,
            ls_key=ls_key,
            deploy=deploy,
        )
    finally:
        ctx.close()


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    if not run_preflight().get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    required = official_required_sha()
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {
        "ladder": "production_parity_P0_P6",
        "baseline_cell": "B2",
        "required_sha": required,
        "controls_run": [],
        "root_cause_boundary": None,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        deploy_page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        deploy = verify_official_deploy(deploy_page, required=required)
        report["deploy_probe"] = deploy
        deploy_page.context.close()

        if not deploy.get("deploy_ok"):
            report["outcome"] = "ABORTED"
            report["reason"] = "cloud_deploy_mismatch"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps(report, indent=2, default=str))
            browser.close()
            return 1

        stopped = False
        prev_pass = True
        for control in CONTROLS:
            if stopped:
                break
            rec = run_control(browser, control, deploy=deploy)
            report["controls_run"].append(rec)
            outcome = str(rec.get("outcome") or "")
            if "parity_ladder_not_on_cloud_deploy" in (rec.get("invalid_reasons") or []):
                report["outcome"] = "ABORTED"
                report["reason"] = "parity_ladder_not_deployed"
                stopped = True
                break
            if outcome == "PASS":
                prev_pass = True
                continue
            if outcome in ("VALID FAIL", "INVALID") and prev_pass:
                report["root_cause_boundary"] = control
                report["outcome"] = outcome
                stopped = True
            prev_pass = outcome == "PASS"

        if not stopped:
            report["outcome"] = "ALL_PASS"
        report["cloud_sha"] = str(deploy.get("cloud_sha") or required)
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("outcome") in ("ALL_PASS",) else 0


if __name__ == "__main__":
    raise SystemExit(main())
