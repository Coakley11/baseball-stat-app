"""Run 2×2 component delivery matrix on Streamlit Cloud (diagnostic-only)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = os.environ.get(
    "SOLO_ISOLATION_BASE_URL",
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app",
)
OUT = ROOT / "data" / "solo_delivery_matrix_2x2.json"
REQUIRED_CYCLES = 4
TIMEOUT_S = 150

MATRIX_CELLS = (
    {
        "cell": 1,
        "label": "app_shell_minimal_wake_repro",
        "component": "minimal_wake_repro",
        "needs_draft_start": False,
        "url": f"{BASE.rstrip('/')}/?solo_delivery_diag=1&solo_delivery_matrix=1",
    },
    {
        "cell": 2,
        "label": "app_shell_solo_countdown_wake",
        "component": "solo_countdown_wake",
        "needs_draft_start": False,
        "url": f"{BASE.rstrip('/')}/?solo_delivery_diag=1&solo_delivery_matrix=2",
    },
    {
        "cell": 3,
        "label": "solo_route_minimal_wake_repro",
        "component": "minimal_wake_repro",
        "needs_draft_start": False,
        "url": (
            f"{BASE.rstrip('/')}/?active_page=Live%20Draft%20Room"
            "&solo_delivery_diag=1&solo_delivery_matrix=3"
        ),
    },
    {
        "cell": 4,
        "label": "solo_route_solo_countdown_wake",
        "component": "solo_countdown_wake",
        "needs_draft_start": False,
        "url": (
            f"{BASE.rstrip('/')}/?active_page=Live%20Draft%20Room"
            "&solo_delivery_diag=1&solo_delivery_matrix=4"
        ),
    },
)

DELIVERY_STAGES = [
    "component_declaration_loaded",
    "browser_deadline_crossed",
    "setComponentValue_called",
    "component_value_sent",
    "websocket_widget_value_frame",
    "session_state_raw_received",
    "on_change_callback_entry",
    "component_return_value_received",
]


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
          const out = { matrix: null, repro_client: null, solo_client: null, delivery: null };
          for (const root of roots()) {
            const m = root.querySelector('#solo-matrix-diag');
            if (m) {
              out.matrix = {
                cell: m.getAttribute('data-matrix-cell') || '',
                passed: m.getAttribute('data-passed') || '',
                callbacks: parseInt(m.getAttribute('data-callbacks') || '0', 10),
                component_name: m.getAttribute('data-component-name') || '',
                key: m.getAttribute('data-key') || '',
                token: m.getAttribute('data-token') || '',
                stages: m.getAttribute('data-stages') || '',
                rerun: m.getAttribute('data-rerun') || '',
                json: m.getAttribute('data-json') || '',
              };
            }
            const caseA = root.querySelector('#solo-case-a-diag');
            if (caseA && !out.matrix) {
              out.matrix = {
                cell: '1',
                passed: caseA.getAttribute('data-passed') || '',
                callbacks: parseInt(caseA.getAttribute('data-callbacks') || '0', 10),
                component_name: caseA.getAttribute('data-component-name') || '',
                key: caseA.getAttribute('data-key') || '',
                token: caseA.getAttribute('data-token') || '',
                stages: caseA.getAttribute('data-stages') || '',
                rerun: caseA.getAttribute('data-rerun') || '',
                json: caseA.getAttribute('data-json') || '',
              };
            }
            const repro = root.querySelector('#repro-client');
            if (repro) {
              out.repro_client = {
                last: repro.getAttribute('data-last') || '',
                chain: repro.getAttribute('data-chain') || '',
              };
            }
            const solo = root.querySelector('#solo-expire-client');
            if (solo) {
              out.solo_client = {
                last: solo.getAttribute('data-last') || '',
                chain: solo.getAttribute('data-chain') || '',
                token: solo.getAttribute('data-token') || '',
              };
            }
            const delivery = root.querySelector('#solo-delivery-diag');
            if (delivery) {
              out.delivery = {
                stages: delivery.getAttribute('data-stages') || '',
                on_change: delivery.getAttribute('data-on-change') || '',
              };
            }
          }
          return out;
        }"""
    )


def _stages_set(chain: str) -> set[str]:
    return {p for p in str(chain or "").split("|") if p}


def _count_stage(chain: str, stage: str) -> int:
    return str(chain or "").count(stage)


def _widget_ids_from_ws(ws_frames: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        for match in re.finditer(r"\$\$ID-([a-f0-9-]+)-([^\\\"'\\s]+)", snippet):
            ids.append(f"$$ID-{match.group(1)}-{match.group(2)}")
    return ids


def _tokens_from_ws(ws_frames: list[dict[str, Any]]) -> list[str]:
    tokens: list[str] = []
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        for match in re.finditer(r"repro\|\d+\|[0-9.]+", snippet):
            tokens.append(match.group(0))
        for match in re.finditer(r"DIAG[A-Z]+\|\d+\|[0-9.]+", snippet):
            tokens.append(match.group(0))
        for match in re.finditer(r"[A-F0-9]{8}\|\d+\|[0-9.]+", snippet):
            tokens.append(match.group(0))
    return tokens


def finalize_cell(
    cell_spec: dict[str, Any],
    report: dict[str, Any],
    *,
    deploy_sha: str,
) -> dict[str, Any]:
    probe = report.get("final_probe") or {}
    matrix = probe.get("matrix") or {}
    repro = probe.get("repro_client") or {}
    solo = probe.get("solo_client") or {}
    delivery = probe.get("delivery") or {}
    python_chain = str(matrix.get("stages") or delivery.get("stages") or "")
    client_chain = str(repro.get("chain") or solo.get("chain") or "")
    client_chain_full = client_chain
    for alt in ("setComponentValue_called", "iframe_setComponentValue_called"):
        if alt in client_chain:
            pass
    ws_frames = list(report.get("ws_frames") or [])
    widget_ids = _widget_ids_from_ws(ws_frames)
    ws_tokens = _tokens_from_ws(ws_frames)

    callbacks = int(matrix.get("callbacks") or 0)
    json_blob = str(matrix.get("json") or "")
    dup = 0
    unique_tokens = len(ws_tokens)
    if json_blob:
        try:
            payload = json.loads(json_blob.replace("'", '"'))
            rows = payload.get("callbacks") or []
            toks = [str(r.get("token") or "") for r in rows if isinstance(r, dict)]
            unique_tokens = len(set(t for t in toks if t))
            dup = max(0, len(toks) - unique_tokens)
        except json.JSONDecodeError:
            pass

    python_stages = _stages_set(python_chain)
    client_stages = _stages_set(client_chain)
    hits = {
        "session_state_raw_received": python_chain.count("session_state_raw_received"),
        "on_change_callback_entry": python_chain.count("on_change_callback_entry"),
        "component_return_value_received": python_chain.count("component_return_value_received"),
        "browser_deadline_crossed": _count_stage(client_chain, "browser_deadline_crossed"),
        "setComponentValue_called": _count_stage(client_chain, "setComponentValue_called")
        + _count_stage(client_chain, "iframe_setComponentValue_called"),
        "component_value_sent": _count_stage(client_chain, "component_value_sent"),
        "websocket_widget_value_frame": len(ws_frames),
    }
    chain_hits = {
        "component_declaration_loaded": "component_declaration_loaded" in python_stages,
        "browser_deadline_crossed": "browser_deadline_crossed" in client_stages,
        "setComponentValue_called": "setComponentValue_called" in client_stages
        or "iframe_setComponentValue_called" in client_stages,
        "component_value_sent": "component_value_sent" in client_stages,
        "websocket_widget_value_frame": bool(ws_frames),
        "session_state_raw_received": "session_state_raw_received" in python_stages,
        "on_change_callback_entry": "on_change_callback_entry" in python_stages,
        "component_return_value_received": "component_return_value_received" in python_stages,
    }
    first_missing = next((s for s in DELIVERY_STAGES if not chain_hits.get(s)), "")

    mount_ids = [w for w in widget_ids if "minimal_wake" in w or "solo_countdown" in w or "diag" in w]
    send_ids = widget_ids[-4:] if widget_ids else []
    widget_id_at_send = send_ids[-1] if send_ids else ""
    mount_id_at_last_mount = mount_ids[-1] if mount_ids else ""
    widget_registered_at_send = (
        not mount_id_at_last_mount
        or not widget_id_at_send
        or mount_id_at_last_mount.split("-")[-1] in widget_id_at_send
    )

    cell_n = int(cell_spec["cell"])
    declared = bool(str(matrix.get("component_name") or "").strip())
    widget_key_recorded = bool(str(matrix.get("key") or "").strip())
    widget_id_recorded = bool(mount_ids) or bool(mount_id_at_last_mount)
    if cell_n in (3, 4):
        valid = declared and widget_key_recorded and widget_id_recorded and bool(ws_tokens)
        invalid_reason = ""
        if not valid:
            if not declared:
                invalid_reason = "component_declaration_not_mounted"
            elif not widget_key_recorded:
                invalid_reason = "widget_key_not_recorded"
            elif not widget_id_recorded:
                invalid_reason = "streamlit_widget_id_not_recorded"
            elif not ws_tokens:
                invalid_reason = "websocket_token_frames_missing"
            else:
                invalid_reason = "matrix_probe_incomplete"
    else:
        valid = declared or bool(matrix.get("stages"))
        invalid_reason = "" if valid else "matrix_probe_not_mounted"

    passed = (matrix.get("passed") in ("1", "true") or callbacks >= REQUIRED_CYCLES) and (
        hits["session_state_raw_received"] >= REQUIRED_CYCLES
        and hits["on_change_callback_entry"] >= REQUIRED_CYCLES
    )
    if valid and not passed and cell_n in (3, 4):
        if hits["session_state_raw_received"] < REQUIRED_CYCLES:
            first_missing = first_missing or "session_state_raw_received"
        elif hits["on_change_callback_entry"] < REQUIRED_CYCLES:
            first_missing = first_missing or "on_change_callback_entry"
        elif hits["setComponentValue_called"] < REQUIRED_CYCLES:
            first_missing = first_missing or "setComponentValue_called"
        elif hits["browser_deadline_crossed"] < REQUIRED_CYCLES:
            first_missing = first_missing or "browser_deadline_crossed"

    verdict = "pass" if passed and valid else ("fail" if valid else "invalid")

    return {
        "cell": cell_spec["cell"],
        "label": cell_spec["label"],
        "url": cell_spec["url"],
        "deploy_sha": deploy_sha,
        "verdict": verdict,
        "valid_case": valid,
        "passed_4_of_4": passed and callbacks >= REQUIRED_CYCLES,
        "callbacks_received": callbacks,
        "component_name": matrix.get("component_name") or cell_spec["component"],
        "frontend_bundle": cell_spec["component"],
        "widget_key": matrix.get("key") or "",
        "streamlit_widget_ids_seen": widget_ids[-12:],
        "widget_id_at_send": widget_id_at_send,
        "widget_id_at_last_mount": mount_id_at_last_mount,
        "widget_registered_at_send": widget_registered_at_send,
        "token_sample": matrix.get("token") or (ws_tokens[-1] if ws_tokens else ""),
        "mount_remount_client": _count_stage(client_chain_full, "iframe_remount"),
        "rerun_count": int(matrix.get("rerun") or 0),
        "hits": hits,
        "chain_hits": chain_hits,
        "duplicate_token_count": dup,
        "first_missing_stage": first_missing if verdict in ("fail", "invalid") else "",
        "invalid_reason": invalid_reason if verdict == "invalid" else "",
        "ws_token_samples": ws_tokens[-6:],
        "draft_start": report.get("draft_start"),
    }


def run_cell(cell_spec: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from run_solo_clean_verification import scrape_live_sha
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {"started_at": time.time(), "samples": []}
    url = cell_spec["url"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)

        if cell_spec["needs_draft_start"]:
            draft_meta = execute_solo_draft_start_workflow(page, url, navigate=True)
            report["draft_start"] = draft_meta
            if not draft_meta.get("start_success"):
                report["final_probe"] = scrape_matrix_probe(page)
                report["deploy_sha"] = scrape_live_sha(page)
                report["ws_frames"] = ws_frames[-50:]
                browser.close()
                return finalize_cell(cell_spec, report, deploy_sha=report.get("deploy_sha") or "")
            page.wait_for_timeout(3000)
        else:
            goto_and_wake(page, url, timeout_s=240)
            page.wait_for_timeout(5000)

        deadline = time.time() + TIMEOUT_S
        best_cb = 0
        while time.time() < deadline:
            snap = scrape_matrix_probe(page)
            snap["elapsed_s"] = round(time.time() - float(report["started_at"]), 2)
            snap["ws_count"] = len(ws_frames)
            cb = int((snap.get("matrix") or {}).get("callbacks") or 0)
            best_cb = max(best_cb, cb)
            if not report["samples"] or int((report["samples"][-1].get("matrix") or {}).get("callbacks") or 0) != cb:
                report["samples"].append(snap)
            if cb >= REQUIRED_CYCLES and (snap.get("matrix") or {}).get("passed") in ("1", "true"):
                break
            page.wait_for_timeout(1000)

        report["final_probe"] = scrape_matrix_probe(page)
        report["deploy_sha"] = scrape_live_sha(page)
        report["ws_frames"] = ws_frames[-60:]
        report["best_callbacks"] = best_cb
        browser.close()

    return finalize_cell(cell_spec, report, deploy_sha=str(report.get("deploy_sha") or ""))


def decision_from_matrix(cells: dict[str, Any]) -> tuple[str, str]:
    def v(n: int) -> str:
        return str((cells.get(str(n)) or {}).get("verdict") or "")

    c1, c2, c3, c4 = v(1), v(2), v(3), v(4)
    if c1 == "pass" and c2 != "pass":
        return (
            "solo_countdown_wake declaration/frontend",
            "App-shell minimal passes but app-shell solo_countdown_wake fails — "
            "inspect solo_countdown_wake component declaration and frontend bundle.",
        )
    if c3 == "invalid" or c4 == "invalid":
        return (
            "inconclusive",
            "Solo-route matrix cells were invalid (harness or deploy) — re-run after "
            "early-route matrix mount is live; do not infer route lifecycle yet.",
        )
    if c1 == "pass" and c2 == "pass" and c3 != "pass" and c4 != "pass":
        return (
            "solo_route_lifecycle",
            "Both app-shell cells pass; both Solo-route cells fail — "
            "inspect Solo route rerun, fragment, or script-run lifecycle.",
        )
    if c3 == "pass" and c4 != "pass":
        return (
            "solo_countdown_wake on route",
            "Solo-route minimal passes but Solo-route solo_countdown_wake fails — "
            "defect is in solo_countdown_wake, not the route shell.",
        )
    if c3 == "pass" and c4 == "pass":
        return (
            "production_placement",
            "Simplified Solo-route mounts pass — later production fragment/placement "
            "likely invalidates the widget instance at expiration.",
        )
    return ("inconclusive", "Matrix mixed or invalid cells — inspect per-cell first_missing_stage.")


def main() -> int:
    only = {x.strip() for x in os.environ.get("SOLO_MATRIX_ONLY", "").split(",") if x.strip()}
    deploy_sha = ""
    results: dict[str, Any] = {"started_at": time.time(), "cells": {}}
    for spec in MATRIX_CELLS:
        if only and str(spec["cell"]) not in only:
            continue
        print(f"MATRIX CELL {spec['cell']}", flush=True)
        row = run_cell(spec)
        results["cells"][str(spec["cell"])] = row
        if row.get("deploy_sha"):
            deploy_sha = row["deploy_sha"]
    results["deploy_sha"] = deploy_sha
    decision, fix = decision_from_matrix(results["cells"])
    results["decision"] = decision
    results["smallest_fix"] = fix
    results["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "deploy_sha": deploy_sha, "decision": decision}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
