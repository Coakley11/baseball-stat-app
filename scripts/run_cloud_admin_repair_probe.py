#!/usr/bin/env python3
"""Trigger cloud admin draft archive repair via Streamlit query param + Playwright."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASEBALL_URL = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
LEAGUE_ID = "league:0bcf703881121de10c2dd439"
EXPECTED_DEPLOY = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0].split()[0]


def _extract_trace_json(body: str) -> dict[str, Any] | None:
    """Pull repair trace JSON from Streamlit code block."""
    marker = '"repair_id": "admin_draft_archive_repair::'
    idx = body.find(marker)
    if idx < 0:
        return None
    start = body.rfind("{", 0, idx)
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(body)):
        ch = body[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = body[start : i + 1]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    return None
    return None


def _probe_deploy(timeout_s: float = 180.0) -> bool:
    import requests

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = requests.get(BASEBALL_URL.rstrip("/") + "/?embed=true", timeout=30)
            if EXPECTED_DEPLOY in resp.text:
                return True
        except Exception:
            pass
        time.sleep(15)
    return False


def _run_repair(mode: str) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    token = LEAGUE_ID
    if mode == "dry":
        token = f"{LEAGUE_ID}:dry"
    elif mode == "live":
        token = f"{LEAGUE_ID}:force"

    url = f"{BASEBALL_URL.rstrip('/')}/?admin_draft_archive_repair={quote(token, safe=':')}"
    row: dict[str, Any] = {"mode": mode, "url": url, "ok": False}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(45000)
            body = page.inner_text("body")
            row["has_repair_banner"] = "Admin draft archive repair" in body
            row["banner_ok"] = "Admin draft archive repair — OK" in body
            row["banner_failed"] = "FAILED" in body and "Admin draft archive repair" in body
            trace = _extract_trace_json(body)
            if trace is None:
                # Fallback: grab pre/code text
                try:
                    code_text = page.locator("code").first.inner_text(timeout=5000)
                    trace = json.loads(code_text)
                except Exception as exc:
                    row["parse_error"] = str(exc)
            row["trace"] = trace
            row["ok"] = bool(trace and trace.get("ok"))
        except Exception as exc:
            row["error"] = str(exc)
        finally:
            browser.close()
    return row


def _summarize(trace: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {}
    out: dict[str, Any] = {
        "ok": trace.get("ok"),
        "shared_doc_found": trace.get("shared_doc_found"),
        "shared_trade_proposal_count": trace.get("shared_trade_proposal_count"),
        "workspaces": [],
    }
    for ws in trace.get("workspace_results") or []:
        if not isinstance(ws, dict):
            continue
        rt = ws.get("repair_trace") or {}
        out["workspaces"].append(
            {
                "workspace_id": ws.get("workspace_id"),
                "cloud_write_ok": ws.get("cloud_write_ok"),
                "readback_verified": ws.get("readback_verified"),
                "draft_archive_count": (ws.get("readback") or {}).get("draft_archive_count"),
                "trade_proposals_after": rt.get("trade_proposals_after"),
                "errors": ws.get("errors") or [],
            }
        )
    return out


def main() -> int:
    print(f"expected_deploy={EXPECTED_DEPLOY}")
    print("Waiting for deploy marker on live app (up to 3 min)...")
    if not _probe_deploy(timeout_s=180):
        print("WARN: deploy marker not confirmed in HTML; continuing anyway.")

    print("\n=== DRY RUN ===")
    dry = _run_repair("dry")
    print(json.dumps(_summarize(dry.get("trace")), indent=2, default=str))
    dry_trace = dry.get("trace") if isinstance(dry.get("trace"), dict) else {}
    if not dry_trace.get("shared_doc_found"):
        print("FAIL: dry-run shared_doc_found != true", file=sys.stderr)
        print(json.dumps(dry, indent=2, default=str))
        return 2

    print("\n=== LIVE REPAIR ===")
    live = _run_repair("live")
    print(json.dumps(live.get("trace"), indent=2, default=str))
    summary = _summarize(live.get("trace"))
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2, default=str))

    failed = False
    trace = live.get("trace") if isinstance(live.get("trace"), dict) else {}
    if not trace.get("ok"):
        failed = True
    for ws in summary.get("workspaces") or []:
        if not ws.get("cloud_write_ok") or not ws.get("readback_verified"):
            failed = True
        if int(ws.get("draft_archive_count") or 0) != 1:
            failed = True
        if int(ws.get("trade_proposals_after") or 0) < 1:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
