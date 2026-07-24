"""Run solo_countdown_wake placement ladder P0–P5 on Streamlit Cloud."""

from __future__ import annotations

import json
import os
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
OUT = ROOT / "data" / "solo_countdown_placement_ladder.json"
REQUIRED_CYCLES = 4
TIMEOUT_S = 150
MIN_SHA = os.environ.get("SOLO_PLACEMENT_MIN_SHA", "d62baa8").lower()[:7]
# App builds that include placement-ladder hooks (2777b7c+ on dev).
LADDER_APP_SHAS = frozenset({"2777b7c", "2d5443f", "d384d92"})
PRE_LADDER_SHAS = frozenset({"d62baa8", "2db387a", "01dc6f0", "a9335e1"})

PLACEMENTS = (
    {
        "placement": "P0",
        "needs_draft_start": False,
        "url": (
            f"{BASE.rstrip('/')}/?active_page=Live%20Draft%20Room"
            "&solo_delivery_diag=1&solo_placement_ladder=P0"
        ),
    },
    {
        "placement": "P1",
        "needs_draft_start": False,
        "url": (
            f"{BASE.rstrip('/')}/?active_page=Live%20Draft%20Room"
            "&solo_delivery_diag=1&solo_placement_ladder=P1"
        ),
    },
    {
        "placement": "P2",
        "needs_draft_start": True,
        "url": (
            f"{BASE.rstrip('/')}/?active_page=Live%20Draft%20Room"
            "&solo_delivery_diag=1"
            "&solo_placement_ladder=P2"
            "&solo_component_diag=1"
            "&solo_diag_timer=10"
        ),
    },
    {
        "placement": "P3",
        "needs_draft_start": True,
        "url": (
            f"{BASE.rstrip('/')}/?active_page=Live%20Draft%20Room"
            "&solo_delivery_diag=1&solo_placement_ladder=P3"
        ),
    },
    {
        "placement": "P4",
        "needs_draft_start": True,
        "url": (
            f"{BASE.rstrip('/')}/?active_page=Live%20Draft%20Room"
            "&solo_delivery_diag=1&solo_placement_ladder=P4"
        ),
    },
    {
        "placement": "P5",
        "needs_draft_start": True,
        "url": (
            f"{BASE.rstrip('/')}/?active_page=Live%20Draft%20Room"
            "&solo_delivery_diag=1&solo_placement_ladder=P5"
        ),
    },
)


def scrape_placement_probe(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots() {
            const out = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) out.push(f.contentDocument); } catch (e) {}
            }
            return out.filter(Boolean);
          }
          const out = { ladder: null, repro_client: null, solo_client: null };
          for (const root of roots()) {
            const m = root.querySelector('#solo-placement-ladder-diag') || root.querySelector('#solo-matrix-diag');
            if (m) {
              const placement = m.getAttribute('data-placement') || '';
              const matrixCell = m.getAttribute('data-matrix-cell') || '';
              out.ladder = {
                placement: placement || (matrixCell === '4' ? 'P0' : matrixCell),
                passed: m.getAttribute('data-passed') || '',
                callbacks: parseInt(m.getAttribute('data-callbacks') || '0', 10),
                component_name: m.getAttribute('data-component-name') || '',
                key: m.getAttribute('data-key') || '',
                token: m.getAttribute('data-token') || '',
                stages: m.getAttribute('data-stages') || '',
                rerun: m.getAttribute('data-rerun') || '',
                mount_run: m.getAttribute('data-mount-run') || '',
                fragment: m.getAttribute('data-fragment') || '',
                json: m.getAttribute('data-json') || '',
              };
            }
            const repro = root.querySelector('#repro-client');
            if (repro) {
              out.repro_client = { chain: repro.getAttribute('data-chain') || '' };
            }
            const solo = root.querySelector('#solo-client');
            if (solo) {
              out.solo_client = { chain: solo.getAttribute('data-chain') || '' };
            }
          }
          return out;
        }"""
    )


def finalize_placement(
    spec: dict[str, Any],
    report: dict[str, Any],
    *,
    deploy_sha: str,
) -> dict[str, Any]:
    from run_solo_delivery_matrix_2x2 import (
        DELIVERY_STAGES,
        _count_stage,
        _python_delivery_complete,
        _stages_set,
        _tokens_from_ws,
        _widget_ids_from_ws,
        _ws_id_instrumentation_unverified,
    )

    probe = report.get("final_probe") or {}
    ladder = probe.get("ladder") or {}
    repro = probe.get("repro_client") or {}
    solo = probe.get("solo_client") or {}
    python_chain = str(ladder.get("stages") or "")
    client_chain = str(repro.get("chain") or solo.get("chain") or "")
    ws_frames = list(report.get("ws_frames") or [])
    widget_ids = _widget_ids_from_ws(ws_frames)
    ws_tokens = _tokens_from_ws(ws_frames)

    callbacks = int(ladder.get("callbacks") or 0)
    json_blob = str(ladder.get("json") or "")
    dup = 0
    if json_blob:
        try:
            payload = json.loads(json_blob.replace("'", '"'))
            rows = payload.get("callbacks") or []
            toks = [str(r.get("token") or "") for r in rows if isinstance(r, dict)]
            dup = max(0, len(toks) - len(set(t for t in toks if t)))
        except json.JSONDecodeError:
            pass

    python_stages = _stages_set(python_chain)
    client_stages = _stages_set(client_chain)
    hits = {
        "session_state_raw_received": python_chain.count("session_state_raw_received"),
        "on_change_callback_entry": python_chain.count("on_change_callback_entry"),
        "browser_deadline_crossed": _count_stage(client_chain, "browser_deadline_crossed"),
        "setComponentValue_called": _count_stage(client_chain, "setComponentValue_called")
        + _count_stage(client_chain, "iframe_setComponentValue_called"),
        "component_value_sent": _count_stage(client_chain, "component_value_sent"),
        "websocket_widget_value_frame": len(ws_frames),
    }
    chain_hits = {s: s.replace("_", " ") in python_chain or s in client_stages for s in DELIVERY_STAGES}
    first_missing = next(
        (
            s
            for s in DELIVERY_STAGES
            if s
            in (
                "session_state_raw_received",
                "on_change_callback_entry",
                "websocket_widget_value_frame",
            )
            and not (
                (s in python_stages)
                or (s == "websocket_widget_value_frame" and ws_frames)
            )
        ),
        "",
    )

    mount_ids = [w for w in widget_ids if "solo_countdown" in w or "diag_p" in w.lower()]
    send_ids = widget_ids[-4:] if widget_ids else []
    widget_id_at_send = send_ids[-1] if send_ids else ""
    mount_id_at_last_mount = mount_ids[-1] if mount_ids else ""
    python_ok, python_fail = _python_delivery_complete(
        callbacks=callbacks,
        hits=hits,
        dup=dup,
        json_blob=json_blob,
        component="solo_countdown_wake",
        ws_tokens=ws_tokens,
    )
    declared = bool(ladder.get("component_name"))
    valid = declared and bool(ladder.get("key")) and python_ok
    passed = valid and python_ok and (
        ladder.get("passed") in ("1", "true") or callbacks >= REQUIRED_CYCLES
    )
    verdict = "pass" if passed else ("fail" if valid else "invalid")
    if valid and not passed:
        first_missing = python_fail or first_missing

    return {
        "placement": spec["placement"],
        "url": spec["url"],
        "deploy_sha": deploy_sha,
        "verdict": verdict,
        "valid_case": valid,
        "callbacks_received": callbacks,
        "component_name": ladder.get("component_name") or "solo_countdown_wake",
        "frontend_bundle": "solo_countdown_wake",
        "widget_key": ladder.get("key") or "",
        "diagnostic_token": ladder.get("token") or "",
        "mount_script_run": ladder.get("mount_run") or "",
        "fragment_context": ladder.get("fragment") or "",
        "streamlit_widget_ids_seen": widget_ids[-12:],
        "widget_id_at_send": widget_id_at_send,
        "widget_id_at_last_mount": mount_id_at_last_mount,
        "widget_registered_at_send": bool(
            mount_id_at_last_mount
            and widget_id_at_send
            and mount_id_at_last_mount.split("-")[-1] in widget_id_at_send
        ),
        "instrumentation_unverified": _ws_id_instrumentation_unverified(
            mount_id_at_last_mount=mount_id_at_last_mount,
            widget_id_at_send=widget_id_at_send,
            mount_ids=mount_ids,
        ),
        "rerun_count": int(ladder.get("rerun") or 0),
        "mount_remount_client": _count_stage(client_chain, "iframe_remount"),
        "hits": hits,
        "duplicate_token_count": dup,
        "first_missing_stage": first_missing if verdict != "pass" else "",
        "ws_token_samples": ws_tokens[-8:],
        "draft_start": report.get("draft_start"),
    }


def run_placement(spec: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {"started_at": time.time()}
    url = spec["url"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)

        if spec["needs_draft_start"]:
            draft_meta = execute_solo_draft_start_workflow(page, url, navigate=True)
            report["draft_start"] = draft_meta
            if not draft_meta.get("start_success"):
                report["final_probe"] = scrape_placement_probe(page)
                report["deploy_sha"] = scrape_live_sha(page)
                report["ws_frames"] = ws_frames[-60:]
                browser.close()
                return finalize_placement(spec, report, deploy_sha=str(report.get("deploy_sha") or ""))
            page.wait_for_timeout(3000)
        else:
            goto_and_wake(page, url, timeout_s=240)
            page.wait_for_timeout(5000)

        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline:
            snap = scrape_placement_probe(page)
            cb = int((snap.get("ladder") or {}).get("callbacks") or 0)
            passed = (snap.get("ladder") or {}).get("passed") in ("1", "true")
            if cb >= REQUIRED_CYCLES and passed:
                break
            page.wait_for_timeout(1000)

        report["final_probe"] = scrape_placement_probe(page)
        report["deploy_sha"] = scrape_live_sha(page)
        report["ws_frames"] = ws_frames[-80:]
        browser.close()

    return finalize_placement(spec, report, deploy_sha=str(report.get("deploy_sha") or ""))


ONLY = {x.strip() for x in os.environ.get("SOLO_PLACEMENT_ONLY", "").split(",") if x.strip()}


def main() -> int:
    results: dict[str, Any] = {
        "started_at": time.time(),
        "min_sha": MIN_SHA,
        "placements": {},
        "first_passing": "",
        "first_failing": "",
        "first_boundary_note": "",
    }
    deploy_sha = ""
    for spec in PLACEMENTS:
        if ONLY and spec["placement"] not in ONLY:
            continue
        print(f"PLACEMENT {spec['placement']}", flush=True)
        row = run_placement(spec)
        results["placements"][spec["placement"]] = row
        if row.get("deploy_sha"):
            deploy_sha = row["deploy_sha"]
        live = str(row.get("deploy_sha") or "").lower()[:7]
        if live in PRE_LADDER_SHAS:
            row["verdict"] = "invalid"
            row["valid_case"] = False
            row["first_missing_stage"] = "pre_ladder_deploy"
        elif MIN_SHA in LADDER_APP_SHAS and live and live not in LADDER_APP_SHAS:
            row["verdict"] = "invalid"
            row["valid_case"] = False
            row["first_missing_stage"] = "ladder_hooks_not_deployed"
        if row.get("verdict") == "pass" and not results["first_passing"]:
            results["first_passing"] = spec["placement"]
        if row.get("verdict") in ("fail",) and row.get("valid_case") and not results["first_failing"]:
            results["first_failing"] = spec["placement"]
            results["first_boundary_note"] = (
                f"{spec['placement']} {row.get('verdict')}: {row.get('first_missing_stage') or ''}"
            )
            break
        if row.get("verdict") == "pass":
            results["last_passing"] = spec["placement"]
    results["deploy_sha"] = deploy_sha
    results["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "first_failing": results.get("first_failing")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
