"""Anonymous vs authenticated Solo A0 with key-ownership forensics."""

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

OUT = ROOT / "data" / "solo_key_ownership_compare.json"

STORAGE_CANDIDATES = [
    ROOT / "data" / "playwright_daniel_auth.storage.json",
    Path.home() / ".cache" / "baseball-stat-app" / "playwright_daniel_auth.storage.json",
]


def resolve_storage_state() -> Path | None:
    env = os.environ.get("SOLO_AUTH_STORAGE_STATE", "").strip()
    if env and Path(env).is_file():
        return Path(env)
    for p in STORAGE_CANDIDATES:
        if p.is_file():
            return p
    return None


def _summarize_ownership(a0: dict[str, Any]) -> dict[str, Any]:
    ko = _decode(a0.get("key_ownership") or {})
    rows = ko.get("rows") if isinstance(ko, dict) else []
    if not isinstance(rows, list):
        rows = []
    widget_hit = ko.get("first_widget_registration") if isinstance(ko, dict) else None
    boundary = ko.get("run_boundary_loss") if isinstance(ko, dict) else None
    repo = ko.get("repo_widget_audit") if isinstance(ko, dict) else {}
    return {
        "widget_key_collision_detected": bool(widget_hit),
        "widget_exact_match_for_live_draft_room": bool(
            widget_hit and widget_hit.get("widget_exact_match_for_user_key")
        ),
        "first_widget_registration": widget_hit,
        "run_boundary_loss": boundary,
        "repo_widget_audit": repo,
        "ownership_row_count": len(rows),
        "ownership_tail": rows[-8:] if rows else [],
    }


def _decode(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    import base64

    from run_solo_bridge_transition_a0_only import _decode_b64_json

    if isinstance(raw, str):
        return _decode_b64_json(raw) or {}
    return {}


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
                "reason": (
                    "No Playwright storage state found. Run scripts/ensure_playwright_daniel_storage.py "
                    "or set SOLO_AUTH_STORAGE_STATE to an existing .storage.json file."
                ),
                "candidates": [str(p) for p in STORAGE_CANDIDATES],
            },
        }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        if storage:
            context = browser.new_context(viewport={"width": 1440, "height": 1400}, storage_state=str(storage))
            meta["storage_state"] = str(storage)
        else:
            context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        install_ws_and_postmessage_hooks(page, ws_frames)
        a0 = run_a0(page, ws_frames)
        context.close()
        browser.close()
    probe = a0.get("key_ownership")
    if probe is None:
        from run_solo_bridge_transition_a0_only import _decode_b64_json

        # filled below from final scrape if needed
        pass
    return {"login": meta, "a0": a0, "ownership_summary": _summarize_ownership(a0)}


def main() -> int:
    report: dict[str, Any] = {"started_at": time.time()}
    report["anonymous"] = run_scenario(authenticated=False)
    report["authenticated"] = run_scenario(authenticated=True)
    report["finished_at"] = time.time()
    anon = report["anonymous"].get("ownership_summary") or {}
    auth = report["authenticated"].get("ownership_summary") or {}
    report["comparison"] = {
        "anonymous_room_loss": report["anonymous"].get("a0", {}).get("python_truly_lost_room"),
        "authenticated_room_loss": (
            None
            if report["authenticated"].get("skipped_run")
            else report["authenticated"].get("a0", {}).get("python_truly_lost_room")
        ),
        "anonymous_widget_collision": anon.get("widget_key_collision_detected"),
        "authenticated_widget_collision": auth.get("widget_key_collision_detected"),
        "auth_skipped": bool(report["authenticated"].get("skipped_run")),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "comparison": report["comparison"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
