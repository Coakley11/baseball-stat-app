"""Strict Playwright auth preflight — requires genuine Streamlit hydration + bridge lookup."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

PREFLIGHT_FAIL_SID_MISMATCH = "suite_sid_mismatch"
PREFLIGHT_FAIL_NO_TOKEN_ROW = "browser_token_record_missing"
PREFLIGHT_FAIL_WRONG_SID_ROW = "browser_token_record_sid_mismatch"
PREFLIGHT_FAIL_INCOMPLETE_RECORD = "browser_token_record_incomplete"
PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE = "streamlit_auth_incomplete"
PREFLIGHT_FAIL_START_DISABLED = "start_control_disabled"
PREFLIGHT_FAIL_PAIRED_FALSE = "paired_transition_authenticated_false"


def suite_sid_from_url(url: str) -> str:
    try:
        return str(parse_qs(urlparse(url).query).get("suite_sid", [""])[0] or "").strip()
    except Exception:
        return ""


def _last_hydration(rows: list[dict[str, Any]], checkpoint: str) -> dict[str, Any] | None:
    matches = [
        r
        for r in rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == checkpoint
    ]
    return matches[-1] if matches else None


def _last_predicate_auth(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [
        r
        for r in rows
        if str(r.get("event") or "") == "production_stage1_queueui_predicate_audit"
        and r.get("authenticated") is not None
    ]
    return matches[-1] if matches else None


def evaluate_strict_preflight(
    *,
    harness_sid: str,
    url_sid: str,
    ledger_rows: list[dict[str, Any]],
    start_enabled: bool,
    start_visible: bool,
    paired_authenticated: bool | None,
    load_reason: str = "",
) -> dict[str, Any]:
    """Pure evaluation for unit tests and Cloud scrape results."""
    out: dict[str, Any] = {
        "harness_sid_prefix": harness_sid[:8] if harness_sid else "",
        "url_sid_prefix": url_sid[:8] if url_sid else "",
        "sid_match": bool(harness_sid and url_sid and harness_sid == url_sid),
        "bridge_lookup": "unknown",
        "streamlit_auth_complete": False,
        "start_enabled": bool(start_enabled),
        "start_visible": bool(start_visible),
        "authenticated_restored": False,
        "failure": "",
        "hydration_source": "",
        "apply_authenticated_user_ok": False,
    }
    if not harness_sid or not url_sid:
        out["failure"] = PREFLIGHT_FAIL_NO_TOKEN_ROW if not harness_sid else "suite_sid_missing_in_url"
        return out
    if harness_sid != url_sid:
        out["failure"] = PREFLIGHT_FAIL_WRONG_SID_ROW if load_reason == "token_record_missing" else PREFLIGHT_FAIL_SID_MISMATCH
        return out

    load_row = _last_hydration(ledger_rows, "load_browser_auth_tokens")
    if load_row:
        loaded = bool(load_row.get("browser_tokens_loaded"))
        access = bool(load_row.get("access_token_present"))
        refresh = bool(load_row.get("refresh_token_present"))
        if loaded and access and refresh:
            out["bridge_lookup"] = "record_found"
        elif load_reason == "token_record_incomplete" or (loaded and not (access and refresh)):
            out["bridge_lookup"] = "record_incomplete"
            out["failure"] = PREFLIGHT_FAIL_INCOMPLETE_RECORD
            return out
        else:
            out["bridge_lookup"] = "record_missing"
            out["failure"] = PREFLIGHT_FAIL_NO_TOKEN_ROW
            return out
    elif load_reason in ("token_record_missing", "suite_sid_missing"):
        out["bridge_lookup"] = "record_missing"
        out["failure"] = PREFLIGHT_FAIL_NO_TOKEN_ROW
        return out

    exit_row = _last_hydration(ledger_rows, "restore_auth_session_exit")
    apply_row = _last_hydration(ledger_rows, "apply_authenticated_user_exit")
    if exit_row:
        out["hydration_source"] = str(exit_row.get("auth_hydration_source") or load_reason or "")
        if str(exit_row.get("skip_or_failure_reason") or "") in ("ok", ""):
            if exit_row.get("authenticated_after") is True:
                out["streamlit_auth_complete"] = True
    if apply_row and apply_row.get("authenticated_after") is True:
        out["apply_authenticated_user_ok"] = True
        out["streamlit_auth_complete"] = True

    pred = _last_predicate_auth(ledger_rows)
    if pred and pred.get("authenticated") is True:
        out["streamlit_auth_complete"] = True
    if paired_authenticated is False:
        out["failure"] = PREFLIGHT_FAIL_PAIRED_FALSE
        return out
    if paired_authenticated is True:
        out["streamlit_auth_complete"] = True

    if not out["streamlit_auth_complete"]:
        out["failure"] = PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE
        return out
    if not start_visible or not start_enabled:
        out["failure"] = PREFLIGHT_FAIL_START_DISABLED
        return out
    out["authenticated_restored"] = True
    out["failure"] = ""
    return out


def inspect_start_control(page) -> dict[str, Any]:
    """Return Start button visibility/enabled without clicking."""
    out: dict[str, Any] = {"visible": False, "enabled": False, "disabled": True}
    try:
        scan = page.evaluate(
            """() => {
              const roots = [document];
              for (const f of document.querySelectorAll('iframe')) {
                try { if (f.contentDocument) roots.push(f.contentDocument); } catch (e) {}
              }
              for (const root of roots) {
                for (const b of root.querySelectorAll('button')) {
                  const t = (b.innerText || '').replace(/\\s+/g, ' ').trim();
                  if (/Start New Live Draft/i.test(t)) {
                    const r = b.getBoundingClientRect();
                    return { visible: r.width > 0 && r.height > 0, disabled: !!b.disabled };
                  }
                }
              }
              return { visible: false, disabled: true };
            }"""
        )
        if isinstance(scan, dict):
            out["visible"] = bool(scan.get("visible"))
            out["disabled"] = bool(scan.get("disabled"))
            out["enabled"] = out["visible"] and not out["disabled"]
    except Exception:
        pass
    return out


def paired_transition_authenticated(page) -> bool | None:
    try:
        import base64

        b64 = page.evaluate(
            """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) {
            try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          for (const root of roots()) {
            const el = root.querySelector('#solo-paired-transition-diag');
            if (el) return el.getAttribute('data-paired-transition-b64') || '';
          }
          return '';
        }"""
        )
        if not b64:
            return None
        raw = base64.b64decode(b64 + "==="[: (4 - len(b64) % 4) % 4])
        payload = json.loads(raw.decode("utf-8"))
        rows = payload.get("rows") or []
        if isinstance(rows, list) and rows:
            for row in reversed(rows):
                if isinstance(row, dict) and "authenticated" in row:
                    return bool(row.get("authenticated"))
    except Exception:
        return None
    return None


def strict_preflight_from_page(
    page,
    *,
    harness_sid: str,
    ledger_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    url_sid = suite_sid_from_url(page.url or "")
    load_row = _last_hydration(ledger_rows, "load_browser_auth_tokens")
    load_reason = ""
    if load_row:
        if not load_row.get("browser_tokens_loaded"):
            load_reason = "token_record_missing"
    start = inspect_start_control(page)
    paired = paired_transition_authenticated(page)
    return evaluate_strict_preflight(
        harness_sid=harness_sid,
        url_sid=url_sid,
        ledger_rows=ledger_rows,
        start_enabled=bool(start.get("enabled")),
        start_visible=bool(start.get("visible")),
        paired_authenticated=paired,
        load_reason=load_reason,
    )
