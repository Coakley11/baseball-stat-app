"""Authenticated Cloud 2×2 component wiring matrix (fresh context/room/key per cell)."""

from __future__ import annotations

import base64
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
OUT = ROOT / "data" / "solo_wiring_matrix_2x2.json"
CELLS = ("A1", "B1", "A2", "B2")

FRONTEND_BY_CELL = {
    "A1": "minimal_wake_repro",
    "B1": "solo_countdown_wake",
    "A2": "minimal_wake_repro",
    "B2": "solo_countdown_wake",
}
DECL_BY_CELL = {
    "A1": "minimal_component_wake_repro_core.mount_single_for_transport",
    "B1": "solo_countdown_component.mount_solo_countdown_wake_direct",
    "A2": "minimal_frontend + micro_isolation_callback_wrapper",
    "B2": "solo_countdown_wake_micro_core.render_micro_isolation_once",
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
from run_production_stage1_authenticated import (  # noqa: E402
    ensure_fresh_setup_lobby,
    redact_url,
    validate_production_draft_start,
)
from run_production_solo_soak import (  # noqa: E402
    scrape_deploy_build,
    scrape_iframe_lifecycle,
    scrape_transport_boundary,
)
from solo_draft_start_harness import execute_solo_draft_start_workflow  # noqa: E402
from stage1_frame_transport_probe import (  # noqa: E402
    collect_frame_topology,
    install_immediate_parent_listeners,
    scrape_immediate_parent_messages,
)


def matrix_cell_url(cell: str, widget_key: str) -> str:
    params = {
        "active_page": "Live Draft Room",
        "solo_diag_timer": "10",
        "solo_transport_probe": "1",
        "solo_wiring_matrix": cell,
        "solo_wiring_key": widget_key,
    }
    return append_suite_sid_to_url(f"{BASE}/?{urlencode(params)}")


def scrape_wiring_matrix_probe(page) -> dict[str, Any]:
    raw = page.evaluate(
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
            if (b64) {
              try {
                decoded = JSON.parse(atob(b64));
              } catch (e) {
                decoded = { parse_error: String(e) };
              }
            }
            return {
              cell: el.getAttribute('data-cell') || '',
              key: el.getAttribute('data-key') || '',
              callbacks_attr: parseInt(el.getAttribute('data-callbacks') || '0', 10),
              decoded,
            };
          }
          return { missing: true };
        }"""
    )
    return raw if isinstance(raw, dict) else {}


def scrape_client_chains(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const out = { repro: null, solo: null };
          const iframes = document.querySelectorAll('iframe');
          for (let i = 0; i < iframes.length; i++) {
            try {
              const doc = iframes[i].contentDocument;
              if (!doc) continue;
              const repro = doc.querySelector('#repro-client');
              if (repro) {
                out.repro = {
                  iframe_index: i,
                  chain: repro.getAttribute('data-chain') || '',
                  last: repro.getAttribute('data-last') || '',
                  console: repro.getAttribute('data-console') || '',
                };
              }
              const solo = doc.querySelector('#solo-expire-client');
              if (solo) {
                out.solo = {
                  iframe_index: i,
                  chain: solo.getAttribute('data-chain') || '',
                  last: solo.getAttribute('data-last') || '',
                  token: solo.getAttribute('data-token') || '',
                  iframe_instance: solo.getAttribute('data-iframe-instance') || '',
                };
              }
            } catch (e) {}
          }
          return out;
        }"""
    )


def _parse_transport_before_postmessage(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in entries:
        if str(e.get("stage") or "") != "transport_before_postMessage":
            continue
        extra = str(e.get("extra") or "")
        try:
            parsed = json.loads(extra)
            if isinstance(parsed, dict):
                out.append(parsed)
        except json.JSONDecodeError:
            out.append({"raw_extra": extra[:500]})
    return out


def _iframe_entries(iframe_life: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for fr in iframe_life.get("frames") or []:
        if not isinstance(fr, dict):
            continue
        for block in fr.get("logs") or []:
            if isinstance(block, dict):
                entries.extend(block.get("entries") or [])
    return [e for e in entries if isinstance(e, dict)]


def _standard_streamlit_payload(msg: dict[str, Any]) -> bool:
    keys = set(msg.get("payload_key_names") or [])
    return bool(msg.get("is_streamlit_message")) and "type" in keys and "value" in keys


def wait_matrix_expire(page, *, cell: str, widget_key: str, timeout_s: float = 55.0) -> dict[str, Any]:
    t0 = time.time()
    install_immediate_parent_listeners(page)
    timer_armed_at: float | None = None
    observe_until = t0 + timeout_s

    while time.time() < observe_until:
        install_immediate_parent_listeners(page)
        chains = scrape_client_chains(page)
        chain = str((chains.get("solo") or chains.get("repro") or {}).get("chain") or "")
        if "timer_armed" in chain or "render token=" in chain:
            if timer_armed_at is None:
                timer_armed_at = time.time()
                observe_until = max(observe_until, timer_armed_at + 22.0)
        if "component_value_sent" in chain or "browser_deadline_crossed" in chain:
            page.wait_for_timeout(8000)
            break
        if timer_armed_at and time.time() >= timer_armed_at + 22:
            break
        page.wait_for_timeout(2000)

    probe = scrape_wiring_matrix_probe(page)
    decoded = probe.get("decoded") if isinstance(probe.get("decoded"), dict) else {}
    meta = decoded.get("meta") if isinstance(decoded.get("meta"), dict) else {}
    log_tail = decoded.get("log_tail") if isinstance(decoded.get("log_tail"), list) else []

    iframe_life = scrape_iframe_lifecycle(page)
    iframe_entries = _iframe_entries(iframe_life)
    setcomp_args = _parse_transport_before_postmessage(iframe_entries)
    chains = scrape_client_chains(page)
    immediate = scrape_immediate_parent_messages(page)
    transport = scrape_transport_boundary(page) or {}
    log_transport = list((transport.get("probe") or {}).get("log_tail") or [])

    matrix_callbacks = int(meta.get("callback_count") or probe.get("callbacks_attr") or 0)
    matrix_log_callbacks = sum(1 for r in log_tail if isinstance(r, dict) and r.get("stage") == "matrix_callback")

    expire_token = str(meta.get("expire_token") or "")
    parent_for_token = [
        m
        for m in immediate
        if isinstance(m, dict)
        and m.get("has_set_component_value")
        and (
            (expire_token and str(m.get("value_preview") or "") == expire_token[:120])
            or (widget_key and widget_key in str(m.get("value_preview") or ""))
        )
    ]
    if not parent_for_token and expire_token:
        parent_for_token = [
            m
            for m in immediate
            if isinstance(m, dict)
            and m.get("has_set_component_value")
            and str(m.get("value_preview") or "").split("|")[0]
            == expire_token.split("|")[0]
        ]
    parent_set = parent_for_token or [
        m for m in immediate if isinstance(m, dict) and m.get("has_set_component_value")
    ][-3:]

    first_parent = parent_set[-1] if parent_set else {}
    payload_keys = list(first_parent.get("payload_key_names") or [])

    repro_chain = str((chains.get("repro") or {}).get("chain") or "")
    solo_chain = str((chains.get("solo") or {}).get("chain") or "")
    client_chain = solo_chain or repro_chain
    merged = iframe_life.get("merged_stages") or []
    browser_deadline = "browser_deadline_crossed" in merged or "component_value_sent" in merged

    transport_matrix_hits = sum(
        1
        for r in log_transport
        if isinstance(r, dict)
        and (
            r.get("stage") == "matrix_callback"
            or (
                r.get("stage") == "python_run_entry"
                and str(r.get("phase") or "").startswith("wiring_matrix")
            )
        )
    )
    python_pass = (
        matrix_callbacks >= 1
        or matrix_log_callbacks >= 1
        or transport_matrix_hits >= 1
    )

    return {
        "cell": cell,
        "component_frontend": FRONTEND_BY_CELL.get(cell, ""),
        "python_declaration": DECL_BY_CELL.get(cell, ""),
        "fresh_widget_key": widget_key,
        "default": None,
        "expire_token": expire_token,
        "component_return": meta.get("component_return"),
        "session_state_value": meta.get("session_state_value"),
        "callback_function": "matrix_simple_callback (_simple_matrix_deliver)",
        "callback_count": max(matrix_callbacks, matrix_log_callbacks, transport_matrix_hits),
        "widget_id": "",
        "setComponentValue_args_from_iframe": setcomp_args,
        "immediate_parent_payload_keys": payload_keys,
        "immediate_parent_standard_streamlit_format": _standard_streamlit_payload(first_parent)
        if first_parent
        else None,
        "immediate_parent_has_widget_key_field": "widget_key" in payload_keys,
        "browser_deadline_crossed": browser_deadline,
        "setComponentValue_called": "setComponentValue" in client_chain
        or "iframe_setComponentValue_called" in client_chain
        or bool(setcomp_args),
        "parent_receipt": bool(parent_set),
        "iframe_merged_stages": iframe_life.get("merged_stages") or [],
        "client_chain": client_chain,
        "immediate_parent_messages": parent_set[-5:],
        "transport_log_tail": log_transport[-15:],
        "matrix_log_tail": log_tail[-10:],
        "frame_topology": collect_frame_topology(page),
        "pass_python_callback": python_pass,
        "observation_s": round(time.time() - t0, 1),
        "pass": python_pass and browser_deadline,
    }


def interpret_matrix(cells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def passed(name: str) -> bool:
        return bool((cells.get(name) or {}).get("pass_python_callback"))

    a1, b1, a2, b2 = passed("A1"), passed("B1"), passed("A2"), passed("B2")
    notes: list[str] = []
    first_diff = ""

    if not a1:
        notes.append("A1 baseline failed — environment or harness broken.")
        first_diff = "harness_or_cloud"
    elif b1 is False and a2:
        first_diff = "production_frontend_or_postmessage"
        notes.append("B1 fails, A2 passes → production frontend or Streamlit protocol message is defective.")
    elif b1 and not a2:
        first_diff = "production_python_micro_wrapper"
        notes.append("B1 passes, A2 fails → production micro-isolation Python wrapper/declaration is defective.")
    elif b1 and a2 and not b2:
        first_diff = "frontend_wrapper_interaction"
        notes.append("B1 and A2 pass, B2 fails → production frontend and wrapper interact incorrectly.")
    elif b1 and not b2:
        first_diff = "migrate_to_direct_declaration"
        notes.append("B1 passes, B2 fails → migrate production countdown to direct minimal declaration pattern.")
    elif not b1:
        first_diff = "production_frontend_line_compare"
        notes.append("B1 fails with fresh key + direct declaration → line-compare production frontend vs minimal_wake_repro.")
    elif a1 and b1 and a2 and b2:
        first_diff = "stale_key_or_delivery_state"
        notes.append("All four pass → historical stable production key or delivery/dedupe state is the defect.")

    return {
        "A1_pass": a1,
        "B1_pass": b1,
        "A2_pass": a2,
        "B2_pass": b2,
        "first_differing_layer": first_diff,
        "interpretation_notes": notes,
        "widget_key_in_parent_payload_is_frontend_only": (
            "Production solo_countdown_component frontend adds widget_key in sendMessage(); "
            "passive Playwright parent listeners do not mutate postMessage payloads."
        ),
    }


def run_one_cell(browser, *, cell: str, preflight: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    widget_key = f"solo_wiring_{cell.lower()}_{uuid.uuid4().hex[:10]}"
    url = matrix_cell_url(cell, widget_key)
    context = browser.new_context(
        storage_state=str(STORAGE_PATH),
        viewport={"width": 1440, "height": 1400},
    )
    page = context.new_page()
    try:
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(12000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(2500)
        except Exception:
            pass
        page.wait_for_timeout(8000)

        sha = scrape_deploy_build(page) or str(preflight.get("cloud_sha") or "")
        sha_short = str(sha).lower()[:7]
        req = _required_cloud_sha()
        if sha_short != req:
            return {
                "aborted": True,
                "cell": cell,
                "reason": "cloud_sha_mismatch",
                "cloud_sha": sha_short,
                "required": req,
            }

        cleanup = ensure_fresh_setup_lobby(page, max_wait_s=240)
        if not cleanup.get("ok"):
            return {"aborted": True, "cell": cell, "reason": "cleanup_failed", "cleanup": cleanup}

        prior = str(cleanup.get("detected_room_id") or "").strip().upper()
        draft = execute_solo_draft_start_workflow(page, url, navigate=False)
        start_val = validate_production_draft_start(page, draft, prior_room_id=prior)
        if not start_val.get("valid"):
            return {"aborted": True, "cell": cell, "reason": "draft_start_invalid", "validation": start_val}

        result = wait_matrix_expire(page, cell=cell, widget_key=widget_key)
        result["setup_url_redacted"] = redact_url(url)
        result["room_id"] = start_val.get("latched_room_id")
        result["cloud_sha"] = sha_short
        result["cleanup"] = cleanup
        return result
    finally:
        context.close()


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
        "started_at": time.time(),
        "required_cloud_sha": req,
        "build_label": f"baseball-dev-{req}",
        "cells": {},
    }

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        for cell in CELLS:
            block = run_one_cell(browser, cell=cell, preflight=pre)
            summary["cells"][cell] = block
            time.sleep(3)
        browser.close()

    summary["interpretation"] = interpret_matrix(summary["cells"])
    summary["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
