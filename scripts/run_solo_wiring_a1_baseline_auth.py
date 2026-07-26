"""A1-only synthetic wiring baseline — strict distinct event counts (Cloud)."""

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
OUT = ROOT / "data" / "solo_wiring_a1_baseline.json"


def _required_sha() -> str:
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from run_production_solo_soak import scrape_deploy_build  # noqa: E402
from solo_wiring_matrix_harness_core import (  # noqa: E402
    build_distinct_counts,
    collect_parent_messages,
    install_parent_capture,
    score_a1,
    scrape_repro_events,
)


def a1_url(widget_key: str, ls_key: str) -> str:
    q = urlencode(
        {
            "active_page": "Live Draft Room",
            "solo_wiring_synthetic": "1",
            "solo_wiring_matrix": "A1",
            "solo_wiring_key": widget_key,
            "solo_wiring_ls_key": ls_key,
            "solo_transport_probe": "1",
        }
    )
    return append_suite_sid_to_url(f"{BASE}/?{q}")


def scrape_probe(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for (const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean);}
          for (const r of roots()) {
            const el = r.querySelector('#solo-wiring-matrix-diag');
            if (!el) continue;
            let decoded = null;
            const b64 = el.getAttribute('data-b64')||'';
            try { decoded = b64 ? JSON.parse(atob(b64)) : null; } catch(e) { decoded = {err:String(e)}; }
            return {
              expected: el.getAttribute('data-expected-token')||'',
              key: el.getAttribute('data-key')||'',
              decoded,
            };
          }
          return {missing:true};
        }"""
    )


def observe_a1(page, *, expected_token: str, deadline: float) -> dict[str, Any]:
    install_parent_capture(page, expected_token=expected_token)
    t0 = time.time()
    browser_send_ts: float | None = None
    samples: list[dict[str, Any]] = []
    parent_all: list[dict[str, Any]] = []

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

        probe = scrape_probe(page)
        decoded = probe.get("decoded") if isinstance(probe.get("decoded"), dict) else {}
        meta = decoded.get("meta") if isinstance(decoded.get("meta"), dict) else {}
        log = decoded.get("log_tail") if isinstance(decoded.get("log_tail"), list) else []
        callbacks = meta.get("callback_log") if isinstance(meta.get("callback_log"), list) else []
        session_raw = str(meta.get("session_state_value") or "").strip("'\"")

        distinct = build_distinct_counts(
            repro=repro,
            parent_rows=parent_rows,
            expected_token=expected_token,
            session_raw=session_raw,
            callback_log=callbacks,
            browser_send_ts=browser_send_ts,
        )
        samples.append({"elapsed_s": round(time.time() - t0, 1), "distinct": distinct})

        scored = score_a1(distinct, expected_token=expected_token)
        if scored.get("outcome") == "PASS":
            scored["distinct"] = distinct
            scored["samples"] = samples
            scored["observation_s"] = round(time.time() - t0, 1)
            return scored

        if time.time() >= deadline + 8 and int(sc.get("browser_deadline_crossed") or 0) >= 1:
            break
        page.wait_for_timeout(800)

    probe = scrape_probe(page)
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
    scored = score_a1(distinct, expected_token=expected_token)
    scored["distinct"] = distinct
    scored["samples"] = samples[-15:]
    scored["observation_s"] = round(time.time() - t0, 1)
    return scored


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    widget_key = f"solo_wiring_a1_{uuid.uuid4().hex[:10]}"
    ls_key = f"solo_wiring_ls_a1_{uuid.uuid4().hex[:10]}"
    url = a1_url(widget_key, ls_key)
    req = _required_sha()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        page = ctx.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(12000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        sha = scrape_deploy_build(page) or ""
        if not sha:
            try:
                from run_solo_clean_verification import scrape_live_sha

                sha = scrape_live_sha(page) or ""
            except ImportError:
                pass
        sha_short = str(sha).lower()[:7]
        if sha_short and sha_short != req:
            ctx.close()
            browser.close()
            out = {
                "outcome": "INVALID",
                "invalid_reasons": ["cloud_sha_mismatch"],
                "cloud_sha": sha_short,
                "required_sha": req,
                "cell": "A1",
                "note": "Deploy harness fixes before A1 baseline; production unchanged.",
            }
            OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
            print(json.dumps(out, indent=2))
            return 1

        for _ in range(15):
            probe = scrape_probe(page)
            if not probe.get("missing"):
                break
            page.wait_for_timeout(2000)

        expected = str(probe.get("expected") or "")
        deadline = float(expected.split("|")[2]) if expected.count("|") >= 2 else time.time() + 12

        result = observe_a1(page, expected_token=expected, deadline=deadline)
        result["cell"] = "A1"
        result["fresh_widget_key"] = widget_key
        result["fresh_local_storage_key"] = ls_key
        result["expected_token"] = expected
        result["cloud_sha"] = sha_short
        result["required_sha"] = req
        ctx.close()
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("outcome") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
