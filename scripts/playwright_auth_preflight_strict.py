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


def _last_event(rows: list[dict[str, Any]], event: str) -> dict[str, Any] | None:
    matches = [r for r in rows if str(r.get("event") or "") == event]
    return matches[-1] if matches else None


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


def _before_start_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _last_event(rows, "production_stage1_auth_state_before_start_control")


def _session_flag_present(row: dict[str, Any] | None) -> bool | None:
    if not row:
        return None
    prot = row.get("protected_keys")
    if isinstance(prot, dict) and "session_flag_present" in prot:
        return bool(prot.get("session_flag_present"))
    if "session_flag_present" in row:
        return bool(row.get("session_flag_present"))
    return None


def evaluate_strict_preflight(
    *,
    harness_sid: str,
    url_sid: str,
    ledger_rows: list[dict[str, Any]],
    start_enabled: bool,
    start_visible: bool,
    paired_authenticated: bool | None,
    load_reason: str = "",
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
) -> dict[str, Any]:
    """Pure evaluation for unit tests and Cloud scrape results."""
    from playwright_auth_ledger_export import filter_ledger_rows

    scoped, scope_meta = filter_ledger_rows(
        ledger_rows,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
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
        "current_state_authoritative": False,
        "paired_transition_ignored": False,
        "incomplete_reason": "",
        "ledger_scope": scope_meta,
    }
    rows = scoped
    before_start = _before_start_row(rows)
    if before_start and before_start.get("is_authenticated") is False:
        out["failure"] = PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE
        out["incomplete_reason"] = "before_start_control_is_authenticated_false"
        return out
    if before_start and before_start.get("auth_session_complete") is False:
        out["failure"] = PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE
        out["incomplete_reason"] = "before_start_control_auth_session_complete_false"
        return out

    if not harness_sid or not url_sid:
        out["failure"] = PREFLIGHT_FAIL_NO_TOKEN_ROW if not harness_sid else "suite_sid_missing_in_url"
        return out
    if harness_sid != url_sid:
        out["failure"] = PREFLIGHT_FAIL_WRONG_SID_ROW if load_reason == "token_record_missing" else PREFLIGHT_FAIL_SID_MISMATCH
        return out

    load_row = _last_hydration(rows, "load_browser_auth_tokens")
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
    elif before_start and before_start.get("auth_session_complete") is True:
        out["bridge_lookup"] = "record_found"
    elif out.get("bridge_lookup") == "unknown" and before_start:
        out["bridge_lookup"] = "not_observed_in_scope"

    exit_row = _last_hydration(rows, "restore_auth_session_exit")
    apply_row = _last_hydration(rows, "apply_authenticated_user_exit")
    hydration_src = ""
    if before_start:
        hydration_src = str(before_start.get("auth_hydration_source") or "").strip()
    if exit_row:
        hydration_src = hydration_src or str(exit_row.get("auth_hydration_source") or load_reason or "")
        out["hydration_source"] = hydration_src
        if str(exit_row.get("skip_or_failure_reason") or "") in ("ok", ""):
            if exit_row.get("authenticated_after") is True:
                out["streamlit_auth_complete"] = True
    else:
        out["hydration_source"] = hydration_src

    if apply_row:
        apply_complete = apply_row.get("auth_session_complete")
        if apply_complete is True:
            out["apply_authenticated_user_ok"] = True
        elif apply_complete is False:
            out["apply_authenticated_user_ok"] = False
        elif apply_row.get("apply_return_ok") is True and apply_row.get("auth_session_complete") is not False:
            out["apply_authenticated_user_ok"] = bool(apply_row.get("session_flag_present"))
        elif apply_row.get("authenticated_after") is True and _session_flag_present(apply_row) is True:
            out["apply_authenticated_user_ok"] = True
        if out["apply_authenticated_user_ok"] and apply_row.get("auth_session_complete") is True:
            out["streamlit_auth_complete"] = True

    if before_start:
        if before_start.get("is_authenticated") is True and before_start.get("auth_session_complete") is True:
            out["streamlit_auth_complete"] = True
            out["current_state_authoritative"] = True
            flag = _session_flag_present(before_start)
            if flag is True:
                out["apply_authenticated_user_ok"] = True
            elif flag is False:
                out["apply_authenticated_user_ok"] = False
            elif hydration_src == "already_complete":
                out["apply_authenticated_user_ok"] = True
        rb = str(before_start.get("restore_blocked_reason") or "").strip()
        if rb:
            out["restore_blocked_reason"] = rb

    if hydration_src == "already_complete" and before_start and before_start.get("auth_session_complete") is True:
        out["streamlit_auth_complete"] = True
        out["current_state_authoritative"] = True
        if not out["apply_authenticated_user_ok"]:
            out["apply_authenticated_user_ok"] = _session_flag_present(before_start) is not False

    pred = _last_predicate_auth(rows)
    if pred and pred.get("authenticated") is True:
        out["streamlit_auth_complete"] = True

    if paired_authenticated is True:
        out["streamlit_auth_complete"] = True
    elif paired_authenticated is False:
        if not out["streamlit_auth_complete"]:
            out["failure"] = PREFLIGHT_FAIL_PAIRED_FALSE
            out["incomplete_reason"] = "paired_transition_authenticated_false"
            return out
        out["paired_transition_ignored"] = True

    if not out["streamlit_auth_complete"]:
        out["failure"] = PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE
        if not out["incomplete_reason"]:
            if apply_row is None and exit_row is None and before_start is None:
                out["incomplete_reason"] = "no_current_state_or_transition_evidence"
            elif paired_authenticated is False:
                out["incomplete_reason"] = "paired_false_without_current_state"
            else:
                out["incomplete_reason"] = "streamlit_auth_not_proven"
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
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
) -> dict[str, Any]:
    from playwright_auth_ledger_export import filter_ledger_rows

    url_sid = suite_sid_from_url(page.url or "")
    scoped, _ = filter_ledger_rows(
        ledger_rows,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
    load_row = _last_hydration(scoped, "load_browser_auth_tokens")
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
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
