"""Read-only headed/headless verify: Start enabled + session/ledger identity binding (no Start click)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "playwright_auth_observability_readonly_verify.json"
EXPECTED_APP_SHA = (
    Path(__file__).resolve().parent.parent / "deploy_commit.txt"
).read_text(encoding="utf-8").splitlines()[0].split("#", 1)[0].strip()[:7]

_TRANSITION_PROBE_JS = """
() => {
  function snapFrom(root) {
    const el = root.getElementById('solo-stage1-auth-transition-snapshot');
    if (!el) return null;
    return {
      row_count: parseInt(el.getAttribute('data-row-count') || '0', 10) || 0,
      run_id: el.getAttribute('data-run-id') || '',
      b64_len: (el.getAttribute('data-b64') || '').length,
    };
  }
  for (const root of [document, ...Array.from(document.querySelectorAll('iframe')).map(f => {
    try { return f.contentDocument; } catch (e) { return null; }
  }).filter(Boolean)]) {
    const s = snapFrom(root);
    if (s) return s;
  }
  return null;
}
"""

_CHECKPOINT_PRESENCE_JS = """
() => {
  const ids = ['solo-stage1-current-auth-state', 'solo-stage1-auth-transition-snapshot'];
  const roots = [document, ...Array.from(document.querySelectorAll('iframe')).map(f => {
    try { return f.contentDocument; } catch (e) { return null; }
  }).filter(Boolean)];
  const out = {};
  for (const id of ids) {
    out[id] = roots.some(r => r.getElementById(id));
  }
  return out;
}
"""


def _capture_url(suite_sid: str) -> str:
    base = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
    return (
        f"{base}/?active_page=Live+Draft+Room"
        f"&solo_component_diag=1&solo_stage1_parent_boundary=1&suite_sid={suite_sid}"
    )


def run_verify(*, headed: bool | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake
    from playwright_auth_observability import gather_page_observability, probe_dom_current_auth_state
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready, load_suite_sid
    from queueui_audit_protocol import scrape_deploy_marker_from_page

    if headed is None:
        headed = os.environ.get("PLAYWRIGHT_HEADED", "").strip() in ("1", "true", "yes")

    result: dict = {
        "harness_ready": harness_ready(),
        "headed": headed,
        "failure": "",
        "pass": False,
    }
    if not harness_ready():
        result["failure"] = "harness_files_incomplete"
        return result

    suite_sid = load_suite_sid()
    result["suite_sid_prefix"] = suite_sid[:8] if suite_sid else ""
    url = _capture_url(suite_sid)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(28000)
        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        obs = gather_page_observability(page, harness_sid=suite_sid, strict_failure="streamlit_auth_incomplete")
        cp = obs.get("checkpoint") or {}
        fi = int(cp.get("start_frame_index") or 0)
        try:
            transition_snap = page.frames[fi].evaluate(_TRANSITION_PROBE_JS) if fi < len(page.frames) else None
        except Exception:
            transition_snap = None
        if not isinstance(transition_snap, dict):
            transition_snap = page.evaluate(_TRANSITION_PROBE_JS) or {}
        current_auth_dom = probe_dom_current_auth_state(page, frame_index=fi) or cp.get("current_auth_dom") or {}
        checkpoint_presence = page.evaluate(_CHECKPOINT_PRESENCE_JS)
        binding = obs.get("binding") or {}
        ss = obs.get("start_surface") or {}
        result.update(
            {
                "expected_app_sha": EXPECTED_APP_SHA,
                "application_diagnostic_sha": EXPECTED_APP_SHA,
                "harness_parser_sha": "e944c1a",
                "cloud_deploy_sha": deploy_sha or cp.get("deploy_sha"),
                "deploy_pin_match": str(deploy_sha or "")[:7] == EXPECTED_APP_SHA,
                "checkpoint_presence": checkpoint_presence,
                "auth_transition_snapshot": transition_snap,
                "page_url": ss.get("page_url"),
                "playwright_page_id": ss.get("playwright_page_id"),
                "start_frame_url": ss.get("frame_url"),
                "start_enabled": bool(cp.get("start_enabled")),
                "start_visible": bool(cp.get("start_visible")),
                "start_frame_index": cp.get("start_frame_index"),
                "streamlit_session_id": cp.get("streamlit_session_id"),
                "diagnostic_run_id": cp.get("diagnostic_run_id"),
                "diagnostic_query_flags": cp.get("diagnostic_query_flags"),
                "ledger_row_count": binding.get("ledger_row_count"),
                "auth_hydration_row_count": binding.get("auth_hydration_row_count"),
                "url_suite_sid_match": binding.get("url_suite_sid_match"),
                "ui_ledger_streamlit_session_match": binding.get("ui_ledger_streamlit_session_match"),
                "ui_ledger_run_match": binding.get("ui_ledger_run_match"),
                "ledger_same_frame_as_start": binding.get("ledger_same_frame_as_start"),
                "is_authenticated_observed": cp.get("is_authenticated"),
                "auth_session_complete_observed": cp.get("auth_session_complete"),
                "session_flag_present_observed": cp.get("session_flag_present"),
                "restore_blocked_reason_observed": cp.get("restore_blocked_reason"),
                "auth_observability_detail": obs.get("auth_observability_detail"),
                "auth_hydration_source": cp.get("auth_hydration_source"),
                "bridge_lookup_status": cp.get("bridge_lookup_status"),
                "current_auth_dom": current_auth_dom,
                "session_binding_failure": obs.get("session_binding_failure"),
                "_obs_ledger_rows": obs.get("ledger_rows_for_eval") or [],
                "_obs_checkpoint": cp,
            }
        )
        context.close()
        browser.close()

    runtime_sha = str(result.get("cloud_deploy_sha") or "")[:7]
    if runtime_sha != EXPECTED_APP_SHA:
        result["failure"] = "deploy_sha_mismatch"
        result["final_observability_classification"] = "DEPLOY_NOT_ON_e944c1a"
        result["auth_observability_classification"] = result["final_observability_classification"]
        return result

    has_current = bool((result.get("checkpoint_presence") or {}).get("solo-stage1-current-auth-state"))
    if not has_current:
        result["failure"] = "current_auth_checkpoint_missing"
        result["final_observability_classification"] = "CHECKPOINT_MISSING_AT_RUNTIME"
        result["auth_observability_classification"] = result["final_observability_classification"]
        return result

    from playwright_auth_current_state_eval import (
        bound_state_passes_observability_resolved,
        evaluate_bound_current_auth_state,
    )

    cp = result.get("_obs_checkpoint") or {}
    current_auth_dom = result.get("current_auth_dom") if isinstance(result.get("current_auth_dom"), dict) else {}
    bound = evaluate_bound_current_auth_state(
        current_auth_dom=current_auth_dom,
        ledger_rows=result.get("_obs_ledger_rows") or [],
        diagnostic_run_id=str(cp.get("diagnostic_run_id") or "")[:64],
        streamlit_session_id=str(cp.get("streamlit_session_id") or "")[:36],
        start_enabled=bool(cp.get("start_enabled")),
        start_visible=bool(cp.get("start_visible")),
    )
    result["bound_current_auth"] = bound
    result["bound_field_sources"] = bound.get("field_sources")

    ok = bound_state_passes_observability_resolved(bound) and (
        result.get("url_suite_sid_match")
        and not result.get("session_binding_failure")
    )
    if ok:
        result["pass"] = True
        result["final_observability_classification"] = "AUTH_OBSERVABILITY_RESOLVED"
        result["auth_observability_classification"] = ""
        result["failure"] = ""
        return result

    stale = (
        cp.get("is_authenticated") is False
        or cp.get("auth_session_complete") is False
        or cp.get("session_flag_present") is False
        or not result.get("start_enabled")
    )
    if stale and has_current:
        result["failure"] = "readonly_storage_stale_or_session_not_authenticated"
        result["final_observability_classification"] = "READONLY_AUTH_STORAGE_STALE"
        result["auth_observability_classification"] = result["final_observability_classification"]
        return result

    result["failure"] = result.get("session_binding_failure") or "binding_or_auth_not_proven"
    result["final_observability_classification"] = result.get("auth_observability_classification") or "AUTH_OBSERVABILITY8"
    result["auth_observability_classification"] = result["final_observability_classification"]
    result.pop("_obs_ledger_rows", None)
    result.pop("_obs_checkpoint", None)
    return result


def main() -> int:
    result = run_verify()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({**result, "artifact": str(OUT)}, default=str))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
