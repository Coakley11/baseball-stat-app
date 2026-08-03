"""Targeted pick-1 countdown mount check (harness only — no claim/pick/commit)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

OUT_JSON = ROOT / "data" / "pick1_mount_targeted_check.json"
OUT_SCREENSHOT = ROOT / "data" / "pick1_mount_targeted_screenshot.png"
RECONCILE = ROOT / "data" / "p8_core_reconcile_ce62d9b7.json"
SUMMARY = ROOT / "data" / "production_stage1_authenticated_summary.json"


def _scrape_iframe_connectivity(page) -> dict[str, Any]:
    try:
        return page.evaluate(
            """() => {
              const out = { iframes: [], any_connected: false, countdown_iframe: null };
              for (const f of document.querySelectorAll('iframe')) {
                let connected = false;
                let href = '';
                try {
                  connected = !!f.contentDocument && f.contentDocument.readyState === 'complete';
                  href = String(f.src || '').slice(0, 240);
                } catch (e) {
                  connected = false;
                }
                const row = { href, connected };
                out.iframes.push(row);
                if (/solo_countdown|countdown_wake/i.test(href)) {
                  out.countdown_iframe = row;
                }
                if (connected) out.any_connected = true;
              }
              return out;
            }"""
        )
    except Exception:
        return {"iframes": [], "any_connected": False}


def _try_continue_saved(page) -> dict[str, Any]:
    from run_production_solo_soak import click_btn

    clicked = click_btn(page, "Continue Saved Draft", wait_ms=3000) or click_btn(
        page, "Continue", wait_ms=2500
    )
    return {"continue_clicked": bool(clicked)}


def _load_artifact_ledger() -> list[dict[str, Any]]:
    if not SUMMARY.is_file():
        return []
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    exp = (summary.get("stage1a") or {}).get("expiration") or {}
    return list(exp.get("merged_server_ledger") or [])


def main() -> int:
    from playwright.sync_api import sync_playwright

    from replay_playwright_daniel_auth_preflight import run_preflight
    from run_production_stage1_authenticated import (
        production_url,
        resolve_required_cloud_sha,
        scrape_component_mount_diag,
        scrape_timer_fields,
    )
    from run_production_solo_soak import scrape_deploy_build, scrape_state
    from stage1_frame2_parent_boundary import scrape_stage1_ledger_all_frames
    from stage1_harness_observability import (
        classify_pick1_mount,
        decode_ledger_b64_padded,
        extract_pick1_post_commit_mount_observation,
        normalize_expire_token,
    )

    reconcile = json.loads(RECONCILE.read_text(encoding="utf-8")) if RECONCILE.is_file() else {}
    expected_room = str(reconcile.get("room_id") or os.environ.get("PICK1_MOUNT_ROOM") or "3BEEA6F2").upper()
    expected_token = str(
        reconcile.get("pick_1_token") or os.environ.get("PICK1_MOUNT_TOKEN") or "3BEEA6F2|1|1785728385.690"
    )
    expected_deadline = str(reconcile.get("pick_1_deadline") or "1785728385.6902428")
    app_run = str(reconcile.get("application_diagnostic_run_id") or "")
    required_sha = resolve_required_cloud_sha() or str(reconcile.get("cloud_sha") or "007c39a")

    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready

    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1

    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_replay_preflight_failed", "failure": pre.get("failure")}))
        return 1

    result: dict[str, Any] = {
        "harness_sha": os.environ.get("HARNESS_SHA") or "",
        "expected_room_id": expected_room,
        "expected_pick1_token": expected_token,
        "expected_pick1_deadline": expected_deadline,
        "authoritative_core_harness_run": reconcile.get("harness_run_id"),
        "mode": "targeted_mount_observe_only",
        "no_claim_pick_commit": True,
    }

    url = production_url()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        live_sha = scrape_deploy_build(page) or ""
        result["cloud_sha"] = live_sha[:7] if live_sha else ""
        result["cloud_build"] = live_sha
        if required_sha and result["cloud_sha"] and not str(result["cloud_sha"]).startswith(required_sha[:7]):
            result["cloud_sha_warning"] = "mismatch"

        continue_meta = _try_continue_saved(page)
        page.wait_for_timeout(5000)
        result["continue_saved_attempt"] = continue_meta

        state = scrape_state(page)
        timer = scrape_timer_fields(page)
        mount = scrape_component_mount_diag(page)
        iframe_info = _scrape_iframe_connectivity(page)
        mount["iframe_connected"] = bool(
            (iframe_info.get("countdown_iframe") or {}).get("connected") or iframe_info.get("any_connected")
        )

        live_ledger: list[dict[str, Any]] = []
        ledger_snap = scrape_stage1_ledger_all_frames(page)
        best = ledger_snap.get("best") or {}
        if best.get("b64"):
            decoded = decode_ledger_b64_padded(str(best.get("b64") or ""))
            live_ledger = list(decoded.get("rows") or [])

        artifact_ledger = _load_artifact_ledger()
        merged = live_ledger if len(live_ledger) >= len(artifact_ledger) else artifact_ledger
        result["ledger_source"] = "live_dom" if merged is live_ledger and live_ledger else "artifact_ce62d9b7"

        visible = timer.get("timer") or timer.get("ccTimer") or (timer.get("mount_diag") or {}).get("diag_remaining")
        observation = extract_pick1_post_commit_mount_observation(
            merged,
            expected_pick1_token=expected_token,
            run_id=app_run,
            room_id=expected_room,
            mount_diag=mount,
            lifecycle_token="",
            visible_countdown=visible,
        )
        live_context = {
            "room_id": state.get("room_id") or mount.get("draft_id") or "",
            "pick_index": mount.get("pick_index") or state.get("pick"),
            "room_status": "in_progress" if int(state.get("pause_draft_count") or 0) >= 1 else "",
            "deadline": mount.get("deadline") or mount.get("diag_deadline") or "",
        }
        if not live_context["room_id"]:
            lobby = page.evaluate(
                """() => {
                  const t = document.body.innerText || '';
                  const m = t.match(/Room ID\\s+([A-F0-9]+)/i);
                  return { room_id: m ? m[1] : '', has_pause: /Pause Draft/i.test(t) };
                }"""
            )
            if isinstance(lobby, dict):
                live_context["room_id"] = lobby.get("room_id") or ""
                if lobby.get("has_pause"):
                    live_context["room_status"] = "in_progress"

        classification = classify_pick1_mount(
            expected_pick1_token=expected_token,
            expected_room_id=expected_room,
            observation=observation,
            live_context=live_context,
        )
        try:
            page.screenshot(path=str(OUT_SCREENSHOT), full_page=True)
            result["screenshot_path"] = str(OUT_SCREENSHOT)
        except Exception as exc:
            result["screenshot_error"] = str(exc)[:200]

        result.update(
            {
                "declaration_token": normalize_expire_token(
                    (observation.get("countdown_declaration_post_pick1") or {}).get("expected_token")
                    or (observation.get("countdown_declaration_pre_pick1") or {}).get("expected_token")
                    or expected_token
                ),
                "component_widget_id": observation.get("component_widget_id") or mount.get("widget_key"),
                "iframe_connection": observation.get("iframe_connected"),
                "iframe_probe": iframe_info,
                "browser_mount_token": observation.get("browser_mount_token") or mount.get("expire_token"),
                "visible_countdown_result": visible,
                "live_context": live_context,
                "mount_diag": mount,
                "timer_fields": timer,
                "pick1_post_commit_mount_observation": observation,
                **classification,
            }
        )
        context.close()
        browser.close()

    try:
        import subprocess

        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
        result["harness_sha"] = sha
    except Exception:
        pass

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
