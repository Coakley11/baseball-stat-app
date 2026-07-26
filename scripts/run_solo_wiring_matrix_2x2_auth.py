"""Synthetic 2×2 wiring matrix on Cloud LDR (no draft; fresh context per cell)."""

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
REQUIRED_SHA = "2e0373a"
OUT = ROOT / "data" / "solo_wiring_matrix_synthetic_2x2.json"
CELLS = ("A1", "B1", "A2", "B2")

FRONTEND = {
    "A1": "minimal_wake_repro",
    "B1": "solo_countdown_wake",
    "A2": "minimal_wake_repro",
    "B2": "solo_countdown_wake",
}
DECL = {
    "A1": "minimal_component_wake_repro_core.mount_single_for_transport",
    "B1": "solo_countdown_component.mount_solo_countdown_wake_direct",
    "A2": "minimal_frontend + micro_isolation_callback_wrapper",
    "B2": "solo_countdown_wake_micro_core.render_micro_isolation_once",
}
EXPECTED_HOST = {
    "A1": "repro-client",
    "B1": "solo-expire-client",
    "A2": "repro-client",
    "B2": "solo-expire-client",
}


def _required_cloud_sha() -> str:
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from run_production_solo_soak import (  # noqa: E402
    scrape_deploy_build,
    scrape_iframe_lifecycle,
    scrape_transport_boundary,
)
from stage1_frame_transport_probe import (  # noqa: E402
    collect_frame_topology,
    install_immediate_parent_listeners,
    scrape_immediate_parent_messages,
)


def cell_url(cell: str, widget_key: str) -> str:
    params = {
        "active_page": "Live Draft Room",
        "solo_wiring_synthetic": "1",
        "solo_wiring_matrix": cell,
        "solo_wiring_key": widget_key,
        "solo_transport_probe": "1",
    }
    return append_suite_sid_to_url(f"{BASE}/?{urlencode(params)}")


def scrape_matrix_probe(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots() {
            const out = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) out.push(f.contentDocument); } catch (e) {}
            }
            return out.filter(Boolean);
          }
          for (const root of roots()) {
            const el = root.querySelector('#solo-wiring-matrix-diag');
            if (!el) continue;
            const b64 = el.getAttribute('data-b64') || '';
            let decoded = null;
            try { decoded = b64 ? JSON.parse(atob(b64)) : null; } catch (e) { decoded = { err: String(e) }; }
            return {
              synthetic: el.getAttribute('data-synthetic') || '',
              cell: el.getAttribute('data-cell') || '',
              key: el.getAttribute('data-key') || '',
              expected_token: el.getAttribute('data-expected-token') || '',
              callbacks: parseInt(el.getAttribute('data-callbacks') || '0', 10),
              decoded,
            };
          }
          return { missing: true };
        }"""
    )


def scrape_client_surfaces(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const out = {
            repro_count: 0,
            solo_count: 0,
            repro_chain: '',
            solo_chain: '',
            repro_console: '',
          };
          for (const f of document.querySelectorAll('iframe')) {
            try {
              const doc = f.contentDocument;
              if (!doc) continue;
              const repro = doc.querySelector('#repro-client');
              if (repro) {
                out.repro_count += 1;
                out.repro_chain = repro.getAttribute('data-chain') || out.repro_chain;
                out.repro_console = repro.getAttribute('data-console') || out.repro_console;
              }
              const solo = doc.querySelector('#solo-expire-client');
              if (solo) {
                out.solo_count += 1;
                out.solo_chain = solo.getAttribute('data-chain') || out.solo_chain;
              }
            } catch (e) {}
          }
          return out;
        }"""
    )


def assess_isolation(page, *, cell: str) -> dict[str, Any]:
    topo = collect_frame_topology(page)
    surf = scrape_client_surfaces(page)
    min_f = sum(1 for fr in (topo.get("frames") or []) if isinstance(fr, dict) and fr.get("has_minimal_control"))
    prod_f = sum(1 for fr in (topo.get("frames") or []) if isinstance(fr, dict) and fr.get("has_production_countdown"))
    min_f = max(min_f, int(surf.get("repro_count") or 0))
    prod_f = max(prod_f, int(surf.get("solo_count") or 0))
    expect_min = cell in ("A1", "A2")
    ok = (min_f == 1 and prod_f == 0) if expect_min else (prod_f == 1 and min_f == 0)
    return {
        "cell": cell,
        "minimal_count": min_f,
        "production_count": prod_f,
        "isolation_ok": ok,
        "isolation_confounded": not ok,
        "frame_count": topo.get("frame_count"),
    }


def _stages_from_run(cell: str, iframe_life: dict[str, Any], surf: dict[str, Any]) -> set[str]:
    stages: set[str] = set()
    for e in _iframe_log_entries(iframe_life):
        stg = str(e.get("stage") or "")
        if stg:
            stages.add(stg)
    chain = str(surf.get("solo_chain") or surf.get("repro_chain") or "")
    for part in chain.split("|"):
        if part.strip():
            stages.add(part.strip())
    if "setComponentValue" in str(surf.get("repro_console") or ""):
        stages.add("setComponentValue_called")
    if cell in ("A1", "A2") and "render token=" in str(surf.get("repro_console") or ""):
        stages.add("render_event_received")
    return stages


def _iframe_log_entries(iframe_life: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fr in iframe_life.get("frames") or []:
        for block in (fr.get("logs") or [] if isinstance(fr, dict) else []):
            if isinstance(block, dict):
                out.extend(block.get("entries") or [])
    return [e for e in out if isinstance(e, dict)]


def _setcomp_count(stages: set[str], iframe_life: dict[str, Any]) -> int:
    n = stages.count("setComponentValue_called") if isinstance(stages, list) else 0
    if "setComponentValue_called" in stages:
        n = max(n, 1)
    if "iframe_setComponentValue_called" in stages:
        n += 1
    for e in _iframe_log_entries(iframe_life):
        if str(e.get("stage") or "") in ("setComponentValue_called", "iframe_setComponentValue_called"):
            n += 1
    return max(1, n) if ("component_value_sent" in stages) else n


def wait_synthetic_expire(page, *, cell: str, widget_key: str, expected_token: str) -> dict[str, Any]:
    install_immediate_parent_listeners(page)
    iso_pre = assess_isolation(page, cell=cell)
    if not iso_pre.get("isolation_ok"):
        return {
            "outcome": "INVALID",
            "invalid_reason": "isolation_before_timer",
            "isolation": iso_pre,
        }

    t0 = time.time()
    armed_at: float | None = None
    while time.time() - t0 < 28.0:
        install_immediate_parent_listeners(page)
        iframe_life = scrape_iframe_lifecycle(page)
        surf = scrape_client_surfaces(page)
        stages = _stages_from_run(cell, iframe_life, surf)
        if "timer_armed" in stages or "render token=" in str(surf.get("repro_console") or ""):
            armed_at = armed_at or time.time()
        if "browser_deadline_crossed" in stages and "component_value_sent" in stages:
            page.wait_for_timeout(6000)
            break
        if armed_at and time.time() - armed_at > 18:
            page.wait_for_timeout(4000)
            break
        page.wait_for_timeout(1500)

    probe = scrape_matrix_probe(page)
    decoded = (probe.get("decoded") or {}) if isinstance(probe.get("decoded"), dict) else {}
    meta = decoded.get("meta") if isinstance(decoded.get("meta"), dict) else {}
    log_tail = decoded.get("log_tail") if isinstance(decoded.get("log_tail"), list) else []

    iframe_life = scrape_iframe_lifecycle(page)
    surf = scrape_client_surfaces(page)
    stages = _stages_from_run(cell, iframe_life, surf)
    immediate = scrape_immediate_parent_messages(page)
    transport = scrape_transport_boundary(page) or {}
    tlog = list((transport.get("probe") or {}).get("log_tail") or [])

    iso_post = assess_isolation(page, cell=cell)
    host = EXPECTED_HOST[cell]
    parent_msgs = [
        m
        for m in immediate
        if isinstance(m, dict)
        and m.get("has_set_component_value")
        and (m.get("iframe_association") or {}).get("component_widget_host_id") == host
    ]
    if not parent_msgs:
        parent_msgs = [m for m in immediate if isinstance(m, dict) and m.get("has_set_component_value")]

    token_ok = all(
        str(m.get("value_preview") or "").startswith(f"WIRING_{cell}")
        for m in parent_msgs
    ) if parent_msgs else False

    payload_keys = list((parent_msgs[-1] if parent_msgs else {}).get("payload_key_names") or [])
    setcomp_n = sum(
        1
        for s in stages
        if s in ("setComponentValue_called", "iframe_setComponentValue_called", "component_value_sent")
    )
    for e in _iframe_log_entries(iframe_life):
        if str(e.get("stage") or "") in ("setComponentValue_called", "iframe_setComponentValue_called"):
            setcomp_n += 1

    cb = int(meta.get("callback_count") or probe.get("callbacks") or 0)
    cb += sum(1 for r in log_tail if isinstance(r, dict) and r.get("stage") == "matrix_callback")
    cb += sum(1 for r in tlog if isinstance(r, dict) and r.get("stage") == "matrix_callback")

    session_raw = meta.get("session_state_value")
    for r in reversed(log_tail):
        if isinstance(r, dict) and r.get("stage") == "matrix_callback":
            session_raw = r.get("raw_repr") or r.get("session_state_raw")
            break

    chain_req = {
        "component_script_loaded": "component_script_loaded" in stages
        or "componentReady" in str(surf.get("repro_console") or ""),
        "render_event_received": "render_event_received" in stages
        or "render token=" in str(surf.get("repro_console") or ""),
        "timer_armed": "timer_armed" in stages
        or armed_at is not None
        or "render token=" in str(surf.get("repro_console") or ""),
        "browser_deadline_crossed": "browser_deadline_crossed" in stages
        or "component_value_sent" in stages,
        "setComponentValue_once": setcomp_n <= 1 and ("component_value_sent" in stages or setcomp_n == 1),
        "parent_receipt": bool(parent_msgs),
        "python_callback": cb >= 1,
        "token_matches_cell": (
            not parent_msgs
            or all(str(m.get("value_preview") or "").startswith(f"WIRING_{cell}") for m in parent_msgs)
        ),
    }

    invalid_reasons: list[str] = []
    if not iso_pre.get("isolation_ok") or not iso_post.get("isolation_ok"):
        invalid_reasons.append("extra_or_missing_component_iframe")
    if not chain_req["timer_armed"]:
        invalid_reasons.append("timer_never_armed")
    if not chain_req["browser_deadline_crossed"]:
        invalid_reasons.append("zero_crossing_never")
    if parent_msgs and not chain_req["token_matches_cell"]:
        invalid_reasons.append("wrong_token")
    if setcomp_n != 1 and chain_req["browser_deadline_crossed"]:
        invalid_reasons.append(f"setComponentValue_count_{setcomp_n}")

    if invalid_reasons:
        outcome = "INVALID"
    elif cb >= 1 and chain_req["browser_deadline_crossed"]:
        outcome = "PASS"
    elif cb >= 1:
        outcome = "PASS"
    else:
        outcome = "VALID FAIL"

    return {
        "outcome": outcome,
        "invalid_reasons": invalid_reasons,
        "cell": cell,
        "fresh_widget_key": widget_key,
        "expected_token": expected_token or probe.get("expected_token") or meta.get("expire_token"),
        "default": None,
        "component_return": meta.get("component_return"),
        "frontend": FRONTEND[cell],
        "python_declaration": DECL[cell],
        "isolation_pre": iso_pre,
        "isolation_post": iso_post,
        "isolation_confounded": iso_post.get("isolation_confounded"),
        "chain_requirements": chain_req,
        "client_stages": sorted(stages),
        "immediate_parent_payload_keys": payload_keys,
        "widget_key_in_parent_payload": "widget_key" in payload_keys,
        "immediate_parent_messages": parent_msgs[-2:],
        "session_state_raw": session_raw,
        "callback_count": cb,
        "pass_python_callback": cb >= 1,
        "observation_s": round(time.time() - t0, 1),
    }


def interpret_results(cells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def ok(name: str) -> bool:
        return (cells.get(name) or {}).get("outcome") == "PASS"

    def valid(name: str) -> bool:
        return (cells.get(name) or {}).get("outcome") in ("PASS", "VALID FAIL")

    a1, b1, a2, b2 = ok("A1"), ok("B1"), ok("A2"), ok("B2")
    notes: list[str] = []
    layer = ""
    if not valid("A1") or cells.get("A1", {}).get("outcome") == "INVALID":
        layer = "harness_invalid"
        notes.append("A1 INVALID — synthetic harness or isolation invalid; do not change production.")
    elif b1 is False and a2 and valid("B1") and valid("A2"):
        layer = "production_frontend_message"
        notes.append("A1 PASS, B1 FAIL, A2 PASS → production frontend/message construction.")
    elif b1 and not a2:
        layer = "production_micro_wrapper"
        notes.append("A1 PASS, B1 PASS, A2 FAIL → micro-isolation wrapper.")
    elif b1 and a2 and not b2:
        layer = "frontend_wrapper_interaction"
        notes.append("A1 PASS, B1 PASS, A2 PASS, B2 FAIL → combination failure.")
    elif a1 and b1 and a2 and b2:
        layer = "persistent_wake_surround"
        notes.append("All PASS → defect is persistent-wake state / historical key / ownership.")
    elif not b1 and valid("B1"):
        layer = "production_frontend_message"
        notes.append("B1 VALID FAIL with A1 PASS pattern → production frontend path.")
    return {
        "A1": cells.get("A1", {}).get("outcome"),
        "B1": cells.get("B1", {}).get("outcome"),
        "A2": cells.get("A2", {}).get("outcome"),
        "B2": cells.get("B2", {}).get("outcome"),
        "first_differing_layer": layer,
        "notes": notes,
    }


def run_cell(browser, *, cell: str, preflight: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    key = f"solo_wiring_{cell.lower()}_{uuid.uuid4().hex[:10]}"
    url = cell_url(cell, key)
    ctx = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
    page = ctx.new_page()
    try:
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(14000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
        page.wait_for_timeout(8000)

        sha = scrape_deploy_build(page) or str(preflight.get("cloud_sha") or "")
        if not str(sha).strip():
            try:
                from run_solo_clean_verification import scrape_live_sha

                sha = scrape_live_sha(page) or sha
            except ImportError:
                pass
        sha_short = str(sha).lower()[:7]
        if sha_short != _required_cloud_sha():
            return {
                "outcome": "INVALID",
                "cell": cell,
                "reason": "cloud_sha_mismatch",
                "cloud_sha": sha_short,
                "required": _required_cloud_sha(),
            }

        probe0 = scrape_matrix_probe(page)
        expected = str(probe0.get("expected_token") or "")
        if not expected and isinstance(probe0.get("decoded"), dict):
            meta = (probe0.get("decoded") or {}).get("meta") or {}
            expected = str(meta.get("expire_token") or "")

        for _ in range(12):
            if expected and not probe0.get("missing"):
                break
            page.wait_for_timeout(2000)
            probe0 = scrape_matrix_probe(page)
            expected = str(probe0.get("expected_token") or expected)

        page.wait_for_timeout(3000)
        for _ in range(8):
            iso = assess_isolation(page, cell=cell)
            if iso.get("isolation_ok"):
                break
            page.wait_for_timeout(2000)

        if probe0.get("missing"):
            return {
                "outcome": "INVALID",
                "cell": cell,
                "reason": "matrix_probe_not_mounted",
                "fresh_widget_key": key,
            }

        result = wait_synthetic_expire(page, cell=cell, widget_key=key, expected_token=expected)
        result["fresh_widget_key"] = key
        result["cloud_sha"] = sha_short
        result["synthetic"] = True
        result["draft_start_success"] = None
        return result
    finally:
        ctx.close()


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    req = _required_cloud_sha()
    summary: dict[str, Any] = {
        "mode": "synthetic",
        "required_cloud_sha": req,
        "build_label": f"baseball-dev-{req}",
        "cells": {},
        "started_at": time.time(),
    }

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        for cell in CELLS:
            summary["cells"][cell] = run_cell(browser, cell=cell, preflight=pre)
            time.sleep(2)
        browser.close()

    summary["interpretation"] = interpret_results(summary["cells"])
    summary["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
