"""Authenticated vs anonymous Solo A0 with paired run-N → run-N+1 transition forensics."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "solo_auth_anon_paired_transition.json"

from solo_diag_artifact_sanitize import boundary_from_a0, sanitize_obj  # noqa: E402
from run_solo_key_ownership_compare import resolve_storage_state  # noqa: E402


def _classify_scenario(*, authenticated: bool, a0: dict[str, Any], login: dict[str, Any]) -> dict[str, Any]:
    if authenticated:
        if not login.get("signed_in_after"):
            return {
                "harness_valid": False,
                "verdict": "INVALID",
                "reason": "authenticated_session_not_proven_after_storage_restore",
            }
        if not a0.get("session_continuity_ok", True):
            return {
                "harness_valid": False,
                "verdict": "INVALID",
                "reason": "streamlit_session_or_navigation_discontinuity",
            }
    room_loss = bool(a0.get("python_truly_lost_room"))
    return {
        "harness_valid": True,
        "verdict": "ROOM_LOST" if room_loss else "ROOM_RETAINED",
        "reason": a0.get("reason") or "",
        "python_truly_lost_room": room_loss,
    }


def _interpret_comparison(*, anon: dict[str, Any], auth: dict[str, Any]) -> dict[str, Any]:
    auth_skipped = bool(auth.get("skipped_run"))
    anon_cls = anon.get("classification") or {}
    auth_cls = auth.get("classification") or {}

    anon_loss = bool(anon_cls.get("python_truly_lost_room"))
    auth_loss = None if auth_skipped else bool(auth_cls.get("python_truly_lost_room"))
    auth_invalid = not auth_skipped and not auth_cls.get("harness_valid", True)

    anon_pt = anon.get("boundary") or {}
    auth_pt = auth.get("boundary") or {}
    anon_ka = anon_pt.get("key_analysis") or {}
    auth_ka = auth_pt.get("key_analysis") or {}

    conclusion = "inconclusive"
    detail = ""
    if auth_skipped:
        conclusion = "auth_harness_missing"
        detail = (
            "Run scripts/ensure_playwright_daniel_storage_manual.py for headed manual sign-in "
            "(no password in repo or logs)."
        )
    elif auth_invalid:
        conclusion = "auth_run_invalid"
        detail = str(auth_cls.get("reason") or "Authenticated run could not prove continuity.")
    elif anon_loss and auth_loss is False:
        conclusion = "harness_or_auth_state_problem"
        detail = (
            "Anonymous loses room; authenticated retains — fix anonymous/harness auth restoration "
            "and validate the signed-in product path before room architecture changes."
        )
    elif anon_loss and auth_loss:
        if anon_ka.get("only_live_draft_room_runtime_lost") and auth_ka.get("only_live_draft_room_runtime_lost"):
            conclusion = "genuine_runtime_lifecycle_defect"
            detail = "Both lose only top-level live_draft_room at run boundary — production lifecycle defect."
        elif anon_ka.get("broad_session_replacement_suspected") or auth_ka.get(
            "broad_session_replacement_suspected"
        ):
            conclusion = "broad_session_reset"
            detail = "Multiple non-widget keys changed — session replacement, not a rename fix."
        else:
            conclusion = "genuine_runtime_lifecycle_defect"
            detail = "Both lose room at boundary — inspect ultra_early vs script_beginning."
    elif not anon_loss and not auth_loss:
        conclusion = "prior_path_artifact"
        detail = "Both preserve room on this build — reproduce prior diagnostic path before production changes."
    elif anon_loss != auth_loss:
        conclusion = "auth_anon_divergence"
        detail = f"anonymous_room_loss={anon_loss}, authenticated_room_loss={auth_loss}"

    return {
        "conclusion": conclusion,
        "detail": detail,
        "anonymous_room_loss": anon_loss,
        "authenticated_room_loss": auth_loss,
        "auth_skipped": auth_skipped,
        "auth_invalid": auth_invalid,
    }


def _ws_continuity(ws_frames: list[dict[str, Any]], baseline: int) -> dict[str, Any]:
    new_frames = ws_frames[baseline:]
    closes = sum(1 for f in new_frames if f.get("kind") == "close")
    opens = sum(1 for f in new_frames if f.get("kind") == "open")
    return {
        "ws_frames_observed": len(new_frames),
        "ws_open_events": opens,
        "ws_close_events": closes,
        "ws_discontinuity_suspected": closes >= 1 and opens >= 1,
    }


def run_scenario(*, authenticated: bool) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright
    from run_solo_bridge_transition_a0_only import run_a0
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

    ws_frames: list[dict[str, Any]] = []
    storage = resolve_storage_state() if authenticated else None
    meta: dict[str, Any] = {"authenticated_requested": authenticated}
    if authenticated and not storage:
        return {
            "skipped_run": True,
            "login": {
                "ok": False,
                "reason": "No Playwright storage — use ensure_playwright_daniel_storage_manual.py",
            },
        }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        if storage:
            context = browser.new_context(viewport={"width": 1440, "height": 1400}, storage_state=str(storage))
            meta["storage_loaded"] = True
        else:
            context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        ws_baseline = len(ws_frames)
        install_ws_and_postmessage_hooks(page, ws_frames)
        a0 = run_a0(page, ws_frames)
        meta["ws"] = _ws_continuity(ws_frames, ws_baseline)
        if authenticated:
            meta["signed_in_after"] = bool(
                page.evaluate("() => /Signed in as/i.test(document.body ? document.body.innerText : '')")
            )
            meta["workspace_hint"] = str(
                page.evaluate(
                    """() => {
                      const t = document.body ? document.body.innerText : '';
                      const ws = t.match(/Workspace[:\\s]+([A-Za-z0-9_-]+)/i);
                      return ws ? ws[1] : '';
                    }"""
                )
                or ""
            ).strip()[:40]
        context.close()
        browser.close()
    boundary = boundary_from_a0(a0)
    slim_a0 = {
        k: a0.get(k)
        for k in (
            "control",
            "deploy_sha",
            "verdict",
            "reason",
            "python_truly_lost_room",
            "session_continuity_ok",
            "streamlit_session_ids_seen",
            "latched_room_id",
            "paired_transition_analysis",
        )
    }
    slim_a0["paired_transition"] = a0.get("paired_transition")
    slim_a0["key_ownership"] = a0.get("key_ownership")
    return {
        "login": meta,
        "a0": slim_a0,
        "boundary": boundary,
        "classification": _classify_scenario(authenticated=authenticated, a0=a0, login=meta),
    }


def main() -> int:
    from run_solo_clean_verification import scrape_live_sha
    from playwright.sync_api import sync_playwright

    deploy: dict[str, Any] = {"expected_from_deploy_commit": ""}
    try:
        line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
        deploy["expected_from_deploy_commit"] = line.split("#", 1)[0].strip()
    except Exception:
        pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        from cloud_streamlit_wake import goto_and_wake

        goto_and_wake(
            page,
            "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/?active_page=Live%20Draft%20Room",
            timeout_s=180,
        )
        deploy["runtime_sha_live"] = scrape_live_sha(page)
        browser.close()

    report: dict[str, Any] = {
        "started_at": time.time(),
        "deploy_probe": deploy,
        "anonymous": run_scenario(authenticated=False),
        "authenticated": run_scenario(authenticated=True),
    }
    report["comparison"] = _interpret_comparison(
        anon=report["anonymous"],
        auth=report["authenticated"],
    )
    report["finished_at"] = time.time()
    safe = sanitize_obj(report)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(safe, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "artifact": str(OUT),
                "runtime_sha_live": deploy.get("runtime_sha_live"),
                "expected_deploy_commit": deploy.get("expected_from_deploy_commit"),
                "comparison": report["comparison"],
                "anonymous_boundary": report["anonymous"].get("boundary"),
                "authenticated_boundary": report["authenticated"].get("boundary"),
                "anonymous_classification": report["anonymous"].get("classification"),
                "authenticated_classification": report["authenticated"].get("classification"),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
